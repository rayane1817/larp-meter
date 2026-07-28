"""Live verification of extracted claims against public registries.

Design rules, in order of importance:

1. A network failure is NEVER evidence of deception. Anything we cannot reach
   comes back UNCHECKABLE and is excluded from scoring — it lowers coverage,
   not the subject's score.
2. Existence is not attribution. When the subject's name is known, a DOI/ORCID/
   repo that exists but does not list them returns MISMATCH, which is a far
   stronger signal than a missing artifact.
3. Everything is cached on disk (30 days) so re-runs are free and we stay
   polite to free APIs.

All calls use urllib from the stdlib — the tool keeps its zero-dependency promise.
"""

import json
import hashlib
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from xml.etree import ElementTree

from . import names
from .extract import VERIFIED, MISMATCH, NOT_FOUND, UNCHECKABLE

VERIFY_TTL = 30 * 24 * 3600
USER_AGENT = ("larp-meter/3.0 (OSINT due-diligence triage; "
              "+https://github.com/rayane1817/larp-meter)")
TIMEOUT = 12


# Words that carry no identifying information in an organization name.
_ORG_STOPWORDS = {
    "of", "the", "at", "for", "and", "in", "de", "des", "du", "der", "die", "das",
    "van", "von", "el", "la", "le", "les", "a", "an", "università", "universite",
}


def _significant_tokens(name):
    return {t for t in re.split(r"[^\w]+", (name or "").casefold())
            if t and t not in _ORG_STOPWORDS and len(t) > 1}


def _is_ambiguous_acronym(name):
    """A bare short acronym identifies an institution only weakly (MIT, UCL, ULB...)."""
    stripped = (name or "").strip()
    return len(stripped) <= 5 and " " not in stripped and stripped.isupper()


def _ror_names(item):
    """Every name variant of a ROR v2 record (display name, labels, aliases, acronyms)."""
    names = item.get("names")
    if isinstance(names, list):                      # ROR v2 schema
        return [n.get("value", "") for n in names if isinstance(n, dict) and n.get("value")]
    legacy = [item.get("name", "")]                  # ROR v1 fallback
    legacy += list(item.get("aliases") or []) + list(item.get("acronyms") or [])
    return [n for n in legacy if n]


def _ror_country(item):
    if not item:
        return ""
    locations = item.get("locations") or []
    if locations:
        country = (locations[0].get("geonames_details") or {}).get("country_name")
        if country:
            return f" ({country})"
    country = (item.get("country") or {}).get("country_name")      # v1 fallback
    return f" ({country})" if country else ""


class Verifier:
    def __init__(self, cache_dir, subject_name=None, enabled=True, timeout=TIMEOUT):
        self.cache_dir = Path(cache_dir)
        self.subject_name = subject_name or ""
        self.enabled = enabled
        self.timeout = timeout
        self.calls = 0
        self.network_failures = 0

    # ── plumbing ────────────────────────────────────────────────────────
    def _cache_path(self, key):
        return self.cache_dir / (hashlib.sha1(key.encode()).hexdigest()[:20] + ".json")

    def _get(self, url, accept="application/json"):
        """Fetch + cache. Returns (payload_text, ok). ok=False means unreachable."""
        cp = self._cache_path(url)
        if cp.exists() and time.time() - cp.stat().st_mtime < VERIFY_TTL:
            try:
                blob = json.loads(cp.read_text(encoding="utf-8"))
                return blob.get("body", ""), blob.get("ok", False)
            except Exception:
                pass
        if not self.enabled:
            return "", False

        headers = {"User-Agent": USER_AGENT, "Accept": accept}
        token = os.environ.get("GITHUB_TOKEN")
        if token and "api.github.com" in url:
            headers["Authorization"] = f"Bearer {token}"

        body, ok = "", False
        try:
            self.calls += 1
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body, ok = resp.read().decode("utf-8", errors="replace"), True
        except urllib.error.HTTPError as e:
            # 404/410 is a real answer: the registry says it does not exist.
            if e.code in (404, 410):
                body, ok = "", True
            else:
                self.network_failures += 1
                return "", False
        except Exception:
            self.network_failures += 1
            return "", False

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            cp.write_text(json.dumps({"body": body, "ok": ok}), encoding="utf-8")
        except Exception:
            pass
        return body, ok

    # ── name matching ───────────────────────────────────────────────────
    def _name_matches(self, candidates):
        """True when the subject appears in `candidates`; None when unanswerable."""
        return names.name_matches(self.subject_name, candidates)

    def _attribute(self, claim, names, label, url):
        """Shared tail: artifact exists — does it belong to the subject?"""
        match = self._name_matches(names)
        shown = ", ".join(names[:4]) or "no names listed"
        if match is None:
            claim.status, claim.detail = VERIFIED, f"{label} exists ({shown}). Pass --name to check attribution."
        elif match:
            claim.status, claim.detail = VERIFIED, f"{label} exists and lists the subject ({shown})."
        else:
            claim.status, claim.detail = MISMATCH, f"{label} exists but does NOT list the subject ({shown})."
        claim.source = url

    # ── per-registry verifiers ──────────────────────────────────────────
    def verify_doi(self, claim):
        url = f"https://api.crossref.org/works/{urllib.parse.quote(claim.value)}"
        body, ok = self._get(url)
        if not ok:
            return self._uncheckable(claim, "Crossref unreachable")
        if not body:
            claim.status = NOT_FOUND
            claim.detail = "Crossref has no record of this DOI."
            claim.source = url
            return claim
        try:
            msg = json.loads(body)["message"]
        except Exception:
            return self._uncheckable(claim, "Crossref returned an unparseable record")
        title = (msg.get("title") or ["untitled"])[0]
        authors = [f"{a.get('given', '')} {a.get('family', '')}".strip()
                   for a in msg.get("author", [])]
        self._attribute(claim, authors, f'Paper "{title[:70]}"', url)
        return claim

    def verify_orcid(self, claim):
        url = f"https://pub.orcid.org/v3.0/{claim.value}/person"
        body, ok = self._get(url)
        if not ok:
            return self._uncheckable(claim, "ORCID unreachable")
        if not body:
            claim.status = NOT_FOUND
            claim.detail = "No such ORCID record."
            claim.source = url
            return claim
        try:
            person = json.loads(body)
            name = person.get("name") or {}
            given = ((name.get("given-names") or {}) or {}).get("value", "")
            family = ((name.get("family-name") or {}) or {}).get("value", "")
            full = f"{given} {family}".strip() or "name withheld"
        except Exception:
            return self._uncheckable(claim, "ORCID returned an unparseable record")
        self._attribute(claim, [full], "ORCID record", url)
        return claim

    def verify_github(self, claim):
        path = claim.value.strip("/")
        is_repo = "/" in path
        url = (f"https://api.github.com/repos/{path}" if is_repo
               else f"https://api.github.com/users/{path}")
        body, ok = self._get(url)
        if not ok:
            return self._uncheckable(claim, "GitHub API unreachable or rate-limited")
        if not body:
            claim.status = NOT_FOUND
            claim.detail = f"GitHub {'repository' if is_repo else 'user'} '{path}' does not exist."
            claim.source = url
            return claim
        try:
            data = json.loads(body)
        except Exception:
            return self._uncheckable(claim, "GitHub returned an unparseable record")
        if is_repo:
            stars = data.get("stargazers_count", 0)
            pushed = (data.get("pushed_at") or "")[:10]
            archived = data.get("archived")
            empty = data.get("size", 0) == 0
            claim.status = VERIFIED
            claim.detail = (f"Repo exists: {stars} stars, last push {pushed or 'unknown'}"
                            + (", archived" if archived else "")
                            + (", EMPTY repository" if empty else ""))
        else:
            repos = data.get("public_repos", 0)
            claim.status = VERIFIED
            claim.detail = (f"GitHub user '{path}': {repos} public repos, "
                            f"{data.get('followers', 0)} followers")
        claim.source = url
        return claim

    def verify_arxiv(self, claim):
        url = f"http://export.arxiv.org/api/query?id_list={urllib.parse.quote(claim.value)}"
        body, ok = self._get(url, accept="application/atom+xml")
        if not ok:
            return self._uncheckable(claim, "arXiv unreachable")
        try:
            ns = {"a": "http://www.w3.org/2005/Atom"}
            root = ElementTree.fromstring(body)
            entry = root.find("a:entry", ns)
            if entry is None:
                claim.status, claim.detail = NOT_FOUND, "No arXiv paper with this ID."
                claim.source = url
                return claim
            title = (entry.findtext("a:title", "", ns) or "").strip()
            authors = [(a.findtext("a:name", "", ns) or "").strip()
                       for a in entry.findall("a:author", ns)]
        except Exception:
            return self._uncheckable(claim, "arXiv returned an unparseable record")
        self._attribute(claim, authors, f'arXiv paper "{title[:70]}"', url)
        return claim

    def verify_nct(self, claim):
        url = f"https://clinicaltrials.gov/api/v2/studies/{claim.value.upper()}?format=json"
        body, ok = self._get(url)
        if not ok:
            return self._uncheckable(claim, "ClinicalTrials.gov unreachable")
        if not body:
            claim.status, claim.detail = NOT_FOUND, "No registered trial with this NCT number."
            claim.source = url
            return claim
        try:
            ident = json.loads(body)["protocolSection"]["identificationModule"]
            status_mod = json.loads(body)["protocolSection"].get("statusModule", {})
            title = ident.get("briefTitle", "untitled")
            overall = status_mod.get("overallStatus", "status unknown")
        except Exception:
            return self._uncheckable(claim, "ClinicalTrials.gov record unparseable")
        claim.status = VERIFIED
        claim.detail = f'Registered trial "{title[:70]}" — {overall}'
        claim.source = url
        return claim

    def verify_institution(self, claim):
        """Does the named university/institute actually exist? (ROR registry)

        ROR's query endpoint is fuzzy: a fabricated name like "Institute of
        Advanced Fictional Studies" still returns tens of thousands of hits, led
        by a real but unrelated organization. Accepting items[0] would hand out
        false assurance on invented credentials — exactly the failure this tool
        exists to catch. So we require that every significant word of the CLAIM
        appears in a real registry name; an invented word is disqualifying.
        """
        url = "https://api.ror.org/organizations?query=" + urllib.parse.quote(claim.value)
        body, ok = self._get(url)
        if not ok:
            return self._uncheckable(claim, "ROR registry unreachable")
        if not body:
            claim.status = NOT_FOUND
            claim.detail = f"'{claim.value}' is not in the Research Organization Registry."
            claim.source = url
            return claim
        try:
            items = json.loads(body).get("items", [])
        except Exception:
            return self._uncheckable(claim, "ROR returned an unparseable record")

        wanted = _significant_tokens(claim.value)
        best_name, best_item, best_overlap = None, None, -1.0
        for item in items[:25]:
            for variant in _ror_names(item):
                have = _significant_tokens(variant)
                if not have:
                    continue
                if wanted and wanted <= have:
                    claim.status = VERIFIED
                    if _is_ambiguous_acronym(claim.value):
                        claim.detail = (f"'{claim.value}' matches a real organization "
                                        f"({variant}{_ror_country(item)}), but a short acronym is "
                                        f"ambiguous — confirm which institution is meant.")
                    else:
                        claim.detail = f"Real institution: {variant}" + _ror_country(item)
                    claim.source = item.get("id", url)
                    return claim
                overlap = len(wanted & have) / len(wanted | have) if (wanted | have) else 0.0
                if overlap > best_overlap:
                    best_name, best_item, best_overlap = variant, item, overlap

        claim.status = NOT_FOUND
        claim.detail = (f"No registry entry matches '{claim.value}'."
                        + (f" Closest is '{best_name}'{_ror_country(best_item)}, which is a "
                           f"different organization." if best_name else ""))
        claim.source = url
        return claim

    def verify_patent(self, claim):
        pid = re.sub(r"\s+", "", claim.value).upper()
        url = f"https://patents.google.com/patent/{pid}/en"
        body, ok = self._get(url, accept="text/html")
        if not ok:
            return self._uncheckable(claim, "Google Patents unreachable")
        if not body:
            claim.status, claim.detail = NOT_FOUND, f"No patent record for {pid}."
            claim.source = url
            return claim
        title_m = re.search(r"<title>(.*?)</title>", body, re.S | re.I)
        title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else ""
        if not title or "not found" in title.lower():
            claim.status, claim.detail = NOT_FOUND, f"No patent record for {pid}."
            claim.source = url
            return claim
        inventors = re.findall(r'<dd itemprop="inventor"[^>]*>([^<]+)</dd>', body)
        self._attribute(claim, inventors, f"Patent {pid} ({title[:60]})", url)
        return claim

    def _uncheckable(self, claim, why):
        claim.status, claim.detail = UNCHECKABLE, why
        return claim

    # ── entry point ─────────────────────────────────────────────────────
    HANDLERS = {
        "doi": "verify_doi", "orcid": "verify_orcid", "github": "verify_github",
        "arxiv": "verify_arxiv", "nct": "verify_nct", "patent": "verify_patent",
        "institution": "verify_institution",
    }

    def verify_all(self, claims, progress=None):
        """Verify every claim that has a registry handler. Returns the same list."""
        checkable = [c for c in claims if c.subtype in self.HANDLERS]
        for i, claim in enumerate(checkable, 1):
            if progress:
                progress(i, len(checkable), claim)
            handler = getattr(self, self.HANDLERS[claim.subtype])
            try:
                handler(claim)
            except Exception as exc:  # a verifier bug must not sink the audit
                self._uncheckable(claim, f"verifier error: {type(exc).__name__}")
        return claims


def summarize(claims):
    """Counts by verification status, for the report header."""
    out = {}
    for c in claims:
        out[c.status] = out.get(c.status, 0) + 1
    return out
