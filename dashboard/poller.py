"""
postwatch dashboard — poller.py
Background job that polls each agent and persists its data to SQLite.

Two things are stored per cycle:
  - Volume buckets (hourly + daily) — UPSERTed from the agent's /stats buckets,
    which are keyed by the time each message was processed. This is the accurate
    mail-volume history the charts read.
  - A point-in-time snapshot — postfix active state, queue depth, token health,
    and the poll timestamp. Feeds the Agent Status table.
"""

import json
from datetime import datetime, timezone

import requests

import config
import models
from models import save_snapshot, upsert_buckets


def poll_agents() -> None:
    """Poll every configured agent for stats, status, queue, and token health."""
    agents = models.get_agents(config.DB_PATH)

    # Get API key from database, fall back to .env
    api_key = models.get_setting(config.DB_PATH, "AGENT_API_KEY") or config.AGENT_API_KEY

    if not agents:
        print("[poller] No agents configured in database")
        return

    headers = {"X-API-Key": api_key}

    for agent in agents:
        url = agent["url"]
        ts = datetime.now(timezone.utc).isoformat()
        try:
            # ── Stats → volume buckets ────────────────────────────────────
            stats_resp = requests.get(
                f"{url}/stats", headers=headers, timeout=10
            ).json()
            totals = stats_resp.get("totals", {})
            upsert_buckets(config.DB_PATH, url, "hourly", stats_resp.get("hourly", {}))
            upsert_buckets(config.DB_PATH, url, "daily", stats_resp.get("daily", {}))

            # ── Status ────────────────────────────────────────────────────
            status_resp = requests.get(
                f"{url}/status", headers=headers, timeout=10
            ).json()
            active = status_resp.get("active", False)
            server_name = status_resp.get("server_name", url)

            # ── Queue ─────────────────────────────────────────────────────
            queue_resp = requests.get(
                f"{url}/queue", headers=headers, timeout=10
            ).json()
            queue_count = queue_resp.get("queue_count", 0)

            # ── Token status (optional — agent may not have TOKEN_DIR) ───
            token_json = None
            try:
                token_resp = requests.get(
                    f"{url}/token-status", headers=headers, timeout=10
                )
                if token_resp.status_code == 200:
                    token_json = json.dumps(token_resp.json().get("tokens", []))
            except Exception:
                pass  # Token monitoring is optional

            # ── Save point-in-time snapshot ───────────────────────────────
            save_snapshot(
                db_path=config.DB_PATH,
                agent_url=url,
                server_name=server_name,
                ts=ts,
                queue_count=queue_count,
                token_status_json=token_json,
                active=active,
            )

            print(
                f"[poller] Polled {server_name} — "
                f"buckets(h={len(stats_resp.get('hourly', {}))} "
                f"d={len(stats_resp.get('daily', {}))}) "
                f"totals(s={totals.get('sent', 0)} d={totals.get('deferred', 0)} "
                f"b={totals.get('bounced', 0)} r={totals.get('rejected', 0)}) "
                f"queue={queue_count}"
            )

        except Exception as exc:
            print(f"[poller] ERROR polling {url}: {exc}")
