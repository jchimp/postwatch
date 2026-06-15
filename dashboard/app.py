"""
postwatch dashboard — app.py
Main Flask application: auth, proxy routes to agents, polled stats API.
"""

import json
from functools import wraps
import secrets
from urllib.parse import urlparse

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

# Migrate agents from .env to database (one-time at startup)
def _migrate_agents_from_config():
    """On startup, migrate any agents from .env to database if not already present."""
    existing_agents = models.get_agents(config.DB_PATH)
    existing_urls = {agent["url"] for agent in existing_agents}

    for env_url in config.AGENTS:
        if env_url not in existing_urls:
            models.add_agent(config.DB_PATH, env_url, env_url)
            print(f"[app] Migrated agent from .env to database: {env_url}")

_migrate_agents_from_config()

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
    return {"X-API-Key": _get_api_key()}


def _agent_display(agent: dict) -> str:
    """Label for an agent dropdown: its name, or the host/IP if no real name is set.

    `add_agent` stores the URL as the name when none is given, so treat a name
    equal to the URL (or blank) as "no name" and fall back to the URL host.
    """
    name = (agent.get("name") or "").strip()
    url = agent.get("url", "")
    if name and name != url:
        return name
    return urlparse(url).hostname or url


def _get_agents() -> list[dict]:
    """Get agent URLs and names from database only (post-migration from .env)."""
    agents = models.get_agents(config.DB_PATH)
    for agent in agents:
        agent["display"] = _agent_display(agent)
    return agents


def _get_api_key() -> str:
    """Get API key from database. Generated at first DB initialization."""
    db_key = models.get_setting(config.DB_PATH, "AGENT_API_KEY")
    if not db_key:
        raise RuntimeError("AGENT_API_KEY not found in database. DB may not be initialized.")
    return db_key


def _get_token_thresholds() -> dict[str, int]:
    """Get token threshold settings from database."""
    stale = models.get_setting(config.DB_PATH, "TOKEN_STALE_MINUTES") or "90"
    expiry_warn = models.get_setting(config.DB_PATH, "TOKEN_EXPIRY_WARN_MINUTES") or "10"
    return {
        "stale_minutes": int(stale),
        "expiry_warn_minutes": int(expiry_warn),
    }


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
    agents = _get_agents()
    for agent in agents:
        agent["snapshot"] = models.get_latest_snapshot(config.DB_PATH, agent["url"]) or {}
    return render_template("overview.html", agents=agents)


@app.route("/logs")
@login_required
def logs_page():
    return render_template("logs.html", agents=_get_agents())


@app.route("/queue")
@login_required
def queue_page():
    return render_template("queue.html", agents=_get_agents())


@app.route("/tokens")
@login_required
def tokens_page():
    return render_template("tokens.html", agents=_get_agents())


@app.route("/settings")
@login_required
def settings():
    api_key = _get_api_key()
    thresholds = _get_token_thresholds()
    return render_template("settings.html", agents=_get_agents(), api_key=api_key, thresholds=thresholds)


# ══════════════════════════════════════════════════════════════════════════════
# API — proxy live data from agents
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/agents")
@login_required
def api_agents():
    """Return the configured agents (url + display label) from the database."""
    agents = _get_agents()
    return jsonify([
        {"url": agent["url"], "display": agent["display"]} for agent in agents
    ])


# ── Settings management ───────────────────────────────────────────────────────

@app.route("/api/agents", methods=["POST"])
@login_required
def api_add_agent():
    """Add a new agent. Expects JSON: {url, name?}"""
    data = request.get_json()
    url = data.get("url", "").strip()
    name = (data.get("name") or "").strip()

    if not name:
        return jsonify({"error": "name is required"}), 400
    if not url:
        return jsonify({"error": "url is required"}), 400

    success = models.add_agent(config.DB_PATH, url, name)
    if not success:
        return jsonify({"error": "agent already exists"}), 400

    return jsonify({"success": True, "url": url}), 201


@app.route("/api/agents/<int:agent_id>", methods=["DELETE"])
@login_required
def api_remove_agent(agent_id):
    """Remove an agent by ID."""
    success = models.remove_agent(config.DB_PATH, agent_id)
    if not success:
        return jsonify({"error": "agent not found"}), 404

    return jsonify({"success": True}), 200


@app.route("/api/settings/api-key", methods=["GET"])
@login_required
def api_get_api_key():
    """Get the current API key."""
    api_key = _get_api_key()
    return jsonify({"api_key": api_key}), 200


@app.route("/api/settings/api-key", methods=["POST"])
@login_required
def api_regenerate_api_key():
    """Generate and save a new API key."""
    new_key = secrets.token_urlsafe(32)
    models.set_setting(config.DB_PATH, "AGENT_API_KEY", new_key)
    return jsonify({"api_key": new_key}), 200


@app.route("/api/settings/token-thresholds", methods=["GET"])
@login_required
def api_get_token_thresholds():
    """Get current token threshold settings."""
    thresholds = _get_token_thresholds()
    return jsonify(thresholds), 200


@app.route("/api/settings/token-thresholds", methods=["POST"])
@login_required
def api_set_token_thresholds():
    """Update token threshold settings. Expects JSON: {stale_minutes, expiry_warn_minutes}"""
    data = request.get_json()
    try:
        stale = int(data.get("stale_minutes", 90))
        expiry_warn = int(data.get("expiry_warn_minutes", 10))

        if stale < 0 or expiry_warn < 0:
            return jsonify({"error": "values must be non-negative"}), 400

        models.set_setting(config.DB_PATH, "TOKEN_STALE_MINUTES", str(stale))
        models.set_setting(config.DB_PATH, "TOKEN_EXPIRY_WARN_MINUTES", str(expiry_warn))
        return jsonify({"stale_minutes": stale, "expiry_warn_minutes": expiry_warn}), 200
    except (ValueError, TypeError):
        return jsonify({"error": "invalid values"}), 400


# ── Live proxy: GET endpoints ─────────────────────────────────────────────────

@app.route("/api/health/<path:agent_url>")
@login_required
def api_health(agent_url):
    """Lightweight reachability check (agent /health needs no API key)."""
    try:
        r = http_requests.get(f"{agent_url}/health", timeout=5)
        return jsonify(r.json()), r.status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


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
        headers = _agent_headers()
        thresholds = _get_token_thresholds()
        headers["X-Token-Stale-Minutes"] = str(thresholds["stale_minutes"])
        headers["X-Token-Expiry-Warn-Minutes"] = str(thresholds["expiry_warn_minutes"])
        r = http_requests.get(
            f"{agent_url}/token-status", headers=headers, timeout=10
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


@app.route("/api/chart/daily/all")
@login_required
def api_chart_daily_all():
    days = request.args.get("days", 7, type=int)
    data = models.get_daily_stats_all(config.DB_PATH, days=days)
    return jsonify(data)


@app.route("/api/chart/hourly/all")
@login_required
def api_chart_hourly_all():
    hours = request.args.get("hours", 24, type=int)
    data = models.get_hourly_stats_all(config.DB_PATH, hours=hours)
    return jsonify(data)


@app.route("/api/chart/weekly/all")
@login_required
def api_chart_weekly_all():
    weeks = request.args.get("weeks", 4, type=int)
    data = models.get_weekly_stats_all(config.DB_PATH, weeks=weeks)
    return jsonify(data)


@app.route("/api/chart/monthly/all")
@login_required
def api_chart_monthly_all():
    months = request.args.get("months", 12, type=int)
    data = models.get_monthly_stats_all(config.DB_PATH, months=months)
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
