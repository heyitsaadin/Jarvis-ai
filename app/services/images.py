"""Image generation, analysis and the background analysis worker."""

import threading
from PIL import Image as PILImage
from urllib.parse import quote
import atexit
import copy
import io as _io
import os
import queue
import requests
import time
from app.config import _HQ_KEYWORDS
from app.services.api_log import log_api_call
from app.services.chats import save_chat_session

# Background worker queue for image analysis (thread-safe).
_analysis_queue = queue.Queue()
_analysis_worker_running = True


def analysis_worker():
    while _analysis_worker_running:
        try:
            task = _analysis_queue.get(timeout=1)
            if task is None:
                break
            img_prompt, session_messages_copy, img_src, username, chat_key = task
            _run_image_analysis(img_prompt, session_messages_copy, img_src, username, chat_key)
        except queue.Empty:
            continue
        except Exception as e:
            print(f"Analysis worker error: {e}")


def _run_image_analysis(img_prompt, session_messages_copy, img_src, username, chat_key):
    import base64 as _b64
    try:
        if img_src and img_src.startswith("data:"):
            header, b64 = img_src.split(",", 1)
            img_bytes = _b64.b64decode(b64)
            img_bytes = compress_image(img_bytes)
            b64 = _b64.b64encode(img_bytes).decode("utf-8")
            mime = "image/jpeg"
        else:
            if img_src:
                img_url = img_src
            else:
                safe_prompt = quote(img_prompt)
                img_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=768&height=768&nologo=true&enhance=true"
            img_resp = requests.get(img_url, timeout=40)
            if img_resp.status_code != 200:
                return
            img_bytes = compress_image(img_resp.content)
            b64 = _b64.b64encode(img_bytes).decode("utf-8")
            mime = "image/jpeg"

        groq_key = os.environ.get("GROQ_API_KEY_2", "") or os.environ.get("GROQ_API_KEY", "")
        if not groq_key:
            return
        content = [
            {"type": "text", "text": "Describe this image in detail — include colours, objects, background, lighting, and any text visible."},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
        ]
        _t0 = time.time()
        try:
            res = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                json={
                    "model": "meta-llama/llama-4-maverick-17b-128e-instruct",
                    "messages": [{"role": "user", "content": content}],
                    "max_tokens": 400
                },
                timeout=35
            )
            _ms = int((time.time() - _t0) * 1000)
            rj = res.json()
            if "choices" in rj:
                log_api_call("groq", "GROQ_API_KEY(_2)", "image-analysis", True, res.status_code, _ms)
            else:
                log_api_call("groq", "GROQ_API_KEY(_2)", "image-analysis", False, res.status_code, _ms, str(rj.get("error", rj))[:500])
            description = rj["choices"][0]["message"]["content"].strip()
        except Exception as ex:
            log_api_call("groq", "GROQ_API_KEY(_2)", "image-analysis", False, None, int((time.time()-_t0)*1000), str(ex))
            raise
        if description:
            analysis_entry = {
                "sender": "Jarvis",
                "text": f"[IMAGE ANALYSIS RESULT]\n{description[:300]}"
            }
            session_messages_copy.append(analysis_entry)
            if username and chat_key:
                try:
                    save_chat_session(username, chat_key, session_messages_copy)
                except Exception:
                    pass
    except Exception as e:
        print(f"Image analysis failed: {e}")


@atexit.register
def shutdown_worker():
    global _analysis_worker_running
    _analysis_worker_running = False
    _analysis_queue.put(None)


def compress_image(raw_bytes, max_kb=2000):
    img = PILImage.open(_io.BytesIO(raw_bytes)).convert("RGB")
    initial_buf = _io.BytesIO()
    img.save(initial_buf, format="JPEG", quality=95)
    if initial_buf.tell() < max_kb * 1024:
        return initial_buf.getvalue()
    quality = 85
    max_iterations = 10
    last_size = float('inf')
    best_buf = initial_buf
    for _ in range(max_iterations):
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        size = buf.tell()
        if size < max_kb * 1024:
            return buf.getvalue()
        if last_size - size < 5000:
            best_buf = buf
            break
        last_size = size
        best_buf = buf
        quality -= 10
    if best_buf.tell() > max_kb * 1024:
        ratio = (max_kb * 1024) / best_buf.tell()
        new_size = (int(img.width * ratio**0.5), int(img.height * ratio**0.5))
        img.thumbnail(new_size, PILImage.Resampling.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=70, optimize=True)
        return buf.getvalue()
    return best_buf.getvalue()


def _img_html(src, prompt):
    """Build the image HTML block — uses jarvis-img CSS classes."""
    escaped = prompt.replace("'", "\\'")
    return (
        f'<div class="jarvis-img-wrap">'
        f'<img src="{src}" alt="{prompt}" class="jarvis-img" '
        f'onload="this.classList.add(\'loaded\')" '
        f'onerror="this.parentElement.innerHTML=\'❌ Could not generate image. Try a different prompt.\'">'
        f'<div class="jarvis-img-footer">'
        f'<span class="jarvis-img-caption">🎨 {prompt}</span>'
        f'<button onclick="downloadImage(\'{src}\',\'{escaped}\')" class="jarvis-img-dl">'
        f'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>'
        f'</button>'
        f'</div>'
        f'</div>'
    )


def _try_huggingface(prompt):
    import base64 as _b64
    # Try multiple HF API keys in sequence
    hf_keys = [
        os.environ.get("HF_API_KEY", ""),
        os.environ.get("HF_API_KEY_2", ""),
        os.environ.get("HF_API_KEY_3", ""),
        os.environ.get("HF_API_KEY_4", ""),
    ]
    hf_keys = [k for k in hf_keys if k]  # Filter out empty keys
    
    if not hf_keys:
        return None
    
    for idx, key in enumerate(hf_keys):
        _t0 = time.time()
        try:
            resp = requests.post(
                "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell",
                headers={"Authorization": f"Bearer {key}"},
                json={"inputs": prompt},
                timeout=60
            )
            _ms = int((time.time() - _t0) * 1000)
            if resp.status_code == 200 and resp.content:
                log_api_call("huggingface", f"HF_API_KEY_{idx+1}" if idx else "HF_API_KEY", "image-generation", True, resp.status_code, _ms)
                b64 = _b64.b64encode(resp.content).decode("utf-8")
                return _img_html(f"data:image/jpeg;base64,{b64}", prompt)
            elif resp.status_code != 200:
                error_detail = resp.text[:100] if resp.text else f"HTTP {resp.status_code}"
                log_api_call("huggingface", f"HF_API_KEY_{idx+1}" if idx else "HF_API_KEY", "image-generation", False, resp.status_code, _ms, error_detail)
                print(f"[IMG][HF] key #{idx+1} returned {resp.status_code}: {error_detail}")
        except Exception as e:
            error_msg = str(e)[:150]
            log_api_call("huggingface", f"HF_API_KEY_{idx+1}" if idx else "HF_API_KEY", "image-generation", False, None, int((time.time()-_t0)*1000), error_msg)
            print(f"[IMG][HF] key #{idx+1} exception: {error_msg}")
    return None


def _try_together(prompt):
    """Together AI — FLUX.1-schnell-Free."""
    import base64 as _b64
    key = os.environ.get("TOGETHER_API_KEY", "")
    if not key:
        return None
    _t0 = time.time()
    try:
        res = requests.post(
            "https://api.together.xyz/v1/images/generations",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "black-forest-labs/FLUX.1-schnell-Free", "prompt": prompt,
                  "width": 768, "height": 768, "steps": 4, "n": 1},
            timeout=60
        )
        _ms = int((time.time() - _t0) * 1000)
        data = res.json()
        if res.status_code == 200 and data.get("data"):
            log_api_call("together", "TOGETHER_API_KEY", "image-generation", True, res.status_code, _ms)
            item = data["data"][0]
            b64_raw = item.get("b64_json", "")
            url     = item.get("url", "")
            if b64_raw:
                return _img_html(f"data:image/jpeg;base64,{b64_raw}", prompt)
            if url:
                img_resp = requests.get(url, timeout=30)
                if img_resp.status_code == 200:
                    b64 = _b64.b64encode(img_resp.content).decode("utf-8")
                    return _img_html(f"data:image/jpeg;base64,{b64}", prompt)
        else:
            log_api_call("together", "TOGETHER_API_KEY", "image-generation", False, res.status_code, _ms, str(data)[:300])
    except Exception as e:
        log_api_call("together", "TOGETHER_API_KEY", "image-generation", False, None, int((time.time()-_t0)*1000), str(e))
        print(f"[IMG][Together] exception: {e}")
    return None


def _try_stable_horde(prompt):
    """Stable Horde — free community GPU pool, no account needed."""
    import base64 as _b64
    import time as _time
    api_key = os.environ.get("HORDE_API_KEY", "0000000000")
    _t0 = time.time()
    try:
        submit = requests.post(
            "https://stablehorde.net/api/v2/generate/async",
            headers={"apikey": api_key, "Content-Type": "application/json"},
            json={
                "prompt": prompt,
                "params": {"sampler_name": "k_euler", "cfg_scale": 7,
                           "steps": 20, "width": 512, "height": 512, "n": 1},
                "models": ["Deliberate", "stable_diffusion"],
                "r2": True, "nsfw": False,
            },
            timeout=20
        )
        if submit.status_code != 202:
            log_api_call("stablehorde", "HORDE_API_KEY", "image-generation", False, submit.status_code, int((time.time()-_t0)*1000), submit.text[:300])
            return None
        job_id = submit.json().get("id")
        if not job_id:
            log_api_call("stablehorde", "HORDE_API_KEY", "image-generation", False, submit.status_code, int((time.time()-_t0)*1000), "no job id returned")
            return None
        for _ in range(18):
            _time.sleep(5)
            check  = requests.get(f"https://stablehorde.net/api/v2/generate/check/{job_id}",
                                  headers={"apikey": api_key}, timeout=10)
            if check.json().get("done"):
                break
        else:
            log_api_call("stablehorde", "HORDE_API_KEY", "image-generation", False, None, int((time.time()-_t0)*1000), "generation timed out")
            return None
        result      = requests.get(f"https://stablehorde.net/api/v2/generate/status/{job_id}",
                                   headers={"apikey": api_key}, timeout=15)
        generations = result.json().get("generations", [])
        if not generations:
            log_api_call("stablehorde", "HORDE_API_KEY", "image-generation", False, result.status_code, int((time.time()-_t0)*1000), "no generations returned")
            return None
        img_url = generations[0].get("img", "")
        if not img_url:
            log_api_call("stablehorde", "HORDE_API_KEY", "image-generation", False, result.status_code, int((time.time()-_t0)*1000), "no img url in generation")
            return None
        img_resp = requests.get(img_url, timeout=30)
        if img_resp.status_code == 200:
            log_api_call("stablehorde", "HORDE_API_KEY", "image-generation", True, img_resp.status_code, int((time.time()-_t0)*1000))
            b64 = _b64.b64encode(img_resp.content).decode("utf-8")
            ct  = img_resp.headers.get("content-type", "image/webp")
            ext = "png" if "png" in ct else "jpeg" if "jpeg" in ct else "webp"
            return _img_html(f"data:image/{ext};base64,{b64}", prompt)
        log_api_call("stablehorde", "HORDE_API_KEY", "image-generation", False, img_resp.status_code, int((time.time()-_t0)*1000), "final image fetch failed")
    except Exception as e:
        log_api_call("stablehorde", "HORDE_API_KEY", "image-generation", False, None, int((time.time()-_t0)*1000), str(e))
        print(f"[IMG][Horde] exception: {e}")
    return None


def generate_image(prompt):
    # 1. HuggingFace FLUX.1-schnell (primary) - tries multiple API keys
    html = _try_huggingface(prompt)
    if html:
        return html
    # 2. Together AI (backup if HF fails)
    html = _try_together(prompt)
    if html:
        return html
    # 3. Stable Horde (final backup)
    html = _try_stable_horde(prompt)
    if html:
        return html
    return "❌ Image generation failed - all providers unavailable right now. Try again in a moment."


def is_high_quality_request(prompt):
    p = prompt.lower()
    return any(kw in p for kw in _HQ_KEYWORDS)


def generate_image_nvidia(prompt):
    import base64 as _b64
    nvapi_key = os.environ.get("NVIDIA_API_KEY_2", "")
    if not nvapi_key:
        return generate_image(prompt), "fallback"
    try:
        res = requests.post(
            "https://integrate.api.nvidia.com/v1/images/generations",
            headers={"Authorization": f"Bearer {nvapi_key}", "Content-Type": "application/json"},
            json={"model": "qwen/qwen-image", "prompt": prompt, "n": 1, "size": "1024x1024"},
            timeout=60
        )
        data = res.json()
        if "data" in data and data["data"]:
            item       = data["data"][0]
            img_url    = item.get("url", "")
            b64_result = item.get("b64_json", "")
            if b64_result:
                src = f"data:image/png;base64,{b64_result}"
            elif img_url:
                src = img_url
            else:
                return generate_image(prompt), "fallback"
            return _img_html(src, prompt) + " ✨", "nvidia"
        return generate_image(prompt), "fallback"
    except Exception:
        return generate_image(prompt), "fallback"


def analyse_generated_image(img_prompt, user_question):
    import base64 as _b64
    try:
        safe_prompt = quote(img_prompt)
        img_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=768&height=768&nologo=true&enhance=true"
        img_resp = requests.get(img_url, timeout=30)
        if img_resp.status_code != 200:
            return None
        img_bytes = compress_image(img_resp.content)
        b64 = _b64.b64encode(img_bytes).decode("utf-8")
        groq_key = os.environ.get("GROQ_API_KEY_2", "") or os.environ.get("GROQ_API_KEY", "")
        if not groq_key:
            return None
        question = user_question.strip() if user_question.strip() else "Describe this image in detail."
        content = [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
        ]
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
            json={
                "model": "meta-llama/llama-4-maverick-17b-128e-instruct",
                "messages": [{"role": "user", "content": content}],
                "max_tokens": 500
            },
            timeout=30
        )
        return res.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def _auto_analyse_generated_image(img_prompt, session_messages, img_src=None, username=None, chat_key=None):
    """Queue image analysis to background worker (non-blocking, thread-safe)"""
    session_copy = copy.deepcopy(session_messages)
    _analysis_queue.put((img_prompt, session_copy, img_src, username, chat_key))


analysis_thread = threading.Thread(target=analysis_worker, daemon=True)
analysis_thread.start()
