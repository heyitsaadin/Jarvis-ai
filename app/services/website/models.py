"""Model registry and the single non-streaming call used by every provider."""
import json
import os
from app.services.website.clients import (
    _nvidia_client, _groq_client, _nvidia3_client, _nvidia4_client,
)
from app.services.website.prompts import SYSTEM_PROMPT

# Maps the model key sent from the frontend picker to its API config.
# Only "nemotron" supports the "Think" toggle (enable_thinking via
# chat_template_kwargs) - the other models ignore the `think` flag entirely.

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


# Maps the legacy per-model function names to registry keys.
_LEGACY_KEYS = {
    "_call_kimi": "nvidia",         # DeepSeek V4 Flash via NVIDIA NIM (the default)
    "_call_groq": "groq",
    "_call_nemotron": "nemotron",
    "_call_kimi_direct": "kimi",
}


def build_files_context(current_files):
    """Serialise the project's current files for the model's prompt."""
    if not current_files:
        return ""
    ctx = "\n\nCURRENT FILES IN PROJECT:\n"
    for f in current_files:
        ctx += f"\n--- {f['filename']} ---\n{f['content']}\n"
    return ctx


def build_api_messages(messages, current_files):
    """Convert stored chat messages to API messages; attach files to the last user turn."""
    files_context = build_files_context(current_files)
    api_messages = []
    for i, m in enumerate(messages):
        role = "user" if m["sender"] == "You" else "assistant"
        content = m["text"]
        if i == len(messages) - 1 and role == "user" and files_context:
            content = content + files_context
        api_messages.append({"role": role, "content": content})
    return api_messages


def strip_code_fences(raw):
    """Remove a leading ```json fence / trailing ``` the model may wrap around JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0].strip()
    if raw.startswith("json"):
        raw = raw[4:].strip()
    return raw


def call_model(model_key, messages, current_files):
    """
    Direct (non-streaming) call to the model registered under `model_key`.
    Returns (parsed_dict, error_str).

    Replaces four copy-pasted functions that differed only in the config
    values already stored in MODEL_CONFIGS. Like them, it never sends the
    Nemotron "think" flag (only the streaming endpoint does).
    """
    cfg = MODEL_CONFIGS[model_key]
    api_key = os.environ.get(cfg["api_key_env"], "")
    if not api_key:
        return None, f"{cfg['api_key_env']} not set in environment."

    api_messages = build_api_messages(messages, current_files)

    try:
        client = cfg["client_fn"]()
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + api_messages,
            max_tokens=cfg["max_tokens"],
            temperature=cfg["temperature"],
            top_p=cfg["top_p"],
            stream=False,
        )
        raw = strip_code_fences(response.choices[0].message.content)
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return None, f"AI returned invalid JSON: {str(e)}"
    except Exception as e:
        return None, str(e)
