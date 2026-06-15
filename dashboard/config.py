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
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "changeme")

# Comma-separated list of agent base URLs, e.g. "http://mail1:5100,http://mail2:5100"
_raw_agents = os.getenv("AGENTS", "")
AGENTS = [url.strip() for url in _raw_agents.split(",") if url.strip()]

# ── Polling / Storage ────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", 120))
DB_PATH = os.getenv("DB_PATH", "data/postwatch.db")

# ── Server bind ──────────────────────────────────────────────────────────────
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 5000))
