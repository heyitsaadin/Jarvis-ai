"""
website_bp.py  –  Website Creation Blueprint for Mia AI
Handles all /project/website/* routes.
Register in app.py with:
    from website_bp import website_bp
    app.register_blueprint(website_bp)

AI Backend: NVIDIA NIM — minimaxai/minimax-m3
Uses SSE streaming to bypass Vercel's 10s serverless timeout.
Checkpoints are emitted at each stage so the frontend can show progress.
"""

import os
import json
import re
import io
import zipfile
from datetime import datetime, timezone, timedelta
from flask import (
    Blueprint, render_template, request, session,
    redirect, jsonify, Response, stream_with_context
)
import psycopg2
from psycopg2.extras import RealDictCursor
from openai import OpenAI

website_bp = Blueprint("website_bp", __name__)

IST = timezone(timedelta(hours=5, minutes=30))

# ─── NVIDIA NIM client ───────────────────────────────────────────────────────

def _nvidia_client():
    return OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=os.environ.get("NVIDIA_API_KEY", ""),
    )


# ─── Groq client ─────────────────────────────────────────────────────────────

def _groq_client():
    return OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=os.environ.get("GROQ_API_KEY", ""),
    )

# ─── DB init ─────────────────────────────────────────────────────────────────

def init_website_db():
    """Run safe migrations. Called once at import time."""
    from app import get_db, return_db
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


# ─── DB helpers ──────────────────────────────────────────────────────────────

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
    cur.execute("""
        INSERT INTO website_versions (project_id, username, label, snapshot, created_at)
        VALUES (%s, %s, %s, %s, %s)
    """, (project_id, username, label, json.dumps(files), now))
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


# ─── System prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert web developer AI inside a website builder called Mia AI.

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


# ─── SSE helper ──────────────────────────────────────────────────────────────

def _sse(payload: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(payload)}\n\n"


# ─── Streaming generator ──────────────────────────────────────────────────────

def _stream_minimax(messages, current_files):
    """
    Generator that yields SSE events:
      checkpoint  →  { checkpoint, label }
      token       →  { token, chars }
      done        →  { checkpoint:'done', result: {message, files} }
      error       →  { error }
    """
    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if not api_key:
        yield _sse({"error": "NVIDIA_API_KEY not set in environment."})
        return

    # ── Build files context ──────────────────────────────────────────────────
    files_context = ""
    if current_files:
        files_context = "\n\nCURRENT FILES IN PROJECT:\n"
        for f in current_files:
            files_context += f"\n--- {f['filename']} ---\n{f['content']}\n"

    # ── Build message history for API ────────────────────────────────────────
    api_messages = []
    for i, m in enumerate(messages):
        role = "user" if m["sender"] == "You" else "assistant"
        content = m["text"]
        if i == len(messages) - 1 and role == "user" and files_context:
            content = content + files_context
        api_messages.append({"role": role, "content": content})

    # ── Checkpoint 1: Starting ───────────────────────────────────────────────
    yield _sse({"checkpoint": "thinking", "label": "🧠 MiniMax is planning your website…"})

    try:
        client = _nvidia_client()
        stream = client.chat.completions.create(
            model="minimaxai/minimax-m3",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + api_messages,
            max_tokens=8192,
            temperature=0.3,
            top_p=0.95,
            stream=True,
            extra_body={
                "chat_template_kwargs": {"thinking_mode": "disabled"}
            }
        )

        full_text = ""
        files_checkpoint_sent = False
        char_count = 0

        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if not delta:
                continue

            full_text += delta
            char_count += len(delta)

            # ── Checkpoint 2: once "files" key appears ───────────────────────
            if not files_checkpoint_sent and '"files"' in full_text:
                files_checkpoint_sent = True
                yield _sse({"checkpoint": "writing", "label": "✍️ Writing your files…"})

            yield _sse({"token": delta, "chars": char_count})

        # ── Checkpoint 3: Parsing ────────────────────────────────────────────
        yield _sse({"checkpoint": "parsing", "label": "⚙️ Processing response…"})

        raw = full_text.strip()

        # Strip markdown fences if model wraps response
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            raw = raw.rsplit("```", 1)[0].strip()

        # Handle bare "json" prefix
        if raw.startswith("json"):
            raw = raw[4:].strip()

        parsed = json.loads(raw)

        # ── Checkpoint 4: Done ───────────────────────────────────────────────
        yield _sse({"checkpoint": "done", "result": parsed})

    except json.JSONDecodeError as e:
        yield _sse({"error": f"AI returned invalid JSON: {str(e)}. Raw length: {len(full_text)} chars."})
    except Exception as e:
        yield _sse({"error": str(e)})


# ─── Groq streaming generator ────────────────────────────────────────────────

def _stream_groq(messages, current_files):
    """
    Same SSE contract as _stream_minimax but routes to Groq (llama-3.3-70b-versatile).
    """
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        yield _sse({"error": "GROQ_API_KEY not set in environment."})
        return

    # ── Build files context ──────────────────────────────────────────────────
    files_context = ""
    if current_files:
        files_context = "\n\nCURRENT FILES IN PROJECT:\n"
        for f in current_files:
            files_context += f"\n--- {f['filename']} ---\n{f['content']}\n"

    # ── Build message history for API ────────────────────────────────────────
    api_messages = []
    for i, m in enumerate(messages):
        role = "user" if m["sender"] == "You" else "assistant"
        content = m["text"]
        if i == len(messages) - 1 and role == "user" and files_context:
            content = content + files_context
        api_messages.append({"role": role, "content": content})

    # ── Checkpoint 1: Starting ───────────────────────────────────────────────
    yield _sse({"checkpoint": "thinking", "label": "⚡ Groq is planning your website…"})

    try:
        client = _groq_client()
        stream = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + api_messages,
            max_tokens=8192,
            temperature=0.3,
            top_p=0.95,
            stream=True,
        )

        full_text = ""
        files_checkpoint_sent = False
        char_count = 0

        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if not delta:
                continue

            full_text += delta
            char_count += len(delta)

            if not files_checkpoint_sent and '"files"' in full_text:
                files_checkpoint_sent = True
                yield _sse({"checkpoint": "writing", "label": "✍️ Writing your files…"})

            yield _sse({"token": delta, "chars": char_count})

        # ── Checkpoint 3: Parsing ────────────────────────────────────────────
        yield _sse({"checkpoint": "parsing", "label": "⚙️ Processing response…"})

        raw = full_text.strip()

        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            raw = raw.rsplit("```", 1)[0].strip()

        if raw.startswith("json"):
            raw = raw[4:].strip()

        parsed = json.loads(raw)

        yield _sse({"checkpoint": "done", "result": parsed})

    except json.JSONDecodeError as e:
        yield _sse({"error": f"AI returned invalid JSON: {str(e)}. Raw length: {len(full_text)} chars."})
    except Exception as e:
        yield _sse({"error": str(e)})


# ─── Routes ──────────────────────────────────────────────────────────────────

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
    """
    Streams the AI response back as SSE events.
    Consume with fetch + ReadableStream on the frontend (not EventSource — this is POST).
    Checkpoints emitted:
      thinking  → model started
      writing   → "files" key spotted in stream
      parsing   → stream done, parsing JSON
      done      → parsed OK (result payload included)
      saving    → DB writes in progress
      complete  → all done, updated file list included
    """
    if "user" not in session:
        return jsonify({"error": "not_logged_in"}), 401

    username = session["user"]
    project = _get_project(project_id, username)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json(silent=True) or {}
    raw_msg = data.get("message", "").strip()
    if not raw_msg:
        return jsonify({"error": "empty"}), 400

    # ── Detect @groq prefix ───────────────────────────────────────────────────
    use_groq = raw_msg.lower().startswith("@groq ")
    user_msg = raw_msg[6:].strip() if use_groq else raw_msg

    messages = _get_chat(project_id, username)
    current_files = _get_files(project_id, username)
    # Store the clean message (without @groq prefix) in chat history
    messages.append({"sender": "You", "text": user_msg})

    def generate():
        result = None
        error = None

        # ── Stream from chosen backend ───────────────────────────────────────
        stream_fn = _stream_groq if use_groq else _stream_minimax
        for line in stream_fn(messages, current_files):
            yield line

            if line.startswith("data: "):
                try:
                    payload = json.loads(line[6:])
                    if "result" in payload:
                        result = payload["result"]
                    if "error" in payload:
                        error = payload["error"]
                except Exception:
                    pass

        # ── Checkpoint 5: Saving to DB ───────────────────────────────────────
        yield _sse({"checkpoint": "saving", "label": "💾 Saving files to database…"})

        if result:
            ai_message = result.get("message", "Done! Here's what I built.")
            new_files = result.get("files", [])

            for f in new_files:
                fname = f.get("filename", "").strip()
                fcontent = f.get("content", "")
                if fname and fcontent:
                    _save_file(project_id, username, fname, fcontent)

            if new_files:
                all_files = _get_files(project_id, username)
                _save_version(project_id, username, all_files)

            messages.append({"sender": "Mia", "text": ai_message})
        else:
            err_text = error or "Something went wrong."
            ai_message = f"Sorry, something went wrong: {err_text}"
            messages.append({"sender": "Mia", "text": ai_message})

        _save_chat(project_id, username, messages)

        # ── Checkpoint 6: All done ───────────────────────────────────────────
        updated_files = _get_files(project_id, username)
        yield _sse({
            "checkpoint": "complete",
            "message": ai_message,
            "files": updated_files,
            "error": error,
        })

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


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
    """Serve the assembled website as raw HTML for the iframe."""
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
        index = next((f for f in files if f["filename"].endswith("/index.html")), None)
    if not index:
        index = files[0]

    html = index["content"]

    # Build lookup: basename → content
    file_map = {}
    for f in files:
        if f["filename"] == index["filename"]:
            continue
        basename = f["filename"].rsplit("/", 1)[-1]
        file_map[basename] = f["content"]
        file_map[f["filename"]] = f["content"]

    # Inline CSS
    def replace_css(m):
        href = m.group(1)
        content = file_map.get(href) or file_map.get(href.rsplit("/", 1)[-1])
        return f"<style>{content}</style>" if content else m.group(0)

    html = re.sub(
        r'<link[^>]+rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)["\'][^>]*/?>',
        replace_css, html, flags=re.IGNORECASE
    )
    html = re.sub(
        r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']stylesheet["\'][^>]*/?>',
        replace_css, html, flags=re.IGNORECASE
    )

    # Inline JS
    def replace_js(m):
        src = m.group(1)
        content = file_map.get(src) or file_map.get(src.rsplit("/", 1)[-1])
        return f"<script>{content}</script>" if content else m.group(0)

    html = re.sub(
        r'<script[^>]+src=["\']([^"\']+)["\'][^>]*></script>',
        replace_js, html, flags=re.IGNORECASE
    )

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
    """Download all project files as a zip."""
    if "user" not in session:
        return "Unauthorized", 401
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


# ─── Run migration at import ──────────────────────────────────────────────────

try:
    init_website_db()
except Exception as e:
    print(f"[website_bp] DB migration warning: {e}")