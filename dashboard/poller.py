"""
postwatch dashboard — poller.py
Background job that polls each agent and stores stats snapshots in SQLite.

Stats are stored as DELTAS between polls. The raw cumulative totals from each
agent response are also saved so the next poll can compute the next delta.
"""

import json
from datetime import datetime, timezone

import requests

import config
import models
from models import save_snapshot


def _compute_delta(current: int, previous: int) -> int:
    """Compute the delta between two cumulative counters.

    If the delta is negative (log rotation reset the counters), treat the
    current value as the delta — everything since the reset is new.
    """
    delta = current - previous
    return delta if delta >= 0 else current


def poll_agents() -> None:
    """Poll every configured agent for stats, status, queue, and token health."""
    # Get agents from database (post-migration from .env)
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
            # ── Stats ─────────────────────────────────────────────────────
            stats_resp = requests.get(
                f"{url}/stats", headers=headers, timeout=10
            ).json()
            totals = stats_resp.get("totals", {})
            raw_sent = totals.get("sent", 0)
            raw_deferred = totals.get("deferred", 0)
            raw_bounced = totals.get("bounced", 0)
            raw_rejected = totals.get("rejected", 0)

            # ── Compute deltas ────────────────────────────────────────────
            prev = models.get_last_totals(config.DB_PATH, url)

            if prev is None:
                # First poll for this agent — no delta yet, just baseline
                d_sent = 0
                d_deferred = 0
                d_bounced = 0
                d_rejected = 0
            else:
                d_sent = _compute_delta(raw_sent, prev["raw_sent"])
                d_deferred = _compute_delta(raw_deferred, prev["raw_deferred"])
                d_bounced = _compute_delta(raw_bounced, prev["raw_bounced"])
                d_rejected = _compute_delta(raw_rejected, prev["raw_rejected"])

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
                sent=d_sent,
                deferred=d_deferred,
                bounced=d_bounced,
                rejected=d_rejected,
                raw_sent=raw_sent,
                raw_deferred=raw_deferred,
                raw_bounced=raw_bounced,
                raw_rejected=raw_rejected,
                queue_count=queue_count,
                token_status_json=token_json,
                active=active,
            )

            print(
                f"[poller] Polled {server_name} — "
                f"Δsent={d_sent} Δdef={d_deferred} "
                f"Δbnc={d_bounced} Δrej={d_rejected} "
                f"queue={queue_count} (raw: s={raw_sent} d={raw_deferred} "
                f"b={raw_bounced} r={raw_rejected})"
            )

        except Exception as exc:
            print(f"[poller] ERROR polling {url}: {exc}")
