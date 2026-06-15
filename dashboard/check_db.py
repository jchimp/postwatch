import sqlite3
from datetime import datetime, timezone, timedelta

db_path = "data/postwatch.db"
conn = sqlite3.connect(db_path)

base_time = datetime.now(timezone.utc)
for i in range(7):
    ts = (base_time - timedelta(days=i)).isoformat()
    conn.execute("""
        INSERT INTO stats_snapshots
        (agent_url, server_name, ts, sent, deferred, bounced, rejected, queue_count, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "http://localhost:5101",
        "Test Agent 2",
        ts,
        50 + i*5,    # sent (different from agent 1)
        5 + i,       # deferred
        2,           # bounced
        1,           # rejected
        0,           # queue_count
        1            # active
    ))

conn.commit()
conn.close()
print("Added test data for Agent 2")
