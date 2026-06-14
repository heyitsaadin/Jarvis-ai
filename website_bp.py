"""
website_bp.py  –  Website Creation Blueprint for Jarvis
Handles all /project/website/* routes.
Register in app.py with:
    from website_bp import website_bp
    app.register_blueprint(website_bp)
"""

import os
import json
import secrets
import requests
from datetime import datetime, timezone, timedelta
from flask import (
    Blueprint, render_template, request, session,
    redirect, jsonify
)
import psycopg2
from psycopg2.extras import RealDictCursor

website_bp = Blueprint("website_bp", __name__)

IST = timezone(timedelta(hours=5, minutes=30))

# ─── DB helpers (reuse app.py's pool via import) ────────────────────────────

def _get_pool():
    """Lazily grab the connection pool that app.py already created."""
    from app import db_pool
    return db_pool

def _db():
    return _get_pool().getconn()

def _ret(conn):
    _get_pool().putconn(conn)

# ─── One-time migration (called from init_website_db) ───────────────────────

def init_website_db():
    """Run safe migrations. Called once at import time."""
    from app import get_db, return_db
    conn = get_db()
    cur = conn.cursor()

    # Add 'type' column to projects if missing
    cur.execute("""
        ALTER TABLE projects
        ADD COLUMN IF NOT EXISTS type TEXT DEFAULT 'general'
    """)

    # Website files table
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

    # Website chat messages (separate from regular chat_sessions)
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

    # Website version snapshots
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


# ─── DB helpers ─────────────────────────────────────────────────────────────

def _get_project(project_id, username):
    from app import get_db, return_db
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
    from app import get_db, return_db
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
    from app import get_db, return_db
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
    from app import get_db, return_db
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
    from app import get_db, return_db
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
    from app import get_db, return_db
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    if not label:
        label = now
    snapshot = json.dumps(files)
    cur.execute("""
        INSERT INTO website_versions (project_id, username, label, snapshot, created_at)
        VALUES (%s, %s, %s, %s, %s)
    """, (project_id, username, label, snapshot, now))
    conn.commit()
    cur.close()
    return_db(conn)


def _get_versions(project_id, username):
    from app import get_db, return_db
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
    from app import get_db, return_db
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


# ─── NVIDIA call ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert web developer AI inside a website builder called Jarvis.

Your ONLY job is to generate or update website files based on the user's request.

CRITICAL FOLDER RULES:
- When creating a multi-file website (more than 1 file), you MUST put ALL files inside a folder named after the project type.
- Derive the folder name from the user's request: "personal portfolio" → "personal-portfolio", "cafe landing page" → "cafe-landing", "blog layout" → "blog", etc.
- Use lowercase, hyphen-separated folder names. No spaces.
- Every filename must start with that folder prefix: "personal-portfolio/index.html", "personal-portfolio/style.css", "personal-portfolio/script.js"
- All internal links in index.html must reference sibling files WITHOUT the folder prefix (just "style.css", "script.js") since they live in the same folder.
- For single-file sites (one index.html with embedded CSS+JS), no folder needed — just "index.html".
- When UPDATING existing files, keep the same folder prefix already in use.

Rules:
- Respond ONLY with a JSON object — no markdown, no explanation outside JSON.
- The JSON format is:
  {
    "message": "short friendly message to user (1-2 sentences max)",
    "files": [
      {"filename": "personal-portfolio/index.html", "content": "...full file content..."},
      {"filename": "personal-portfolio/style.css", "content": "..."},
      {"filename": "personal-portfolio/script.js", "content": "..."}
    ]
  }
- Create as many files as the website needs. For simple sites, one index.html with embedded CSS/JS is fine.
- For complex sites, split into index.html + style.css + script.js (or more), all inside the project folder.
- Always write complete, working, production-quality code.
- Make the website look modern, mobile-responsive, and visually impressive.
- When the user asks to update/change something, update only the relevant files and return ALL files (unchanged ones too).
- Never return partial files. Always return the complete file content.
- If the user sends a follow-up, look at the current_files context and build upon it."""


def _call_nvidia(messages, current_files):
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return None, "GROQ_API_KEY not set"

    # Build context of current files for the AI
    files_context = ""
    if current_files:
        files_context = "\n\nCURRENT FILES IN PROJECT:\n"
        for f in current_files:
            preview = f["content"][:500] + ("..." if len(f["content"]) > 500 else "")
            files_context += f"\n--- {f['filename']} ---\n{preview}\n"

    # Inject files context into last user message
    api_messages = []
    for i, m in enumerate(messages):
        role = "user" if m["sender"] == "You" else "assistant"
        content = m["text"]
        if i == len(messages) - 1 and role == "user" and files_context:
            content = content + files_context
        api_messages.append({"role": role, "content": content})

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + api_messages,
            max_tokens=8192,
            temperature=0.3,
        )
        raw = completion.choices[0].message.content.strip()

        # Strip markdown fences if model wraps response
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            raw = raw.rsplit("```", 1)[0].strip()

        parsed = json.loads(raw)
        return parsed, None

    except requests.exceptions.Timeout:
        return None, "Request timed out. Try a simpler request."
    except json.JSONDecodeError as e:
        return None, f"AI returned invalid format: {str(e)}"
    except Exception as e:
        return None, str(e)


# ─── Routes ─────────────────────────────────────────────────────────────────

@website_bp.route("/project/website/<int:project_id>")
def website_editor(project_id):
    if "user" not in session:
        return redirect("/")
    username = session["user"]
    project = _get_project(project_id, username)
    if not project:
        return redirect("/landing")
    messages = _get_chat(project_id, username)
    files = _get_files(project_id, username)
    return render_template(
        "website_chat.html",
        project=dict(project),
        messages=messages,
        files=files,
        username=username
    )


@website_bp.route("/project/website/<int:project_id>/send", methods=["POST"])
def website_send(project_id):
    if "user" not in session:
        return jsonify({"error": "not_logged_in"}), 401

    username = session["user"]
    project = _get_project(project_id, username)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json(silent=True) or {}
    user_msg = data.get("message", "").strip()
    if not user_msg:
        return jsonify({"error": "empty"}), 400

    # Load existing chat + files
    messages = _get_chat(project_id, username)
    current_files = _get_files(project_id, username)

    # Append user message
    messages.append({"sender": "You", "text": user_msg})

    # Call NVIDIA
    result, error = _call_nvidia(messages, current_files)

    if error:
        messages.append({"sender": "Jarvis", "text": f"Sorry, something went wrong: {error}"})
        _save_chat(project_id, username, messages)
        return jsonify({"error": error, "message": error}), 500

    ai_message = result.get("message", "Done! Here's what I built.")
    new_files = result.get("files", [])

    # Save each file
    for f in new_files:
        fname = f.get("filename", "").strip()
        fcontent = f.get("content", "")
        if fname and fcontent:
            _save_file(project_id, username, fname, fcontent)

    # Save version snapshot if files changed
    if new_files:
        all_files = _get_files(project_id, username)
        _save_version(project_id, username, all_files)

    # Append AI message
    messages.append({"sender": "Jarvis", "text": ai_message})
    _save_chat(project_id, username, messages)

    # Return updated files list
    updated_files = _get_files(project_id, username)

    return jsonify({
        "message": ai_message,
        "files": updated_files,
    }), 200


@website_bp.route("/project/website/<int:project_id>/files")
def website_files(project_id):
    if "user" not in session:
        return jsonify({"error": "not_logged_in"}), 401
    username = session["user"]
    files = _get_files(project_id, username)
    return jsonify({"files": files}), 200


@website_bp.route("/project/website/<int:project_id>/file/<path:filename>")
def website_file_content(project_id, filename):
    if "user" not in session:
        return jsonify({"error": "not_logged_in"}), 401
    username = session["user"]
    from app import get_db, return_db
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT content FROM website_files WHERE project_id=%s AND username=%s AND filename=%s",
        (project_id, username, filename)
    )
    row = cur.fetchone()
    cur.close()
    return_db(conn)
    if not row:
        return jsonify({"error": "File not found"}), 404
    return jsonify({"filename": filename, "content": row["content"]}), 200


@website_bp.route("/project/website/<int:project_id>/preview")
def website_preview(project_id):
    """Serve the assembled website as a raw HTML page for iframe."""
    if "user" not in session:
        return "Unauthorized", 401
    username = session["user"]
    files = _get_files(project_id, username)

    if not files:
        return """<!DOCTYPE html><html><body style="font-family:sans-serif;display:flex;
        align-items:center;justify-content:center;height:100vh;margin:0;background:#0a0a0a;color:#666;">
        <p>No files yet. Start chatting to build your website!</p></body></html>"""

    # Find index.html
    index = next((f for f in files if f["filename"] == "index.html"), None)
    if not index:
        index = files[0]

    html = index["content"]
    index_folder = index["filename"].rsplit("/", 1)[0] if "/" in index["filename"] else ""

    # Build lookup: basename → content (handles folder-prefixed filenames)
    file_map = {}
    for f in files:
        if f["filename"] == index["filename"]:
            continue
        basename = f["filename"].rsplit("/", 1)[-1]
        file_map[basename] = f["content"]
        # Also store full path as key for exact matches
        file_map[f["filename"]] = f["content"]

    import re

    # Inline all <link rel="stylesheet" href="..."> tags
    def replace_css(m):
        href = m.group(1)
        basename = href.rsplit("/", 1)[-1]
        content = file_map.get(href) or file_map.get(basename)
        if content:
            return f'<style>{content}</style>'
        return m.group(0)
    html = re.sub(r'<link[^>]+rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)["\'][^>]*/?>', replace_css, html, flags=re.IGNORECASE)
    html = re.sub(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']stylesheet["\'][^>]*/?>', replace_css, html, flags=re.IGNORECASE)

    # Inline all <script src="..."> tags
    def replace_js(m):
        src = m.group(1)
        basename = src.rsplit("/", 1)[-1]
        content = file_map.get(src) or file_map.get(basename)
        if content:
            return f'<script>{content}</script>'
        return m.group(0)
    html = re.sub(r'<script[^>]+src=["\']([^"\']+)["\'][^>]*></script>', replace_js, html, flags=re.IGNORECASE)

    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@website_bp.route("/project/website/<int:project_id>/versions")
def website_versions(project_id):
    if "user" not in session:
        return jsonify({"error": "not_logged_in"}), 401
    username = session["user"]
    versions = _get_versions(project_id, username)
    return jsonify({"versions": versions}), 200


@website_bp.route("/project/website/<int:project_id>/restore/<int:version_id>", methods=["POST"])
def website_restore(project_id, version_id):
    if "user" not in session:
        return jsonify({"error": "not_logged_in"}), 401
    username = session["user"]
    ok = _restore_version(version_id, project_id, username)
    if not ok:
        return jsonify({"error": "Version not found"}), 404
    files = _get_files(project_id, username)
    return jsonify({"ok": True, "files": files}), 200


@website_bp.route("/project/website/<int:project_id>/download")
def website_download(project_id):
    """Download all files as a zip."""
    if "user" not in session:
        return "Unauthorized", 401
    import io
    import zipfile
    username = session["user"]
    project = _get_project(project_id, username)
    files = _get_files(project_id, username)

    if not files:
        return "No files to download", 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.writestr(f["filename"], f["content"])
    buf.seek(0)

    project_name = (project["name"] if project else "website").replace(" ", "_")
    return (
        buf.read(),
        200,
        {
            "Content-Type": "application/zip",
            "Content-Disposition": f'attachment; filename="{project_name}.zip"'
        }
    )


# ─── Run migration at import ─────────────────────────────────────────────────

try:
    init_website_db()
except Exception as e:
    print(f"[website_bp] DB migration warning: {e}")
