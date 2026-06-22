# Postwatch

A lightweight, two-component Postfix monitoring dashboard for tracking mail server health across your infrastructure.

**Agent** (per mail server) + **Dashboard** (centralized, Docker).

## Features

- **Real-time monitoring** — Queue depth, error counts, delivery status
- **Log streaming** — Live tail of mail logs with search and filtering
- **Queue management** — Flush, delete, or restart operations from the dashboard
- **OAuth token health** — Track token age, expiry, and staleness
- **Multi-server support** — Monitor multiple mail servers from one dashboard
- **Aggregated views** — "All Hosts" mode to see combined stats across all servers
- **Historical analytics** — 4 time-period charts: hourly, daily, weekly, monthly (single-agent and aggregate)
- **Simple authentication** — Single admin user, plaintext credential check
- **No dependencies bloat** — Flask, SQLite, Bootstrap CDN, Chart.js CDN only

## Architecture

```
Agent (×N, systemd, root, :5100) <--- REST/JSON --->  Dashboard (×1, Docker, :5000)  <--->  Browser
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

### Option 1: Docker (Dashboard) — Local Dev

```bash
cd dashboard
docker compose up --build
```

Visit `http://localhost:5000` (default credentials: `admin` / `admin`)

### Option 2: Local Development (No Docker)

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

### Option 3: Production Install (Systemd + Docker)

See **Installation** section below for production deployment of agent and dashboard.

## Installation

### Agent Installation (Systemd)

Requires: **Linux, root access, Python 3.7+**

First, make the installer executable:
```bash
cd agent
chmod +x install.sh
```

Then run it as root:
```bash
sudo ./install.sh
```

The installer will:
- Create `/opt/postwatch-agent/` directory
- Install Python virtual environment
- Copy agent code and configuration
- Install systemd service (`postwatch-agent`)
- Enable UFW firewall rule for port 5100 (if UFW is installed)

**After installation:**

1. Edit the agent config:
   ```bash
   sudo nano /opt/postwatch-agent/.env
   ```
   - Set `API_KEY` to match the dashboard's key (you'll get this from Settings after starting the dashboard)
   - Verify `LOG_FILE`, `HOST`, `PORT`, `TOKEN_DIR` are correct for your system

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

#### Option 1: Systemd Installation

Requires: **Linux, root access, Docker, docker-compose**

First, make the installer executable:
```bash
cd dashboard
chmod +x install.sh
```

Then run it as root:
```bash
sudo ./install.sh
```

The installer will:
- Create `/opt/postwatch-dashboard/` directory
- Copy all application files (Flask app, templates, static assets)
- Copy configuration template
- Create `data/` directory for SQLite database
- Set appropriate file permissions

**After installation:**

1. Edit the dashboard config:
   ```bash
   sudo nano /opt/postwatch-dashboard/.env
   ```
   - `SECRET_KEY` — Flask session secret (use a long random string)
   - `ADMIN_USER` / `ADMIN_PASS` — Login credentials
   - `POLL_INTERVAL_SECONDS` — Poll interval in seconds (default: 120)

2. Start the dashboard:
   ```bash
   cd /opt/postwatch-dashboard
   docker-compose up --build -d
   ```
   The agent API key is **auto-generated** on first startup and stored in the database.

3. Access at `http://localhost:5000` (or at the port specified in `.env` if PORT was customized)

4. Log in and retrieve the API key:
   - Go to **Settings** → **Agent API Key**
   - Copy this key to each agent's `API_KEY` in `.env`
   - To regenerate anytime: click **Regenerate** on the Settings page

5. View logs:
   ```bash
   docker-compose logs -f
   ```

#### Option 2: Local Development (Without Docker)

For development or testing without Docker:

```bash
cd dashboard
cp .env.example .env
nano .env  # Configure as needed
pip install -r requirements.txt
python app.py  # Flask dev server, for testing only
```

Access at `http://localhost:5000`

**Note:** Uses Flask dev server. For production, use Docker (systemd installation) with Gunicorn.

## Configuration

### Agent (.env)

```env
# Shared secret — must match dashboard's AGENT_API_KEY
API_KEY=changeme-use-a-long-random-string

# Path to Postfix mail log
LOG_FILE=/var/log/mail.log

# Bind address and port
HOST=0.0.0.0
PORT=5100

# Token directory (agent-specific path)
TOKEN_DIR=/var/spool/postfix/etc/tokens
```

**Note:** Agent name, server details, and token thresholds are now configured centrally in the dashboard. Add agents via Dashboard → Settings → Add Agent.

### Dashboard (.env)

These settings are loaded at startup. Some can be changed later via the **Settings** page:

```env
# Flask session secret — NOT configurable via UI
SECRET_KEY=change-me-to-a-long-random-string

# Admin login credentials — NOT configurable via UI
ADMIN_USER=admin
ADMIN_PASS=admin

# Polling interval — NOT configurable via UI (seconds)
POLL_INTERVAL_SECONDS=120

# Database path — NOT configurable via UI
DB_PATH=data/postwatch.db

# Server bind address and port — NOT configurable via UI
HOST=0.0.0.0
PORT=5000
```

**Startup-only settings:** `SECRET_KEY`, `ADMIN_USER`, `ADMIN_PASS`, `POLL_INTERVAL_SECONDS`, `DB_PATH`, `HOST`, and `PORT` require a restart to change.

**Database-backed settings (configurable via Settings page):**
- Agent API key (auto-generated on first startup, regenerate anytime)
- Agent URLs and names (add/remove agents)
- Token thresholds: `TOKEN_STALE_MINUTES` and `TOKEN_EXPIRY_WARN_MINUTES` (applied globally)

## Dashboard Pages

| Page | Purpose |
|------|---------|
| **Overview** | Stat cards + daily/hourly bar charts |
| **Logs** | Log viewer + live streaming + search |
| **Queue** | Queue depth + message count + flush/delete modals |
| **Tokens** | OAuth token health (age, expiry, staleness) |
| **Settings** | Manage agents, regenerate API key |

### Using the Settings Page

After logging in, click **⚙️ Settings** in the navbar to:

- **Display the current API key** used by all agents
- **Regenerate the API key** — generates a new cryptographically secure random key
  - ⚠️ After regenerating, update all agents' `.env` files with the new key
  - The dashboard will use the new key on the next poll cycle
- **View all configured agents** in a table
- **Add agents** — enter agent URL and optional friendly name
  - Format: `http://192.168.1.10:5100`
  - Optional name: `mail-relay-1`
- **Remove agents** — delete from monitoring (requires confirmation)

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

## Documentation

For detailed information, see:

- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — System overview, data flows, database schema, and design patterns (with ASCII diagrams)
- **[docs/API.md](docs/API.md)** — Complete API reference for agent and dashboard endpoints

## Directory Structure

```
postwatch/
├── README.md                   # This file
├── CLAUDE.md                   # Developer notes
├── docs/
│   ├── ARCHITECTURE.md         # System design & data flows
│   └── API.md                  # Complete API reference
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

## License

[Your License Here]

## Contact

For issues or feature requests, open an issue or contact the maintainer.
