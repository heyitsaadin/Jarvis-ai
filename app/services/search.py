"""Wikipedia, Google and YouTube lookups."""

import os
import requests
import time
from app.services.api_log import log_api_call


def wikipedia_search(query):
    """Wikipedia search — free, no API key needed. Returns list of results or None."""
    try:
        search_resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "srlimit": 4,
                "srprop": "snippet"
            },
            timeout=10
        )
        items = search_resp.json().get("query", {}).get("search", [])
        if not items:
            return None
        results = []
        for item in items:
            title = item.get("title", "")
            snippet = item.get("snippet", "").replace('<span class="searchmatch">', "").replace("</span>", "")
            url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
            results.append({"title": title, "snippet": snippet, "url": url})
        return results
    except Exception as e:
        print(f"[WIKI SEARCH] exception: {e}")
        return None


def _do_google_search(query, user_msg=None):
    """Wikipedia search wrapper. Never hallucinates — returns None if no results."""
    results = wikipedia_search(query)
    if not results:
        return None
    sources_html = (
        '<div class="wsearch-wrap">'
        '<div class="wsearch-header">📖 Wikipedia Results</div>'
        '<div class="wsearch-results">' +
        "".join([
            f'<a class="wsearch-result" href="{r["url"]}" target="_blank">'
            f'<span class="wsearch-title">{r["title"]}</span>'
            f'<span class="wsearch-snippet">{r["snippet"]}</span>'
            f'<span class="wsearch-url">{r["url"]}</span>'
            f'</a>'
            for r in results
        ]) +
        '</div></div>'
    )
    context = "\n".join([f"- {r['title']}: {r['snippet']}" for r in results])
    groq_key = os.environ.get("GROQ_API_KEY", "")
    summary = ""
    if groq_key and user_msg:
        try:
            sum_resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                json={
                    "model": "openai/gpt-oss-20b",
                    "messages": [
                        {"role": "system", "content": "Answer using ONLY the Wikipedia results below. Be concise (2-3 sentences). Don't say 'based on search results' or 'according to'."},
                        {"role": "user", "content": f"Question: {user_msg}\n\nWikipedia results:\n{context}"}
                    ],
                    "max_tokens": 200
                },
                timeout=15
            )
            summary = sum_resp.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            pass
    if summary:
        return f"{summary}\n\n{sources_html}"
    return sources_html


def search_youtube(query):
    from urllib.parse import quote as _url_quote
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    safe_q  = _url_quote(query)
    fallback = (
        f'<div class="jarvis-yt-wrap jarvis-yt-fallback">'
        f'<a href="https://www.youtube.com/results?search_query={safe_q}" '
        f'target="_blank" class="jarvis-yt-link">&#9658; Search YouTube: {query}</a>'
        f'</div>'
    )
    if not api_key:
        print("[YT] No YOUTUBE_API_KEY set — returning fallback link")
        return fallback
    _t0 = time.time()
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": 1,
                "key": api_key,
                "safeSearch": "moderate",
                "videoEmbeddable": "true",
            },
            timeout=10
        )
        _ms = int((time.time() - _t0) * 1000)
        raw = resp.json()
        print(f"[YT] API status={resp.status_code} keys={list(raw.keys())}")
        if "error" in raw:
            print(f"[YT] API error: {raw['error']}")
            log_api_call("youtube", "YOUTUBE_API_KEY", "search", False, resp.status_code, _ms, str(raw["error"])[:400])
            return fallback
        items = raw.get("items", [])
        if not items:
            print(f"[YT] No items returned for query: {query}")
            log_api_call("youtube", "YOUTUBE_API_KEY", "search", False, resp.status_code, _ms, "no items returned")
            return fallback
        log_api_call("youtube", "YOUTUBE_API_KEY", "search", True, resp.status_code, _ms)
        item    = items[0]
        vid_id  = item["id"]["videoId"]
        title   = item["snippet"]["title"].replace('"', '&quot;').replace("'", "&#39;")
        channel = item["snippet"]["channelTitle"].replace('"', '&quot;').replace("'", "&#39;")
        print(f"[YT] Found: {vid_id} — {title}")
        return (
            f'<div class="jarvis-yt-wrap">'
            f'<div class="jarvis-yt-player">'
            f'<iframe src="https://www.youtube.com/embed/{vid_id}?rel=0&modestbranding=1" '
            f'title="{title}" frameborder="0" allowfullscreen '
            f'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture">'
            f'</iframe></div>'
            f'<div class="jarvis-yt-footer">'
            f'<span class="jarvis-yt-title">&#9658; {title}</span>'
            f'<span class="jarvis-yt-channel">{channel}</span>'
            f'</div></div>'
        )
    except Exception as e:
        log_api_call("youtube", "YOUTUBE_API_KEY", "search", False, None, int((time.time()-_t0)*1000), str(e))
        print(f"[YT] Exception: {e}")
        return fallback
