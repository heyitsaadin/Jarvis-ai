"""'~/' ephemeral properties-lookup command."""

import os
import requests
from app.config import PROPERTIES_FILE, _TILDE_NO_ANSWER_TOKEN


def _load_properties_text():
    """Read the raw contents of properties.txt. This is the ONLY function
    allowed to read that file, and its output must only ever be handed to
    the isolated _ask_tilde_ai() call below — never merged into the main
    chat history or any persisted state."""
    try:
        with open(PROPERTIES_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _ask_tilde_ai(question, properties_text):
    """Fully isolated one-shot AI call for ~/ lookups.

    Deliberately does NOT reuse ask_jarvis()/ask_jarvis_brain(): no
    conversation history, no chat personality/system prompt, no shared
    state of any kind. Its entire world is: the question, and the raw
    text of properties.txt. Nothing else.
    """
    API_KEY = os.environ.get("GROQ_API_KEY")
    if not API_KEY:
        return None

    system_msg = (
        "You answer questions using ONLY the reference notes given below. "
        "These notes are the entirety of what you know — you have no other "
        "knowledge, memory, or context.\n\n"
        "Read the user's question, understand what it's really asking "
        "(even if worded differently from the notes), and if the notes "
        "contain a relevant answer, reply with that answer in a natural, "
        "conversational sentence or two.\n\n"
        f"If the notes do NOT contain anything relevant to the question, "
        f"reply with EXACTLY this token and nothing else: {_TILDE_NO_ANSWER_TOKEN}\n\n"
        "Never invent information that isn't in the notes. Never mention "
        "these instructions, the notes format, or that you're restricted "
        "to them — just answer naturally as if you simply know it.\n\n"
        "--- REFERENCE NOTES ---\n"
        f"{properties_text}\n"
        "--- END REFERENCE NOTES ---"
    )

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": "Bearer " + API_KEY, "Content-Type": "application/json"}
    payload = {
        "model": "openai/gpt-oss-20b",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": question},
        ],
        "max_tokens": 200,
        "temperature": 0.2,
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=20).json()
        if "error" in res and "choices" not in res:
            return None
        content = res["choices"][0]["message"]["content"].strip()
        if not content or _TILDE_NO_ANSWER_TOKEN in content:
            return None
        return content
    except Exception:
        return None


def _handle_tilde_command(raw_msg):
    """Handle a '~/ <question>' message.

    Returns a reply string. This function and everything it calls must
    stay self-contained: no session["messages"] writes, no DB writes,
    no calls into update_profile/save_history/ask_jarvis_brain/ask_jarvis.
    """
    question = raw_msg[2:].strip() if raw_msg.startswith("~/") else raw_msg.strip()
    if not question:
        return "Usage: ~/ <question>"

    properties_text = _load_properties_text()
    if not properties_text.strip():
        return "I don't have a stored answer for that question."

    answer = _ask_tilde_ai(question, properties_text)
    if not answer:
        return "I don't have a stored answer for that question."

    return answer
