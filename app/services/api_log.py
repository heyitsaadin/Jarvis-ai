"""Outbound API call logging and provider key registry."""

from datetime import datetime, timezone, timedelta
import os
from app.config import IST, SILICONFLOW_API_KEY
from app.services.database import get_db, return_db


def log_api_call(provider, key_label, endpoint, success, status_code=None, response_ms=None, error_message=None):
    """Record one outbound API call so the admin panel can show usage + health.
    Never raises — logging must not break the caller's actual request."""
    try:
        conn = get_db()
        cur = conn.cursor()
        now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            """INSERT INTO api_call_logs
               (provider, key_label, endpoint, success, status_code, response_ms, error_message, called_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (provider, key_label, endpoint, bool(success), status_code, response_ms,
             (error_message[:500] if error_message else None), now)
        )
        conn.commit()
        cur.close()
        return_db(conn)
    except Exception as e:
        print(f"[api_log] failed to record call: {e}")


# ── API KEY USAGE + HEALTH ──────────────────────────────────────────────
# Providers Jarvis calls out to. Each entry knows how to run a cheap,
# real request against that provider so admin can check it's still working.
def _api_key_registry():
    return {
        "groq": {
            "label": "Groq (chat + vision)",
            "keys": [k for k in [
                ("GROQ_API_KEY", os.environ.get("GROQ_API_KEY", "")),
                ("GROQ_API_KEY_2", os.environ.get("GROQ_API_KEY_2", "")),
                ("GROQ_API_KEY_3", os.environ.get("GROQ_API_KEY_3", "")),
            ] if k[1]],
        },
        "huggingface": {
            "label": "HuggingFace (image generation)",
            "keys": [k for k in [
                ("HF_API_KEY", os.environ.get("HF_API_KEY", "")),
                ("HF_API_KEY_2", os.environ.get("HF_API_KEY_2", "")),
                ("HF_API_KEY_3", os.environ.get("HF_API_KEY_3", "")),
                ("HF_API_KEY_4", os.environ.get("HF_API_KEY_4", "")),
            ] if k[1]],
        },
        "together": {
            "label": "Together AI (image generation)",
            "keys": [k for k in [("TOGETHER_API_KEY", os.environ.get("TOGETHER_API_KEY", ""))] if k[1]],
        },
        "stablehorde": {
            "label": "Stable Horde (image generation)",
            "keys": [("HORDE_API_KEY", os.environ.get("HORDE_API_KEY", "0000000000"))],
        },
        "youtube": {
            "label": "YouTube Data API (video search)",
            "keys": [k for k in [("YOUTUBE_API_KEY", os.environ.get("YOUTUBE_API_KEY", ""))] if k[1]],
        },
        "siliconflow": {
            "label": "SiliconFlow",
            "keys": [k for k in [("SILICONFLOW_API_KEY", SILICONFLOW_API_KEY)] if k[1]],
        },
        "nvidia": {
            "label": "NVIDIA NIM",
            "keys": [k for k in [("NVIDIA_API_KEY_2", os.environ.get("NVIDIA_API_KEY_2", ""))] if k[1]],
        },
    }
