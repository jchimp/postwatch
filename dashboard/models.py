"""
postwatch dashboard — models.py
SQLite helpers for storing and querying mail stats.

Data model:
  - hourly_buckets / daily_buckets — accurate mail-volume history, keyed by the
    time each message was processed (from the agent's log parser). The poller
    UPSERTs these every cycle with MAX(existing, new) so a bucket grows while its
    hour/day is still inside the agent's log window, then freezes at the complete
    value once older lines scroll off. Charts read from here.
  - stats_snapshots — point-in-time state per poll (postfix active, queue depth,
    token health, last-poll time). Feeds the Agent Status table. NOT used for
    volume charts.
"""

import os
import secrets
import sqlite3
from datetime import datetime, timezone

CATEGORIES = ("sent", "deferred", "bounced", "rejected")


def _connect(db_path: str) -> sqlite3.Connection:
    """Open a connection with row-factory enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> None:
    """Create the database file, parent dirs, and tables if they don't exist."""
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    with _connect(db_path) as conn:
        # Point-in-time poll state (status table). No volume columns.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stats_snapshots (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_url     TEXT    NOT NULL,
                server_name   TEXT,
                ts            TEXT    NOT NULL,
                queue_count   INTEGER DEFAULT 0,
                token_status  TEXT,
                active        INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_agent_ts
            ON stats_snapshots (agent_url, ts)
        """)

        # Accurate mail-volume buckets, keyed by processing time.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hourly_buckets (
                agent_url  TEXT    NOT NULL,
                bucket     TEXT    NOT NULL,           -- "YYYY-MM-DD HH" (agent local time)
                sent       INTEGER DEFAULT 0,
                deferred   INTEGER DEFAULT 0,
                bounced    INTEGER DEFAULT 0,
                rejected   INTEGER DEFAULT 0,
                updated    TEXT    NOT NULL,
                PRIMARY KEY (agent_url, bucket)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_buckets (
                agent_url  TEXT    NOT NULL,
                bucket     TEXT    NOT NULL,           -- "YYYY-MM-DD" (agent local time)
                sent       INTEGER DEFAULT 0,
                deferred   INTEGER DEFAULT 0,
                bounced    INTEGER DEFAULT 0,
                rejected   INTEGER DEFAULT 0,
                updated    TEXT    NOT NULL,
                PRIMARY KEY (agent_url, bucket)
            )
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


# ── Snapshots (point-in-time poll state) ──────────────────────────────────────

def save_snapshot(
    db_path: str,
    agent_url: str,
    server_name: str,
    ts: str,
    queue_count: int,
    token_status_json: str | None,
    active: bool,
) -> None:
    """Insert a single point-in-time snapshot (status, queue, token health)."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO stats_snapshots
                (agent_url, server_name, ts, queue_count, token_status, active)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (agent_url, server_name, ts, queue_count, token_status_json, 1 if active else 0),
        )
        conn.commit()


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


# ── Volume buckets (accurate, mail-time history) ──────────────────────────────

def upsert_buckets(db_path: str, agent_url: str, period: str, buckets: dict) -> None:
    """UPSERT a map of {bucket_key: {sent, deferred, ...}} into hourly/daily.

    Uses MAX(existing, new) per category so a bucket only ever grows. While the
    bucket's hour/day is fully inside the agent's log window the count climbs to
    its true total; once older lines scroll off the agent reports a smaller
    (partial) count, and MAX preserves the complete value already stored.

    period must be "hourly" or "daily".
    """
    table = {"hourly": "hourly_buckets", "daily": "daily_buckets"}[period]
    now = datetime.now(timezone.utc).isoformat()

    rows = [
        (
            agent_url,
            key,
            int(cats.get("sent", 0)),
            int(cats.get("deferred", 0)),
            int(cats.get("bounced", 0)),
            int(cats.get("rejected", 0)),
            now,
        )
        for key, cats in buckets.items()
    ]
    if not rows:
        return

    with _connect(db_path) as conn:
        conn.executemany(
            f"""
            INSERT INTO {table}
                (agent_url, bucket, sent, deferred, bounced, rejected, updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_url, bucket) DO UPDATE SET
                sent     = MAX(sent,     excluded.sent),
                deferred = MAX(deferred, excluded.deferred),
                bounced  = MAX(bounced,  excluded.bounced),
                rejected = MAX(rejected, excluded.rejected),
                updated  = excluded.updated
            """,
            rows,
        )
        conn.commit()


def _bucket_table(period: str) -> str:
    return {"hourly": "hourly_buckets", "daily": "daily_buckets"}[period]


def get_buckets(db_path: str, agent_url: str, period: str, limit: int) -> dict:
    """Return the most recent `limit` buckets for one agent as {key: {cats}}."""
    table = _bucket_table(period)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT bucket, sent, deferred, bounced, rejected
            FROM {table}
            WHERE agent_url = ?
            ORDER BY bucket DESC
            LIMIT ?
            """,
            (agent_url, limit),
        ).fetchall()
    return {
        r["bucket"]: {c: r[c] for c in CATEGORIES}
        for r in rows
    }


def get_buckets_all(db_path: str, period: str, limit: int) -> dict:
    """Return the most recent `limit` buckets summed across all agents."""
    table = _bucket_table(period)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT bucket,
                   SUM(sent) AS sent, SUM(deferred) AS deferred,
                   SUM(bounced) AS bounced, SUM(rejected) AS rejected
            FROM {table}
            GROUP BY bucket
            ORDER BY bucket DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return {
        r["bucket"]: {c: r[c] for c in CATEGORIES}
        for r in rows
    }


def get_period_rollup(db_path: str, agent_url: str, fmt: str, limit: int) -> list[dict]:
    """Aggregate daily_buckets into longer periods for one agent.

    `fmt` is an sqlite strftime format applied to the daily bucket date, e.g.
    "%Y-W%W" (ISO-ish week) or "%Y-%m" (month). Returns oldest-first.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT strftime('{fmt}', bucket) AS period,
                   SUM(sent) AS sent, SUM(deferred) AS deferred,
                   SUM(bounced) AS bounced, SUM(rejected) AS rejected
            FROM daily_buckets
            WHERE agent_url = ?
            GROUP BY period
            ORDER BY period DESC
            LIMIT ?
            """,
            (agent_url, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_period_rollup_all(db_path: str, fmt: str, limit: int) -> list[dict]:
    """Aggregate daily_buckets into longer periods across all agents."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT strftime('{fmt}', bucket) AS period,
                   SUM(sent) AS sent, SUM(deferred) AS deferred,
                   SUM(bounced) AS bounced, SUM(rejected) AS rejected
            FROM daily_buckets
            GROUP BY period
            ORDER BY period DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


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
