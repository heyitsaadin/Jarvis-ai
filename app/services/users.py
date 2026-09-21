"""User accounts, auth tokens and guest sessions."""

from datetime import datetime, timezone, timedelta
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
from app.config import IST
from app.services.database import get_db, return_db


def get_user(username):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE username=%s", (username,))
    user = cur.fetchone()
    cur.close()
    return_db(conn)
    return user


def add_user(username, password):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO users VALUES (%s, %s)", (username, generate_password_hash(password)))
    conn.commit()
    cur.close()
    return_db(conn)


def create_auth_token(username):
    token = secrets.token_hex(32)
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute(
        "INSERT INTO auth_tokens (token, username, created_at, last_used) VALUES (%s, %s, %s, %s)",
        (token, username, now, now)
    )
    conn.commit()
    cur.close()
    return_db(conn)
    return token


def get_user_by_token(token):
    if not token:
        return None
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT username FROM auth_tokens WHERE token=%s", (token,))
    row = cur.fetchone()
    if row:
        now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("UPDATE auth_tokens SET last_used=%s WHERE token=%s", (now, token))
        conn.commit()
    cur.close()
    return_db(conn)
    return row["username"] if row else None


def delete_auth_token(token):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM auth_tokens WHERE token=%s", (token,))
    conn.commit()
    cur.close()
    return_db(conn)


def update_username_db(old_username, new_username):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users            SET username=%s WHERE username=%s", (new_username, old_username))
    cur.execute("UPDATE history          SET username=%s WHERE username=%s", (new_username, old_username))
    cur.execute("UPDATE user_profiles    SET username=%s WHERE username=%s", (new_username, old_username))
    cur.execute("UPDATE chat_sessions    SET username=%s WHERE username=%s", (new_username, old_username))
    conn.commit()
    cur.close()
    return_db(conn)


def update_password_db(username, new_password):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET password=%s WHERE username=%s",
                (generate_password_hash(new_password), username))
    conn.commit()
    cur.close()
    return_db(conn)


def get_next_guest_label():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM guest_sessions")
    count = cur.fetchone()[0]
    cur.close()
    return_db(conn)
    return f"guest{count + 1}"


def create_guest_session(session_id, guest_label):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    cur.execute(
        "INSERT INTO guest_sessions (session_id, guest_label, created_at) VALUES (%s, %s, %s)",
        (session_id, guest_label, now)
    )
    conn.commit()
    cur.close()
    return_db(conn)


def log_visit():
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(IST)
    cur.execute("INSERT INTO visits VALUES (%s, %s)",
                (now.strftime("%Y-%m-%d %H:%M"), now.strftime("%Y-%m-%d")))
    conn.commit()
    cur.close()
    return_db(conn)
