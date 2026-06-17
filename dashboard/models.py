"""
postwatch dashboard — models.py
SQLite helpers for storing and querying polled stats snapshots.

The sent/deferred/bounced/rejected columns store DELTAS (change since the last
snapshot). The raw_* columns store the cumulative totals reported by the agent
so the next poll can compute the next delta.
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
                raw_sent      INTEGER DEFAULT 0,
                raw_deferred  INTEGER DEFAULT 0,
                raw_bounced   INTEGER DEFAULT 0,
                raw_rejected  INTEGER DEFAULT 0,
                queue_count   INTEGER DEFAULT 0,
                token_status  TEXT,
                active        INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_agent_ts
            ON stats_snapshots (agent_url, ts)
        """)

        # Migrate existing DBs: add raw_* columns if they don't exist yet.
        existing_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(stats_snapshots)").fetchall()
        }
        for col in ("raw_sent", "raw_deferred", "raw_bounced", "raw_rejected"):
            if col not in existing_cols:
                conn.execute(
                    f"ALTER TABLE stats_snapshots ADD COLUMN {col} INTEGER DEFAULT 0"
                )
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
    raw_sent: int,
    raw_deferred: int,
    raw_bounced: int,
    raw_rejected: int,
    queue_count: int,
    token_status_json: str | None,
    active: bool,
) -> None:
    """Insert a single stats snapshot row (deltas + raw cumulative)."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO stats_snapshots
                (agent_url, server_name, ts,
                 sent, deferred, bounced, rejected,
                 raw_sent, raw_deferred, raw_bounced, raw_rejected,
                 queue_count, token_status, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_url,
                server_name,
                ts,
                sent,
                deferred,
                bounced,
                rejected,
                raw_sent,
                raw_deferred,
                raw_bounced,
                raw_rejected,
                queue_count,
                token_status_json,
                1 if active else 0,
            ),
        )
        conn.commit()


def get_last_totals(db_path: str, agent_url: str) -> dict | None:
    """Return the raw cumulative totals from the most recent snapshot.

    Used by the poller to compute deltas for the next snapshot.
    Returns None if no previous snapshot exists for this agent.
    """
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT raw_sent, raw_deferred, raw_bounced, raw_rejected
            FROM stats_snapshots
            WHERE agent_url = ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            (agent_url,),
        ).fetchone()

    return dict(row) if row else None


def get_daily_stats(db_path: str, agent_url: str, days: int = 7) -> list[dict]:
    """Return daily aggregated deltas for the last N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                date(ts)       AS day,
                SUM(sent)      AS sent,
                SUM(deferred)  AS deferred,
                SUM(bounced)   AS bounced,
                SUM(rejected)  AS rejected
            FROM stats_snapshots
            WHERE agent_url = ? AND ts >= ?
            GROUP BY date(ts)
            ORDER BY day
            """,
            (agent_url, cutoff),
        ).fetchall()

    return [dict(row) for row in rows]


def get_hourly_stats(db_path: str, agent_url: str, hours: int = 24) -> list[dict]:
    """Return hourly aggregated deltas for the last N hours."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                strftime('%Y-%m-%d %H', ts) AS hour,
                SUM(sent)                   AS sent,
                SUM(deferred)               AS deferred,
                SUM(bounced)                AS bounced,
                SUM(rejected)               AS rejected
            FROM stats_snapshots
            WHERE agent_url = ? AND ts >= ?
            GROUP BY strftime('%Y-%m-%d %H', ts)
            ORDER BY hour
            """,
            (agent_url, cutoff),
        ).fetchall()

    return [dict(row) for row in rows]


def get_weekly_stats(db_path: str, agent_url: str, weeks: int = 4) -> list[dict]:
    """Return weekly aggregated deltas for the last N weeks."""
    cutoff = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).isoformat()

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                strftime('%Y-W%W', ts) AS week,
                SUM(sent)              AS sent,
                SUM(deferred)          AS deferred,
                SUM(bounced)           AS bounced,
                SUM(rejected)          AS rejected
            FROM stats_snapshots
            WHERE agent_url = ? AND ts >= ?
            GROUP BY strftime('%Y-W%W', ts)
            ORDER BY week
            """,
            (agent_url, cutoff),
        ).fetchall()

    return [dict(row) for row in rows]


def get_monthly_stats(db_path: str, agent_url: str, months: int = 12) -> list[dict]:
    """Return monthly aggregated deltas for the last N months."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=months*30)).isoformat()

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                strftime('%Y-%m', ts) AS month,
                SUM(sent)             AS sent,
                SUM(deferred)         AS deferred,
                SUM(bounced)          AS bounced,
                SUM(rejected)         AS rejected
            FROM stats_snapshots
            WHERE agent_url = ? AND ts >= ?
            GROUP BY strftime('%Y-%m', ts)
            ORDER BY month
            """,
            (agent_url, cutoff),
        ).fetchall()

    return [dict(row) for row in rows]


def get_daily_stats_all(db_path: str, days: int = 7) -> list[dict]:
    """Return aggregated daily deltas across all agents for the last N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                date(ts)       AS day,
                SUM(sent)      AS sent,
                SUM(deferred)  AS deferred,
                SUM(bounced)   AS bounced,
                SUM(rejected)  AS rejected
            FROM stats_snapshots
            WHERE ts >= ?
            GROUP BY date(ts)
            ORDER BY day
            """,
            (cutoff,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_hourly_stats_all(db_path: str, hours: int = 24) -> list[dict]:
    """Return aggregated hourly deltas across all agents for the last N hours."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                strftime('%Y-%m-%d %H', ts) AS hour,
                SUM(sent)                   AS sent,
                SUM(deferred)               AS deferred,
                SUM(bounced)                AS bounced,
                SUM(rejected)               AS rejected
            FROM stats_snapshots
            WHERE ts >= ?
            GROUP BY strftime('%Y-%m-%d %H', ts)
            ORDER BY hour
            """,
            (cutoff,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_weekly_stats_all(db_path: str, weeks: int = 4) -> list[dict]:
    """Return aggregated weekly deltas across all agents for the last N weeks."""
    cutoff = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).isoformat()

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                strftime('%Y-W%W', ts) AS week,
                SUM(sent)              AS sent,
                SUM(deferred)          AS deferred,
                SUM(bounced)           AS bounced,
                SUM(rejected)          AS rejected
            FROM stats_snapshots
            WHERE ts >= ?
            GROUP BY strftime('%Y-W%W', ts)
            ORDER BY week
            """,
            (cutoff,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_monthly_stats_all(db_path: str, months: int = 12) -> list[dict]:
    """Return aggregated monthly deltas across all agents for the last N months."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=months*30)).isoformat()

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                strftime('%Y-%m', ts) AS month,
                SUM(sent)             AS sent,
                SUM(deferred)         AS deferred,
                SUM(bounced)          AS bounced,
                SUM(rejected)         AS rejected
            FROM stats_snapshots
            WHERE ts >= ?
            GROUP BY strftime('%Y-%m', ts)
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
                SUM(raw_sent) AS sent,
                SUM(raw_deferred) AS deferred,
                SUM(raw_bounced) AS bounced,
                SUM(raw_rejected) AS rejected
            FROM (
                SELECT agent_url, raw_sent, raw_deferred, raw_bounced, raw_rejected
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
