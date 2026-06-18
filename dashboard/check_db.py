"""Dev helper: seed the volume bucket tables with test data for a second agent.

Charts read from hourly_buckets / daily_buckets, so seed those. For manual UI
testing only — not used by the app.
"""
import sqlite3
from datetime import datetime, timezone, timedelta

db_path = "data/postwatch.db"
agent_url = "http://localhost:5101"
now = datetime.now(timezone.utc)
stamp = now.isoformat()

conn = sqlite3.connect(db_path)

# Daily buckets — last 14 days
for i in range(14):
    day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
    conn.execute(
        """
        INSERT INTO daily_buckets (agent_url, bucket, sent, deferred, bounced, rejected, updated)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(agent_url, bucket) DO UPDATE SET
            sent=excluded.sent, deferred=excluded.deferred,
            bounced=excluded.bounced, rejected=excluded.rejected, updated=excluded.updated
        """,
        (agent_url, day, 50 + i * 5, 5 + i, 2, 1, stamp),
    )

# Hourly buckets — last 48 hours
for i in range(48):
    hour = (now - timedelta(hours=i)).strftime("%Y-%m-%d %H")
    conn.execute(
        """
        INSERT INTO hourly_buckets (agent_url, bucket, sent, deferred, bounced, rejected, updated)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(agent_url, bucket) DO UPDATE SET
            sent=excluded.sent, deferred=excluded.deferred,
            bounced=excluded.bounced, rejected=excluded.rejected, updated=excluded.updated
        """,
        (agent_url, hour, 3 + (i % 6), i % 3, 0, 0, stamp),
    )

conn.commit()
conn.close()
print(f"Seeded bucket test data for {agent_url}")
