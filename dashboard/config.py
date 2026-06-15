"""
postwatch dashboard — config.py
Loads all configuration from environment variables / .env file.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Flask / Auth ──────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-to-a-long-random-string")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin")  # plaintext in .env, bcrypt-checked at login

# ── Agent connectivity ────────────────────────────────────────────────────────
# API key is now generated and stored entirely in SQLite at first startup.
# No longer in .env — use dashboard Settings page to retrieve or regenerate.

# Agents are now managed in the dashboard Settings page (stored in SQLite).
# This variable is kept for backward compatibility but is not used.
AGENTS = []

# ── Polling / Storage ────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", 120))
DB_PATH = os.getenv("DB_PATH", "data/postwatch.db")

# ── Server bind ──────────────────────────────────────────────────────────────
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 5000))
