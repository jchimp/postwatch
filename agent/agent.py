"""
postwatch-agent — Phase 1 + Phase 2
Lightweight REST API for monitoring a Postfix mail server.
Runs as root via systemd. Secured with a shared API key.

Endpoints:
  Phase 1: /health, /status, /queue, /logs, /logs/stream
  Phase 2: /restart, /queue/flush, /queue/delete, /token-status, /stats
"""

import glob
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, stream_with_context

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY               = os.getenv("API_KEY", "changeme")
SERVER_NAME           = os.getenv("SERVER_NAME", "mail-server")
LOG_FILE              = os.getenv("LOG_FILE", "/var/log/mail.log")
HOST                  = os.getenv("HOST", "0.0.0.0")
PORT                  = int(os.getenv("PORT", 5100))

# Phase 2 — Token monitoring
TOKEN_DIR             = os.getenv("TOKEN_DIR", "")
TOKEN_STALE_MINUTES   = int(os.getenv("TOKEN_STALE_MINUTES", 90))
TOKEN_EXPIRY_WARN_MINUTES = int(os.getenv("TOKEN_EXPIRY_WARN_MINUTES", 10))

app = Flask(__name__)


# ── Auth middleware ────────────────────────────────────────────────────────────
def require_api_key(f):
    """Decorator that checks the X-API-Key header on every request."""
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key", "")
        if key != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ── Helpers ───────────────────────────────────────────────────────────────────
def _run(cmd: list[str], timeout: int = 15) -> tuple[str, int]:
    """Run a shell command and return (stdout+stderr, returncode)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout + result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "Command timed out", -1
    except Exception as exc:
        return str(exc), -1


def _utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ── GET /health ───────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    """Public health check — no API key required."""
    return jsonify({"status": "ok", "server_name": SERVER_NAME, "ts": _utcnow()})


# ── GET /status ───────────────────────────────────────────────────────────────
@app.route("/status")
@require_api_key
def status():
    """Return the current state of the postfix service."""
    active_out, active_rc = _run(["systemctl", "is-active", "postfix"])
    status_out, _         = _run(["systemctl", "status", "postfix", "--no-pager", "-l"])

    return jsonify({
        "server_name": SERVER_NAME,
        "active": active_rc == 0,
        "active_text": active_out.strip(),
        "status_text": status_out.strip(),
        "ts": _utcnow(),
    })


# ── GET /queue ────────────────────────────────────────────────────────────────
@app.route("/queue")
@require_api_key
def queue():
    """Return the current Postfix mail queue."""
    raw, rc = _run(["mailq"])

    if "is empty" in raw.lower():
        count = 0
    else:
        count = sum(
            1 for line in raw.splitlines()
            if line and not line.startswith(" ")
            and not line.startswith("-") and not line.startswith("Total")
        )

    return jsonify({
        "server_name": SERVER_NAME,
        "queue_count": count,
        "raw": raw.strip(),
        "ts": _utcnow(),
    })


# ── GET /logs ─────────────────────────────────────────────────────────────────
@app.route("/logs")
@require_api_key
def logs():
    """Return the last 200 lines of the mail log, with optional search filter."""
    search = request.args.get("search", "").lower()

    if not os.path.isfile(LOG_FILE):
        return jsonify({"error": f"Log file not found: {LOG_FILE}"}), 404

    raw, _ = _run(["tail", "-n", "200", LOG_FILE], timeout=5)
    lines = raw.splitlines()

    if search:
        lines = [l for l in lines if search in l.lower()]

    return jsonify({
        "server_name": SERVER_NAME,
        "log_file": LOG_FILE,
        "count": len(lines),
        "lines": lines,
        "ts": _utcnow(),
    })


# ── GET /logs/stream (SSE) ───────────────────────────────────────────────────
@app.route("/logs/stream")
@require_api_key
def logs_stream():
    """Stream new log lines via Server-Sent Events (SSE)."""

    def generate():
        proc = subprocess.Popen(
            ["tail", "-F", "-n", "0", LOG_FILE],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
        try:
            while True:
                line = proc.stdout.readline()
                if line:
                    payload = json.dumps({"line": line.rstrip(), "ts": _utcnow()})
                    yield f"data: {payload}\n\n"
                else:
                    time.sleep(0.1)
        except GeneratorExit:
            proc.terminate()
            proc.wait()

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

# ══════════════════════════════════════════════════════════════════════════════
# Phase 2 — Actions, Token Monitor, Stats
# ══════════════════════════════════════════════════════════════════════════════


# ── POST /restart ─────────────────────────────────────────────────────────────
@app.route("/restart", methods=["POST"])
@require_api_key
def restart():
    """Restart the postfix service."""
    out, rc = _run(["systemctl", "restart", "postfix"], timeout=30)
    return jsonify({
        "server_name": SERVER_NAME,
        "success": rc == 0,
        "message": out.strip() if out.strip() else ("Postfix restarted" if rc == 0 else "Restart failed"),
        "ts": _utcnow(),
    })


# ── POST /queue/flush ────────────────────────────────────────────────────────
@app.route("/queue/flush", methods=["POST"])
@require_api_key
def queue_flush():
    """Flush the deferred mail queue (attempt immediate delivery)."""
    out, rc = _run(["postqueue", "-f"], timeout=15)
    return jsonify({
        "server_name": SERVER_NAME,
        "success": rc == 0,
        "message": out.strip() if out.strip() else ("Queue flushed" if rc == 0 else "Flush failed"),
        "ts": _utcnow(),
    })


# ── POST /queue/delete ───────────────────────────────────────────────────────
@app.route("/queue/delete", methods=["POST"])
@require_api_key
def queue_delete():
    """Delete ALL messages from the mail queue."""
    out, rc = _run(["postsuper", "-d", "ALL"], timeout=30)
    return jsonify({
        "server_name": SERVER_NAME,
        "success": rc == 0,
        "message": out.strip() if out.strip() else ("All queued messages deleted" if rc == 0 else "Delete failed"),
        "ts": _utcnow(),
    })


# ── GET /token-status ────────────────────────────────────────────────────────
@app.route("/token-status")
@require_api_key
def token_status():
    """Check freshness and expiry of OAuth token files in TOKEN_DIR."""
    if not TOKEN_DIR:
        return jsonify({"error": "TOKEN_DIR not configured"}), 404

    if not os.path.isdir(TOKEN_DIR):
        return jsonify({"error": f"TOKEN_DIR not found: {TOKEN_DIR}"}), 404

    now = datetime.now(timezone.utc)
    tokens = []

    # Glob all files in the token directory
    for fpath in sorted(glob.glob(os.path.join(TOKEN_DIR, "*"))):
        if not os.path.isfile(fpath):
            continue

        # File mtime
        mtime_epoch = os.path.getmtime(fpath)
        mtime_dt = datetime.fromtimestamp(mtime_epoch, tz=timezone.utc)
        age_minutes = (now - mtime_dt).total_seconds() / 60.0

        # Try to parse expiry from JSON content
        expiry_iso = None
        expiry_minutes_remaining = None
        expiry_epoch = None

        try:
            with open(fpath, "r") as f:
                data = json.load(f)
            # sasl-xoauth2 stores "expiry" as a Unix epoch (string or int)
            if "expiry" in data:
                expiry_epoch = float(data["expiry"])
                expiry_dt = datetime.fromtimestamp(expiry_epoch, tz=timezone.utc)
                expiry_iso = expiry_dt.isoformat()
                expiry_minutes_remaining = round((expiry_dt - now).total_seconds() / 60.0, 1)
        except (json.JSONDecodeError, ValueError, KeyError, OSError):
            pass

        # Determine status
        if expiry_epoch is not None and expiry_minutes_remaining is not None:
            if expiry_minutes_remaining <= 0:
                file_status = "expired"
            elif expiry_minutes_remaining <= TOKEN_EXPIRY_WARN_MINUTES:
                file_status = "expiring_soon"
            elif age_minutes > TOKEN_STALE_MINUTES:
                file_status = "stale"
            else:
                file_status = "ok"
        else:
            # No expiry data — fall back to staleness check only
            file_status = "stale" if age_minutes > TOKEN_STALE_MINUTES else "ok"

        tokens.append({
            "path": fpath,
            "filename": os.path.basename(fpath),
            "mtime_iso": mtime_dt.isoformat(),
            "age_minutes": round(age_minutes, 1),
            "expiry_iso": expiry_iso,
            "expiry_minutes_remaining": expiry_minutes_remaining,
            "status": file_status,
        })

    return jsonify({
        "server_name": SERVER_NAME,
        "token_dir": TOKEN_DIR,
        "thresholds": {
            "stale_minutes": TOKEN_STALE_MINUTES,
            "expiry_warn_minutes": TOKEN_EXPIRY_WARN_MINUTES,
        },
        "tokens": tokens,
        "ts": _utcnow(),
    })


# ── GET /stats ────────────────────────────────────────────────────────────────
@app.route("/stats")
@require_api_key
def stats():
    """Parse mail.log and return send/error counts bucketed by hour and day."""
    if not os.path.isfile(LOG_FILE):
        return jsonify({"error": f"Log file not found: {LOG_FILE}"}), 404

    # Read last 10 000 lines for performance
    raw, _ = _run(["tail", "-n", "10000", LOG_FILE], timeout=10)
    lines = raw.splitlines()

    current_year = datetime.now().year

    # Syslog date pattern: "Jun 10 07:40:28"
    date_re = re.compile(r"^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})")

    totals = {"sent": 0, "deferred": 0, "bounced": 0, "rejected": 0}
    hourly: dict[str, dict[str, int]] = {}
    daily: dict[str, dict[str, int]] = {}

    for line in lines:
        lower = line.lower()

        # Determine category
        category = None
        if "status=sent" in lower:
            category = "sent"
        elif "status=deferred" in lower:
            category = "deferred"
        elif "status=bounced" in lower:
            category = "bounced"
        elif "reject:" in lower or "rejected" in lower:
            category = "rejected"

        if category is None:
            continue

        totals[category] += 1

        # Parse timestamp
        m = date_re.match(line)
        if not m:
            continue

        try:
            dt = datetime.strptime(f"{current_year} {m.group(1)}", "%Y %b %d %H:%M:%S")
        except ValueError:
            continue

        hour_key = dt.strftime("%Y-%m-%d %H")
        day_key = dt.strftime("%Y-%m-%d")

        # Hourly bucket
        if hour_key not in hourly:
            hourly[hour_key] = {"sent": 0, "deferred": 0, "bounced": 0, "rejected": 0}
        hourly[hour_key][category] += 1

        # Daily bucket
        if day_key not in daily:
            daily[day_key] = {"sent": 0, "deferred": 0, "bounced": 0, "rejected": 0}
        daily[day_key][category] += 1

    return jsonify({
        "server_name": SERVER_NAME,
        "log_file": LOG_FILE,
        "lines_parsed": len(lines),
        "totals": totals,
        "hourly": dict(sorted(hourly.items())),
        "daily": dict(sorted(daily.items())),
        "ts": _utcnow(),
    })


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[postwatch-agent] {SERVER_NAME} listening on {HOST}:{PORT}")
    app.run(host=HOST, port=PORT, threaded=True)
