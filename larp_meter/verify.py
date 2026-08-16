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
import html as html_lib
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from xml.etree import ElementTree

from . import names
from .extract import VERIFIED, MISMATCH, NOT_FOUND, UNCHECKABLE, EMITTED_SUBTYPES

VERIFY_TTL = 30 * 24 * 3600
MAX_RESPONSE_BYTES = 2_000_000
USER_AGENT = ("larp-meter/3.0 (OSINT due-diligence triage; "
              "+https://github.com/rayane1817/larp-meter)")
TIMEOUT = 12


# Words that carry no identifying information in an organization name.
_ORG_STOPWORDS = {
    "of", "the", "at", "for", "and", "in", "de", "des", "du", "der", "die", "das",
    "van", "von", "el", "la", "le", "les", "a", "an", "università", "universite",
}


# Institution-type words differ by language and inflection across registries:
# Institute/Institutet/Instituto/Institut, University/Universiteit/Université.
# Comparing them literally makes a real university look like "a different
# organization", so they are folded to a common stem before matching.
_ORG_STEMS = (
    ("universit", "univ"), ("uniwersytet", "univ"), ("universidad", "univ"),
    ("universidade", "univ"), ("hochschule", "univ"),
    ("institut", "institut"), ("instituto", "institut"),
    ("polytech", "polytech"), ("politecnico", "polytech"), ("polytechni", "polytech"),
    ("college", "college"), ("colegio", "college"),
    ("school", "school"), ("schule", "school"), ("escuela", "school"), ("ecole", "school"),
    ("academy", "academy"), ("akademie", "academy"), ("academia", "academy"),
)


def _stem_org_token(token):
    for prefix, stem in _ORG_STEMS:
        if token.startswith(prefix):
            return stem
    return token


def _significant_tokens(name):
    decomposed = unicodedata.normalize("NFKD", name or "")
    flat = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return {_stem_org_token(t) for t in re.split(r"[^\w]+", flat.casefold())
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
        # Claim subtypes no registry was asked about, so a report can show
        # "never checked" as something other than "checked and clean".
        self.skipped = {}

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
        # Host check, not a substring of the URL: a path or query containing
        # "api.github.com" must never leak the token to another host.
        if token and urllib.parse.urlsplit(url).hostname == "api.github.com":
            headers["Authorization"] = f"Bearer {token}"

        body, ok = "", False
        try:
            self.calls += 1
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body, ok = resp.read(MAX_RESPONSE_BYTES).decode("utf-8", errors="replace"), True
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

    def _attribute(self, claim, candidate_names, label, url):
        """Shared tail: the artifact exists — does it belong to the subject?

        Three outcomes, and conflating them is how this tool would libel
        someone. A registry that returns no usable names (books with no author
        array, ORCID records set to private, scraped markup that drifted) tells
        us nothing about attribution, so it must not resolve to MISMATCH.
        """
        usable = [n for n in candidate_names or [] if n and n.strip()]
        match = names.name_matches(self.subject_name, usable)
        shown = ", ".join(usable[:4])

        if not self.subject_name:
            claim.status = VERIFIED
            claim.detail = f"{label} exists ({shown or 'no names listed'}). Pass --name to check attribution."
        elif not usable:
            claim.status = UNCHECKABLE
            claim.detail = (f"{label} exists, but the registry published no names to compare "
                            f"against — attribution cannot be checked here.")
        elif match is None:
            # `elif match:` used to fall through to MISMATCH here, because
            # `None` is as falsy as `False` — the exact conflation this
            # docstring's "three outcomes" warns against. name_matches
            # returns None for a middle-token surname or a non-Latin script
            # it cannot compare, deliberately distinct from "no": treating
            # that as a mismatch libelled a Hispanic/Lusophone author cited
            # by only their first surname, and anyone whose record is held
            # in a script this tool cannot read, on the tool's own strongest
            # and most damaging verdict.
            claim.status = UNCHECKABLE
            claim.detail = (f"{label} exists, but attribution could not be determined from the "
                            f"published names ({shown}) — neither confirmed nor refuted.")
        elif match:
            claim.status = VERIFIED
            claim.detail = f"{label} exists and lists the subject ({shown})."
        else:
            claim.status = MISMATCH
            claim.detail = f"{label} exists but does NOT list the subject ({shown})."
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
            full = f"{given} {family}".strip()
        except Exception:
            return self._uncheckable(claim, "ORCID returned an unparseable record")
        # An ORCID holder may set their name to private. Passing a placeholder
        # like "name withheld" would sail past the emptiness guard and be
        # scored as "this record names someone else".
        self._attribute(claim, [full] if full else [], "ORCID record", url)
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
            owner = ((data.get("owner") or {}).get("login") or "").strip()
            shape = (f"{stars} stars, last push {pushed or 'unknown'}"
                     + (", archived" if archived else "")
                     + (", EMPTY repository" if empty else ""))
            # Owning a repository is not writing it, and citing an employer's or
            # a dependency's repo is normal rather than dishonest. The owner
            # login is the only name this payload carries and it cannot settle
            # authorship either way, so existence is recorded WITHOUT being
            # counted as attribution — reporting it as confirmation let a
            # subject cite a stranger's famous repository and be credited with
            # its 190k stars.
            claim.status = UNCHECKABLE
            claim.detail = (f"Repo '{path}' exists ({shape})"
                            + (f", owned by '{owner}'" if owner else "")
                            + ". Ownership does not establish authorship, so attribution "
                              "was not checked.")
            claim.source = url
            return claim

        # A user URL is a claim about an identity — the same question
        # _attribute answers for ORCID. Only a published full name is
        # comparable: a login is a handle, and a one-word display name cannot
        # support a mismatch finding, so both fall through to UNCHECKABLE.
        published = (data.get("name") or "").strip()
        comparable = [published] if len(published.split()) >= 2 else []
        repos = data.get("public_repos", 0)
        self._attribute(claim, comparable,
                        f"GitHub user '{path}' ({repos} public repos, "
                        f"{data.get('followers', 0)} followers)", url)
        return claim

    def verify_arxiv(self, claim):
        url = f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(claim.value)}"
        body, ok = self._get(url, accept="application/atom+xml")
        if not ok:
            return self._uncheckable(claim, "arXiv unreachable")
        if not body:
            claim.status, claim.detail = NOT_FOUND, "No arXiv paper with this ID."
            claim.source = url
            return claim
        try:
            ns = {"a": "http://www.w3.org/2005/Atom"}
            root = ElementTree.fromstring(body)
            entry = root.find("a:entry", ns)
            if entry is None:
                claim.status, claim.detail = NOT_FOUND, "No arXiv paper with this ID."
                claim.source = url
                return claim
            title = (entry.findtext("a:title", "", ns) or "").strip()
            # arXiv serves its errors as a 200 OK Atom feed whose single entry
            # is titled "Error" and authored by "arXiv api core". Attributing
            # that entry would accuse the subject of not writing an error page.
            entry_id = (entry.findtext("a:id", "", ns) or "")
            if "api/errors" in entry_id or title.casefold() == "error":
                claim.status, claim.detail = NOT_FOUND, "arXiv has no paper with this ID."
                claim.source = url
                return claim
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
            section = json.loads(body)["protocolSection"]
            ident = section["identificationModule"]
            title = ident.get("briefTitle", "untitled")
            overall = section.get("statusModule", {}).get("overallStatus", "status unknown")
            sponsor = ((section.get("sponsorCollaboratorsModule") or {})
                       .get("leadSponsor") or {}).get("name", "")
            officials = [(o or {}).get("name", "") for o in
                         ((section.get("contactsLocationsModule") or {})
                          .get("overallOfficials") or [])]
        except Exception:
            return self._uncheckable(claim, "ClinicalTrials.gov record unparseable")
        # A trial's overall officials are its principal investigators, not a
        # roster of everyone who worked on it, and the sponsor is an institution.
        # Neither can refute a person's involvement, so this records existence
        # and names the parties for a human to judge rather than asserting
        # attribution the registry cannot support.
        who = ", ".join([n for n in ([sponsor] + officials) if n][:4])
        claim.status = UNCHECKABLE
        claim.detail = (f'Registered trial "{title[:70]}" — {overall}'
                        + (f" (sponsor/investigators: {who})" if who else "")
                        + ". A trial record does not list every contributor, so attribution "
                          "was not checked.")
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

        # ROR indexes research organizations. Absence is a lead, not a finding:
        # asserting that a named institution "is a different organization" would
        # be this tool stating as fact something it cannot know.
        claim.status = NOT_FOUND
        claim.detail = (f"'{claim.value}' has no matching entry in ROR, which indexes research "
                        f"organizations — confirm directly before drawing any conclusion."
                        + (f" Nearest listed name: '{best_name}'{_ror_country(best_item)}."
                           if best_name else ""))
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
        # Scraped markup, not an API: if Google changes this element every
        # patent claim would silently become a weight-2.5 accusation. No
        # inventors parsed means the scrape failed, not that the subject lied.
        inventors = [html_lib.unescape(n).strip()
                     for n in re.findall(r'<dd itemprop="inventor"[^>]*>([^<]+)</dd>', body)]
        if not inventors:
            claim.status = UNCHECKABLE
            claim.detail = (f"Patent {pid} exists ({title[:60]}), but no inventor list could be "
                            f"read from the page — attribution not checked.")
            claim.source = url
            return claim
        self._attribute(claim, inventors, f"Patent {pid} ({title[:60]})", url)
        return claim

    def _uncheckable(self, claim, why):
        claim.status, claim.detail = UNCHECKABLE, why
        return claim

    # ── entry point ─────────────────────────────────────────────────────
    # Keys MUST be subtypes extract_claims actually emits — see the guard below.
    # `mentioned_institution` is deliberately absent: those are employers and
    # venues, and ROR indexes research organizations, so an ordinary company's
    # absence would manufacture a finding out of nothing.
    HANDLERS = {
        "doi": "verify_doi", "orcid": "verify_orcid", "github": "verify_github",
        "arxiv": "verify_arxiv", "nct": "verify_nct", "patent": "verify_patent",
        "degree_institution": "verify_institution",
    }

    def verify_all(self, claims, progress=None):
        """Verify every claim that has a registry handler. Returns the same list."""
        checkable = [c for c in claims if c.subtype in self.HANDLERS]
        for c in claims:
            if c.subtype not in self.HANDLERS:
                self.skipped[c.subtype] = self.skipped.get(c.subtype, 0) + 1
        for i, claim in enumerate(checkable, 1):
            if progress:
                progress(i, len(checkable), claim)
            handler = getattr(self, self.HANDLERS[claim.subtype])
            try:
                handler(claim)
            except Exception as exc:  # a verifier bug must not sink the audit
                self._uncheckable(claim, f"verifier error: {type(exc).__name__}")
        return claims


# A registry no claim can reach is worse than one that is missing: it counts as
# coverage in the README and in --explain while checking nothing at all, and the
# flag reading its result can only ever see UNCHECKED. Fail loudly at import
# rather than let that drift back in.
_ORPHANED = set(Verifier.HANDLERS) - EMITTED_SUBTYPES
if _ORPHANED:
    raise RuntimeError(
        "Verifier.HANDLERS dispatches on subtypes extract_claims never emits: "
        f"{sorted(_ORPHANED)}. A renamed subtype has orphaned its registry — "
        "update HANDLERS and extract.EMITTED_SUBTYPES together.")


def summarize(claims):
    """Counts by verification status, for the report header."""
    out = {}
    for c in claims:
        out[c.status] = out.get(c.status, 0) + 1
    return out
