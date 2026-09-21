"""Bans, IP checks and Discord security alerts."""

from datetime import datetime, timezone, timedelta
from psycopg2.extras import RealDictCursor
import os
import requests
from app.config import IST
from app.services.database import get_db, return_db


def is_banned(value, ban_type):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM bans WHERE type=%s AND value=%s", (ban_type, value))
    found = cur.fetchone() is not None
    cur.close()
    return_db(conn)
    return found


def add_ban(ban_type, value, reason, banned_by):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    cur.execute("""
        INSERT INTO bans (type, value, reason, banned_at, banned_by)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (value) DO UPDATE SET reason=%s, banned_at=%s, banned_by=%s
    """, (ban_type, value, reason, now, banned_by, reason, now, banned_by))
    conn.commit()
    cur.close()
    return_db(conn)


def remove_ban(value):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM bans WHERE value=%s", (value,))
    conn.commit()
    cur.close()
    return_db(conn)


def get_all_bans():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM bans ORDER BY banned_at DESC")
    rows = cur.fetchall()
    cur.close()
    return_db(conn)
    return rows


def send_discord_alert(user, reason, message):
    WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK")
    if not WEBHOOK_URL:
        return
    payload = {
        "username": "Jarvis Security",
        "embeds": [{
            "title": "⚠️ Security Alert",
            "description": f"**User:** {user}\n**Reason:** {reason}\n**Message:** {message}",
            "color": 15158332
        }]
    }
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=5)
    except:
        pass
