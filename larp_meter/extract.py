"""Claim extraction: turn free text into discrete, individually checkable claims.

This is what separates v3 from keyword counting. A profile is decomposed into
typed claims (degree, role, partnership, artifact, traction, timeline) so each
one can be carried through the report and — where an identifier exists — checked
against a public registry in verify.py.
"""

import re
from dataclasses import dataclass, field, asdict

# Claim verification states
UNCHECKED = "UNCHECKED"      # never submitted to a verifier
VERIFIED = "VERIFIED"        # registry confirms the artifact exists
MISMATCH = "MISMATCH"        # artifact exists but the subject isn't attached to it
NOT_FOUND = "NOT_FOUND"      # registry says it does not exist
UNCHECKABLE = "UNCHECKABLE"  # no network / no verifier / rate-limited


@dataclass
class Claim:
    kind: str                  # artifact | degree | role | partnership | traction | timeline
    subtype: str               # doi | orcid | github | arxiv | nct | patent | institution ...
    value: str                 # the identifier or object of the claim
    context: str = ""          # the sentence fragment it came from
    status: str = UNCHECKED
    detail: str = ""           # human-readable verification result
    source: str = ""           # URL consulted by the verifier

    def to_dict(self):
        return asdict(self)


# ── Identifier patterns (verifiable artifacts) ──────────────────────────
ARTIFACT_PATTERNS = [
    ("doi",    re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.I)),
    ("arxiv",  re.compile(r"arxiv\.org/abs/(\d{4}\.\d{4,5})", re.I)),
    ("orcid",  re.compile(r"\b(?:orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])\b", re.I)),
    ("github", re.compile(r"github\.com/([A-Za-z0-9](?:[\w.-]*[A-Za-z0-9])?(?:/[\w.-]+)?)", re.I)),
    ("nct",    re.compile(r"\b(NCT\d{8})\b", re.I)),
    ("patent", re.compile(r"\b((?:US|EP|WO)\s?\d{7,11}(?:\s?[ABC]\d?)?)\b")),
]

# Claims of regulatory clearance — checkable in principle, but not via a free API
SOFT_EVIDENCE = [
    (re.compile(r"\b(?:FDA|CE)[\s-](?:cleared|approved|marking|marked|certified)\b", re.I),
     "regulatory clearance"),
    (re.compile(r"\bpeer[\s-]reviewed\b", re.I), "peer-review claim"),
    (re.compile(r"\bISO\s?\d{4,5}\b", re.I), "ISO certification"),
]

DEGREE_RE = re.compile(
    r"\b(MSc|M\.Sc\.|BSc|B\.Sc\.|PhD|Ph\.D\.|MBA|MEng|BEng|LLM|"
    r"Master(?:'s)?|Bachelor(?:'s)?|Doctorate)\b"
    r"(?:\s+(?:of|in))?\s*([A-Za-z][\w\s&,-]{0,50}?)?"
    r"(?:\s*(?:,|\bat\b|\bfrom\b)\s*"
    r"((?:[A-Z][\w.-]+\s+){0,3}(?:University|Universiteit|Université|Institute|College|School|Polytechnic)"
    r"(?:\s+(?:of|de|van)\s+[A-Z][\w.-]+(?:\s+[A-Z][\w.-]+)?)?"
    r"|(?:University|Institute|College)\s+of\s+[A-Z][\w.-]+(?:\s+[A-Z][\w.-]+)?))?",
    re.I)

INSTITUTION_RE = re.compile(
    r"\b((?:[A-Z][\w.-]+\s+){0,3}(?:University|Universiteit|Université|Institute|College|Polytechnic)"
    r"(?:\s+(?:of|de|van)\s+[A-Z][\w.-]+(?:\s+[A-Z][\w.-]+)?)?"
    r"|(?:University|Institute)\s+of\s+[A-Z][\w.-]+(?:\s+[A-Z][\w.-]+)?)")

# Case-insensitive trigger word, case-sensitive org name (orgs are capitalised)
OWNED_ORG_RE = re.compile(
    r"(?i:founder|co-founder|founded|president|created|established|my company|"
    r"chairman|owner|ceo|cto)\s+(?i:(?:and\s+\w+\s+)?(?:of|at|@))\s+"
    r"([A-Z][\w&-]*(?:[ \t][A-Z][\w&-]*){0,3})")
PARTNER_ORG_RE = re.compile(
    r"(?i:partner(?:ship|ed|s)?|collaborat\w+|mou|alliance|consortium|agreement|"
    r"teamed\s+up)\s+(?i:with|between)\s+"
    r"([A-Z][\w&-]*(?:[ \t][A-Z][\w&-]*){0,3})")

ROLE_RE = re.compile(
    r"\b(CEO|CTO|President|Founder|Co-founder|Chairman|Managing Director|"
    r"Head of [A-Z]\w+)\b\s*(?:of|at|@)\s+([A-Z][\w&-]*(?:[ \t][A-Z][\w&-]*){0,3})")

TRACTION_RE = re.compile(
    r"([€$£]?\s?\d[\d,.]*\s?(?:k|m|bn|million|billion)?)\s*"
    r"(customers|clients|users|subscribers|revenue|arr|mrr|employees|units|installations)",
    re.I)

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "twenty-five": 25, "thirty": 30, "forty": 40, "fifty": 50,
}
EXPERIENCE_RE = re.compile(
    r"\b(\d{1,2}|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")\+?\s*"
    r"years?\s+(?:of\s+)?(?:experience|expertise)", re.I)
YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")


def experience_years(raw):
    """'15' or 'fifteen' -> 15. Returns None if unparseable."""
    raw = (raw or "").strip().casefold()
    if raw.isdigit():
        return int(raw)
    return NUMBER_WORDS.get(raw)

ORG_SUFFIX = re.compile(
    r"\s+(?:gmbh|ltd|llc|inc|bv|nv|sa|ag|plc|foundation|association|institute)\.?$", re.I)


def norm_org(name):
    return ORG_SUFFIX.sub("", (name or "").strip()).casefold()


def _context(text, match, width=60):
    start = max(match.start() - width // 2, 0)
    end = min(match.end() + width // 2, len(text))
    return re.sub(r"\s+", " ", text[start:end]).strip()


def extract_claims(text):
    """Return every typed claim found in `text`."""
    claims = []
    seen = set()

    def add(kind, subtype, value, context):
        key = (kind, subtype, value.casefold())
        if key in seen:
            return
        seen.add(key)
        claims.append(Claim(kind=kind, subtype=subtype, value=value, context=context))

    for subtype, rx in ARTIFACT_PATTERNS:
        for m in rx.finditer(text):
            value = m.group(1).strip().rstrip(".,;)")
            # A bare "github.com/user" is a profile, not a repo — keep both, verify differently
            add("artifact", subtype, value, _context(text, m))

    for rx, label in SOFT_EVIDENCE:
        m = rx.search(text)
        if m:
            add("artifact", "assertion", label, _context(text, m))

    for m in DEGREE_RE.finditer(text):
        level, field_, institution = m.group(1), (m.group(2) or "").strip(" ,."), m.group(3)
        value = " ".join(x for x in [level, field_] if x).strip()
        add("degree", "degree", value, _context(text, m))
        if institution:
            add("degree", "institution", institution.strip(), _context(text, m))

    # Institutions named outside a degree phrase still matter (employers, collaborators)
    for m in INSTITUTION_RE.finditer(text):
        add("degree", "institution", m.group(1).strip(), _context(text, m))

    for m in ROLE_RE.finditer(text):
        add("role", "leadership", f"{m.group(1)} of {m.group(2)}", _context(text, m))

    for m in OWNED_ORG_RE.finditer(text):
        add("role", "owned_org", m.group(1).strip(), _context(text, m))

    for m in PARTNER_ORG_RE.finditer(text):
        add("partnership", "partner_org", m.group(1).strip(), _context(text, m))

    for m in TRACTION_RE.finditer(text):
        add("traction", m.group(2).lower(), f"{m.group(1).strip()} {m.group(2)}", _context(text, m))

    for m in EXPERIENCE_RE.finditer(text):
        add("timeline", "claimed_experience_years", m.group(1), _context(text, m))

    for m in YEAR_RE.finditer(text):
        add("timeline", "year", m.group(1), _context(text, m))

    return claims


def claims_by(claims, kind=None, subtype=None):
    return [c for c in claims
            if (kind is None or c.kind == kind) and (subtype is None or c.subtype == subtype)]


def owned_and_partner_orgs(claims):
    """(overlap, owned, partners) — orgs the subject leads that also appear as 'partners'."""
    owned = {norm_org(c.value): c.value for c in claims_by(claims, "role", "owned_org")}
    for c in claims_by(claims, "role", "leadership"):
        org = c.value.split(" of ", 1)[-1]
        owned.setdefault(norm_org(org), org)
    partners = {norm_org(c.value): c.value for c in claims_by(claims, "partnership", "partner_org")}
    overlap = [partners[k] for k in owned.keys() & partners.keys()]
    return overlap, list(owned.values()), list(partners.values())


def specificity_index(text):
    """Verifiable details per 100 words. Vague profiles score low; real CVs score high."""
    words = max(len(text.split()), 1)
    signals = len(YEAR_RE.findall(text))
    signals += len(re.findall(
        r"\b\d[\d,.]*\s?(?:%|€|\$|£|k\b|m\b|users|employees|patients|units|customers)", text, re.I))
    signals += len(re.findall(r"\bhttps?://\S+", text))
    signals += len(INSTITUTION_RE.findall(text))
    for _subtype, rx in ARTIFACT_PATTERNS:
        signals += len(rx.findall(text))
    return round(signals / words * 100, 2)
