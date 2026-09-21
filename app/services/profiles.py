"""Per-user interest profile and AI-generated summary."""

from datetime import datetime, timezone, timedelta
from psycopg2.extras import RealDictCursor
import json as _json_mod
import os
import requests
import threading
from app.config import IST, TOPIC_KEYWORDS
from app.services.database import get_db, return_db


def get_profile(username):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT profile_json FROM user_profiles WHERE username=%s", (username,))
    row = cur.fetchone()
    cur.close()
    return_db(conn)
    if row:
        return _json_mod.loads(row["profile_json"])
    return {
        "interests": {k: 0 for k in TOPIC_KEYWORDS},
        "total_messages": 0,
        "user_messages": 0,
        "avg_length": 0,
        "peak_hour": None,
        "hour_counts": {},
        "top_topics": [],
        "sentiment": "neutral",
        "last_groq_analysis": None,
        "groq_summary": ""
    }


def save_profile(username, profile):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    cur.execute("""
        INSERT INTO user_profiles (username, profile_json, last_updated)
        VALUES (%s, %s, %s)
        ON CONFLICT (username) DO UPDATE SET profile_json=%s, last_updated=%s
    """, (username, _json_mod.dumps(profile), now, _json_mod.dumps(profile), now))
    conn.commit()
    cur.close()
    return_db(conn)


def update_profile(username, message, sender):
    profile = get_profile(username)
    profile["total_messages"] += 1
    if sender == "You":
        profile["user_messages"] += 1
        prev_avg = profile.get("avg_length", 0)
        n = profile["user_messages"]
        profile["avg_length"] = round(((prev_avg * (n - 1)) + len(message)) / n)
        msg_lower = message.lower()
        for topic, keywords in TOPIC_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in msg_lower)
            if hits:
                profile["interests"][topic] = round(profile["interests"].get(topic, 0) + hits * 0.1, 2)
        hour = str(datetime.now(IST).hour)
        hc = profile.get("hour_counts", {})
        hc[hour] = hc.get(hour, 0) + 1
        profile["hour_counts"] = hc
        profile["peak_hour"] = max(hc, key=hc.get)
        sorted_topics = sorted(profile["interests"].items(), key=lambda x: x[1], reverse=True)
        profile["top_topics"] = [t for t, s in sorted_topics if s > 0][:5]
    save_profile(username, profile)
    if sender == "You" and profile["user_messages"] % 15 == 0:
        threading.Thread(target=_groq_profile_update, args=(username, message), daemon=True).start()


def _groq_profile_update(username, last_message):
    try:
        profile = get_profile(username)
        API_KEY = os.environ.get("GROQ_API_KEY", "")
        if not API_KEY:
            return
        top = profile.get("top_topics", [])
        prompt = (
            f"A user has been chatting with an AI assistant. "
            f"Their current top interests based on keyword analysis: {top}. "
            f"Their latest message: '{last_message[:200]}'. "
            f"Their message count: {profile['user_messages']}, avg message length: {profile.get('avg_length',0)} chars. "
            f"In 1-2 sentences, write a friendly summary of this user's personality and interests. "
            f"Also rate their overall sentiment as one of: curious, creative, technical, casual, mixed. "
            'Reply ONLY as JSON: {"summary": "...", "sentiment": "..."}'
        )
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={"model": "openai/gpt-oss-20b", "messages": [{"role": "user", "content": prompt}], "max_tokens": 120, "temperature": 0.4},
            timeout=15
        )
        raw = res.json()["choices"][0]["message"]["content"].strip()
        raw = raw.replace("```json","").replace("```","").strip()
        parsed = _json_mod.loads(raw)
        profile["groq_summary"]       = parsed.get("summary", "")
        profile["sentiment"]          = parsed.get("sentiment", "neutral")
        profile["last_groq_analysis"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
        save_profile(username, profile)
    except Exception:
        pass
