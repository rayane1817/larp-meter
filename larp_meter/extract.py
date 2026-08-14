"""Claim extraction: turn free text into discrete, individually checkable claims.

This is what separates v3 from keyword counting. A profile is decomposed into
typed claims (degree, role, partnership, artifact, traction, timeline) so each
one can be carried through the report and — where an identifier exists — checked
against a public registry in verify.py.
"""

import re
from dataclasses import dataclass, field, asdict

from .matching import is_negated

# Claim verification states
UNCHECKED = "UNCHECKED"      # never submitted to a verifier
VERIFIED = "VERIFIED"        # registry confirms the artifact exists
MISMATCH = "MISMATCH"        # artifact exists but the subject isn't attached to it
NOT_FOUND = "NOT_FOUND"      # registry says it does not exist
UNCHECKABLE = "UNCHECKABLE"  # no network / no verifier / rate-limited

# Traction subtypes are the object nouns of TRACTION_RE, lowercased.
TRACTION_SUBTYPES = frozenset({
    "customers", "clients", "users", "subscribers", "revenue", "arr", "mrr",
    "employees", "units", "installations",
})

# Every subtype `extract_claims` can emit. verify.py checks its dispatch table
# against this at import time. Renaming a subtype used to orphan its registry
# in silence: the ROR institution check was dead from the moment "institution"
# was split into "degree_institution"/"mentioned_institution" without updating
# the verifier, so `--verify` made zero API calls for credentials and a wholly
# invented university came back as a *satisfied* credential flag.
EMITTED_SUBTYPES = frozenset({
    "doi", "arxiv", "orcid", "github", "nct", "patent", "assertion",
    "degree", "degree_institution", "mentioned_institution",
    "leadership", "owned_org", "partner_org",
    "claimed_experience_years", "year", "year_target",
}) | TRACTION_SUBTYPES


@dataclass
class Claim:
    kind: str                  # artifact | degree | role | partnership | traction | timeline
    subtype: str               # doi | orcid | github | arxiv | nct | patent | institution ...
    value: str                 # the identifier or object of the claim
    context: str = ""          # the sentence fragment it came from
    status: str = UNCHECKED
    detail: str = ""           # human-readable verification result
    source: str = ""           # URL consulted by the verifier
    negated: bool = False      # the text denies this ("no customers", "not raising")

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

# Institution-type words in the languages this tool is likely to meet. Matching
# only the English spellings made the credential flag fire on how a university
# happens to spell itself: "Technische Universität München" parsed as nothing.
_INST_TYPES = (r"Universit\w*|Uniwersytet\w*|Universidad\w*|Universidade\w*|Institut\w*|"
               r"Hochschule\w*|Fachhochschule\w*|Hogeschool\w*|"
               r"Polytechni\w*|Politecnico\w*|Coll[eè]g\w*|Colegio\w*|"
               r"Escuela\w*|[EÉ]cole\w*|Lyc[eé]e\w*|Facult[eé]\w*|Conservatoire\w*|"
               r"Akadem\w*|Academ\w*|Gymnasi\w*|School\w*")

# The prefix class excludes '.' so a sentence boundary cannot be swallowed
# ("...in Wilrijk. Karolinska Institutet" must not parse as one name), and the
# trailing \b stops "Institutet" being truncated to "Institute".
_INSTITUTION_CORE = (
    r"(?:[A-Z][\w-]*\s+){0,3}(?:" + _INST_TYPES + r")"
    r"(?:\s+(?:of|de|des|der|van|voor|di|du|und|et|en|för|für)\s+[A-Z][\w-]*(?:\s+[A-Z][\w-]*){0,2})?")

INSTITUTION_RE = re.compile(r"\b(" + _INSTITUTION_CORE + r")\b")

# The field of study is matched lazily but anchored on a following delimiter.
# Without the lookahead the lazy group sat inside an optional group followed by
# another optional group, so it settled for one character and the report quoted
# degrees like "MSc A" and "MBA f".
DEGREE_RE = re.compile(
    r"\b(MSc|M\.Sc\.|BSc|B\.Sc\.|PhD|Ph\.D\.|MBA|MEng|BEng|LLM|LLB|"
    r"Master(?:'s)?|Bachelor(?:'s)?|Doctorate|Doctor)\b"
    r"(?:[\s,]+(?:of\s+|in\s+)?(?!from\b|at\b|and\b|with\b)"
    r"(?P<field>[A-Za-z][A-Za-z&\- ]{1,60}?)"
    r"(?=\s*(?:[,;.]|\bat\b|\bfrom\b|\band\b|$)))?"
    r"(?:\s*(?:,|\bat\b|\bfrom\b)\s*(?P<inst>" + _INSTITUTION_CORE + r")\b)?",
    re.I)

# Case-insensitive trigger word, case-sensitive org name (orgs are capitalised)
OWNED_ORG_RE = re.compile(
    r"(?i:founder|co-founder|founded|president|created|established|my company|"
    r"chairman|owner|ceo|cto)\s+(?i:(?:and\s+\w+\s+)?(?:of|at|@))\s+"
    r"([A-Z][\w&-]*(?:[ \t][A-Z][\w&-]*){0,3})")
# The honorific guard stops "partnership with Dr. Smith" being recorded as a
# partner organization called "Dr", which then counted toward the logo wall.
PARTNER_ORG_RE = re.compile(
    r"(?i:partner(?:ship|ed|s)?|collaborat\w+|mou|alliance|consortium|agreement|"
    r"teamed\s+up)\s+(?i:with|between)\s+"
    r"(?!(?:Dr|Mr|Mrs|Ms|Prof|Sir|Dame|Rev|The)\b)"
    r"([A-Z][\w&-]*(?:[ \t][A-Z][\w&-]*){0,3})")

ROLE_RE = re.compile(
    r"\b(CEO|CTO|President|Founder|Co-founder|Chairman|Managing Director|"
    r"Head of [A-Z]\w+)\b\s*(?:of|at|@)\s+([A-Z][\w&-]*(?:[ \t][A-Z][\w&-]*){0,3})")

# The digit run is bounded: an unbounded [\d,.]* before an alternation that
# often fails backtracks quadratically, so a page with a long number could hang
# the whole analysis.
TRACTION_RE = re.compile(
    r"([€$£]?\s?\d[\d,.]{0,24}\s?(?:k|m|bn|million|billion)?)\s*"
    r"(customers|clients|users|subscribers|revenue|arr|mrr|employees|units|installations)",
    re.I)

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "twenty-five": 25, "thirty": 30, "forty": 40, "fifty": 50,
}
# Duration is stated many ways. Recognising only "N years of experience" meant
# the same career read as less evidence when described in plainer or
# non-native English ("spent eight years as a design engineer"), which pushed
# otherwise identical profiles across the coverage floor into a different
# verdict. Phrasing should not change what the tool can see.
EXPERIENCE_RE = re.compile(
    r"\b(\d{1,2}|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")\+?\s*"
    r"years?\s+(?:of\s+)?"
    r"(?:experience|expertise|as\b|in\b|working|building|leading|developing|"
    r"designing|managing|practising|practicing|teaching|researching)", re.I)
YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")

# A stated goal is not a falsified credential. "Full deployment is targeted for
# 2030" must not be read as a date the subject claims to have lived through.
FORWARD_MARKERS = re.compile(
    r"\b(?:by|target(?:ed|ing)?|projected|expected|planned|planning|roadmap|horizon|"
    r"due|forecast|goal|aim(?:ing)?|launch(?:ing)?|shipping|will|anticipated|"
    r"scheduled|from now until|through)\b[^.;\n]{0,40}$", re.I)


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

    def add(kind, subtype, value, context, negated=False):
        key = (kind, subtype, value.casefold())
        if key in seen:
            return
        seen.add(key)
        claims.append(Claim(kind=kind, subtype=subtype, value=value, context=context,
                            negated=negated))

    for subtype, rx in ARTIFACT_PATTERNS:
        for m in rx.finditer(text):
            value = m.group(1).strip().rstrip(".,;)")
            # A bare "github.com/user" is a profile, not a repo — keep both, verify differently
            add("artifact", subtype, value, _context(text, m))

    for rx, label in SOFT_EVIDENCE:
        m = rx.search(text)
        if m:
            add("artifact", "assertion", label, _context(text, m))

    degree_institutions = set()
    for m in DEGREE_RE.finditer(text):
        level = m.group(1)
        field_ = (m.group("field") or "").strip(" ,.")
        institution = (m.group("inst") or "").strip()
        value = " ".join(x for x in [level, field_] if x).strip()
        add("degree", "degree", value, _context(text, m))
        if institution:
            degree_institutions.add(institution)
            add("degree", "degree_institution", institution, _context(text, m))

    # Institutions named outside a degree phrase are employers, collaborators or
    # venues — kept under a distinct subtype so the credential flag cannot bind
    # a degree to whatever institution happens to appear elsewhere in the text.
    for m in INSTITUTION_RE.finditer(text):
        name = m.group(1).strip()
        if name not in degree_institutions:
            add("degree", "mentioned_institution", name, _context(text, m))

    for m in ROLE_RE.finditer(text):
        add("role", "leadership", f"{m.group(1)} of {m.group(2)}", _context(text, m))

    for m in OWNED_ORG_RE.finditer(text):
        add("role", "owned_org", m.group(1).strip(), _context(text, m))

    for m in PARTNER_ORG_RE.finditer(text):
        add("partnership", "partner_org", m.group(1).strip(), _context(text, m))

    for m in TRACTION_RE.finditer(text):
        # "no customers" and "0 users" are not traction.
        amount = m.group(1).strip()
        zero = re.fullmatch(r"[€$£]?\s?0+([.,]0+)?", amount) is not None
        add("traction", m.group(2).lower(), f"{amount} {m.group(2)}", _context(text, m),
            negated=zero or is_negated(text, m.start()))

    for m in EXPERIENCE_RE.finditer(text):
        add("timeline", "claimed_experience_years", m.group(1), _context(text, m))

    # Years are read from text with identifiers and quantities blanked out.
    # Unmasked, the digits inside "10.1109/TNS.2023.3241234" became a career
    # date and the profile was accused of an impossible timeline.
    masked = _mask_non_dates(text)
    for m in YEAR_RE.finditer(masked):
        forward = bool(FORWARD_MARKERS.search(masked[max(0, m.start() - 60):m.start()]))
        add("timeline", "year_target" if forward else "year", m.group(1), _context(text, m))

    return claims


def _mask_non_dates(text):
    """Blank spans whose digits are identifiers or quantities, not dates."""
    chars = list(text)
    spans = []
    for _subtype, rx in ARTIFACT_PATTERNS:
        spans.extend(m.span() for m in rx.finditer(text))
    spans.extend(m.span(1) for m in TRACTION_RE.finditer(text))
    spans.extend(m.span() for m in re.finditer(r"\b\d[\d,.]{0,24}\s?(?:MHz|GHz|kHz|km|kg|nm|"
                                               r"mm|hours?|days?|%)\b", text, re.I))
    for start, end in spans:
        for i in range(start, min(end, len(chars))):
            chars[i] = " "
    return "".join(chars)


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
