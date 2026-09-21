"""User projects and project-scoped chats."""

from datetime import datetime, timezone, timedelta
from psycopg2.extras import RealDictCursor
import json as _json_mod
from app.config import IST
from app.services.database import get_db, return_db


def get_projects(username):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT id, name, description, color, created_at FROM projects WHERE username=%s ORDER BY id DESC",
        (username,)
    )
    rows = cur.fetchall()
    cur.close()
    return_db(conn)
    return rows


def create_project(username, name, description, color):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    cur.execute(
        "INSERT INTO projects (username, name, description, color, created_at) VALUES (%s,%s,%s,%s,%s) RETURNING id,name,description,color,created_at",
        (username, name, description, color, now)
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    return_db(conn)
    return row


def delete_project(username, project_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM projects WHERE id=%s AND username=%s", (project_id, username))
    conn.commit()
    cur.close()
    return_db(conn)


def get_project_chats(username, project_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT id, session_key, messages, created_at, updated_at FROM chat_sessions WHERE username=%s AND project_id=%s ORDER BY updated_at DESC",
        (username, project_id)
    )
    rows = cur.fetchall()
    cur.close()
    return_db(conn)
    return rows


def save_chat_session_project(username, session_key, messages, project_id):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    cur.execute("""
        INSERT INTO chat_sessions (username, session_key, messages, created_at, updated_at, project_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (username, session_key) DO UPDATE
            SET messages=%s, updated_at=%s, project_id=%s
    """, (username, session_key, _json_mod.dumps(messages), now, now, project_id,
          _json_mod.dumps(messages), now, project_id))
    conn.commit()
    cur.close()
    return_db(conn)
