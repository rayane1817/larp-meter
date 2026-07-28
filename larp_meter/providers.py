"""Evidence providers for web mode.

v2 and early v3 depended on scraping one search engine. That engine now answers
automated requests with an anti-bot page, which took the whole mode down — and
scraped SERP snippets were weak evidence anyway.

The chain here leads with authoritative, key-free APIs that answer the questions
this tool actually asks — does this person have a publication record? is there
independent encyclopedic coverage? — and treats HTML search as an optional
bonus. Every provider fails soft: an unreachable source contributes nothing and
is reported as unavailable, never as evidence against the subject.
"""

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import names
from .matching import host_matches

API_UA = ("larp-meter/3.0 (OSINT due-diligence triage; "
          "+https://github.com/rayane1817/larp-meter)")
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# Platforms the subject controls: presence there is self-publication, not validation.
CONTROLLED_HOSTS = (
    "linkedin.com", "medium.com", "substack.com", "wordpress.com", "blogspot.com",
    "wixsite.com", "facebook.com", "x.com", "twitter.com", "instagram.com",
    "youtube.com", "about.me", "angel.co", "notion.site",
)


@dataclass
class Finding:
    url: str
    title: str
    snippet: str = ""
    provider: str = ""
    kind: str = "web"          # encyclopedia | publication | profile | web
    independent: bool = True   # not a platform the subject controls
    about_subject: bool = True # does this material actually describe the subject?

    def as_text(self):
        return f"{self.title}. {self.snippet}".strip()


@dataclass
class Gathered:
    findings: list = field(default_factory=list)
    signals: dict = field(default_factory=dict)   # structured, per-provider facts
    providers_ok: list = field(default_factory=list)
    providers_failed: list = field(default_factory=list)

    @property
    def corpus(self):
        """Only material that plausibly describes the subject.

        A name search returns several different people. Pouring all of it into
        one profile would attribute a stranger's claims to the subject — the
        cheapest way this tool could produce a false accusation.
        """
        return "\n".join(f.as_text() for f in self.findings if f.about_subject)

    @property
    def urls(self):
        return self._urls(only_used=False)

    @property
    def used_urls(self):
        return self._urls(only_used=True)

    def _urls(self, only_used):
        seen, out = set(), []
        for f in self.findings:
            if only_used and not f.about_subject:
                continue
            if f.url and f.url not in seen:
                seen.add(f.url)
                out.append(f.url)
        return out

    @property
    def discarded(self):
        return [f for f in self.findings if not f.about_subject]


def _is_independent(url):
    return not host_matches(url, CONTROLLED_HOSTS)


class Provider:
    name = "provider"
    kind = "web"

    def __init__(self, fetch):
        self._fetch = fetch

    def search(self, subject):
        raise NotImplementedError


class Wikipedia(Provider):
    """Independent encyclopedic coverage — the strongest cheap validation signal."""
    name = "wikipedia"
    kind = "encyclopedia"

    def search(self, subject):
        url = ("https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch="
               + urllib.parse.quote(f'"{subject}"') + "&format=json&srlimit=5")
        body = self._fetch(url)
        if not body:
            return [], {}
        try:
            hits = json.loads(body)["query"]["search"]
        except Exception:
            return [], {}

        findings, exact = [], []
        for h in hits:
            title = h.get("title", "")
            snippet = re.sub(r"<[^>]+>", "", h.get("snippet", ""))
            page = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
            # An article ABOUT the subject is validation; one that merely mentions
            # them is not, and its text must not be read as their own claims.
            is_about = bool(names.name_matches(subject, [title]))
            findings.append(Finding(page, title, snippet, self.name, self.kind, True, is_about))
            if is_about:
                exact.append(title)
        return findings, {"wikipedia_articles": len(findings),
                          "wikipedia_about_subject": exact}


class OpenAlex(Provider):
    """Scholarly record: works, citations, affiliations. Free, no key, authoritative."""
    name = "openalex"
    kind = "publication"

    def search(self, subject):
        url = ("https://api.openalex.org/authors?search=" + urllib.parse.quote(subject)
               + "&per_page=5")
        body = self._fetch(url)
        if not body:
            return [], {}
        try:
            results = json.loads(body).get("results", [])
        except Exception:
            return [], {}

        findings, best, matches = [], None, 0
        for a in results:
            display = a.get("display_name", "")
            if not names.name_matches(subject, [display]):
                continue      # a different researcher who happens to rank highly
            matches += 1
            works = a.get("works_count", 0)
            cited = a.get("cited_by_count", 0)
            insts = [i.get("display_name") for i in (a.get("last_known_institutions") or [])
                     if i.get("display_name")]
            findings.append(Finding(
                a.get("id", ""), f"{display} — scholarly record",
                f"{works} works, {cited} citations"
                + (f", affiliated with {', '.join(insts)}" if insts else ""),
                self.name, self.kind, True, True))
            if best is None or works > best.get("works", 0):
                best = {"works": works, "citations": cited, "institutions": insts,
                        "orcid": a.get("orcid"), "display_name": display}
        signals = {"openalex": best}
        # Several distinct researchers sharing the name means any web-mode
        # conclusion may be conflating people. The human needs to know.
        if matches > 1:
            signals["ambiguous_identity"] = matches
        return findings, signals


class Crossref(Provider):
    """Publication titles by author name — corroborates or contradicts a research claim."""
    name = "crossref"
    kind = "publication"

    def search(self, subject):
        url = ("https://api.crossref.org/works?query.author=" + urllib.parse.quote(subject)
               + "&rows=5&select=title,author,issued,DOI")
        body = self._fetch(url)
        if not body:
            return [], {}
        try:
            items = json.loads(body)["message"]["items"]
        except Exception:
            return [], {}

        findings = []
        for it in items:
            authors = [f"{a.get('given', '')} {a.get('family', '')}".strip()
                       for a in it.get("author", [])]
            if not names.name_matches(subject, authors):
                continue
            title = (it.get("title") or ["untitled"])[0]
            doi = it.get("DOI", "")
            findings.append(Finding(f"https://doi.org/{doi}" if doi else "", title,
                                    f"authors: {', '.join(authors[:5])}",
                                    self.name, self.kind, True, True))
        return findings, {"crossref_works": len(findings)}


class DuckDuckGo(Provider):
    """Best-effort general web search. Frequently blocked; never required."""
    name = "duckduckgo"
    kind = "web"

    def search(self, subject):
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(f'"{subject}"')
        body = self._fetch(url, browser=True)
        if not body or "result__a" not in body:
            return [], {}
        findings = []
        for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                             body, re.S):
            href, title_html = m.group(1), m.group(2)
            uddg = re.search(r"uddg=([^&]+)", href)
            link = urllib.parse.unquote(uddg.group(1)) if uddg else href
            title = re.sub(r"<[^>]+>", "", title_html).strip()
            if link.startswith("http") and title:
                # A general web hit only counts as the subject's if their name
                # is actually in it; namesakes are otherwise silently merged.
                is_about = bool(names.name_matches(subject, [title]))
                findings.append(Finding(link, title, "", self.name, self.kind,
                                        _is_independent(link), is_about))
            if len(findings) >= 8:
                break
        return findings, {}


ALL_PROVIDERS = (Wikipedia, OpenAlex, Crossref, DuckDuckGo)


def gather(subject, fetch, providers=ALL_PROVIDERS, progress=None):
    """Run every provider. Returns a Gathered bundle; failures are recorded, not raised."""
    out = Gathered()
    for cls in providers:
        provider = cls(fetch)
        if progress:
            progress(f"querying {provider.name}")
        try:
            findings, signals = provider.search(subject)
        except Exception:
            findings, signals = [], {}
        if findings or signals:
            out.providers_ok.append(provider.name)
        else:
            out.providers_failed.append(provider.name)
        out.findings.extend(findings)
        out.signals.update(signals)
    return out
