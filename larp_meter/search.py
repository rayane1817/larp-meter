"""Web footprint gathering: DuckDuckGo HTML endpoint + optional page fetching.

No API key, no dependencies, 7-day disk cache. Search engines throttle
aggressively, so every query is cached and re-runs of an audit are free.
"""

import hashlib
import html as html_lib
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import providers
from .providers import API_UA, BROWSER_UA

SEARCH_TTL = 7 * 24 * 3600
USER_AGENT = BROWSER_UA

TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)


def _clean(fragment):
    return html_lib.unescape(TAG_RE.sub("", fragment)).strip()


class WebSource:
    def __init__(self, cache_dir, delay=0.8, timeout=15):
        self.cache_dir = Path(cache_dir)
        self.delay = delay
        self.timeout = timeout

    def _cache_path(self, key):
        return self.cache_dir / (hashlib.sha1(key.encode()).hexdigest()[:16] + ".json")

    def _cached(self, key):
        cp = self._cache_path(key)
        if cp.exists() and time.time() - cp.stat().st_mtime < SEARCH_TTL:
            try:
                return json.loads(cp.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def _store(self, key, value):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._cache_path(key).write_text(json.dumps(value), encoding="utf-8")
        except Exception:
            pass

    def _fetch(self, url, data=None, timeout=None):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                ctype = resp.headers.get("Content-Type", "")
                if "html" not in ctype and "text" not in ctype and data is None:
                    return ""
                return resp.read(600_000).decode("utf-8", errors="replace")
        except Exception:
            return ""

    def search(self, query, limit=6):
        cached = self._cached("q:" + query)
        if cached is not None:
            return cached[:limit]

        html = self._fetch("https://html.duckduckgo.com/html/",
                           data=urllib.parse.urlencode({"q": query}).encode())
        results = []
        for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                             html, re.S):
            href, title_html = m.group(1), m.group(2)
            uddg = re.search(r"uddg=([^&]+)", href)
            url = urllib.parse.unquote(uddg.group(1)) if uddg else href
            title = _clean(title_html)
            if url.startswith("http") and title:
                results.append({"url": url, "title": title, "snippet": ""})
            if len(results) >= 12:
                break
        for i, s in enumerate(re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)):
            if i < len(results):
                results[i]["snippet"] = _clean(s)

        self._store("q:" + query, results)
        return results[:limit]

    def page_text(self, url, max_chars=6000):
        """Readable text of a page — used by --deep to enrich the corpus."""
        cached = self._cached("p:" + url)
        if cached is not None:
            return cached.get("text", "")
        html = self._fetch(url, timeout=10)
        text = _clean(SCRIPT_RE.sub(" ", html))
        text = re.sub(r"\s+", " ", text)[:max_chars]
        self._store("p:" + url, {"text": text})
        return text


def gather(name, cache_dir, deep=False, progress=None, refresh=False):
    """Gather a public footprint via the provider chain. Returns a Gathered bundle."""
    ws = WebSource(cache_dir)
    failures = []

    def fetch(url, browser=False):
        """Returns the body, or "" on failure. Failures are never cached.

        Caching an empty body on a network error turned a blocked or throttled
        request into a permanent "no third-party coverage exists" for the whole
        cache lifetime — and flag 10 then read that silence as an echo chamber.
        """
        if not refresh:
            cached = ws._cached("g:" + url)
            if cached is not None:
                return cached.get("body", "")
        headers = {"User-Agent": BROWSER_UA if browser else API_UA,
                   "Accept": "text/html" if browser else "application/json"}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=ws.timeout) as resp:
                body = resp.read(800_000).decode("utf-8", errors="replace")
        except Exception as exc:
            failures.append(f"{urllib.parse.urlsplit(url).hostname}: {type(exc).__name__}")
            return ""
        ws._store("g:" + url, {"body": body})
        time.sleep(ws.delay)
        return body

    bundle = providers.gather(name, fetch, progress=progress)

    if deep:
        extra = []
        for f in bundle.findings[:8]:
            # These URLs come from search results, i.e. from untrusted input.
            # Restrict to http(s) so --deep cannot be steered into file://,
            # ftp:// or a link-local metadata address.
            parts = urllib.parse.urlsplit(f.url)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                continue
            if parts.hostname in ("localhost", "127.0.0.1", "::1", "169.254.169.254"):
                continue
            if not f.about_subject:
                continue
            if progress:
                progress(f"reading {f.url[:60]}")
            body = ws.page_text(f.url)
            if body:
                extra.append(providers.Finding(f.url, f.title, body[:4000],
                                               f.provider, f.kind, f.independent, True))
        bundle.findings.extend(extra)

    # The search layer's own health, so downstream flags can tell "nobody has
    # written about this person" apart from "we could not ask".
    bundle.signals["search_failures"] = failures
    bundle.signals["search_ok"] = not failures or bool(bundle.providers_ok)

    shared = providers.shared_name_evidence(bundle.findings)
    if shared:
        bundle.signals["shared_name_evidence"] = shared
    return bundle
