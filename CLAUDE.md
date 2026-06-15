# CLAUDE.md — Postwatch

Two-component Postfix monitoring dashboard. **Agent** (per mail server) + **Dashboard** (central, Docker).

## Tech Stack

Python 3.12 · Flask · SQLite · Bootstrap 5.3 (CDN) · Chart.js 4 (CDN) · APScheduler · SSE
No ORM, no npm, no build step, no heavy frameworks.

## Architecture

Agent (×N, systemd, root, :5100)  ←──REST/JSON──→  Dashboard (×1, Docker, :5000)  ←──→  Browser

- **Agent** — Flask REST API. Minimal config (API key only). Talks to Postfix via subprocess (`systemctl`, `mailq`, `postqueue`, `postsuper`, `tail`). Reads OAuth token files from disk. Streams logs via SSE (`tail -F`). Token thresholds passed by dashboard via request headers.
- **Dashboard** — Flask app. APScheduler polls agents every 2 min → SQLite. Proxies live requests (logs, queue, status, actions) directly to agents. Serves Jinja2 + Bootstrap frontend.
- **Auth** — Single admin user, plaintext `.env` check, Flask session.
- **Comms** — REST/JSON over HTTP. Shared API key in `X-API-Key` header.

## File Map


agent/
agent.py                     # All agent endpoints (Flask)
.env.example                 # Agent config template
install.sh                     # Root installer → /opt/postwatch-agent/
postwatch-agent.service      # systemd unit
dashboard/
app.py                       # Main Flask app — routes, proxy, scheduler
config.py                    # Loads .env → module-level vars
models.py                    # SQLite schema + query helpers
poller.py                    # Background job — polls agents, saves snapshots
requirements.txt             # flask, python-dotenv, requests, apscheduler
Dockerfile                   # python:3.12-slim
docker-compose.yml           # Single service, SQLite volume
.env.example                 # Dashboard config template
static/style.css             # Nord/Slate dark theme (CSS vars in :root)
templates/
base.html                  # Layout — navbar, Bootstrap/Chart.js CDN
login.html                 # Centered login card
overview.html              # Stat cards + daily/hourly bar charts
logs.html                  # Log viewer + SSE live toggle + search
queue.html                 # Queue view + flush/delete/restart modals
tokens.html                # OAuth token health cards
part2 = """## Agent Endpoints

| Route | Method | Auth | Action |
|---|---|---|---|
| `/health` | GET | None | Health check |
| `/status` | GET | Key | `systemctl status postfix` |
| `/queue` | GET | Key | `mailq` output + count |
| `/logs` | GET | Key | Last 200 lines, `?search=` filter |
| `/logs/stream` | GET | Key | SSE real-time tail |
| `/stats` | GET | Key | Parsed log → totals + hourly/daily buckets |
| `/token-status` | GET | Key | Token file age, expiry, staleness |
| `/restart` | POST | Key | `systemctl restart postfix` |
| `/queue/flush` | POST | Key | `postqueue -f` |
| `/queue/delete` | POST | Key | `postsuper -d ALL` |

## Key Patterns

- **Agent auth**: `@require_api_key` decorator checks `X-API-Key` header.
- **Dashboard proxy**: `/api/*` routes forward to agents via `requests`, return 502 on failure.
- **Frontend JS**: Each template has `{% block scripts %}` — vanilla JS, no framework. Calls `/api/*` with `fetch()`.
- **SSE chain**: `tail -F` → agent generator → `text/event-stream` → dashboard proxy → browser `EventSource`.
- **Config**: Startup via `.env` (python-dotenv). Runtime via SQLite `settings` table (API key, token thresholds) and `agents` table (agent URLs/names).
- **Charts**: Chart.js in `overview.html`. Daily data from `/api/chart/daily/` (SQLite). Live stats from `/api/stats/` (agent).

## Common Tasks

**Add agent endpoint** → add route in `agent.py` → add proxy in `app.py` → call from template JS.

**Add dashboard page** → add route in `app.py` → create `templates/new.html` extending `base.html` → add nav link in `base.html`.

**Change poll interval** → `POLL_INTERVAL_SECONDS` in dashboard `.env`.

**Change theme** → edit CSS custom properties in `static/style.css` `:root` block.

**Add a dependency** → add to `requirements.txt` → rebuild Docker image.

## Development

```bash
# Agent (needs root for postfix commands)
cd agent && python3 agent.py

# Dashboard (local dev — Flask dev server)
cd dashboard && pip install -r requirements.txt && python app.py

# Dashboard (Docker — production with Gunicorn)
cd dashboard && docker compose up --build
```

**Production notes:**
- Dashboard runs under Gunicorn (2 workers, gthread threading)
- Port configurable via .env PORT variable (default 5000)
- Health check verifies login page reachability
- Logs streamed to stdout for container log aggregation

## Conventions

- All timestamps: UTC, ISO-8601.
- Agent always returns JSON. Dashboard proxy routes always return JSON.
- HTTP codes: 200 OK · 401 bad/missing API key · 404 not found · 502 agent unreachable.
- No hardcoded config — everything via .env with sensible defaults.
- Minimal deps — stdlib preferred. No ORMs, no webpack, no transpilation.
- Queue/restart actions require confirmation modals in the UI.

## Not Yet Implemented

- Tests / CI
- HTTPS (use reverse proxy)
- Multi-user auth / roles
- Per-message queue operations
- Database pruning / retention policy
- Gunicorn (Flask dev server is fine for 1-2 users)
