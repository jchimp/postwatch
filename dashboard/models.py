"""
postwatch dashboard — models.py
SQLite helpers for storing and querying polled stats snapshots.
"""

import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone


def _connect(db_path: str) -> sqlite3.Connection:
    """Open a connection with row-factory enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> None:
    """Create the database file, parent dirs, and tables if they don't exist."""
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    with _connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stats_snapshots (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_url     TEXT    NOT NULL,
                server_name   TEXT,
                ts            TEXT    NOT NULL,
                sent          INTEGER DEFAULT 0,
                deferred      INTEGER DEFAULT 0,
                bounced       INTEGER DEFAULT 0,
                rejected      INTEGER DEFAULT 0,
                queue_count   INTEGER DEFAULT 0,
                token_status  TEXT,
                active        INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_agent_ts
            ON stats_snapshots (agent_url, ts)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                url       TEXT    NOT NULL UNIQUE,
                name      TEXT,
                created   TEXT    NOT NULL,
                updated   TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key       TEXT    PRIMARY KEY,
                value     TEXT    NOT NULL,
                updated   TEXT    NOT NULL
            )
        """)
        conn.commit()

        # Initialize default settings if they don't exist
        now = datetime.now(timezone.utc).isoformat()
        defaults = {
            "TOKEN_STALE_MINUTES": "90",
            "TOKEN_EXPIRY_WARN_MINUTES": "10",
        }
        for key, value in defaults.items():
            existing = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO settings (key, value, updated) VALUES (?, ?, ?)",
                    (key, value, now),
                )

        # Generate AGENT_API_KEY if it doesn't exist
        existing_key = conn.execute(
            "SELECT value FROM settings WHERE key = ?", ("AGENT_API_KEY",)
        ).fetchone()
        if not existing_key:
            api_key = secrets.token_urlsafe(32)
            conn.execute(
                "INSERT INTO settings (key, value, updated) VALUES (?, ?, ?)",
                ("AGENT_API_KEY", api_key, now),
            )

        conn.commit()


def save_snapshot(
    db_path: str,
    agent_url: str,
    server_name: str,
    ts: str,
    sent: int,
    deferred: int,
    bounced: int,
    rejected: int,
    queue_count: int,
    token_status_json: str | None,
    active: bool,
) -> None:
    """Insert a single stats snapshot row."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO stats_snapshots
                (agent_url, server_name, ts, sent, deferred, bounced, rejected,
                 queue_count, token_status, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_url,
                server_name,
                ts,
                sent,
                deferred,
                bounced,
                rejected,
                queue_count,
                token_status_json,
                1 if active else 0,
            ),
        )
        conn.commit()


def get_daily_stats(db_path: str, agent_url: str, days: int = 7) -> list[dict]:
    """Return daily aggregated stats for the last N days (per-day deltas)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                day,
                MAX(CASE WHEN rn = 1 THEN sent_delta ELSE 0 END) AS sent,
                MAX(CASE WHEN rn = 1 THEN deferred_delta ELSE 0 END) AS deferred,
                MAX(CASE WHEN rn = 1 THEN bounced_delta ELSE 0 END) AS bounced,
                MAX(CASE WHEN rn = 1 THEN rejected_delta ELSE 0 END) AS rejected
            FROM (
                SELECT
                    date(ts)                                    AS day,
                    LAST_VALUE(sent)      OVER w - FIRST_VALUE(sent)      OVER w  AS sent_delta,
                    LAST_VALUE(deferred)  OVER w - FIRST_VALUE(deferred)  OVER w  AS deferred_delta,
                    LAST_VALUE(bounced)   OVER w - FIRST_VALUE(bounced)   OVER w  AS bounced_delta,
                    LAST_VALUE(rejected)  OVER w - FIRST_VALUE(rejected)  OVER w  AS rejected_delta,
                    ROW_NUMBER() OVER w AS rn
                FROM stats_snapshots
                WHERE agent_url = ? AND ts >= ?
                WINDOW w AS (
                    PARTITION BY date(ts)
                    ORDER BY ts
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                )
            )
            GROUP BY day
            ORDER BY day
            """,
            (agent_url, cutoff),
        ).fetchall()

    return [dict(row) for row in rows]


def get_hourly_stats(db_path: str, agent_url: str, hours: int = 24) -> list[dict]:
    """Return hourly aggregated stats for the last N hours (per-hour deltas)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                hour,
                MAX(CASE WHEN rn = 1 THEN sent_delta ELSE 0 END) AS sent,
                MAX(CASE WHEN rn = 1 THEN deferred_delta ELSE 0 END) AS deferred,
                MAX(CASE WHEN rn = 1 THEN bounced_delta ELSE 0 END) AS bounced,
                MAX(CASE WHEN rn = 1 THEN rejected_delta ELSE 0 END) AS rejected
            FROM (
                SELECT
                    strftime('%Y-%m-%d %H', ts)                             AS hour,
                    LAST_VALUE(sent)      OVER w - FIRST_VALUE(sent)      OVER w  AS sent_delta,
                    LAST_VALUE(deferred)  OVER w - FIRST_VALUE(deferred)  OVER w  AS deferred_delta,
                    LAST_VALUE(bounced)   OVER w - FIRST_VALUE(bounced)   OVER w  AS bounced_delta,
                    LAST_VALUE(rejected)  OVER w - FIRST_VALUE(rejected)  OVER w  AS rejected_delta,
                    ROW_NUMBER() OVER w AS rn
                FROM stats_snapshots
                WHERE agent_url = ? AND ts >= ?
                WINDOW w AS (
                    PARTITION BY strftime('%Y-%m-%d %H', ts)
                    ORDER BY ts
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                )
            )
            GROUP BY hour
            ORDER BY hour
            """,
            (agent_url, cutoff),
        ).fetchall()

    return [dict(row) for row in rows]


def get_weekly_stats(db_path: str, agent_url: str, weeks: int = 4) -> list[dict]:
    """Return weekly aggregated stats for the last N weeks (per-week deltas)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).isoformat()

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                week,
                MAX(CASE WHEN rn = 1 THEN sent_delta ELSE 0 END) AS sent,
                MAX(CASE WHEN rn = 1 THEN deferred_delta ELSE 0 END) AS deferred,
                MAX(CASE WHEN rn = 1 THEN bounced_delta ELSE 0 END) AS bounced,
                MAX(CASE WHEN rn = 1 THEN rejected_delta ELSE 0 END) AS rejected
            FROM (
                SELECT
                    strftime('%Y-W%W', ts)                                  AS week,
                    LAST_VALUE(sent)      OVER w - FIRST_VALUE(sent)      OVER w  AS sent_delta,
                    LAST_VALUE(deferred)  OVER w - FIRST_VALUE(deferred)  OVER w  AS deferred_delta,
                    LAST_VALUE(bounced)   OVER w - FIRST_VALUE(bounced)   OVER w  AS bounced_delta,
                    LAST_VALUE(rejected)  OVER w - FIRST_VALUE(rejected)  OVER w  AS rejected_delta,
                    ROW_NUMBER() OVER w AS rn
                FROM stats_snapshots
                WHERE agent_url = ? AND ts >= ?
                WINDOW w AS (
                    PARTITION BY strftime('%Y-W%W', ts)
                    ORDER BY ts
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                )
            )
            GROUP BY week
            ORDER BY week
            """,
            (agent_url, cutoff),
        ).fetchall()

    return [dict(row) for row in rows]


def get_monthly_stats(db_path: str, agent_url: str, months: int = 12) -> list[dict]:
    """Return monthly aggregated stats for the last N months (per-month deltas)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=months*30)).isoformat()

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                month,
                MAX(CASE WHEN rn = 1 THEN sent_delta ELSE 0 END) AS sent,
                MAX(CASE WHEN rn = 1 THEN deferred_delta ELSE 0 END) AS deferred,
                MAX(CASE WHEN rn = 1 THEN bounced_delta ELSE 0 END) AS bounced,
                MAX(CASE WHEN rn = 1 THEN rejected_delta ELSE 0 END) AS rejected
            FROM (
                SELECT
                    strftime('%Y-%m', ts)                                   AS month,
                    LAST_VALUE(sent)      OVER w - FIRST_VALUE(sent)      OVER w  AS sent_delta,
                    LAST_VALUE(deferred)  OVER w - FIRST_VALUE(deferred)  OVER w  AS deferred_delta,
                    LAST_VALUE(bounced)   OVER w - FIRST_VALUE(bounced)   OVER w  AS bounced_delta,
                    LAST_VALUE(rejected)  OVER w - FIRST_VALUE(rejected)  OVER w  AS rejected_delta,
                    ROW_NUMBER() OVER w AS rn
                FROM stats_snapshots
                WHERE agent_url = ? AND ts >= ?
                WINDOW w AS (
                    PARTITION BY strftime('%Y-%m', ts)
                    ORDER BY ts
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                )
            )
            GROUP BY month
            ORDER BY month
            """,
            (agent_url, cutoff),
        ).fetchall()

    return [dict(row) for row in rows]


def get_daily_stats_all(db_path: str, days: int = 7) -> list[dict]:
    """Return aggregated daily stats across all agents for the last N days (per-day deltas)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                day,
                SUM(sent_delta)      AS sent,
                SUM(deferred_delta)  AS deferred,
                SUM(bounced_delta)   AS bounced,
                SUM(rejected_delta)  AS rejected
            FROM (
                SELECT
                    day,
                    agent_url,
                    MAX(CASE WHEN rn = 1 THEN sent_delta ELSE 0 END) AS sent_delta,
                    MAX(CASE WHEN rn = 1 THEN deferred_delta ELSE 0 END) AS deferred_delta,
                    MAX(CASE WHEN rn = 1 THEN bounced_delta ELSE 0 END) AS bounced_delta,
                    MAX(CASE WHEN rn = 1 THEN rejected_delta ELSE 0 END) AS rejected_delta
                FROM (
                    SELECT
                        day,
                        agent_url,
                        LAST_VALUE(sent)      OVER w - FIRST_VALUE(sent)      OVER w  AS sent_delta,
                        LAST_VALUE(deferred)  OVER w - FIRST_VALUE(deferred)  OVER w  AS deferred_delta,
                        LAST_VALUE(bounced)   OVER w - FIRST_VALUE(bounced)   OVER w  AS bounced_delta,
                        LAST_VALUE(rejected)  OVER w - FIRST_VALUE(rejected)  OVER w  AS rejected_delta,
                        ROW_NUMBER() OVER w AS rn
                    FROM (
                        SELECT
                            date(ts) AS day,
                            agent_url,
                            ts,
                            sent,
                            deferred,
                            bounced,
                            rejected
                        FROM stats_snapshots
                        WHERE ts >= ?
                    )
                    WINDOW w AS (
                        PARTITION BY agent_url, day
                        ORDER BY ts
                        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                    )
                )
                GROUP BY day, agent_url
            )
            GROUP BY day
            ORDER BY day
            """,
            (cutoff,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_hourly_stats_all(db_path: str, hours: int = 24) -> list[dict]:
    """Return aggregated hourly stats across all agents for the last N hours (per-hour deltas)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                hour,
                SUM(sent_delta)      AS sent,
                SUM(deferred_delta)  AS deferred,
                SUM(bounced_delta)   AS bounced,
                SUM(rejected_delta)  AS rejected
            FROM (
                SELECT
                    hour,
                    agent_url,
                    MAX(CASE WHEN rn = 1 THEN sent_delta ELSE 0 END) AS sent_delta,
                    MAX(CASE WHEN rn = 1 THEN deferred_delta ELSE 0 END) AS deferred_delta,
                    MAX(CASE WHEN rn = 1 THEN bounced_delta ELSE 0 END) AS bounced_delta,
                    MAX(CASE WHEN rn = 1 THEN rejected_delta ELSE 0 END) AS rejected_delta
                FROM (
                    SELECT
                        hour,
                        agent_url,
                        LAST_VALUE(sent)      OVER w - FIRST_VALUE(sent)      OVER w  AS sent_delta,
                        LAST_VALUE(deferred)  OVER w - FIRST_VALUE(deferred)  OVER w  AS deferred_delta,
                        LAST_VALUE(bounced)   OVER w - FIRST_VALUE(bounced)   OVER w  AS bounced_delta,
                        LAST_VALUE(rejected)  OVER w - FIRST_VALUE(rejected)  OVER w  AS rejected_delta,
                        ROW_NUMBER() OVER w AS rn
                    FROM (
                        SELECT
                            strftime('%Y-%m-%d %H', ts) AS hour,
                            agent_url,
                            ts,
                            sent,
                            deferred,
                            bounced,
                            rejected
                        FROM stats_snapshots
                        WHERE ts >= ?
                    )
                    WINDOW w AS (
                        PARTITION BY agent_url, hour
                        ORDER BY ts
                        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                    )
                )
                GROUP BY hour, agent_url
            )
            GROUP BY hour
            ORDER BY hour
            """,
            (cutoff,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_weekly_stats_all(db_path: str, weeks: int = 4) -> list[dict]:
    """Return aggregated weekly stats across all agents for the last N weeks (per-week deltas)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).isoformat()

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                week,
                SUM(sent_delta)      AS sent,
                SUM(deferred_delta)  AS deferred,
                SUM(bounced_delta)   AS bounced,
                SUM(rejected_delta)  AS rejected
            FROM (
                SELECT
                    week,
                    agent_url,
                    MAX(CASE WHEN rn = 1 THEN sent_delta ELSE 0 END) AS sent_delta,
                    MAX(CASE WHEN rn = 1 THEN deferred_delta ELSE 0 END) AS deferred_delta,
                    MAX(CASE WHEN rn = 1 THEN bounced_delta ELSE 0 END) AS bounced_delta,
                    MAX(CASE WHEN rn = 1 THEN rejected_delta ELSE 0 END) AS rejected_delta
                FROM (
                    SELECT
                        week,
                        agent_url,
                        LAST_VALUE(sent)      OVER w - FIRST_VALUE(sent)      OVER w  AS sent_delta,
                        LAST_VALUE(deferred)  OVER w - FIRST_VALUE(deferred)  OVER w  AS deferred_delta,
                        LAST_VALUE(bounced)   OVER w - FIRST_VALUE(bounced)   OVER w  AS bounced_delta,
                        LAST_VALUE(rejected)  OVER w - FIRST_VALUE(rejected)  OVER w  AS rejected_delta,
                        ROW_NUMBER() OVER w AS rn
                    FROM (
                        SELECT
                            strftime('%Y-W%W', ts) AS week,
                            agent_url,
                            ts,
                            sent,
                            deferred,
                            bounced,
                            rejected
                        FROM stats_snapshots
                        WHERE ts >= ?
                    )
                    WINDOW w AS (
                        PARTITION BY agent_url, week
                        ORDER BY ts
                        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                    )
                )
                GROUP BY week, agent_url
            )
            GROUP BY week
            ORDER BY week
            """,
            (cutoff,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_monthly_stats_all(db_path: str, months: int = 12) -> list[dict]:
    """Return aggregated monthly stats across all agents for the last N months (per-month deltas)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=months*30)).isoformat()

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                month,
                SUM(sent_delta)      AS sent,
                SUM(deferred_delta)  AS deferred,
                SUM(bounced_delta)   AS bounced,
                SUM(rejected_delta)  AS rejected
            FROM (
                SELECT
                    month,
                    agent_url,
                    MAX(CASE WHEN rn = 1 THEN sent_delta ELSE 0 END) AS sent_delta,
                    MAX(CASE WHEN rn = 1 THEN deferred_delta ELSE 0 END) AS deferred_delta,
                    MAX(CASE WHEN rn = 1 THEN bounced_delta ELSE 0 END) AS bounced_delta,
                    MAX(CASE WHEN rn = 1 THEN rejected_delta ELSE 0 END) AS rejected_delta
                FROM (
                    SELECT
                        month,
                        agent_url,
                        LAST_VALUE(sent)      OVER w - FIRST_VALUE(sent)      OVER w  AS sent_delta,
                        LAST_VALUE(deferred)  OVER w - FIRST_VALUE(deferred)  OVER w  AS deferred_delta,
                        LAST_VALUE(bounced)   OVER w - FIRST_VALUE(bounced)   OVER w  AS bounced_delta,
                        LAST_VALUE(rejected)  OVER w - FIRST_VALUE(rejected)  OVER w  AS rejected_delta,
                        ROW_NUMBER() OVER w AS rn
                    FROM (
                        SELECT
                            strftime('%Y-%m', ts) AS month,
                            agent_url,
                            ts,
                            sent,
                            deferred,
                            bounced,
                            rejected
                        FROM stats_snapshots
                        WHERE ts >= ?
                    )
                    WINDOW w AS (
                        PARTITION BY agent_url, month
                        ORDER BY ts
                        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                    )
                )
                GROUP BY month, agent_url
            )
            GROUP BY month
            ORDER BY month
            """,
            (cutoff,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_latest_snapshot(db_path: str, agent_url: str) -> dict | None:
    """Return the most recent snapshot for an agent, or None."""
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM stats_snapshots
            WHERE agent_url = ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            (agent_url,),
        ).fetchone()

    return dict(row) if row else None


def get_latest_totals_all(db_path: str) -> dict:
    """Return aggregated totals from the latest snapshot of each agent.

    Uses the most recent snapshot per agent to avoid counting the same
    running totals multiple times. Returns totals that match the agent logs.
    """
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                SUM(sent) AS sent,
                SUM(deferred) AS deferred,
                SUM(bounced) AS bounced,
                SUM(rejected) AS rejected
            FROM (
                SELECT agent_url, sent, deferred, bounced, rejected
                FROM stats_snapshots
                WHERE (agent_url, ts) IN (
                    SELECT agent_url, MAX(ts)
                    FROM stats_snapshots
                    GROUP BY agent_url
                )
            )
            """,
        ).fetchone()

    return dict(row) if row else {"sent": 0, "deferred": 0, "bounced": 0, "rejected": 0}


# ── Agent management ──────────────────────────────────────────────────────────

def get_agents(db_path: str) -> list[dict]:
    """Return all agents from the database."""
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT id, url, name FROM agents ORDER BY created").fetchall()
    return [dict(row) for row in rows]


def add_agent(db_path: str, url: str, name: str = None) -> bool:
    """Add a new agent URL. Returns True on success, False if already exists."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _connect(db_path) as conn:
            conn.execute(
                "INSERT INTO agents (url, name, created, updated) VALUES (?, ?, ?, ?)",
                (url, name or url, now, now),
            )
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def remove_agent(db_path: str, agent_id: int) -> bool:
    """Remove an agent by ID. Returns True if found and deleted, False otherwise."""
    with _connect(db_path) as conn:
        cursor = conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        conn.commit()
        return cursor.rowcount > 0


def get_setting(db_path: str, key: str) -> str | None:
    """Get a setting value, or None if not found."""
    with _connect(db_path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(db_path: str, key: str, value: str) -> None:
    """Set or update a setting value."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value, updated) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated = ?
            """,
            (key, value, now, value, now),
        )
        conn.commit()
