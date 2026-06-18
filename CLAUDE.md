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
- **Charts**: Chart.js in `overview.html`. Hourly/daily charts come from the agent's live `/stats` buckets (bucketed by log-entry time) via `/api/stats/<agent>` (single) and `/api/stats/all` (merged). Monthly chart is the only chart still from SQLite deltas (`/api/chart/monthly/`).

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

## Recent Changes

### Multi-Host Aggregation ("All Hosts" View)
- **Feature:** Overview page now includes "All Hosts" dropdown option when 2+ agents configured
- **Stat cards:** Show aggregated totals from latest snapshot of each agent (using MAX, not SUM, to avoid double-counting)
- **Endpoint:** `/api/totals/all` — sums latest snapshots from all agents
- **Implementation:** `get_latest_totals_all()` in models.py

### Live-Bucketed Charts (Hourly + Daily from agent, Monthly from SQLite)
- **Why:** SQLite snapshots are bucketed by *poll time*, not *mail time*. The
  first poll after a restart/log-rotation dumps the whole backlog into one
  bucket → artificial spike (often midnight). Hourly/daily now read the agent's
  `/stats` buckets, which are keyed by actual log-entry timestamps.
- **Hourly:** Last 24 h, bucket key `YYYY-MM-DD HH` (agent local log time).
- **Daily:** Last 7 days, bucket key `YYYY-MM-DD`. Gap-filled to zero in JS
  (`expandHourly`/`expandDaily` in `overview.html`) so dead hours show as empty bars.
- **Monthly:** Last 12 months, still from SQLite deltas (the agent's ~10k-line
  log window can't span months). Weekly chart was removed for the same reason.
- **Endpoints:** `/api/stats/<agent>` (single, proxies agent), `/api/stats/all`
  (fans out + merges buckets server-side), `/api/chart/monthly/{agent|all}` (SQLite).
- **Trade-off:** Hourly/daily history is bounded by what's in the agent's current
  `mail.log` — rotated logs are not visible. Flagged in the chart card headers.
- **Note:** `get_hourly_stats`/`get_daily_stats`/`get_weekly_stats` (+ `_all`)
  were removed from `models.py`. The delta columns now feed only the Monthly
  chart and the Agent Status table's initial server-render.

### API Key Auth Error Handling
- **Before:** Mismatched API key showed "Online · postfix down" (misleading)
- **After:** Check response status code; show "Auth failed" (red) for 401, "Agent error" (yellow) for other errors
- **File:** dashboard/templates/settings.html, `checkAgent()` function

### Install Script Improvements
- **Feature:** `install.sh` now force-overwrites all code files (`-f` flag) and recreates directories (`rm -rf`) to ensure clean upgrades
- **Behavior:** Preserves .env and data/ directory for in-place upgrades
- **Files:** dashboard/install.sh

### Clipboard Copy Fallback
- **Issue:** Clipboard API requires HTTPS; fallback to `execCommand` for HTTP (local dev)
- **File:** dashboard/templates/settings.html, `copyApiKey()` + `copyFallback()`

## Not Yet Implemented

- Tests / CI
- HTTPS (use reverse proxy)
- Multi-user auth / roles
- Per-message queue operations
- Database pruning / retention policy
- Gunicorn (Flask dev server is fine for 1-2 users)
