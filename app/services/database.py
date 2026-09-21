"""PostgreSQL connection pool and schema creation."""

from psycopg2 import pool
from app.config import DATABASE_URL

# Connection pool, created lazily by init_db_pool().
db_pool = None


def init_db_pool():
    global db_pool
    if db_pool is None:
        db_pool = pool.SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=DATABASE_URL
        )


def get_db():
    if db_pool is None:
        init_db_pool()
    return db_pool.getconn()


def return_db(conn):
    if db_pool and conn:
        db_pool.putconn(conn)


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users    (username TEXT PRIMARY KEY, password TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS history  (username TEXT, calculation TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS visits   (timestamp TEXT, date TEXT)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            username     TEXT PRIMARY KEY,
            profile_json TEXT,
            last_updated TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS auth_tokens (
            token       TEXT PRIMARY KEY,
            username    TEXT,
            created_at  TEXT,
            last_used   TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id          SERIAL PRIMARY KEY,
            username    TEXT,
            session_key TEXT,
            messages    TEXT,
            created_at  TEXT,
            updated_at  TEXT,
            is_pinned   BOOLEAN DEFAULT FALSE,
            UNIQUE(username, session_key)
        )
    """)
    conn.commit()
    try:
        cur.execute("ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN DEFAULT FALSE")
        conn.commit()
    except Exception:
        conn.rollback()
    try:
        cur.execute("""
            DELETE FROM chat_sessions
            WHERE id NOT IN (
                SELECT MAX(id) FROM chat_sessions GROUP BY username, session_key
            )
        """)
        conn.commit()
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uniq_user_session ON chat_sessions(username, session_key)")
        conn.commit()
    except Exception:
        conn.rollback()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bans (
            id         SERIAL PRIMARY KEY,
            type       TEXT,
            value      TEXT UNIQUE,
            reason     TEXT,
            banned_at  TEXT,
            banned_by  TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS shared_chats (
            share_token TEXT PRIMARY KEY,
            username    TEXT,
            session_key TEXT,
            messages    TEXT,
            title       TEXT,
            shared_at   TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS guest_sessions (
            session_id  TEXT PRIMARY KEY,
            guest_label TEXT,
            created_at  TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id          SERIAL PRIMARY KEY,
            username    TEXT NOT NULL,
            name        TEXT NOT NULL,
            description TEXT DEFAULT \'\',
            color       TEXT DEFAULT \'#6366f1\',
            created_at  TEXT
        )
    """)
    try:
        cur.execute("ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS project_id INTEGER")
        conn.commit()
    except Exception:
        conn.rollback()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS api_call_logs (
            id            SERIAL PRIMARY KEY,
            provider      TEXT,
            key_label     TEXT,
            endpoint      TEXT,
            success       BOOLEAN,
            status_code   INTEGER,
            response_ms   INTEGER,
            error_message TEXT,
            called_at     TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_api_call_logs_provider_time ON api_call_logs(provider, called_at)")
    conn.commit()
    cur.close()
    return_db(conn)
