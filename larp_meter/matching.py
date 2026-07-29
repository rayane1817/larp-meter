"""Word-boundary term matching and the (overridable) keyword banks.

v1 used `term in text`, which made "ai" match *said*, *email* and *airline*.
Every match here is anchored on word boundaries, and multi-word terms tolerate
hyphen/space variation so "edge-AI" and "edge ai" are the same term.
"""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

_TERM_CACHE = {}


def term_re(term):
    """Word-boundary regex for a term or phrase. Cached — banks are re-scanned often."""
    rx = _TERM_CACHE.get(term)
    if rx is None:
        parts = [re.escape(p) for p in re.split(r"[\s\-]+", term.strip()) if p]
        if not parts:
            parts = [re.escape(term.strip())]
        rx = re.compile(r"(?<!\w)" + r"[\s\-]+".join(parts) + r"(?!\w)", re.IGNORECASE)
        _TERM_CACHE[term] = rx
    return rx


# Reading a term as evidence when the text denies it inverts the finding.
# "We have no customers and no revenue" previously satisfied the traction
# check — clearing the very flag it should have tripped.
#
# English negation scope is not uniform, and treating it as uniform suppressed
# genuine evidence: "grew beyond 40 customers", "unlike competitors we have
# revenue" and "our lack of debt helped revenue" were all read as denials,
# which makes an honest profile score worse.
#
# Clause negators legitimately govern the rest of their clause, including
# coordination ("I do not build technology or hardware").
CLAUSE_NEGATORS = {
    "no", "not", "never", "without", "none", "neither", "nor", "cannot", "cant",
    "dont", "doesnt", "didnt", "isnt", "arent", "wasnt", "werent", "hasnt",
    "havent", "zero", "0",
}
# Local negators govern only the phrase immediately after them: "lack OF debt",
# "rather THAN churn", "unlike COMPETITORS". What follows later in the sentence
# is usually being asserted, often emphatically.
LOCAL_NEGATORS = {
    "lack", "lacks", "lacking", "rather", "instead", "unlike", "avoid", "avoids",
    "avoiding", "free", "excluding", "besides",
}
# Deliberately absent: "yet" ("we have yet to lose a customer" is covered by the
# clause set via its own verb, and a trailing "yet" negates nothing) and
# "beyond" ("beyond 40 customers" means more of them, not none).

_WORD_RE = re.compile(r"[\w']+")
_CLAUSE_END_CHARS = ".;:!?\n•|"
_CLAUSE_LOOKBACK_TOKENS = 6
_LOCAL_LOOKBACK_TOKENS = 2
# Six tokens fit comfortably; the cap only bounds the scan on pathological
# input. Scanning to the clause boundary was quadratic — on a long text with no
# punctuation the whole prefix was re-tokenized for every single match, which
# cost 19s on a 50k-character document.
_MAX_LOOKBACK_CHARS = 200


def is_negated(text, start):
    """Is the term at `start` denied by something earlier in its clause?

    Clause negators reach back several words, so negation distributes over
    coordination the way it does in English. They stop at the clause boundary,
    so "no legacy systems at all. We serve 40 customers" leaves *customers*
    asserted. Local negators reach back only as far as the phrase they govern.
    """
    boundary = 0
    for ch in _CLAUSE_END_CHARS:
        i = text.rfind(ch, 0, start)
        if i >= boundary:
            boundary = i + 1

    window = max(boundary, start - _MAX_LOOKBACK_CHARS)
    prefix = text[window:start].casefold().replace("'", "")
    tokens_before = _WORD_RE.findall(prefix)
    # A window that starts mid-word would leave a fragment that could itself
    # look like a negator ("cannot" sliced into "not").
    if tokens_before and window > boundary and window > 0 and (text[window - 1].isalnum()
                                                              or text[window - 1] == "_"):
        tokens_before = tokens_before[1:]

    if any(tok in CLAUSE_NEGATORS for tok in tokens_before[-_CLAUSE_LOOKBACK_TOKENS:]):
        return True
    return any(tok in LOCAL_NEGATORS for tok in tokens_before[-_LOCAL_LOOKBACK_TOKENS:])


# Kept for callers and tests that want the full vocabulary.
NEGATORS = CLAUSE_NEGATORS | LOCAL_NEGATORS


def _matches(text, term, skip_negated):
    for m in term_re(term).finditer(text):
        if skip_negated and is_negated(text, m.start()):
            continue
        yield m


def has_term(text, term, skip_negated=False):
    return any(True for _ in _matches(text, term, skip_negated))


def find_terms(text, terms, skip_negated=False):
    """Subset of `terms` asserted in `text`, order preserved.

    With skip_negated, a term the text denies ("no revenue", "not raising")
    does not count as present.
    """
    return [t for t in terms if has_term(text, t, skip_negated)]


def count_occurrences(text, terms, skip_negated=False):
    return sum(sum(1 for _ in _matches(text, t, skip_negated)) for t in terms)


def find_non_overlapping(text, terms, skip_negated=False):
    """(distinct terms, occurrence count) counting each span of text once.

    Banks legitimately contain nested entries ("paradigm" and "paradigm
    shift"). Counting both made one phrase read as two separate buzzwords and
    doubled the density, so a single cliche could carry the flag.
    """
    spans = []
    for term in terms:
        for m in _matches(text, term, skip_negated):
            spans.append((m.start(), m.end(), term))
    # Longest first, so "paradigm shift" claims the span before "paradigm".
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    # Accepted spans are non-overlapping and in increasing start order, so the
    # most recently accepted one has the largest end: comparing against it
    # alone is sufficient. Scanning every accepted span was quadratic in the
    # number of matches and dominated the cost on hype-heavy documents.
    chosen, last_end = [], -1
    for start, end, term in spans:
        if start < last_end:
            continue
        last_end = end
        chosen.append(term)
    distinct = list(dict.fromkeys(chosen))
    return distinct, len(chosen)


# ── Default keyword banks ────────────────────────────────────────────────
DEFAULT_BANKS = {
    "tech_edu": [
        "engineering", "computer science", "physics", "electrical engineering",
        "mechanical engineering", "biomedical engineering", "mathematics",
        "informatics", "robotics", "aerospace engineering", "data science",
        "electronics", "telecommunications", "nuclear engineering", "chemistry",
        "bioinformatics", "computational science", "applied mathematics",
        "materials science", "software engineering",
    ],
    "nontech_edu": [
        "public health", "public policy", "governance", "advocacy", "law",
        "political science", "european studies", "international relations",
        "sociology", "psychology", "business administration", "mba",
        "humanities", "history", "philosophy", "communication studies",
        "marketing", "public administration", "journalism", "fine arts",
    ],
    "degree_words": [
        "msc", "bsc", "phd", "mba", "master", "bachelor", "doctorate",
        "postdoc", "llm", "meng", "beng",
    ],
    "tech_claims": [
        "artificial intelligence", "edge ai", "radiation tolerant", "hardware",
        "satellite", "dual use", "deep tech", "nuclear", "rocket",
        "machine learning", "neural network", "semiconductor", "biometric",
        "genomics", "robotics", "blockchain", "quantum", "aerospace",
        "cybersecurity", "photonics", "space grade",
    ],
    "leadership_titles": [
        "president", "founder", "co-founder", "ceo", "cto", "chief executive",
        "chief technology officer", "chief scientist", "chief medical officer",
        "chief financial officer", "chief operating officer", "managing director",
        "managing partner", "executive director", "director general",
        "secretary general", "chairman", "chairwoman", "head of", "general counsel",
        "principal investigator", "founding partner",
    ],
    "tech_roles": [
        "engineer", "developer", "chief technology officer", "research scientist",
        "scientist", "software architect", "lead developer", "principal engineer",
        "researcher", "postdoctoral", "technical lead", "programmer",
    ],
    "policy_roles": [
        "patient advocacy", "secretary general", "policy officer", "public health",
        "governance", "board member", "consultant", "advisor", "lobbyist",
        "ambassador", "spokesperson", "communications manager",
    ],
    "buzzwords": [
        "synergy", "paradigm", "paradigm shift", "disruption", "disruptive",
        "game changing", "revolutionary", "groundbreaking", "pioneering",
        "cutting edge", "bleeding edge", "next generation", "state of the art",
        "world class", "visionary", "thought leader", "thought leadership",
        "exponential", "moonshot", "transformative", "trailblazing",
        "future proof", "hypergrowth", "unicorn", "ecosystem play",
        "best in class", "industry leading", "holistic", "seamless",
    ],
    "vague_partnership": [
        "mou", "memorandum of understanding", "nda", "non-disclosure",
        "in discussion", "discussions ongoing", "in talks", "preliminary",
        "exploratory", "letter of intent", "loi", "heads of terms",
        "term sheet", "early conversations", "planned collaboration",
    ],
    "concrete_partnership": [
        "grant", "funded by", "contract", "joint venture", "joint development",
        "co-development", "collaboration agreement", "series a", "series b",
        "seed round closed", "revenue", "paying customer", "pilot deployed",
        "acquired", "licensing agreement", "purchase order", "framework agreement",
    ],
    "building_claims": [
        "building", "developing", "creating", "working on", "patent pending",
        "stealth", "coming soon", "pre-launch", "in development", "roadmap",
    ],
    "traction": [
        "customers", "revenue", "clients", "paying users", "arr", "mrr",
        "contracts signed", "deployed in production", "units sold",
        "subscribers", "bookings", "active users", "installed base",
    ],
    "funding_ask": [
        "seeking investment", "seeking funding", "raising", "funding round",
        "looking for investors", "open to investors", "seed round", "funding ask",
        "investment opportunity", "capital raise",
    ],
    "deep_collab": [
        "co-authored", "joint paper", "joint research", "co-developed",
        "integration partner", "technology partner", "reseller", "oem",
        "distributor", "system integrator", "joint publication", "co-funded",
    ],
    "external_validation": [
        "featured in", "as seen on", "interviewed by", "published in",
        "recognized by", "awarded", "award winner", "keynote", "covered by",
        "profiled in", "cited by", "shortlisted for",
    ],
    "press_outlets": [
        "techcrunch", "forbes", "wired", "reuters", "bloomberg",
        "financial times", "the economist", "bbc", "nature", "ieee spectrum",
        "mit technology review", "wall street journal", "ars technica",
        "der spiegel", "le monde", "de standaard",
    ],
    "self_published_domains": [
        "medium.com", "substack.com", "linkedin.com", "wordpress.com",
        "blogspot.com", "wixsite.com", "facebook.com", "x.com", "twitter.com",
        "instagram.com", "youtube.com", "about.me", "crunchbase.com",
    ],
}


def host_of(url):
    """Registrable host of a URL, lowercased and without a leading www."""
    try:
        host = (urlsplit(str(url)).hostname or "").casefold()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def host_matches(url, domains):
    """True when the URL's host IS one of `domains` or a subdomain of one.

    A substring test against the whole URL made "x.com" match vox.com,
    xerox.com and netflix.com, so genuine third-party press was classified as
    the subject's own platform and reported as an echo chamber.
    """
    host = host_of(url)
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in
               ((d[4:] if d.startswith("www.") else d).casefold() for d in domains))


def load_banks(path=None):
    """Default banks, optionally extended/overridden by a user JSON file.

    A key in the JSON replaces that bank; prefix a key with '+' to append to it.
    Path resolution: explicit arg, then $LARP_KEYWORDS, then ./keywords.json.
    """
    banks = {k: list(v) for k, v in DEFAULT_BANKS.items()}
    candidate = path or os.environ.get("LARP_KEYWORDS") or (Path.cwd() / "keywords.json")
    p = Path(candidate)
    if not p.is_file():
        return banks
    try:
        overrides = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return banks
    for key, values in overrides.items():
        if not isinstance(values, list):
            continue
        if key.startswith("+"):
            banks.setdefault(key[1:], []).extend(values)
        else:
            banks[key] = list(values)
    return banks
