"""
postfix-watcher dashboard — models.py
SQLite helpers for storing and querying polled stats snapshots.

The sent/deferred/bounced/rejected columns store DELTAS (change since last
snapshot). The raw_* columns store the cumulative totals reported by the agent
so the next poll can compute the next delta.
"""

import os
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
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_url       TEXT    NOT NULL,
                server_name     TEXT,
                ts              TEXT    NOT NULL,
                sent            INTEGER DEFAULT 0,
                deferred        INTEGER DEFAULT 0,
                bounced         INTEGER DEFAULT 0,
                rejected        INTEGER DEFAULT 0,
                raw_sent        INTEGER DEFAULT 0,
                raw_deferred    INTEGER DEFAULT 0,
                raw_bounced     INTEGER DEFAULT 0,
                raw_rejected    INTEGER DEFAULT 0,
                queue_count     INTEGER DEFAULT 0,
                token_status    TEXT,
                active          INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_agent_ts
            ON stats_snapshots (agent_url, ts)
        """)
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
