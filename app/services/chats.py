"""Chat history and saved chat sessions."""

from datetime import datetime, timezone, timedelta
from psycopg2.extras import RealDictCursor
import json as _json_mod
from app.config import IST
from app.services.database import get_db, return_db


def save_history(username, calculation):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO history VALUES (%s, %s)", (username, calculation))
    conn.commit()
    cur.close()
    return_db(conn)


def get_chat_sessions(username):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT id, session_key, messages, created_at, updated_at, COALESCE(is_pinned, FALSE) as is_pinned "
        "FROM chat_sessions WHERE username=%s ORDER BY is_pinned DESC, updated_at DESC",
        (username,)
    )
    rows = cur.fetchall()
    cur.close()
    return_db(conn)
    return rows


def save_chat_session(username, session_key, messages):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    cur.execute("""
        INSERT INTO chat_sessions (username, session_key, messages, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (username, session_key) DO UPDATE
            SET messages=%s, updated_at=%s
    """, (username, session_key, _json_mod.dumps(messages), now, now,
          _json_mod.dumps(messages), now))
    conn.commit()
    cur.close()
    return_db(conn)


def delete_chat_session(username, session_key):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM chat_sessions WHERE username=%s AND session_key=%s",
                (username, session_key))
    conn.commit()
    cur.close()
    return_db(conn)


def delete_all_chat_sessions(username):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM chat_sessions WHERE username=%s", (username,))
    conn.commit()
    cur.close()
    return_db(conn)
