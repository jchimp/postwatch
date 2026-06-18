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
- **Charts**: Chart.js in `overview.html`. All four charts read SQLite **bucket tables** via `/api/charts/<agent>` and `/api/charts/all`. Buckets are backfilled each poll from the agent's `/stats` (keyed by mail-processing time), so history survives log rotation. Stat **cards** stay live from `/api/stats/<agent>` and `/api/stats/all` (current-window totals).

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

### Persisted Bucket Charts (accurate history, survives log rotation)
- **Why:** The original SQLite snapshots were bucketed by *poll time*, not *mail
  time* — the first poll after a restart/log-rotation dumped the whole backlog
  into one bucket → artificial midnight spike. The agent now timestamps each log
  line correctly (`_parse_log_timestamp` handles ISO-8601 + BSD syslog), and the
  poller persists those accurate buckets so charts have durable history.
- **Tables:** `hourly_buckets` / `daily_buckets`, PK `(agent_url, bucket)`.
  Bucket keys are agent-local `YYYY-MM-DD HH` / `YYYY-MM-DD`.
- **UPSERT with `MAX(existing, new)`** (`upsert_buckets` in `models.py`): a bucket
  grows while its hour/day is fully inside the agent's log window, then freezes at
  the complete value once older lines scroll off. No deltas, no double-counting.
- **Charts:** Hourly (24 h) + Daily (7 d) read buckets directly, gap-filled to
  zero bars in JS (`expandHourly`/`expandDaily`). Weekly (4 w) + Monthly (12 mo)
  are rolled up from `daily_buckets` in SQL (`get_period_rollup`).
- **Endpoints:** `/api/charts/<agent>` and `/api/charts/all` return
  `{hourly, daily, weekly, monthly}`. Cards use `/api/stats/<agent>` and
  `/api/stats/all` (live current-window totals).
- **`stats_snapshots` slimmed** to point-in-time state only (`queue_count`,
  `token_status`, `active`, `ts`) — feeds the Agent Status table. All delta /
  `raw_*` columns and `_compute_delta` were removed; the poller no longer
  computes deltas. **Schema changed → existing DB must be recreated.**
- **Trade-off:** Buckets older than the agent's first poll are never seen; the
  very oldest in-window hour at first-ever poll may be slightly undercounted.

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
