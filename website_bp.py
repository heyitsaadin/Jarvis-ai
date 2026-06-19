"""
website_bp.py  –  Website Creation Blueprint for Mia AI
Handles all /project/website/* routes.
Register in app.py with:
    from website_bp import website_bp
    app.register_blueprint(website_bp)

AI Backend: NVIDIA NIM — deepseek-ai/deepseek-v4-flash
Uses direct JSON responses — no streaming needed on Railway.
"""

import os
import json
import re
import io
import zipfile
from datetime import datetime, timezone, timedelta
from flask import (
    Blueprint, render_template, request, session,
    redirect, jsonify, Response
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


# ─── NVIDIA NIM client #2 (Nemotron — supports "Think" mode) ────────────────

def _nvidia3_client():
    return OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=os.environ.get("NVIDIA_API_3", ""),
    )


# ─── NVIDIA NIM client #4 (Kimi K2.6) ───────────────────────────────────────

def _nvidia4_client():
    return OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=os.environ.get("NVIDIA_API_4", ""),
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
- If the user sends a follow-up, look at the current_files context and build upon it.
- If the user sends a casual/conversational message (greetings, questions not about building a website, etc.),
  still respond with valid JSON but with an empty files array:
  {"message": "your friendly reply here", "files": []}
  Never return plain text — always return valid JSON."""


# ─── Intent check ────────────────────────────────────────────────────────────

CHAT_KEYWORDS = {
    "hi", "hey", "hello", "hola", "yo", "sup", "wassup", "whats up", "what's up",
    "how are you", "how r u", "u good", "you good", "how do you do",
    "good morning", "good evening", "good night", "gm", "gn",
    "thanks", "thank you", "thx", "ty", "np", "no problem", "ok", "okay", "k",
    "lol", "lmao", "haha", "nice", "cool", "great", "awesome", "wow",
    "bye", "goodbye", "cya", "see you", "later",
    "who are you", "what are you", "what can you do",
    "yes", "no", "yep", "nope", "sure", "maybe",
}

def _is_chat_message(msg: str) -> bool:
    """Return True if msg looks like casual chat rather than a website request."""
    clean = msg.strip().lower().rstrip("!?.,'")
    # Short messages (≤4 words) that match known chat phrases
    words = clean.split()
    if len(words) <= 6 and clean in CHAT_KEYWORDS:
        return True
    # Very short messages with no web-related words are likely chat
    web_hints = {"website", "site", "page", "build", "create", "make", "design",
                 "html", "css", "js", "landing", "portfolio", "blog", "shop",
                 "update", "change", "add", "remove", "fix", "style", "color",
                 "layout", "section", "navbar", "footer", "header", "button",
                 "form", "image", "font", "dark", "light", "animation", "menu"}
    has_web_hint = any(w in web_hints for w in words)
    if len(words) <= 3 and not has_web_hint:
        return True
    return False


def _chat_reply(msg: str) -> str:
    """Generate a quick conversational reply without touching the website AI."""
    low = msg.strip().lower().rstrip("!?.,")
    greetings = {"hi", "hey", "hello", "hola", "yo", "sup", "wassup",
                 "whats up", "what's up", "gm", "good morning", "good evening"}
    how_are = {"how are you", "how r u", "u good", "you good", "how do you do",
               "you ok", "u ok"}
    thanks   = {"thanks", "thank you", "thx", "ty"}
    bye      = {"bye", "goodbye", "cya", "see you", "later", "gn", "good night"}
    who      = {"who are you", "what are you", "what can you do"}

    if low in greetings:
        return "Hey! 👋 Ready to build something great. What kind of website do you have in mind?"
    if low in how_are:
        return "Doing great, thanks for asking! 😊 Ready to build whenever you are. What website can I create for you?"
    if low in thanks:
        return "You're welcome! Let me know if you want to tweak anything or build something new."
    if low in bye:
        return "See you! Come back anytime to keep building. 👋"
    if low in who:
        return "I'm Mia, your AI website builder! Describe any website — landing page, portfolio, blog, shop — and I'll generate the code instantly."
    return "I'm your website builder — describe a site you'd like and I'll create it for you! 🚀"


def _call_kimi(messages, current_files):
    """
    Direct (non-streaming) call to DeepSeek V4 Flash via NVIDIA NIM.
    Returns (parsed_dict, error_str).
    """
    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if not api_key:
        return None, "NVIDIA_API_KEY not set in environment."

    files_context = ""
    if current_files:
        files_context = "\n\nCURRENT FILES IN PROJECT:\n"
        for f in current_files:
            files_context += f"\n--- {f['filename']} ---\n{f['content']}\n"

    api_messages = []
    for i, m in enumerate(messages):
        role = "user" if m["sender"] == "You" else "assistant"
        content = m["text"]
        if i == len(messages) - 1 and role == "user" and files_context:
            content = content + files_context
        api_messages.append({"role": role, "content": content})

    try:
        client = _nvidia_client()
        response = client.chat.completions.create(
            model="deepseek-ai/deepseek-v4-flash",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + api_messages,
            max_tokens=16384,
            temperature=1,
            top_p=0.95,
            stream=False,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            raw = raw.rsplit("```", 1)[0].strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return None, f"AI returned invalid JSON: {str(e)}"
    except Exception as e:
        return None, str(e)


# ─── Groq direct call ────────────────────────────────────────────────────────

def _call_groq(messages, current_files):
    """
    Direct (non-streaming) call to Groq (llama-3.3-70b-versatile).
    Returns (parsed_dict, error_str).
    """
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return None, "GROQ_API_KEY not set in environment."

    files_context = ""
    if current_files:
        files_context = "\n\nCURRENT FILES IN PROJECT:\n"
        for f in current_files:
            files_context += f"\n--- {f['filename']} ---\n{f['content']}\n"

    api_messages = []
    for i, m in enumerate(messages):
        role = "user" if m["sender"] == "You" else "assistant"
        content = m["text"]
        if i == len(messages) - 1 and role == "user" and files_context:
            content = content + files_context
        api_messages.append({"role": role, "content": content})

    try:
        client = _groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + api_messages,
            max_tokens=8192,
            temperature=0.3,
            top_p=0.95,
            stream=False,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            raw = raw.rsplit("```", 1)[0].strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return None, f"AI returned invalid JSON: {str(e)}"
    except Exception as e:
        return None, str(e)


# ─── Nemotron direct call ────────────────────────────────────────────────────

def _call_nemotron(messages, current_files):
    """
    Direct (non-streaming) call to Nemotron 3 Ultra via NVIDIA NIM.
    Returns (parsed_dict, error_str).
    """
    api_key = os.environ.get("NVIDIA_API_3", "")
    if not api_key:
        return None, "NVIDIA_API_3 not set in environment."

    files_context = ""
    if current_files:
        files_context = "\n\nCURRENT FILES IN PROJECT:\n"
        for f in current_files:
            files_context += f"\n--- {f['filename']} ---\n{f['content']}\n"

    api_messages = []
    for i, m in enumerate(messages):
        role = "user" if m["sender"] == "You" else "assistant"
        content = m["text"]
        if i == len(messages) - 1 and role == "user" and files_context:
            content = content + files_context
        api_messages.append({"role": role, "content": content})

    try:
        client = _nvidia3_client()
        response = client.chat.completions.create(
            model="nvidia/nemotron-3-ultra-550b-a55b",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + api_messages,
            max_tokens=32768,
            temperature=0.6,
            top_p=0.95,
            stream=False,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            raw = raw.rsplit("```", 1)[0].strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return None, f"AI returned invalid JSON: {str(e)}"
    except Exception as e:
        return None, str(e)


# ─── Kimi K2.6 direct call ───────────────────────────────────────────────────

def _call_kimi_direct(messages, current_files):
    """
    Direct (non-streaming) call to Kimi K2.6 via NVIDIA NIM.
    Returns (parsed_dict, error_str).
    """
    api_key = os.environ.get("NVIDIA_API_4", "")
    if not api_key:
        return None, "NVIDIA_API_4 not set in environment."

    files_context = ""
    if current_files:
        files_context = "\n\nCURRENT FILES IN PROJECT:\n"
        for f in current_files:
            files_context += f"\n--- {f['filename']} ---\n{f['content']}\n"

    api_messages = []
    for i, m in enumerate(messages):
        role = "user" if m["sender"] == "You" else "assistant"
        content = m["text"]
        if i == len(messages) - 1 and role == "user" and files_context:
            content = content + files_context
        api_messages.append({"role": role, "content": content})

    try:
        client = _nvidia4_client()
        response = client.chat.completions.create(
            model="moonshotai/kimi-k2.6",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + api_messages,
            max_tokens=16384,
            temperature=0.7,
            top_p=0.95,
            stream=False,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            raw = raw.rsplit("```", 1)[0].strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return None, f"AI returned invalid JSON: {str(e)}"
    except Exception as e:
        return None, str(e)


# ─── Model registry ──────────────────────────────────────────────────────────
# Maps the model key sent from the frontend picker to its API config.
# Only "nemotron" supports the "Think" toggle (enable_thinking via
# chat_template_kwargs) — the other two ignore the `think` flag entirely.

MODEL_CONFIGS = {
    "nvidia": {
        "label": "DeepSeek V4 Flash",
        "model": "deepseek-ai/deepseek-v4-flash",
        "client_fn": _nvidia_client,
        "api_key_env": "NVIDIA_API_KEY",
        "max_tokens": 16384,
        "temperature": 1,
        "top_p": 0.95,
        "supports_think": False,
    },
    "groq": {
        "label": "Llama 3.3 70B (Groq)",
        "model": "llama-3.3-70b-versatile",
        "client_fn": _groq_client,
        "api_key_env": "GROQ_API_KEY",
        "max_tokens": 8192,
        "temperature": 0.3,
        "top_p": 0.95,
        "supports_think": False,
    },
    "nemotron": {
        "label": "Nemotron 3 Ultra",
        "model": "nvidia/nemotron-3-ultra-550b-a55b",
        "client_fn": _nvidia3_client,
        "api_key_env": "NVIDIA_API_3",
        "max_tokens": 32768,
        "temperature": 0.6,
        "top_p": 0.95,
        "supports_think": True,
    },
    "kimi": {
        "label": "Kimi K2.6",
        "model": "moonshotai/kimi-k2.6",
        "client_fn": _nvidia4_client,
        "api_key_env": "NVIDIA_API_4",
        "max_tokens": 16384,
        "temperature": 0.7,
        "top_p": 0.95,
        "supports_think": False,
    },
}
DEFAULT_MODEL = "nvidia"


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
    Direct JSON response — no SSE streaming.
    Returns JSON with { message, files, error }.
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

    # Detect @groq prefix
    use_groq = raw_msg.lower().startswith("@groq ")
    user_msg = raw_msg[6:].strip() if use_groq else raw_msg

    messages = _get_chat(project_id, username)
    current_files = _get_files(project_id, username)

    # ── Intent check ──────────────────────────────────────────────────────────
    if not use_groq and _is_chat_message(user_msg):
        reply = _chat_reply(user_msg)
        messages.append({"sender": "You", "text": user_msg})
        messages.append({"sender": "Mia", "text": reply})
        _save_chat(project_id, username, messages)
        return jsonify({"message": reply, "files": [], "error": None}), 200

    messages.append({"sender": "You", "text": user_msg})

    # Model selection — frontend sends { model: "nvidia"|"groq"|"nemotron"|"kimi" }
    selected_model = data.get("model", DEFAULT_MODEL)

    # Route to the correct direct-call function based on selected model
    if use_groq or selected_model == "groq":
        call_fn = _call_groq
    elif selected_model == "nemotron":
        call_fn = _call_nemotron
    elif selected_model == "kimi":
        call_fn = _call_kimi_direct
    else:
        call_fn = _call_kimi  # default: DeepSeek via nvidia

    result, error = call_fn(messages, current_files)

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
    updated_files = _get_files(project_id, username)

    return jsonify({
        "message": ai_message,
        "files": updated_files,
        "error": error,
    }), 200

@website_bp.route("/project/website/<int:project_id>/send-stream", methods=["POST"])
def website_send_stream(project_id):
    """
    SSE streaming endpoint.
    Streams raw JSON token-by-token from the AI so the frontend can
    render code live.  On completion sends a final 'done' event with
    { message, files, error } so the frontend can update the file list.
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

    # Model comes from the UI picker now. "@groq " prefix kept as a manual
    # override for backwards compatibility.
    model_choice = data.get("model", DEFAULT_MODEL)
    if model_choice not in MODEL_CONFIGS:
        model_choice = DEFAULT_MODEL
    if raw_msg.lower().startswith("@groq "):
        model_choice = "groq"
        raw_msg = raw_msg[6:].strip()

    think_enabled = bool(data.get("think", False)) and MODEL_CONFIGS[model_choice]["supports_think"]

    user_msg = raw_msg
    messages = _get_chat(project_id, username)
    current_files = _get_files(project_id, username)

    # ── Intent check: short-circuit casual chat without hitting website AI ──
    if _is_chat_message(user_msg):
        reply = _chat_reply(user_msg)
        messages.append({"sender": "You", "text": user_msg})
        messages.append({"sender": "Mia", "text": reply})
        _save_chat(project_id, username, messages)
        done_payload = json.dumps({"message": reply, "files": [], "error": None})
        def _chat_stream():
            yield f"event: done\ndata: {done_payload}\n\n"
        return Response(
            _chat_stream(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    messages.append({"sender": "You", "text": user_msg})

    # Build API messages list
    files_context = ""
    if current_files:
        files_context = "\n\nCURRENT FILES IN PROJECT:\n"
        for f in current_files:
            files_context += f"\n--- {f['filename']} ---\n{f['content']}\n"

    api_messages = []
    for i, m in enumerate(messages):
        role = "user" if m["sender"] == "You" else "assistant"
        content = m["text"]
        if i == len(messages) - 1 and role == "user" and files_context:
            content = content + files_context
        api_messages.append({"role": role, "content": content})

    def _start_stream(choice, think):
        """Create a streaming completion for the given model choice."""
        cfg = MODEL_CONFIGS[choice]
        api_key = os.environ.get(cfg["api_key_env"], "")
        if not api_key:
            raise RuntimeError(f"{cfg['api_key_env']} not set")
        client = cfg["client_fn"]()
        kwargs = dict(
            model=cfg["model"],
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + api_messages,
            max_tokens=cfg["max_tokens"],
            temperature=cfg["temperature"],
            top_p=cfg["top_p"],
            stream=True,
        )
        if cfg["supports_think"]:
            kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": think}}
        return client.chat.completions.create(**kwargs)

    def generate():
        accumulated = ""
        error = None

        try:
            stream = _start_stream(model_choice, think_enabled)
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                # "Think" reasoning tokens (Nemotron only) — streamed separately
                # so the frontend can show them in a collapsible thought panel.
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    yield f"data: {json.dumps({'reasoning': reasoning})}\n\n"

                content = delta.content if delta else None
                if content:
                    accumulated += content
                    yield f"data: {json.dumps({'chunk': content})}\n\n"

        except Exception as e:
            error = str(e)
            yield f"event: error\ndata: {json.dumps({'error': error})}\n\n"
            return

        # ── Parse + save ──────────────────────────────────────────
        result = None
        parse_error = None

        # If accumulated is empty, the primary AI returned nothing — fallback to Groq
        if not accumulated.strip() and model_choice != "groq":
            try:
                groq_api_key = os.environ.get("GROQ_API_KEY", "")
                if groq_api_key:
                    yield "data: " + json.dumps({"chunk": ""}) + "\n\n"
                    fb_client = _groq_client()
                    fb_resp = fb_client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + api_messages,
                        max_tokens=8192, temperature=0.3, top_p=0.95, stream=False,
                    )
                    accumulated = fb_resp.choices[0].message.content.strip()
            except Exception as fb_e:
                parse_error = f"Fallback also failed: {str(fb_e)}"

        try:
            raw = accumulated.strip()
            if not raw:
                raise json.JSONDecodeError("Empty response from AI", "", 0)
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw
                raw = raw.rsplit("```", 1)[0].strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
            result = json.loads(raw)
        except json.JSONDecodeError as e:
            parse_error = f"AI returned invalid JSON: {str(e)}"

        if result:
            ai_message = result.get("message", "Done!")
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
            _save_chat(project_id, username, messages)
            # Send file metadata only (no content) — frontend fetches full files via /files
            updated_files = _get_files(project_id, username)
            file_meta = [{"filename": f["filename"]} for f in updated_files]
            done_payload = json.dumps({
                "message": ai_message,
                "files": file_meta,
                "has_files": len(file_meta) > 0,
                "error": None,
            })
        else:
            err_text = parse_error or "Something went wrong."
            ai_message = f"Sorry, something went wrong: {err_text}"
            messages.append({"sender": "Mia", "text": ai_message})
            _save_chat(project_id, username, messages)
            done_payload = json.dumps({
                "message": ai_message,
                "files": [],
                "error": err_text,
            })

        yield f"event: done\ndata: {done_payload}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
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

# ─── Live Dev Server routes ───────────────────────────────────────────────────
# Serves the project at /dev/<project_id>/ so users can open it in a real
# browser tab (or point localhost/<path> at it) without an iframe.
# Sub-file requests (style.css, script.js, images) are served individually
# so relative links just work — no inlining needed.

@website_bp.route("/dev/<int:project_id>/")
@website_bp.route("/dev/<int:project_id>")
def website_dev_index(project_id):
    """Serve index.html for the live dev preview."""
    if "user" not in session:
        return "Unauthorized — please log in first.", 401
    username = session["user"]
    project = _get_project(project_id, username)
    if not project:
        return "Project not found.", 404

    files = _get_files(project_id, username)
    if not files:
        return (
            "<!DOCTYPE html><html><body style='font-family:sans-serif;"
            "display:flex;align-items:center;justify-content:center;"
            "height:100vh;margin:0;background:#0a0a0a;color:#666;'>"
            "<p>No files yet — go back and start chatting!</p></body></html>",
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    index = (
        next((f for f in files if f["filename"] == "index.html"), None)
        or next((f for f in files if f["filename"].endswith("/index.html")), None)
        or files[0]
    )

    # Rewrite asset links to point at /dev/<id>/<filename>
    html = index["content"]
    folder = index["filename"].rsplit("/", 1)[0] if "/" in index["filename"] else ""

    def rewrite_href(m):
        href = m.group(1)
        if href.startswith(("http", "//", "data:")):
            return m.group(0)
        # Strip any folder prefix the template may already have
        bare = href.rsplit("/", 1)[-1]
        return m.group(0).replace(href, f"/dev/{project_id}/{bare}")

    html = re.sub(r'href=["\']([^"\']+)["\']', rewrite_href, html)
    html = re.sub(r'src=["\']([^"\']+)["\']', rewrite_href, html)

    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@website_bp.route("/dev/<int:project_id>/<path:asset>")
def website_dev_asset(project_id, asset):
    """Serve a specific project file (CSS, JS, images, etc.)."""
    if "user" not in session:
        return "Unauthorized", 401
    username = session["user"]

    files = _get_files(project_id, username)
    # Match by basename or full path
    match = next(
        (f for f in files if f["filename"] == asset
         or f["filename"].rsplit("/", 1)[-1] == asset),
        None
    )
    if not match:
        return f"File not found: {asset}", 404

    ext = asset.rsplit(".", 1)[-1].lower() if "." in asset else ""
    mime_map = {
        "css":  "text/css",
        "js":   "application/javascript",
        "html": "text/html",
        "json": "application/json",
        "svg":  "image/svg+xml",
        "png":  "image/png",
        "jpg":  "image/jpeg",
        "jpeg": "image/jpeg",
        "ico":  "image/x-icon",
        "woff": "font/woff",
        "woff2":"font/woff2",
    }
    mime = mime_map.get(ext, "text/plain")
    return match["content"], 200, {"Content-Type": f"{mime}; charset=utf-8"}


try:
    init_website_db()
except Exception as e:
    print(f"[website_bp] DB migration warning: {e}")
