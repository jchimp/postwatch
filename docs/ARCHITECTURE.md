# Postwatch Architecture

A lightweight, distributed Postfix monitoring system. Agents on mail servers send data to a central dashboard.

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         BROWSER / CLIENT                             │
│                      (HTTP, port 5000)                              │
└──────────────────────────────────────┬──────────────────────────────┘
                                       │
                          HTTPS/HTTP (JSON)
                                       │
┌──────────────────────────────────────▼──────────────────────────────┐
│                      POSTWATCH DASHBOARD                             │
│                     (Docker, :5000, Docker)                         │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  Flask App (app.py)                                            │ │
│  │  - Login & auth (session-based)                                │ │
│  │  - Routes (overview, logs, queue, tokens, settings)            │ │
│  │  - Proxies to agents via /api/*                                │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                       │                              │
│  ┌─────────────────────────────┬─────▼─────────────────────────────┐ │
│  │ Poller (poller.py)          │  SQLite (data/postwatch.db)       │ │
│  │ Every 2 min (APScheduler):  │  ┌─────────────────────────────┐ │ │
│  │ - Polls /stats, /status,    │  │ stats_snapshots (history)   │ │ │
│  │   /queue, /token-status     │  │ agents (config)             │ │ │
│  │   from each agent           │  │ settings (api key, etc)     │ │ │
│  │ - Stores in SQLite          │  └─────────────────────────────┘ │ │
│  └─────────────────────────────┴──────────────────────────────────┘ │
│                                                                      │
└──────────────────────────────────────┬──────────────────────────────┘
                                       │
                          HTTP/REST, X-API-Key header
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
        ┌───────────▼────────┐ ┌───────▼────────┐ ┌───────▼────────┐
        │  AGENT 1 (mail1)   │ │  AGENT 2       │ │  AGENT N       │
        │  (systemd, :5100)  │ │  (systemd)     │ │  (systemd)     │
        │                    │ │                │ │                │
        │  Flask REST API    │ │  Flask REST    │ │  Flask REST    │
        │  /health           │ │  /health       │ │  /health       │
        │  /status           │ │  /status       │ │  /status       │
        │  /stats            │ │  /stats        │ │  /stats        │
        │  /queue            │ │  /queue        │ │  /queue        │
        │  /logs /logs/stream│ │  /logs         │ │  /logs         │
        │  /token-status     │ │  /token-status │ │  /token-status │
        │  /restart          │ │  /restart      │ │  /restart      │
        │  /queue/flush      │ │  /queue/flush  │ │  /queue/flush  │
        │  /queue/delete     │ │  /queue/delete │ │  /queue/delete │
        │                    │ │                │ │                │
        │ Postfix commands:  │ │ Postfix cmds   │ │ Postfix cmds   │
        │ systemctl, mailq   │ │ systemctl      │ │ systemctl      │
        │ postqueue, postfix │ │ mailq          │ │ mailq          │
        │ token file reading │ │ postqueue      │ │ postqueue      │
        │ mail.log tailing   │ │ mail.log       │ │ mail.log       │
        └────────────────────┘ │ tailing        │ │ tailing        │
                               └────────────────┘ │                │
                                                  └────────────────┘
```

## Data Flow

### 1. Polling Cycle (Every 120 seconds)

```
┌─────────────────────────────────────────────────────────────┐
│  Poller (APScheduler) wakes up                              │
└──────────────────────────┬──────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
    ┌─────────┐       ┌─────────┐       ┌─────────┐
    │ Agent 1 │       │ Agent 2 │       │ Agent N │
    └────┬────┘       └────┬────┘       └────┬────┘
         │                 │                 │
         │ HTTP GET        │ HTTP GET        │ HTTP GET
         │ /stats          │ /stats          │ /stats
         │ /status         │ /status         │ /status
         │ /queue          │ /queue          │ /queue
         │ /token-status   │ /token-status   │ /token-status
         │ (w/ X-API-Key)  │ (w/ X-API-Key)  │ (w/ X-API-Key)
         │                 │                 │
         │ ┌───────────────┼──────────────┐  │
         └─┤               │              ├──┘
           │               │              │
           └───────────────┼──────────────┘
                           │
                    JSON Response:
                    {
                      "totals": {...},
                      "active": true,
                      "queue_count": 5,
                      "tokens": [...]
                    }
                           │
           ┌───────────────┼──────────────┐
           │               │              │
           ▼               ▼              ▼
      ┌─────────┐     ┌─────────┐    ┌─────────┐
      │ Parse   │     │ Parse   │    │ Parse   │
      │ Response│     │ Response│    │ Response│
      └────┬────┘     └────┬────┘    └────┬────┘
           │               │              │
           │  Save Snapshot (insert into stats_snapshots)
           │  - agent_url, ts, sent, deferred, bounced, rejected, etc
           │  - One row per agent per poll cycle
           │
           └───────────────┬──────────────┐
                           ▼
                    SQLite Database
                    (stats_snapshots)
```

### 2. Dashboard Frontend Request → API Response

```
Browser                    Dashboard              Agent
   │                            │                  │
   │ Click "All Hosts"          │                  │
   │                            │                  │
   ├─ GET /overview ───────────>│                  │
   │                            │                  │
   │<───────── overview.html ────┤                  │
   │ (with agent dropdown)       │                  │
   │                            │                  │
   │ JavaScript runs,           │                  │
   │ /api/status/{agent} called  │                  │
   │                            │                  │
   ├─ GET /api/status/all ─────>│                  │
   │ (or /api/status/{url})     │ GET /status ────>│
   │                            │ (X-API-Key hdr)  │
   │                            │<─── JSON ───────┤
   │<──── JSON (agg or single)──┤                  │
   │                            │                  │
   │ JavaScript renders cards   │                  │
   │ and builds charts          │                  │
   │                            │                  │
   ├─ GET /api/chart/daily/all ─┤                  │
   │                            │ Query SQLite    │
   │<──── JSON (7 rows) ────────┤ (aggregated)     │
   │                            │                  │
   │ Chart.js draws bars        │                  │
```

## Database Schema

### stats_snapshots
Stores historical polling data from agents. One row per agent per poll cycle.

```sql
CREATE TABLE stats_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_url     TEXT NOT NULL,              -- HTTP URL of agent
    server_name   TEXT,                       -- Display name (from agent /status)
    ts            TEXT NOT NULL,              -- ISO-8601 timestamp (UTC)
    sent          INTEGER DEFAULT 0,          -- Cumulative from log parse
    deferred      INTEGER DEFAULT 0,          -- Cumulative from log parse
    bounced       INTEGER DEFAULT 0,          -- Cumulative from log parse
    rejected      INTEGER DEFAULT 0,          -- Cumulative from log parse
    queue_count   INTEGER DEFAULT 0,          -- Current mailq depth
    token_status  TEXT,                       -- JSON array of token health
    active        INTEGER DEFAULT 1           -- Boolean: postfix active?
);

CREATE INDEX idx_snapshots_agent_ts 
    ON stats_snapshots (agent_url, ts);
```

**Key insight:** `sent`, `deferred`, `bounced`, `rejected` are **cumulative running totals from the logs**, not incremental counts. Each poll captures the current day's total. Aggregation functions use `MAX()` to get the latest value per agent, not `SUM()`.

### agents
Configured mail servers being monitored.

```sql
CREATE TABLE agents (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    url       TEXT NOT NULL UNIQUE,  -- http://192.168.1.10:5100
    name      TEXT,                  -- "mail-relay-1" (optional)
    created   TEXT NOT NULL,         -- ISO-8601 timestamp
    updated   TEXT NOT NULL          -- Last modified
);
```

**Note:** Agents are added via dashboard Settings page or seeded from .env at startup.

### settings
Key-value store for global dashboard config.

```sql
CREATE TABLE settings (
    key       TEXT PRIMARY KEY,
    value     TEXT NOT NULL,
    updated   TEXT NOT NULL  -- ISO-8601 timestamp
);
```

**Common keys:**
- `AGENT_API_KEY` — Shared secret for agent authentication (auto-generated on first startup)
- `TOKEN_STALE_MINUTES` — Warn if token not modified in N minutes (default 90)
- `TOKEN_EXPIRY_WARN_MINUTES` — Warn if token expires in N minutes (default 10)

## API Key & Authentication

**Shared Secret Model:**
- One API key for all agents, stored in dashboard `settings` table
- Generated cryptographically secure random string on first dashboard startup
- Displayed and regenerable via dashboard Settings page
- Passed to agents in HTTP header: `X-API-Key: <key>`
- Agent verifies on every request (except `/health`)

**Flow:**
```
1. Dashboard starts → generates and stores AGENT_API_KEY in SQLite
2. Admin copies key from Settings page
3. Admin pastes into each agent's .env (AGENT_API_KEY=...)
4. Poller sends: GET /stats HTTP/1.1\n  X-API-Key: <key>
5. Agent @require_api_key decorator checks header
6. If mismatch → 401 Unauthorized
```

**Dashboard to Agent:**
- Header: `X-API-Key: <shared-secret>`
- Also passes token thresholds: `X-Token-Stale-Minutes`, `X-Token-Expiry-Warn-Minutes`

**Dashboard User to Dashboard:**
- Session-based (Flask `session['logged_in']`)
- Single hardcoded user: `ADMIN_USER` / `ADMIN_PASS` from .env
- Plaintext password check (suitable for internal tools)

## Historical Data Aggregation

### Daily Stats (Last 7 days)
```
Snapshot: {ts: "2026-06-15T12:00:00+00:00", sent: 105, ...}
Snapshot: {ts: "2026-06-15T12:02:00+00:00", sent: 105, ...}  ← same total
Snapshot: {ts: "2026-06-15T14:30:00+00:00", sent: 120, ...}

Aggregation (for stat cards):
SELECT MAX(sent) AS sent FROM stats_snapshots WHERE date(ts) = '2026-06-15'
→ 120 (latest snapshot's value)

Aggregation (across agents):
SELECT agent_url, MAX(sent) FROM stats_snapshots WHERE date(ts) = '2026-06-15'
GROUP BY agent_url
→ agent1: 120, agent2: 98
Then sum: 218
```

### Weekly & Monthly Stats
```
SELECT strftime('%Y-W%W', ts) AS week, SUM(sent) AS sent
FROM stats_snapshots
WHERE ts >= datetime('now', '-4 weeks')
GROUP BY week
ORDER BY week

Caveat: Uses SUM of daily MAX values to show volume across servers.
Each daily bucket is the final value for that day across all agents.
```

## Configuration Loading Order

```
Dashboard startup:
1. Load .env file (python-dotenv)
   - SECRET_KEY, ADMIN_USER, ADMIN_PASS (required at startup)
   - POLL_INTERVAL_SECONDS, DB_PATH, HOST, PORT
   - AGENTS, AGENT_API_KEY (fallback only)

2. Initialize SQLite
   - Create tables if not exist
   - Auto-generate AGENT_API_KEY if not in settings table

3. Check for agents in settings table
   - If found: use database agents
   - If not found: migrate from .env AGENTS list (one-time)

4. Poller reads from database:
   - agents table (active URLs)
   - settings table (API key)
   - settings table (token thresholds)

Updating agents:
- Via Settings page (add/remove) → written to agents table
- Poller automatically picks up changes on next cycle (no restart needed)

Updating API key:
- Via Settings page (regenerate)
- New key written to settings table
- Takes effect on next poll cycle
- ⚠️ Agents must have updated .env API_KEY before then
```

## Frontend Data Binding

**Overview Page** (4 charts + stat cards):

```
User selects dropdown: "All Hosts" or "mail-relay-1" (agent.display)

If "All Hosts":
  - Fetch /api/totals/all → stat cards (sent, deferred, bounced, queue)
  - Fetch /api/chart/daily/all?days=7 → daily bar chart (SUM by day)
  - Fetch /api/chart/hourly/all?hours=24 → hourly bar chart (SUM by hour)
  - Fetch /api/chart/weekly/all?weeks=4 → weekly bar chart
  - Fetch /api/chart/monthly/all?months=12 → monthly bar chart

If single agent (e.g., "http://192.168.1.10:5100"):
  - Fetch /api/status/{enc(url)} → Live "Active"/"Inactive" + stat cards
  - Fetch /api/stats/{enc(url)} → Live totals (from agent log parse)
  - Fetch /api/queue/{enc(url)} → Live queue depth
  - Fetch /api/chart/daily/{enc(url)}?days=7 → historical daily
  - Fetch /api/chart/hourly/{enc(url)}?hours=24 → historical hourly
  - Fetch /api/chart/weekly/{enc(url)}?weeks=4 → historical weekly
  - Fetch /api/chart/monthly/{enc(url)}?months=12 → historical monthly
```

**Other pages:**

- **Logs**: Fetch /api/logs/{enc(url)} + stream /api/logs/stream/{enc(url)} (SSE)
- **Queue**: Fetch /api/queue/{enc(url)} + POST /api/queue/flush, /api/queue/delete
- **Tokens**: Fetch /api/token-status/{enc(url)}
- **Settings**: Fetch /api/agents, POST /api/agents, DELETE /api/agents/{id}

## Error Handling & Status Codes

| Code | Scenario | Recovery |
|------|----------|----------|
| 200 | Success | Display data |
| 401 | Agent API key mismatch | Show "Auth failed" in UI |
| 404 | Agent endpoint doesn't exist | Show "Agent error" in UI |
| 502 | Agent unreachable (network) | Show "Unreachable" in UI |
| 500 | Dashboard internal error | Show error message, check logs |

**Auth Error Detection (Overview page):**
```javascript
if (r.status === 401) {
    label.textContent = 'Auth failed';  // API key mismatch
} else if (!r.ok) {
    label.textContent = 'Agent error';  // Other 4xx/5xx
}
```

## Upgrade & Deployment

### Fresh Install
```bash
1. Clone repo
2. cd agent && sudo ./install.sh
3. cd dashboard && sudo ./install.sh
4. Edit agent .env: API_KEY, LOG_FILE, TOKEN_DIR
5. Start dashboard container, get API key from Settings
6. Paste API key into agent .env files
7. Restart agents
```

### In-Place Upgrade
```bash
1. git pull origin main (or reclone)
2. cd dashboard && sudo ./install.sh
   - Force overwrites all .py, templates, static
   - Preserves .env and data/ directory
3. Restart dashboard container
4. Agents unchanged (unless you upgrade them too)
```

**install.sh behavior:**
```bash
cp -f app.py ...      # Force overwrite Python files
cp -f models.py ...
rm -rf templates/     # Clean slate for UI changes
cp -r templates/ ...
# Preserves .env and data/ (config + database)
```
