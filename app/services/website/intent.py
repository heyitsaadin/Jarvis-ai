"""Casual-chat detection so greetings never hit the (expensive) website model."""

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
