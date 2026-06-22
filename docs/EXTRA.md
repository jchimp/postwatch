
## Configuration Management

The dashboard supports **two configuration methods**:

1. **Environment variables (`.env`)** — Initial setup only, loaded at startup
2. **Database (SQLite)** — Runtime management via **Settings** page, persists across restarts

### Configuration Priority

- If agents or API key are stored in the database, they take precedence over `.env`
- If the database is empty, the dashboard falls back to `.env` for agents and API key
- Start with `.env` and optionally migrate to database-backed config via the **Settings** page

### Agent Storage

When you add/remove agents via the Settings page, they're persisted in the SQLite `agents` table:

```sql
CREATE TABLE agents (
    id        INTEGER PRIMARY KEY,
    url       TEXT NOT NULL UNIQUE,
    name      TEXT,
    created   TEXT NOT NULL,
    updated   TEXT NOT NULL
)
```

Settings (like the API key) are stored in the `settings` table:

```sql
CREATE TABLE settings (
    key       TEXT PRIMARY KEY,
    value     TEXT NOT NULL,
    updated   TEXT NOT NULL
)
```

The poller and all dashboard routes automatically use database-backed config if available.

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
