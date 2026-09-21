"""Top-level reply builder that orchestrates all services."""

from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, request, redirect, session, jsonify, send_from_directory
import hmac
import re
import threading
import time
from app.config import IST, OWNER_CODE
from app.services.ai import ask_jarvis_brain
from app.services.chats import save_history
from app.services.database import get_db, return_db
from app.services.images import _auto_analyse_generated_image, generate_image, generate_image_nvidia, is_high_quality_request
from app.services.search import _do_google_search, search_youtube
from app.services.security import send_discord_alert
from app.utils.helpers import contains_bad_words, is_asking_date, is_asking_time, safe_eval


def _build_reply(user_msg):
    reply = ""
    if session.get("awaiting_owner_code"):
        if hmac.compare_digest(user_msg.strip(), OWNER_CODE):
            session["is_owner"]            = True
            session["awaiting_owner_code"] = False
            reply = "🔐 Identity confirmed. Welcome back, Aadin. 🔓"
        else:
            session["awaiting_owner_code"] = False
            send_discord_alert(session["user"], "Failed owner code attempt", user_msg)
            reply = "Incorrect code. Access denied."
        return reply
    # /search command — force Google search, no hallucination
    if user_msg.lower().startswith('/search '):
        query = user_msg[8:].strip()
        if not query:
            return "Usage: /search <your query>"
        result = _do_google_search(query, user_msg=query)
        if result:
            return result
        return "Couldn't find results for that. Try rephrasing."
        return "❌ Google search returned no results for that. Try a different query."

    if is_asking_time(user_msg):
        return "🕐 It's " + datetime.now(IST).strftime("%I:%M %p") + " IST right now!"
    if is_asking_date(user_msg):
        return "📅 Today is " + datetime.now(IST).strftime("%A, %B %d %Y") + "!"
    if user_msg.lower() == "history":
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT calculation FROM history WHERE username=%s", (session["user"],))
        rows = cur.fetchall()
        cur.close()
        return_db(conn)
        return ("📜 Here's your calculation history:\n" + "\n".join(r[0] for r in rows) if rows else "🤷 No history yet!")
    if (any(op in user_msg for op in ["+", "-", "*", "/", "×", "÷"]) and any(c.isdigit() for c in user_msg)):
        try:
            result = safe_eval(user_msg)
            reply  = f"{user_msg} = {result}"
            save_history(session["user"], reply)
            return reply
        except Exception:
            pass
    if contains_bad_words(user_msg):
        send_discord_alert(session["user"], "Abusive language toward Jarvis or Aadin", user_msg)
    _img_question_triggers = [
        "color", "colour", "what is in", "what's in", "whats in",
        "describe", "explain", "what does", "tell me about", "analyse",
        "analyze", "what is the image", "what's the image", "name",
        "species", "type of", "what kind", "background", "foreground",
        "what animal", "what object", "what is it", "what's it",
    ]
    _has_recent_image = any(
        'jarvis-img-wrap' in m.get("text", "") or 'mia-img-wrap' in m.get("text", "") or m.get("text", "").startswith("[IMAGE GENERATED:")
        for m in session.get("messages", [])
    )
    _is_img_question = _has_recent_image and any(t in user_msg.lower() for t in _img_question_triggers)
    if _is_img_question:
        _waited = 0
        while _waited < 8:
            _has_analysis = any(m.get("text", "").startswith("[IMAGE ANALYSIS RESULT]") for m in session.get("messages", []))
            if _has_analysis:
                break
            time.sleep(0.5)
            _waited += 0.5
    decision = ask_jarvis_brain(user_msg, session["messages"])
    action   = decision["action"]

    if action == "get_time":
        return "🕐 It's " + datetime.now(IST).strftime("%I:%M %p") + " IST right now!"

    if action == "get_date":
        return "📅 Today is " + datetime.now(IST).strftime("%A, %B %d %Y") + "!"

    if action == "math":
        expr = decision["reply"].strip() or user_msg
        try:
            result = safe_eval(expr)
            calc_reply = f"{expr} = {result}"
            save_history(session["user"], calc_reply)
            return calc_reply
        except Exception:
            action = "text"  # fall through to text handler below

    if action == "quiz_redirect":
        return "📄 Upload a PDF on the <a href='/quiz' style='text-decoration:underline'>Quiz page</a> and I'll generate questions for you! 🎓"

    if action == "web_search":
        query = decision["reply"].strip() or user_msg
        result = _do_google_search(query, user_msg=user_msg)
        if result:
            return result
        return "I couldn't find any current information on that. Try asking differently or use /search <query> to search directly."

    if action == "youtube_search":
        query     = decision["reply"].strip() or user_msg
        plus_text = decision.get("youtube_plus_text", "").strip()
        yt_html   = search_youtube(query)
        if plus_text:
            return f"{plus_text}##YT_SPLIT##{yt_html}"
        return yt_html

    if action == "text":
        raw_reply = decision["reply"]
        if "##OWNER_CLAIM##" in raw_reply:
            session["awaiting_owner_code"] = True
            return "Identity Code, please?"
        if "##SECURITY_BREACH##" in raw_reply:
            send_discord_alert(session["user"], "User attempted to extract sensitive system info", user_msg)
            return "I don't have access to that information."
        if "##IMAGE:" in raw_reply:
            m2 = re.search(r'##IMAGE:(.*?)##', raw_reply, re.DOTALL)
            img_prompt = m2.group(1).strip() if m2 else raw_reply.split("##IMAGE:", 1)[1].strip().rstrip("#").strip()
            if is_high_quality_request(img_prompt) or decision["high_quality"]:
                reply, _ = generate_image_nvidia(img_prompt)
            else:
                reply = generate_image(img_prompt)
            _msgs_copy = list(session["messages"])
            threading.Thread(
                target=_auto_analyse_generated_image,
                args=(img_prompt, _msgs_copy, None, session.get("user"), session.get("chat_key")),
                daemon=True
            ).start()
            return reply
        return raw_reply
    if action in ("generate_image", "edit_image"):
        img_prompt = decision["image_prompt"].strip()
        if not img_prompt:
            return "Sure! What would you like me to draw? Describe the image and I'll generate it 🎨"
        if decision["high_quality"] or is_high_quality_request(img_prompt):
            reply, _src_type = generate_image_nvidia(img_prompt)
            _img_src = None
        else:
            reply = generate_image(img_prompt)
            _img_src = None
        _msgs_copy = list(session["messages"])
        threading.Thread(
            target=_auto_analyse_generated_image,
            args=(img_prompt, _msgs_copy, _img_src, session.get("user"), session.get("chat_key")),
            daemon=True
        ).start()
        return reply
    return decision.get("reply") or "I'm having a moment — try again! 😅"
