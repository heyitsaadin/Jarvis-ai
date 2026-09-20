"""Small pure helpers (intent detection, math, greetings)."""

from datetime import datetime, timezone, timedelta
import ast
from app.config import BAD_WORDS, DATE_TRIGGERS, IMAGE_TRIGGERS, IST, TIME_TRIGGERS, _HQ_KEYWORDS


def get_greeting(username):
    hour = datetime.now(IST).hour
    if hour < 12:
        time_greets = [
            f"Morning, {username}! ☀️ What are we tackling today?",
            f"Rise and shine, {username}! Let's get into it — what's first?",
            f"Good morning, {username}! Brain's warmed up. What do you need?",
            f"Hey {username}! Early bird energy. What's on your mind?",
            f"Morning! I'm already thinking, {username} — give me something good.",
        ]
    elif hour < 17:
        time_greets = [
            f"Hey {username}! Midday hit different — what are we doing?",
            f"Afternoon, {username}! Still got tons of energy. What's up?",
            f"What's good, {username}? Let's make this afternoon count.",
            f"Hey! {username}, I've been waiting — what do you need?",
            f"Afternoon, {username}! Drop it on me — I'm ready.",
        ]
    else:
        time_greets = [
            f"Evening, {username}! Still up? Let's get things done.",
            f"Hey {username}! Night owl mode activated — what's the move?",
            f"Good evening, {username}! I don't sleep, so you're covered.",
            f"Evening! {username}, you and me, let's figure something out.",
            f"Hey {username}! Late session? I'm fully charged — what do you need?",
        ]
    return time_greets[datetime.now(IST).minute % len(time_greets)]


def safe_eval(expr):
    expr = expr.replace("×", "*").replace("÷", "/").replace(" x ", "*").strip()
    try:
        tree = ast.parse(expr, mode='eval')
        allowed_nodes = (
            ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
            ast.FloorDiv, ast.USub, ast.UAdd
        )
        for node in ast.walk(tree):
            if not isinstance(node, allowed_nodes):
                raise ValueError("Invalid expression")
        return eval(compile(tree, "<string>", "eval"), {"__builtins__": {}}, {})
    except (ValueError, SyntaxError, ZeroDivisionError):
        raise ValueError("Invalid expression")


def contains_bad_words(text):
    return any(word in text.lower() for word in BAD_WORDS)


def is_asking_time(text):
    return any(t in text.lower().strip() for t in TIME_TRIGGERS)


def is_asking_date(text):
    return any(t in text.lower().strip() for t in DATE_TRIGGERS)


def is_code_request(text):
    code_keywords = [
        "code", "program", "script", "function", "write a", "create a program",
        "implement", "algorithm", "syntax", "compile", "c++", "python", "java",
        "javascript", "html", "css", "snippet", "example code", "source code"
    ]
    return any(kw in text.lower() for kw in code_keywords)


def is_image_request(text):
    t = text.lower()
    if any(trigger in t for trigger in IMAGE_TRIGGERS):
        return True
    has_hq = any(kw in t for kw in _HQ_KEYWORDS)
    is_question = t.strip().startswith(("what", "why", "how", "when", "who", "where", "is ", "are ", "do ", "does ", "can "))
    return has_hq and not is_question


def extract_image_prompt(text):
    t = text.lower()
    for trigger in sorted(IMAGE_TRIGGERS, key=len, reverse=True):
        if trigger in t:
            idx = t.find(trigger) + len(trigger)
            prompt = text[idx:].strip().lstrip("of ").strip()
            return prompt if prompt else text
    return text
