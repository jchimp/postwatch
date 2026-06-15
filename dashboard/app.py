"""
postwatch dashboard — app.py
Main Flask application: auth, proxy routes to agents, polled stats API.
"""

import json
from functools import wraps

import requests as http_requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import (
    Flask, Response, jsonify, redirect, render_template,
    request, session, stream_with_context, url_for,
)

import config
import models
import poller

# ── App setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# Initialize database
models.init_db(config.DB_PATH)

# Background poller
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(
    poller.poll_agents,
    "interval",
    seconds=config.POLL_INTERVAL_SECONDS,
    id="poll_agents",
    replace_existing=True,
)
scheduler.start()

# Run an initial poll at startup (don't crash if agents are down)
try:
    poller.poll_agents()
except Exception as exc:
    print(f"[app] Initial poll failed (agents may be unreachable): {exc}")


# ── Auth helpers ──────────────────────────────────────────────────────────────
def login_required(f):
    """Redirect to /login if the user isn't authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def _agent_headers() -> dict:
    """Standard headers for agent API calls."""
    return {"X-API-Key": config.AGENT_API_KEY}


# ── Login / Logout ────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == config.ADMIN_USER and password == config.ADMIN_PASS:
            session["logged_in"] = True
            session["username"] = username
            return redirect(url_for("overview"))
        error = "Invalid credentials"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ══════════════════════════════════════════════════════════════════════════════
# Page routes
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
@login_required
def index():
    return redirect(url_for("overview"))


@app.route("/overview")
@login_required
def overview():
    return render_template("overview.html", agents=config.AGENTS)


@app.route("/logs")
@login_required
def logs_page():
    return render_template("logs.html", agents=config.AGENTS)


@app.route("/queue")
@login_required
def queue_page():
    return render_template("queue.html", agents=config.AGENTS)


@app.route("/tokens")
@login_required
def tokens_page():
    return render_template("tokens.html", agents=config.AGENTS)


# ══════════════════════════════════════════════════════════════════════════════
# API — proxy live data from agents
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/agents")
@login_required
def api_agents():
    """Return the list of configured agent URLs."""
    return jsonify(config.AGENTS)


# ── Live proxy: GET endpoints ─────────────────────────────────────────────────

@app.route("/api/status/<path:agent_url>")
@login_required
def api_status(agent_url):
    try:
        r = http_requests.get(f"{agent_url}/status", headers=_agent_headers(), timeout=10)
        return jsonify(r.json()), r.status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/queue/<path:agent_url>")
@login_required
def api_queue(agent_url):
    try:
        r = http_requests.get(f"{agent_url}/queue", headers=_agent_headers(), timeout=10)
        return jsonify(r.json()), r.status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/logs/<path:agent_url>")
@login_required
def api_logs(agent_url):
    try:
        params = {}
        search = request.args.get("search", "")
        if search:
            params["search"] = search
        r = http_requests.get(
            f"{agent_url}/logs", headers=_agent_headers(), params=params, timeout=10
        )
        return jsonify(r.json()), r.status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/logs/stream/<path:agent_url>")
@login_required
def api_logs_stream(agent_url):
    """Proxy the SSE log stream from an agent to the browser."""
    def generate():
        try:
            with http_requests.get(
                f"{agent_url}/logs/stream",
                headers=_agent_headers(),
                stream=True,
                timeout=(5, None),  # 5s connect, no read timeout
            ) as r:
                for line in r.iter_lines(decode_unicode=True):
                    if line:
                        yield f"{line}\n\n"
        except GeneratorExit:
            pass
        except Exception as exc:
            payload = json.dumps({"error": str(exc)})
            yield f"data: {payload}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/token-status/<path:agent_url>")
@login_required
def api_token_status(agent_url):
    try:
        r = http_requests.get(
            f"{agent_url}/token-status", headers=_agent_headers(), timeout=10
        )
        return jsonify(r.json()), r.status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/stats/<path:agent_url>")
@login_required
def api_stats(agent_url):
    try:
        r = http_requests.get(f"{agent_url}/stats", headers=_agent_headers(), timeout=10)
        return jsonify(r.json()), r.status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


# ── Live proxy: POST actions ─────────────────────────────────────────────────

@app.route("/api/restart/<path:agent_url>", methods=["POST"])
@login_required
def api_restart(agent_url):
    try:
        r = http_requests.post(
            f"{agent_url}/restart", headers=_agent_headers(), timeout=30
        )
        return jsonify(r.json()), r.status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/queue/flush/<path:agent_url>", methods=["POST"])
@login_required
def api_queue_flush(agent_url):
    try:
        r = http_requests.post(
            f"{agent_url}/queue/flush", headers=_agent_headers(), timeout=15
        )
        return jsonify(r.json()), r.status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/queue/delete/<path:agent_url>", methods=["POST"])
@login_required
def api_queue_delete(agent_url):
    try:
        r = http_requests.post(
            f"{agent_url}/queue/delete", headers=_agent_headers(), timeout=30
        )
        return jsonify(r.json()), r.status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


# ══════════════════════════════════════════════════════════════════════════════
# API — stored stats from SQLite
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/chart/daily/<path:agent_url>")
@login_required
def api_chart_daily(agent_url):
    days = request.args.get("days", 7, type=int)
    data = models.get_daily_stats(config.DB_PATH, agent_url, days=days)
    return jsonify(data)


@app.route("/api/chart/hourly/<path:agent_url>")
@login_required
def api_chart_hourly(agent_url):
    hours = request.args.get("hours", 24, type=int)
    data = models.get_hourly_stats(config.DB_PATH, agent_url, hours=hours)
    return jsonify(data)


@app.route("/api/snapshot/<path:agent_url>")
@login_required
def api_snapshot(agent_url):
    snap = models.get_latest_snapshot(config.DB_PATH, agent_url)
    return jsonify(snap or {})


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[postwatch] Dashboard on {config.HOST}:{config.PORT}")
    app.run(host=config.HOST, port=config.PORT, threaded=True)
