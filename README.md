# Postwatch

A lightweight, two-component Postfix monitoring dashboard for tracking mail server health across your infrastructure.

**Agent** (per mail server) + **Dashboard** (centralized, Docker).

## Features

- **Real-time monitoring** — Queue depth, error counts, delivery status
- **Log streaming** — Live tail of mail logs with search and filtering
- **Queue management** — Flush, delete, or restart operations from the dashboard
- **OAuth token health** — Track token age, expiry, and staleness
- **Multi-server support** — Monitor multiple mail servers from one dashboard
- **Simple authentication** — Single admin user, plaintext credential check
- **No dependencies bloat** — Flask, SQLite, Bootstrap CDN, Chart.js CDN only

## Architecture

```
Agent (×N, systemd, root, :5100)  ←──REST/JSON──→  Dashboard (×1, Docker, :5000)  ←──→  Browser
```

| Component | Role | Transport |
|-----------|------|-----------|
| **Agent** | Runs on each Postfix server. Exposes REST API for queue, logs, status. Talks to Postfix via subprocess. Streams logs via SSE. | REST/JSON over HTTP |
| **Dashboard** | Central Flask app. Polls agents every 2 min → SQLite. Proxies live requests. Serves Bootstrap + Chart.js frontend. | Shared API key (`X-API-Key` header) |

## Tech Stack

| Layer | Tech |
|-------|------|
| **Language** | Python 3.12 |
| **Backend** | Flask (both agent and dashboard) |
| **Database** | SQLite (dashboard only) |
| **Frontend** | Bootstrap 5.3 (CDN), Chart.js 4 (CDN), vanilla JS |
| **Task scheduling** | APScheduler (dashboard) |
| **Streaming** | Server-Sent Events (SSE) |
| **Container** | Docker + Docker Compose |

**No ORM, no npm, no build step.**

## Quick Start

### Option 1: Docker (Dashboard)

```bash
cd dashboard
docker compose up --build
```

Visit `http://localhost:5000` (default credentials: `admin` / `admin`)

### Option 2: Local Development

**Dashboard:**
```bash
cd dashboard
pip install -r requirements.txt
python app.py
```

**Agent:**
```bash
cd agent
pip install flask python-dotenv
python agent.py
```

## Installation

### Agent Installation (Systemd)

Requires: **Linux, root access, Python 3.7+**

```bash
cd agent
sudo ./install.sh
```

The installer will:
- Create `/opt/postwatch-agent/` directory
- Install Python virtual environment
- Copy agent code and configuration
- Install systemd service (`postwatch-agent`)

**After installation:**

1. Edit the agent config:
   ```bash
   sudo nano /opt/postwatch-agent/.env
   ```
   - Set `API_KEY` to a strong random string (must match dashboard's `AGENT_API_KEY`)
   - Set `SERVER_NAME` (e.g., "mail-relay-1")
   - Verify `LOG_FILE`, `HOST`, `PORT`, `TOKEN_DIR`

2. Start the service:
   ```bash
   sudo systemctl start postwatch-agent
   sudo systemctl enable postwatch-agent  # Auto-start on reboot
   ```

3. Check status:
   ```bash
   sudo systemctl status postwatch-agent
   sudo journalctl -u postwatch-agent -f  # View logs
   ```

### Dashboard Installation (Docker)

1. Copy `.env.example` to `.env`:
   ```bash
   cd dashboard
   cp .env.example .env
   ```

2. Edit `.env`:
   ```bash
   nano .env
   ```
   - `SECRET_KEY` — Flask session secret (use a long random string)
   - `ADMIN_USER` / `ADMIN_PASS` — Login credentials
   - `AGENT_API_KEY` — Must match each agent's API_KEY
   - `AGENTS` — Comma-separated list of agent base URLs (e.g., `http://192.168.1.10:5100,http://192.168.1.11:5100`)
   - `POLL_INTERVAL_SECONDS` — How often to poll agents for snapshots (default: 120)

3. Start:
   ```bash
   docker compose up --build
   ```

4. Access at `http://localhost:5005` (port 5005 → 5000 inside container)

## Configuration

### Agent (.env)

```env
# Shared secret — must match dashboard's AGENT_API_KEY
API_KEY=changeme-use-a-long-random-string

# Friendly name shown in dashboard
SERVER_NAME=mail-relay-1

# Path to Postfix mail log
LOG_FILE=/var/log/mail.log

# Bind address and port
HOST=0.0.0.0
PORT=5100

# Token monitoring
TOKEN_DIR=/var/spool/postfix/etc/tokens
TOKEN_STALE_MINUTES=90
TOKEN_EXPIRY_WARN_MINUTES=10
```

### Dashboard (.env)

```env
# Flask session secret
SECRET_KEY=change-me-to-a-long-random-string

# Admin login
ADMIN_USER=admin
ADMIN_PASS=admin

# Agent communication
AGENT_API_KEY=changeme-use-a-long-random-string
AGENTS=http://192.168.1.10:5100,http://192.168.1.11:5100

# Polling interval (seconds)
POLL_INTERVAL_SECONDS=120

# Database
DB_PATH=data/postwatch.db

# Bind
HOST=0.0.0.0
PORT=5000
```

## API Endpoints (Agent)

| Route | Method | Auth | Action |
|-------|--------|------|--------|
| `/health` | GET | — | Health check |
| `/status` | GET | API Key | `systemctl status postfix` |
| `/queue` | GET | API Key | `mailq` output + count |
| `/logs` | GET | API Key | Last 200 lines (supports `?search=` filter) |
| `/logs/stream` | GET | API Key | Real-time log tail (SSE) |
| `/stats` | GET | API Key | Parsed stats → hourly/daily buckets |
| `/token-status` | GET | API Key | Token health (age, expiry, staleness) |
| `/restart` | POST | API Key | `systemctl restart postfix` |
| `/queue/flush` | POST | API Key | `postqueue -f` |
| `/queue/delete` | POST | API Key | `postsuper -d ALL` |

**Auth:** All endpoints except `/health` require `X-API-Key: <API_KEY>` header.

**Responses:** JSON. HTTP codes: `200` OK, `401` bad/missing key, `404` not found, `502` agent unreachable.

## Dashboard Pages

| Page | Purpose |
|------|---------|
| **Overview** | Stat cards + daily/hourly bar charts |
| **Logs** | Log viewer + live streaming + search |
| **Queue** | Queue depth + message count + flush/delete modals |
| **Tokens** | OAuth token health (age, expiry, staleness) |

## Key Patterns

### Adding an Agent Endpoint

1. Add route in `agent/agent.py`:
   ```python
   @app.route('/my-endpoint', methods=['GET'])
   @require_api_key
   def my_endpoint():
       return jsonify({"result": "..."}), 200
   ```

2. Add proxy in `dashboard/app.py`:
   ```python
   @app.route('/api/my-endpoint', methods=['GET'])
   def proxy_my_endpoint():
       return proxy_to_agent(f"/my-endpoint")
   ```

3. Call from frontend template with `fetch('/api/my-endpoint')`.

### Adding a Dashboard Page

1. Create `dashboard/templates/new.html` (extend `base.html`):
   ```html
   {% extends "base.html" %}
   {% block title_suffix %} — New Page{% endblock %}
   {% block content %}
   <div class="container-fluid">
       <!-- Your content -->
   </div>
   {% endblock %}
   ```

2. Add route in `dashboard/app.py`:
   ```python
   @app.route('/new-page')
   def new_page():
       return render_template('new.html')
   ```

3. Add nav link in `dashboard/templates/base.html`.

### Changing the Theme

Edit CSS custom properties in `dashboard/static/style.css` (`:root` block):

```css
:root {
    --primary: #2e3440;
    --accent: #88c0d0;
    /* ... */
}
```

## Development

### Run Agent Locally

```bash
cd agent
python agent.py
# Listens on http://localhost:5100
```

### Run Dashboard Locally

```bash
cd dashboard
pip install -r requirements.txt
python app.py
# Listens on http://localhost:5000
```

### Run Dashboard in Docker

```bash
cd dashboard
docker compose up --build
# Accessible at http://localhost:5005
```

### Running Tests

Currently no tests. PRs welcome! 📝

## Conventions

- **Timestamps** — UTC, ISO-8601 format
- **Agent responses** — Always JSON
- **Authentication** — Shared API key in `X-API-Key` header
- **HTTP codes** — `200` OK, `401` auth failure, `404` not found, `502` unreachable
- **Config** — All via `.env` with sensible defaults
- **Minimal deps** — Prefer stdlib. No ORMs, no transpilation.
- **Safe operations** — Queue/restart actions require UI confirmation modals

## Directory Structure

```
postwatch/
├── README.md                   # This file
├── CLAUDE.md                   # Architecture notes
├── agent/
│   ├── agent.py                # REST API + log streaming
│   ├── agent.py.phase1         # Phase 1 reference
│   ├── install.sh              # Systemd installer (run as root)
│   ├── postwatch-agent.service # Systemd unit file
│   └── .env.example            # Agent config template
├── dashboard/
│   ├── app.py                  # Main Flask app (routes, scheduler)
│   ├── config.py               # Config loader (.env → module vars)
│   ├── models.py               # SQLite schema + query helpers
│   ├── poller.py               # Background job (polls agents)
│   ├── requirements.txt        # Python dependencies
│   ├── Dockerfile              # Container image
│   ├── docker-compose.yml      # Docker Compose config
│   ├── .env.example            # Dashboard config template
│   ├── .env                    # Active config (gitignored)
│   ├── data/                   # SQLite database (gitignored)
│   ├── static/
│   │   └── style.css           # Nord/Slate dark theme
│   └── templates/
│       ├── base.html           # Layout + navbar
│       ├── login.html          # Login form
│       ├── overview.html       # Stats + charts
│       ├── logs.html           # Log viewer + streaming
│       ├── queue.html          # Queue management
│       └── tokens.html         # Token health
└── docs/
    └── private/
        ├── PROMPT.md           # Development notes
        └── TODO.md             # Feature backlog
```

## Troubleshooting

**Dashboard can't reach agent:**
- Verify agent is running: `sudo systemctl status postwatch-agent`
- Check agent logs: `sudo journalctl -u postwatch-agent -f`
- Verify firewall allows port 5100 (or configured PORT)
- Confirm `AGENTS` URL is correct in dashboard `.env`

**Agent won't start:**
- Check config: `cat /opt/postwatch-agent/.env`
- View error logs: `sudo journalctl -u postwatch-agent -f`
- Verify Python venv: `/opt/postwatch-agent/venv/bin/python3 --version`
- Ensure running as root (required for Postfix access)

**Dashboard login fails:**
- Verify `ADMIN_USER` and `ADMIN_PASS` in `.env`
- Check Flask session is working: Clear browser cookies and try again

**No data showing in charts:**
- Verify `POLL_INTERVAL_SECONDS` (default 120 seconds)
- Wait at least one poll cycle after dashboard start
- Check dashboard logs for proxy errors

## Planned Features

- [ ] Tests / CI
- [ ] HTTPS / TLS (use reverse proxy)
- [ ] Multi-user auth / roles
- [ ] Per-message queue operations
- [ ] Database pruning / retention policy
- [ ] Gunicorn deployment (Flask dev server fine for 1-2 users)

## License

[Your License Here]

## Contact

For issues or feature requests, open an issue or contact the maintainer.
