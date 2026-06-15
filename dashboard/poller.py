"""
postwatch dashboard — poller.py
Background job that polls each agent and stores stats snapshots in SQLite.
"""

import json
from datetime import datetime, timezone

import requests

import config
import models
from models import save_snapshot


def poll_agents() -> None:
    """Poll every configured agent for stats, status, queue, and token health."""
    # Get agents from database (post-migration from .env)
    agents = models.get_agents(config.DB_PATH)
    agent_urls = [agent["url"] for agent in agents]

    # Get API key from database, fall back to .env
    api_key = models.get_setting(config.DB_PATH, "AGENT_API_KEY") or config.AGENT_API_KEY

    if not agent_urls:
        print("[poller] No agents configured in database")
        return

    ts = datetime.now(timezone.utc).isoformat()
    headers = {"X-API-Key": api_key}
    try:
        # ── Stats ─────────────────────────────────────────────────────
        stats_resp = requests.get(
            f"{url}/stats", headers=headers, timeout=10
        ).json()
        totals = stats_resp.get("totals", {})
        sent = totals.get("sent", 0)
        deferred = totals.get("deferred", 0)
        bounced = totals.get("bounced", 0)
        rejected = totals.get("rejected", 0)

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

        # ── Save ──────────────────────────────────────────────────────
        save_snapshot(
            db_path=config.DB_PATH,
            agent_url=url,
            server_name=server_name,
            ts=ts,
            sent=sent,
            deferred=deferred,
            bounced=bounced,
            rejected=rejected,
            queue_count=queue_count,
            token_status_json=token_json,
            active=active,
        )

        print(
            f"[poller] Polled {server_name} — "
            f"sent={sent} deferred={deferred} bounced={bounced} "
            f"rejected={rejected} queue={queue_count}"
        )

    except Exception as exc:
        print(f"[poller] ERROR polling {url}: {exc}")
