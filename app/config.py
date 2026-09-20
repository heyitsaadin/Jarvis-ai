"""Central configuration: environment variables, constants and trigger lists.

Importing this module validates required environment variables, exactly as
the original single-file app did at import time.
"""
import os
from datetime import timezone, timedelta

REQUIRED_ENV_VARS = ["DATABASE_URL", "GROQ_API_KEY", "ADMIN_PASSWORD"]
MISSING_VARS = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
if MISSING_VARS:
    raise ValueError(f"Missing required environment variables: {', '.join(MISSING_VARS)}")

if not os.environ.get("OWNER_CODE"):
    print("WARNING: OWNER_CODE not set. Owner verification will not work.")
if not os.environ.get("DISCORD_WEBHOOK"):
    print("WARNING: DISCORD_WEBHOOK not set. Security alerts will not be sent.")

ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
OWNER_CODE     = os.environ.get("OWNER_CODE", "")
ADMIN_SLUG     = os.environ.get("ADMIN_SLUG", "x7k2mq9p")
ADMIN_BASE     = f"/admin/{ADMIN_SLUG}"
IST            = timezone(timedelta(hours=5, minutes=30))
DATABASE_URL   = os.environ["DATABASE_URL"]

_malayalam = os.environ.get("MALAYALAM_BAD_WORDS", "")
_english   = os.environ.get("ENGLISH_BAD_WORDS", "")
BAD_WORDS = (
    [w.strip() for w in _malayalam.split(",") if w.strip()] +
    [w.strip() for w in _english.split(",")   if w.strip()]
)

TIME_TRIGGERS = [
    "what time is it", "what's the time", "whats the time",
    "current time", "tell me the time", "the time now",
    "time now", "time please", "what time"
]
DATE_TRIGGERS = [
    "what's the date", "whats the date", "what date is it",
    "today's date", "todays date", "current date",
    "what day is it", "what's today", "whats today",
    "today is what", "tell me the date", "date today",
    "day today", "which day"
]
IMAGE_TRIGGERS = [
    "generate an image", "generate image", "create an image", "create image",
    "draw an image", "draw a", "draw me", "make an image", "make a picture",
    "generate a picture", "create a picture", "show me an image of",
    "show me a picture of", "generate a photo", "create a photo",
    "make an illustration", "generate art", "create art", "draw art",
    "imagine", "visualize", "generate a", "make a drawing",
    "image of", "picture of", "photo of", "illustration of"
]

TOPIC_KEYWORDS = {
    "coding":   ["code","python","javascript","html","css","function","bug","error","script","program","api","git","database","sql","flask","react","debug"],
    "images":   ["image","picture","photo","generate","draw","art","illustration","visual","design","logo","poster"],
    "math":     ["calculate","math","equation","solve","formula","algebra","geometry","percent","multiply","divide"],
    "writing":  ["write","essay","story","poem","email","letter","summarise","summarize","draft","paragraph","blog"],
    "general":  ["explain","what","how","why","who","when","where","tell me","define","meaning"],
    "creative": ["idea","brainstorm","creative","imagine","concept","suggest","help me think"],
    "tech":     ["ai","machine learning","neural","model","gpt","chatgpt","jarvis","llm","data","server","cloud"],
    "personal": ["i feel","i am","my life","im sad","im happy","struggling","advice","help me"],
}

_HQ_KEYWORDS = [
    "high quality", "high-quality", "hq", "realistic", "photorealistic",
    "photo realistic", "ultra realistic", "4k", "8k", "detailed", "highly detailed",
    "professional", "cinematic", "sharp", "best quality", "masterpiece",
    "hyper realistic", "hyperrealistic", "lifelike", "stunning", "premium"
]

# Paths (project root = parent of this package)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
PROPERTIES_FILE = os.path.join(DATA_DIR, "properties.txt")

_TILDE_NO_ANSWER_TOKEN = "##NO_MATCH##"

GUEST_MSG_LIMIT     = 10
GUEST_IMG_LIMIT     = 2
GUEST_ANALYSIS_LIMIT = 2
GUEST_EDIT_LIMIT    = 1
GUEST_QUIZ_LIMIT    = 1

# Flask session / cookie settings (applied by the app factory)
SECRET_KEY = os.environ.get("SECRET_KEY", "jarvis_ai_stable_secret_key_8a5c26c")
FLASK_CONFIG = {
    "SESSION_PERMANENT": True,
    "PERMANENT_SESSION_LIFETIME": timedelta(days=90),
    "MAX_COOKIE_SIZE": 4093,
    "SESSION_COOKIE_SAMESITE": "None",
    "SESSION_COOKIE_SECURE": True,
    "SESSION_COOKIE_HTTPONLY": True,
}
