# Postwatch API Reference

Complete API reference for agent and dashboard endpoints.

## Agent API (`http://<agent>:5100`)

All endpoints except `/health` require `X-API-Key: <api_key>` header.

### Health Check

**GET `/health`**

No authentication required. Used for liveness checks.

```
GET /health HTTP/1.1

200 OK
{
  "status": "ok",
  "server_name": "postwatch-agent",
  "ts": "2026-06-15T19:00:00+00:00"
}
```

---

### Service Status

**GET `/status`**

Return current Postfix service state.

```
GET /status HTTP/1.1
X-API-Key: abc123...

200 OK
{
  "server_name": "mail-relay-1",
  "active": true,
  "active_text": "active",
  "status_text": "● postfix.service - Postfix Mail Transport Agent\n...",
  "ts": "2026-06-15T19:00:00+00:00"
}
```

**Response:**
- `active` — boolean, true if `systemctl is-active postfix` returns 0
- `active_text` — raw output from `systemctl is-active postfix`
- `status_text` — full `systemctl status` output
- `ts` — ISO-8601 UTC timestamp

---

### Mail Queue

**GET `/queue`**

Return current mail queue status.

```
GET /queue HTTP/1.1
X-API-Key: abc123...

200 OK
{
  "server_name": "mail-relay-1",
  "queue_count": 5,
  "raw": "-CAB3Rxxx (1234 bytes) user@example.com\n...",
  "ts": "2026-06-15T19:00:00+00:00"
}
```

**Response:**
- `queue_count` — integer, number of messages in queue
- `raw` — full output from `mailq` command

---

### Mail Logs

**GET `/logs`**

Last 200 lines of mail log with optional search filter.

```
GET /logs?search=status%3Dsent HTTP/1.1
X-API-Key: abc123...

200 OK
{
  "server_name": "mail-relay-1",
  "log_file": "/var/log/mail.log",
  "count": 5,
  "lines": [
    "Jun 15 19:00:00 mail1 postfix/smtp[12345]: ABC123: to=<user@example.com>, status=sent",
    ...
  ],
  "ts": "2026-06-15T19:00:00+00:00"
}
```

**Query params:**
- `search` (optional) — filter lines (case-insensitive substring match)

**Response:**
- `count` — number of lines returned (after filter)
- `lines` — array of log lines

---

### Log Streaming (SSE)

**GET `/logs/stream`**

Real-time log tail via Server-Sent Events. Connection stays open; new lines streamed as they appear.

```
GET /logs/stream HTTP/1.1
X-API-Key: abc123...

200 OK
Content-Type: text/event-stream

data: {"line": "Jun 15 19:05:00 mail1 postfix/smtp[12345]: ABC123: to=<user@example.com>, status=sent", "ts": "2026-06-15T19:05:00+00:00"}

data: {"line": "Jun 15 19:05:02 mail1 postfix/smtp[12346]: DEF456: to=<admin@example.com>, status=sent", "ts": "2026-06-15T19:05:02+00:00"}

...
```

**Client-side usage:**
```javascript
const eventSource = new EventSource('/api/logs/stream/' + encodeURIComponent(agentUrl));
eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log(data.line);  // new log line
};
```

---

### Mail Statistics

**GET `/stats`**

Parse mail log and return send/error totals with hourly and daily buckets.

```
GET /stats HTTP/1.1
X-API-Key: abc123...

200 OK
{
  "server_name": "mail-relay-1",
  "log_file": "/var/log/mail.log",
  "lines_parsed": 10000,
  "totals": {
    "sent": 105,
    "deferred": 8,
    "bounced": 3,
    "rejected": 2
  },
  "hourly": {
    "2026-06-15 19": { "sent": 15, "deferred": 1, "bounced": 0, "rejected": 0 },
    "2026-06-15 20": { "sent": 20, "deferred": 2, "bounced": 1, "rejected": 0 },
    ...
  },
  "daily": {
    "2026-06-15": { "sent": 105, "deferred": 8, "bounced": 3, "rejected": 2 },
    ...
  },
  "ts": "2026-06-15T20:30:00+00:00"
}
```

**Response:**
- `totals` — cumulative counts from today's logs (running total)
- `hourly` — grouped by hour (YYYY-MM-DD HH)
- `daily` — grouped by day (YYYY-MM-DD)
- `lines_parsed` — how many log lines were analyzed

**Note:** Counts are **cumulative from logs**, not incremental. Each call returns the current day's total.

---

### OAuth Token Health

**GET `/token-status`**

Check age and expiry of OAuth token files in TOKEN_DIR.

```
GET /token-status HTTP/1.1
X-API-Key: abc123...
X-Token-Stale-Minutes: 90
X-Token-Expiry-Warn-Minutes: 10

200 OK
{
  "token_dir": "/var/spool/postfix/etc/tokens",
  "thresholds": {
    "stale_minutes": 90,
    "expiry_warn_minutes": 10
  },
  "tokens": [
    {
      "path": "/var/spool/postfix/etc/tokens/sasl-xoauth2",
      "filename": "sasl-xoauth2",
      "mtime_iso": "2026-06-13T08:00:00+00:00",
      "age_minutes": 2880,
      "expiry_iso": "2026-07-01T00:00:00+00:00",
      "expiry_minutes_remaining": 10080,
      "status": "ok"
    }
  ],
  "ts": "2026-06-15T20:30:00+00:00"
}
```

**Request headers:**
- `X-Token-Stale-Minutes` — override global threshold (optional)
- `X-Token-Expiry-Warn-Minutes` — override global threshold (optional)

**Response:**
- `status` — "ok", "stale", "expiring_soon", or "expired"
- `age_minutes` — how long since token file was modified
- `expiry_minutes_remaining` — seconds until expiry (if available in token JSON)

**Errors:**
- 404 — TOKEN_DIR not configured on agent

---

### Service Control: Restart

**POST `/restart`**

Restart the Postfix service.

```
POST /restart HTTP/1.1
X-API-Key: abc123...

200 OK
{
  "server_name": "mail-relay-1",
  "success": true,
  "message": "Postfix restarted",
  "ts": "2026-06-15T20:30:00+00:00"
}
```

**Response:**
- `success` — boolean, true if `systemctl restart postfix` returned 0

---

### Service Control: Queue Flush

**POST `/queue/flush`**

Attempt immediate delivery of deferred mail.

```
POST /queue/flush HTTP/1.1
X-API-Key: abc123...

200 OK
{
  "server_name": "mail-relay-1",
  "success": true,
  "message": "Queue flushed",
  "ts": "2026-06-15T20:30:00+00:00"
}
```

**Equivalent to:** `postqueue -f`

---

### Service Control: Queue Delete

**POST `/queue/delete`**

Delete ALL messages from the mail queue.

```
POST /queue/delete HTTP/1.1
X-API-Key: abc123...

200 OK
{
  "server_name": "mail-relay-1",
  "success": true,
  "message": "All queued messages deleted",
  "ts": "2026-06-15T20:30:00+00:00"
}
```

**⚠️ Destructive:** Deletes all messages. Requires dashboard UI confirmation before calling.

**Equivalent to:** `postsuper -d ALL`

---

## Dashboard API (`http://<dashboard>:5000`)

All endpoints require login (session-based). Most endpoints proxy to agents.

### Authentication

**GET `/login` / POST `/login`**

```
GET /login
→ HTML login form

POST /login
Content-Type: application/x-www-form-urlencoded

username=admin&password=admin

200 OK
Sets session['logged_in'] = True
Redirects to /overview
```

All other endpoints check `session['logged_in']` and redirect to `/login` if not present.

---

### Pages

These return HTML (not JSON). For API calls, see proxy routes below.

- **GET `/`** — Redirects to `/overview`
- **GET `/overview`** — Dashboard home (stat cards + 4 charts)
- **GET `/logs`** — Log viewer page
- **GET `/queue`** — Queue management page
- **GET `/tokens`** — OAuth token health page
- **GET `/settings`** — Agent & API key configuration page

---

### API: Agent Management

**GET `/api/agents`**

List all configured agents.

```
GET /api/agents HTTP/1.1

200 OK
[
  { "url": "http://192.168.1.10:5100", "display": "mail-relay-1" },
  { "url": "http://192.168.1.11:5100", "display": "mail-relay-2" }
]
```

---

**POST `/api/agents`**

Add a new agent.

```
POST /api/agents HTTP/1.1
Content-Type: application/json

{ "url": "http://192.168.1.12:5100", "name": "mail-relay-3" }

201 Created
{ "success": true, "url": "http://192.168.1.12:5100" }

400 Bad Request
{ "error": "agent already exists" }
```

---

**DELETE `/api/agents/<id>`**

Remove an agent.

```
DELETE /api/agents/3 HTTP/1.1

200 OK
{ "success": true }

404 Not Found
{ "error": "agent not found" }
```

---

### API: Settings

**GET `/api/settings/api-key`**

Get current API key (for copying to agent .env files).

```
200 OK
{ "api_key": "abc123def456..." }
```

---

**POST `/api/settings/api-key`**

Generate a new API key.

```
POST /api/settings/api-key HTTP/1.1

200 OK
{ "api_key": "xyz789uvw012..." }
```

⚠️ All agents must update their API_KEY in .env before next poll cycle.

---

**GET `/api/settings/token-thresholds`**

Get current token health thresholds.

```
200 OK
{
  "stale_minutes": 90,
  "expiry_warn_minutes": 10
}
```

---

**POST `/api/settings/token-thresholds`**

Update token health thresholds (global).

```
POST /api/settings/token-thresholds HTTP/1.1
Content-Type: application/json

{
  "stale_minutes": 120,
  "expiry_warn_minutes": 15
}

200 OK
{
  "stale_minutes": 120,
  "expiry_warn_minutes": 15
}
```

---

### API: Health & Status (Proxy)

These proxy to agent endpoints.

**GET `/api/health/<agent_url>`**

Lightweight reachability check.

```
GET /api/health/http%3A%2F%2F192.168.1.10%3A5100 HTTP/1.1

200 OK
{ "status": "ok", "server_name": "mail-relay-1", ... }

502 Bad Gateway
{ "error": "..." }  (if agent unreachable)
```

---

**GET `/api/status/<agent_url>`**

Postfix service status.

```
GET /api/status/http%3A%2F%2F192.168.1.10%3A5100 HTTP/1.1

200 OK
{ "active": true, "active_text": "active", ... }

401 Unauthorized
{ "error": "..." }  (API key mismatch)

502 Bad Gateway
{ "error": "..." }  (if agent unreachable)
```

---

### API: Queue (Proxy)

**GET `/api/queue/<agent_url>`**

Current queue depth.

```
GET /api/queue/http%3A%2F%2F192.168.1.10%3A5100 HTTP/1.1

200 OK
{ "queue_count": 5, "raw": "...", ... }
```

---

**POST `/api/queue/flush/<agent_url>`**

Flush the queue.

```
POST /api/queue/flush/http%3A%2F%2F192.168.1.10%3A5100 HTTP/1.1

200 OK
{ "success": true, "message": "Queue flushed", ... }
```

---

**POST `/api/queue/delete/<agent_url>`**

Delete all queued messages.

```
POST /api/queue/delete/http%3A%2F%2F192.168.1.10%3A5100 HTTP/1.1

200 OK
{ "success": true, "message": "All queued messages deleted", ... }
```

---

### API: Logs (Proxy)

**GET `/api/logs/<agent_url>`**

Last 200 log lines (supports search filter).

```
GET /api/logs/http%3A%2F%2F192.168.1.10%3A5100?search=status%3Dsent HTTP/1.1

200 OK
{
  "log_file": "/var/log/mail.log",
  "count": 25,
  "lines": [ "...", "...", ... ]
}
```

---

**GET `/api/logs/stream/<agent_url>`**

Real-time log streaming (SSE).

```
GET /api/logs/stream/http%3A%2F%2F192.168.1.10%3A5100 HTTP/1.1

200 OK
Content-Type: text/event-stream

data: { "line": "...", "ts": "..." }
data: { "line": "...", "ts": "..." }
...
```

---

### API: Statistics (Proxy)

**GET `/api/stats/<agent_url>`**

Live log statistics (sent, deferred, bounced, rejected totals).

```
GET /api/stats/http%3A%2F%2F192.168.1.10%3A5100 HTTP/1.1

200 OK
{
  "totals": { "sent": 105, "deferred": 8, "bounced": 3, "rejected": 2 },
  "hourly": { "2026-06-15 19": {...}, ... },
  "daily": { "2026-06-15": {...}, ... }
}
```

---

### API: Token Status (Proxy)

**GET `/api/token-status/<agent_url>`**

OAuth token health.

```
GET /api/token-status/http%3A%2F%2F192.168.1.10%3A5100 HTTP/1.1

200 OK
{
  "token_dir": "/var/spool/postfix/etc/tokens",
  "tokens": [
    {
      "filename": "sasl-xoauth2",
      "status": "ok",
      "age_minutes": 2880,
      "expiry_iso": "2026-07-01T00:00:00+00:00",
      ...
    }
  ]
}
```

---

### API: Service Control (Proxy)

**POST `/api/restart/<agent_url>`**

Restart Postfix.

```
POST /api/restart/http%3A%2F%2F192.168.1.10%3A5100 HTTP/1.1

200 OK
{ "success": true, "message": "Postfix restarted", ... }
```

---

### API: Historical Chart Data (SQLite)

These query the dashboard's SQLite database (not proxied to agents).

**GET `/api/chart/daily/<agent_url>`**

7 days of daily totals (from stats_snapshots).

```
GET /api/chart/daily/http%3A%2F%2F192.168.1.10%3A5100?days=7 HTTP/1.1

200 OK
[
  { "day": "2026-06-09", "sent": 105, "deferred": 8, "bounced": 3, "rejected": 2 },
  { "day": "2026-06-10", "sent": 112, "deferred": 5, "bounced": 2, "rejected": 1 },
  ...
]
```

**Query params:**
- `days` (optional, default 7) — number of days to return

---

**GET `/api/chart/hourly/<agent_url>`**

24 hours of hourly totals.

```
GET /api/chart/hourly/http%3A%2F%2F192.168.1.10%3A5100?hours=24 HTTP/1.1

200 OK
[
  { "hour": "2026-06-15 19", "sent": 15, "deferred": 1, "bounced": 0, "rejected": 0 },
  { "hour": "2026-06-15 20", "sent": 20, "deferred": 2, "bounced": 1, "rejected": 0 },
  ...
]
```

---

**GET `/api/chart/weekly/<agent_url>`**

4 weeks of weekly totals.

```
GET /api/chart/weekly/http%3A%2F%2F192.168.1.10%3A5100?weeks=4 HTTP/1.1

200 OK
[
  { "week": "2026-W23", "sent": 750, "deferred": 60, "bounced": 20, "rejected": 10 },
  { "week": "2026-W24", "sent": 840, "deferred": 50, "bounced": 15, "rejected": 8 },
  ...
]
```

---

**GET `/api/chart/monthly/<agent_url>`**

12 months of monthly totals.

```
GET /api/chart/monthly/http%3A%2F%2F192.168.1.10%3A5100?months=12 HTTP/1.1

200 OK
[
  { "month": "2025-07", "sent": 3000, "deferred": 200, "bounced": 50, "rejected": 25 },
  { "month": "2025-08", "sent": 3200, "deferred": 180, "bounced": 45, "rejected": 20 },
  ...
]
```

---

### API: Aggregated Stats (All Hosts)

**GET `/api/totals/all`**

Latest aggregated totals from all agents (for stat cards).

```
GET /api/totals/all HTTP/1.1

200 OK
{
  "totals": {
    "sent": 210,      (agent1: 105 + agent2: 105)
    "deferred": 16,
    "bounced": 6,
    "rejected": 4
  }
}
```

**How it works:**
1. Get the most recent snapshot per agent
2. Sum their totals
3. Return aggregated values

Used by "All Hosts" mode on overview page to show combined totals.

---

**GET `/api/chart/daily/all`**

7 days of aggregated daily totals.

```
GET /api/chart/daily/all?days=7 HTTP/1.1

200 OK
[
  { "day": "2026-06-09", "sent": 210, "deferred": 16, "bounced": 6, "rejected": 4 },
  { "day": "2026-06-10", "sent": 224, "deferred": 10, "bounced": 4, "rejected": 2 },
  ...
]
```

---

**GET `/api/chart/hourly/all`**

24 hours of aggregated hourly totals.

```
GET /api/chart/hourly/all?hours=24 HTTP/1.1

200 OK
[
  { "hour": "2026-06-15 19", "sent": 30, "deferred": 2, "bounced": 0, "rejected": 0 },
  { "hour": "2026-06-15 20", "sent": 40, "deferred": 4, "bounced": 2, "rejected": 0 },
  ...
]
```

---

**GET `/api/chart/weekly/all`**

4 weeks of aggregated weekly totals.

```
GET /api/chart/weekly/all?weeks=4 HTTP/1.1

200 OK
[
  { "week": "2026-W23", "sent": 1500, "deferred": 120, "bounced": 40, "rejected": 20 },
  ...
]
```

---

**GET `/api/chart/monthly/all`**

12 months of aggregated monthly totals.

```
GET /api/chart/monthly/all?months=12 HTTP/1.1

200 OK
[
  { "month": "2025-07", "sent": 6000, "deferred": 400, "bounced": 100, "rejected": 50 },
  ...
]
```

---

## URL Encoding

Agent URLs contain colons and slashes, so they must be URL-encoded in the request path:

```
http://192.168.1.10:5100
↓
http%3A%2F%2F192.168.1.10%3A5100
```

JavaScript: `encodeURIComponent(url)`
Python: `urllib.parse.quote(url, safe='')`

---

## Error Responses

All endpoints return JSON errors:

```
401 Unauthorized
{ "error": "Unauthorized" }

404 Not Found
{ "error": "Log file not found: /var/log/mail.log" }

502 Bad Gateway
{ "error": "..." }  (agent unreachable)

500 Internal Server Error
{ "error": "..." }  (dashboard error, check logs)
```

---

## Rate Limiting

None. Design assumes internal network only.

---

## CORS

Not enabled. Dashboard and agents are accessed from the same origin (dashboard proxies all agent calls).
