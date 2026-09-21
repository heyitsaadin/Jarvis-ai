"""Database access for the website builder (files, chats, versions)."""
import json
from datetime import datetime
from psycopg2.extras import RealDictCursor
from app.config import IST
from app.services.database import get_db, return_db


def init_website_db():
    """Run safe migrations. Called once at import time."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        ALTER TABLE projects
        ADD COLUMN IF NOT EXISTS type TEXT DEFAULT 'general'
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS website_files (
            id          SERIAL PRIMARY KEY,
            project_id  INTEGER NOT NULL,
            username    TEXT NOT NULL,
            filename    TEXT NOT NULL,
            content     TEXT NOT NULL,
            updated_at  TEXT,
            UNIQUE(project_id, filename)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS website_chats (
            id          SERIAL PRIMARY KEY,
            project_id  INTEGER NOT NULL,
            username    TEXT NOT NULL,
            messages    TEXT NOT NULL DEFAULT '[]',
            updated_at  TEXT,
            UNIQUE(project_id, username)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS website_versions (
            id          SERIAL PRIMARY KEY,
            project_id  INTEGER NOT NULL,
            username    TEXT NOT NULL,
            label       TEXT,
            snapshot    TEXT NOT NULL,
            created_at  TEXT
        )
    """)

    conn.commit()
    cur.close()
    return_db(conn)


def _get_project(project_id, username):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT * FROM projects WHERE id=%s AND username=%s",
        (project_id, username)
    )
    row = cur.fetchone()
    cur.close()
    return_db(conn)
    return row


def _get_files(project_id, username):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT filename, content, updated_at FROM website_files "
        "WHERE project_id=%s AND username=%s ORDER BY filename",
        (project_id, username)
    )
    rows = cur.fetchall()
    cur.close()
    return_db(conn)
    return [dict(r) for r in rows]


def _save_file(project_id, username, filename, content):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    cur.execute("""
        INSERT INTO website_files (project_id, username, filename, content, updated_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (project_id, filename)
        DO UPDATE SET content=%s, updated_at=%s
    """, (project_id, username, filename, content, now, content, now))
    conn.commit()
    cur.close()
    return_db(conn)


def _get_chat(project_id, username):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT messages FROM website_chats WHERE project_id=%s AND username=%s",
        (project_id, username)
    )
    row = cur.fetchone()
    cur.close()
    return_db(conn)
    if row:
        return json.loads(row["messages"])
    return []


def _save_chat(project_id, username, messages):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    cur.execute("""
        INSERT INTO website_chats (project_id, username, messages, updated_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (project_id, username)
        DO UPDATE SET messages=%s, updated_at=%s
    """, (project_id, username, json.dumps(messages), now,
          json.dumps(messages), now))
    conn.commit()
    cur.close()
    return_db(conn)


def _save_version(project_id, username, files, label=None):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    if not label:
        label = now
    cur.execute("""
        INSERT INTO website_versions (project_id, username, label, snapshot, created_at)
        VALUES (%s, %s, %s, %s, %s)
    """, (project_id, username, label, json.dumps(files), now))
    conn.commit()
    cur.close()
    return_db(conn)


def _get_versions(project_id, username):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT id, label, created_at FROM website_versions "
        "WHERE project_id=%s AND username=%s ORDER BY id DESC LIMIT 20",
        (project_id, username)
    )
    rows = cur.fetchall()
    cur.close()
    return_db(conn)
    return [dict(r) for r in rows]


def _restore_version(version_id, project_id, username):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT snapshot FROM website_versions WHERE id=%s AND project_id=%s AND username=%s",
        (version_id, project_id, username)
    )
    row = cur.fetchone()
    cur.close()
    return_db(conn)
    if not row:
        return False
    files = json.loads(row["snapshot"])
    for f in files:
        _save_file(project_id, username, f["filename"], f["content"])
    return True
