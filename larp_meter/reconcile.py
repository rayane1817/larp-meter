"""Subject-anchored reconciliation: check a claim against what a register holds.

verify.py can only check identifiers the subject chose to type in -- a DOI, an
ORCID, a patent number. A profile that cites none gives it nothing to look up,
so the most vague profiles were the least examined. This module starts from
the other end: from what the profile CLAIMS ("President of Vane Systems AG
since 2004"), it asks a register what it actually holds, and compares.

The first source is Switzerland's commercial register (Zefix), because a claim
to a role at a registered legal entity implies an entry there, and that
register is complete for its jurisdiction. Every other outcome is a note; only
one can count against the subject, and only `gate()` can produce it:

    CONTRADICTED  confident match, and the record disagrees with the claim
    CONFIRMED     confident match, and the subject is named in the record
    EXISTS        the company is real, the subject is not named in it
    AMBIGUOUS     several matches, an unconfirmed jurisdiction, a predecessor
                  business in the record, or a role that can predate the company
    NO_RECORD     nothing registered under that name
    UNCHECKABLE   the register could not be reached

Finding nothing is never evidence. A name can be spelled differently, and a
real company can be registered somewhere this check cannot see.

The second source is OpenAlex, for publication-volume claims ("published over
200 papers", "published extensively"). It can confirm a claim but never
contradict one: OpenAlex routinely splits one researcher across several author
records, so a record holding fewer works than claimed is what an honest,
badly-indexed researcher looks like too. `OpenAlexAuthors.complete` is False
for that reason, and gate() turns every shortfall into a note.
"""

import hashlib
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from . import names
from .providers import MERGE_RISK_INSTITUTION_COUNT, _affiliation_institution_count
from .verify import USER_AGENT, TIMEOUT

CONFIRMED = "CONFIRMED"
CONTRADICTED = "CONTRADICTED"
EXISTS = "EXISTS"
AMBIGUOUS = "AMBIGUOUS"
NO_RECORD = "NO_RECORD"
UNCHECKABLE = "UNCHECKABLE"

CONFIDENT = "confident"
UNCERTAIN = "uncertain"

CACHE_TTL = 30 * 24 * 3600
MAX_RESPONSE_BYTES = 2_000_000
# Articles of association are signed before the entry is published, often in
# the previous calendar year, so a claim one year earlier is not a conflict.
FOUNDING_SLACK_YEARS = 1


@dataclass
class CompanyClaim:
    role: str
    company: str             # the name without its legal form
    legal_form: str          # normalised: AG, GmbH, SA, Sàrl, Sagl, ...
    since: Optional[int]
    swiss: bool              # a Swiss location is stated alongside the claim
    board_role: bool         # a role that cannot exist before the company does
    text: str
    named_before: list = field(default_factory=list)   # names just before the role

    @property
    def full_name(self):
        return f"{self.company} {self.legal_form}"


@dataclass
class Reconciliation:
    kind: str = "company"
    claim: str = ""
    company: str = ""
    role: str = ""
    since: Optional[int] = None
    outcome: str = UNCHECKABLE
    identity: str = UNCERTAIN
    detail: str = ""
    source: str = ""
    evidence: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    def line(self):
        """One evidence line naming what was checked."""
        if self.kind == "company":
            return f"company {self.company}: {self.detail}"
        return f"{self.kind} ({self.source}): {self.detail}"


def gate(outcome, identity, implies_footprint, source_complete):
    """The single place a reconciliation may become an accusation.

    A contradiction survives only when the register entry is confidently the
    one the subject meant, the claim is one that must leave an entry, and the
    register is complete for the jurisdiction. Any doubt demotes it to
    AMBIGUOUS, which is shown to a human and never scored against anyone.
    """
    if outcome == CONTRADICTED and not (identity == CONFIDENT and implies_footprint and source_complete):
        return AMBIGUOUS
    return outcome


# ── Extracting register-implying claims ─────────────────────────────────
_ROLES = (r"President|Chair(?:man|woman|person)?|Board\s+Member|Member\s+of\s+the\s+Board|"
          r"Managing\s+Director|Director|Gesch[äa]ftsf[üu]hrer(?:in)?|"
          r"Verwaltungsrats(?:pr[äa]sident(?:in)?|mitglied)|"
          r"Pr[äa]sident(?:in)?(?:\s+des\s+Verwaltungsrate?s)?|"
          r"Pr[ée]sident(?:e)?(?:\s+du\s+conseil(?:\s+d'administration)?)?|Presidente|"
          r"Co-?founder|Founder|Owner|CEO|CTO|COO|CFO")
# Roles entered in the Swiss register as officers of the company itself. A
# founder or a CEO can have done the work for years before incorporating; a
# board seat cannot exist before the board does.
_BOARD_ROLE_RE = re.compile(
    r"^(?:president|chair|board|member of the board|managing director|director|"
    r"gesch[äa]ftsf[üu]hrer|verwaltungsrat|pr[äa]sident|pr[ée]sident|presidente)", re.I)
_FORMS = r"AG|GmbH|S\.A\.|SA|S\.[àa]\s?r\.l\.|S[àa]rl|SARL|Sagl|SAGL|Genossenschaft|Stiftung"
_COMPANY_CLAIM_RE = re.compile(
    r"(?P<role>(?i:" + _ROLES + r"))\s*,?\s*"
    r"(?:(?i:of|at|@|der|du|de\s+la|de|von|bei|chez|di|della)\s+)?"
    r"(?P<name>[A-Z0-9][\w&'.\-]*(?:\s+[A-Z0-9][\w&'.\-]*){0,5}?)\s+"
    r"(?P<form>" + _FORMS + r")(?![\w])")
_FORM_CANON = {"s.a.": "SA", "sa": "SA", "sarl": "Sàrl", "sàrl": "Sàrl", "s.àr.l.": "Sàrl",
               "s.à r.l.": "Sàrl", "s.ar.l.": "Sàrl", "s.a r.l.": "Sàrl", "sagl": "Sagl",
               "ag": "AG", "gmbh": "GmbH", "genossenschaft": "Genossenschaft", "stiftung": "Stiftung"}

# A Swiss location stated with the claim. Deliberately excludes "Swiss"
# embedded in a word: a company called "DocSWISS" says nothing about where it
# is registered, and "Freiburg" is excluded because it is also a German city.
_SWISS_RE = re.compile(
    r"\b(?:Switzerland|Swiss|Schweiz|Suisse|Svizzera|Z[üu]rich|Zuerich|Gen[èe]ve|Geneva|Genf|"
    r"Basel|B[âa]le|Bern|Berne|Lausanne|Lugano|Zug|Luzern|Lucerne|St\.?\s?Gallen|Winterthur|Chur|"
    r"Neuch[âa]tel|Fribourg|Sion|Schaffhausen|Aarau|Biel|Bienne|Thun|Baar|Vevey|Montreux)\b"
    r"|\.ch\b|\bCHE-\d{3}\.\d{3}\.\d{3}\b", re.I)
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Januar|Februar|März|Juni|Juli|Oktober|Dezember)[a-z]*\.?"
_SINCE_RE = re.compile(
    r"\b(?:since|seit|depuis|d[èe]s|dal|from)\s+(?:" + _MONTH + r"\s+)?((?:19|20)\d{2})\b"
    r"|\b((?:19|20)\d{2})\s*[-–—]\s*(?:present|today|now|heute|aujourd'hui|oggi)\b", re.I)
# A sentence ends at punctuation followed by a capital, not at the dots of "S.A.".
_SENTENCE_END_RE = re.compile(r"[.;!?](?=\s+[A-ZÄÖÜÉ])|\n")
# Two or more capitalised words in a row: a personal name, or a title such as
# "Senior Engineer". Mistaking a title for a name only costs a contradiction.
_NAME_LIKE_RE = re.compile(r"\b[A-ZÄÖÜÉ][a-zäöüéèàçñ'\-]+(?:\s+[A-ZÄÖÜÉ][a-zäöüéèàçñ'\-]+)+\b")


def _names_before(text, start):
    """Name-like phrases between the start of the role's sentence and the role."""
    before = text[max(0, start - 80):start]
    cut = None
    for cut in _SENTENCE_END_RE.finditer(before):
        pass
    before = before[cut.end():] if cut else before
    return _NAME_LIKE_RE.findall(before)


def _since_near(text, start, end):
    after = text[end:end + 120]
    cut = _SENTENCE_END_RE.search(after)
    after = after[:cut.start()] if cut else after
    m = _SINCE_RE.search(after)
    if not m:
        before = text[max(0, start - 60):start]
        cut = None
        for cut in _SENTENCE_END_RE.finditer(before):
            pass
        before = before[cut.end():] if cut else before
        m = _SINCE_RE.search(before)
    return int(m.group(1) or m.group(2)) if m else None


def extract_company_claims(text):
    """Every role claimed at a company that carries a registrable legal form."""
    out, seen = [], {}
    for m in _COMPANY_CLAIM_RE.finditer(text or ""):
        form = _FORM_CANON.get(m.group("form").casefold(), m.group("form"))
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        line_end = len(text) if line_end == -1 else line_end
        window = text[max(line_start, m.start() - 160):min(line_end, m.end() + 160)]
        role = re.sub(r"\s+", " ", m.group("role"))
        claim = CompanyClaim(
            role=role, company=m.group("name").strip(), legal_form=form,
            since=_since_near(text, m.start(), m.end()),
            swiss=bool(_SWISS_RE.search(window)),
            board_role=bool(_BOARD_ROLE_RE.match(role)),
            text=re.sub(r"\s+", " ", text[m.start():min(line_end, m.end() + 60)]).strip(),
            named_before=_names_before(text, m.start()))
        key = _norm(claim.full_name)
        if key in seen:
            # One company named twice: keep whichever version says more.
            prev = out[seen[key]]
            if (claim.since and not prev.since) or (claim.board_role and not prev.board_role):
                out[seen[key]] = claim
            continue
        seen[key] = len(out)
        out.append(claim)
    return out


def _norm(name):
    flat = unicodedata.normalize("NFKD", name or "")
    flat = "".join(ch for ch in flat if not unicodedata.combining(ch)).casefold()
    flat = re.sub(r"\bs\.?\s?a\.?\s?r\.?\s?l\.?(?=\s|$)", "sarl", flat)
    flat = re.sub(r"\bs\.a\.(?=\s|$)", "sa", flat)
    return re.sub(r"[^\w]+", " ", flat).strip()


# ── Network, with the same rules as verify.py ───────────────────────────
def _http(url, payload=None, headers=None):
    """(ok, status, body). ok=False means unreachable -- never evidence."""
    headers = dict(headers or {}, **{"User-Agent": USER_AGENT, "Accept": "application/json"})
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return True, resp.status, resp.read(MAX_RESPONSE_BYTES).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:   # Zefix answers "no such company" with a 404: a real answer
            return True, 404, e.read(4000).decode("utf-8", errors="replace")
        return False, e.code, ""
    except Exception:
        return False, 0, ""


def _fetch(cache_dir, url, payload=None, headers=None):
    """Cached _http. Failures are never cached: an outage stored as an empty
    answer would read as "no such company" for the whole cache lifetime.
    Headers stay out of the cache key, so an API key never lands on disk."""
    key = url + "\n" + json.dumps(payload, sort_keys=True)
    path = Path(cache_dir) / (hashlib.sha1(key.encode("utf-8")).hexdigest()[:20] + ".json")
    if path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL:
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
            return True, blob["status"], blob["body"]
        except Exception:
            pass
    ok, status, body = _http(url, payload) if headers is None else _http(url, payload, headers)
    if ok:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"status": status, "body": body}), encoding="utf-8")
        except Exception:
            pass
    return ok, status, body


class ZefixWeb:
    """Switzerland's commercial register, through the endpoint its own web
    front end uses. Keyless but undocumented: if it changes, every lookup
    comes back UNCHECKABLE rather than as a finding, the same way the scraped
    Google Patents page is handled in verify.py."""

    name = "Swiss commercial register (Zefix)"
    complete = True
    SEARCH = "https://www.zefix.admin.ch/ZefixREST/api/v1/firm/search.json"
    DETAIL = "https://www.zefix.admin.ch/ZefixREST/api/v1/firm/{}.json"

    def __init__(self, cache_dir):
        self.cache_dir = cache_dir

    def search(self, full_name):
        ok, status, body = _fetch(self.cache_dir, self.SEARCH,
                                  {"name": full_name, "searchType": "exact", "maxEntries": 10})
        if not ok:
            return None
        if status == 404:
            return []
        try:
            return list(json.loads(body).get("list") or [])
        except Exception:
            return None

    def detail(self, ehraid):
        ok, status, body = _fetch(self.cache_dir, self.DETAIL.format(int(ehraid)))
        if not ok or status == 404:
            return None
        try:
            return json.loads(body)
        except Exception:
            return None


# ── Reading a register entry ────────────────────────────────────────────
_TAG_RE = re.compile(r"<[^>]+>")
_NEW_ENTRY_RE = re.compile(r"\((?:Neueintragung|Nouvelle inscription|Nuova iscrizione)\)", re.I)
_ARTICLES_RE = re.compile(
    r"(?:Statutendatum|Date des statuts|Data dello statuto)\s*:\s*\d{1,2}\.\d{1,2}\.((?:19|20)\d{2})", re.I)
# A new entity that took over an existing business carries its history in
# substance but not in its founding date.
_PREDECESSOR_RE = re.compile(
    r"Sacheinlage|Sach[üu]bernahme|[üu]bernimmt|[ÜU]bernahme|Aktiven und Passiven|Umwandlung|Fusion|"
    r"Verm[öo]gens[üu]bertragung|apport en nature|reprise|transformation|transfert de patrimoine|"
    r"conferimento|ripresa|trasformazione|fusione|trasferimento di patrimonio", re.I)
_PERSONS_HEADER_RE = re.compile(
    r"(?:Eingetragene Personen(?: neu oder mutierend)?|Ausgeschiedene Personen[^:]*|"
    r"Personnes? inscrites?[^:]*|Personne\(s\) inscrite\(s\)[^:]*|Personnes? radi[ée]es?[^:]*|"
    r"Persone iscritte[^:]*|Persone radiate[^:]*)\s*:", re.I)


def _messages(record):
    return [(p.get("shabDate", ""), _TAG_RE.sub("", p.get("message") or ""))
            for p in (record.get("shabPub") or [])]


def _founding(record):
    """(year, message) from the new-registration entry, or (None, None).

    The gazette history Zefix serves reaches back to about April 2016. A
    company registered earlier has no such entry, and its founding year is
    unknown -- not "recent".
    """
    for date, msg in _messages(record):
        if _NEW_ENTRY_RE.search(msg):
            m = _ARTICLES_RE.search(msg)
            if m:
                return int(m.group(1)), msg
            if date[:4].isdigit():
                return int(date[:4]), msg
    return None, None


def _registered_people(record):
    """'Given Surname' for everyone named in the entry's person sections."""
    people = []
    for _date, msg in _messages(record):
        for header in _PERSONS_HEADER_RE.finditer(msg):
            section = msg[header.end():]
            nxt = _PERSONS_HEADER_RE.search(section)
            section = section[:nxt.start()] if nxt else section
            for entry in section.split(";"):
                fields = [f.strip(" .") for f in entry.split(",")]
                if len(fields) >= 2 and fields[0] and fields[1]:
                    people.append(f"{fields[1]} {fields[0]}")
    return people


def _names_subject(record, subject):
    """True only on a positive match. Checked one person at a time, because
    joining every name into one blob lets tokens from different people
    combine into a match for someone who is not there."""
    if not subject:
        return False
    return any(names.name_matches(subject, [p]) is True for p in _registered_people(record))


def _reconcile_company(claim, subject, source):
    rec = Reconciliation(claim=claim.text, company=claim.full_name, role=claim.role,
                         since=claim.since, source=source.name)
    rows = source.search(claim.full_name)
    if rows is None:
        rec.outcome, rec.detail = UNCHECKABLE, f"{source.name} could not be reached."
        return rec
    if not rows:
        rec.outcome = NO_RECORD
        rec.detail = (f"No company is registered in Switzerland under exactly '{claim.full_name}'. "
                      + ("A spelling variant would also miss — worth a manual search."
                         if claim.swiss else
                         "It may be registered outside Switzerland, which this check cannot see."))
        return rec
    if len(rows) > 1:
        rec.outcome = AMBIGUOUS
        rec.detail = (f"{len(rows)} register entries match '{claim.full_name}' "
                      f"({', '.join(sorted({r.get('name', '?') for r in rows}))[:160]}) — "
                      f"cannot tell which one is meant.")
        rec.evidence = [f"{r.get('name')} — {r.get('uidFormatted') or r.get('uid')}, "
                        f"{r.get('legalSeat')}, {r.get('status')}" for r in rows[:4]]
        return rec

    record = source.detail(rows[0].get("ehraid"))
    if record is None:
        rec.outcome, rec.detail = UNCHECKABLE, f"The {source.name} entry could not be retrieved."
        return rec
    registered_names = {_norm(record.get("name"))} | {_norm(t) for t in (record.get("translation") or [])}
    if _norm(claim.full_name) not in registered_names:
        rec.outcome = AMBIGUOUS
        rec.detail = f"The closest register entry is '{record.get('name')}', not '{claim.full_name}'."
        return rec

    on_record = _names_subject(record, subject)
    # "I worked with Hans Muster, President of ..." is Hans Muster's claim. When
    # someone other than the subject is named right before the role, the role
    # is not established as the subject's, so nothing about it can be scored
    # against them -- whoever the register names.
    about_someone_else = bool(claim.named_before) and not any(
        subject and names.name_matches(subject, [n]) is True for n in claim.named_before)
    rec.identity = CONFIDENT if (claim.swiss or on_record) and not about_someone_else else UNCERTAIN
    founded, founding_msg = _founding(record)
    predecessor = bool(record.get("oldNames") or record.get("hasTakenOver")
                       or (founding_msg and _PREDECESSOR_RE.search(founding_msg)))
    rec.evidence = [f"{record.get('name')} — {record.get('uidFormatted') or record.get('uid')}, "
                    f"{record.get('legalSeat')}, {record.get('status')}"
                    + (f", incorporated {founded}" if founded else ", incorporated before 2016 or unknown"),
                    "subject named in the register entries" if on_record
                    else "subject not named in the register entries available (reaching back to 2016)"]

    if claim.since and founded and claim.since < founded - FOUNDING_SLACK_YEARS:
        if predecessor:
            outcome = AMBIGUOUS
            rec.detail = (f"Claims {claim.role} since {claim.since}; {record.get('name')} was incorporated "
                          f"in {founded}, but its record shows a predecessor business, name change or "
                          f"takeover that may account for the earlier date.")
        elif not claim.board_role:
            outcome = AMBIGUOUS
            rec.detail = (f"Claims {claim.role} since {claim.since}; {record.get('name')} was incorporated "
                          f"in {founded}. A {claim.role.lower()} commonly works on a business for years "
                          f"before incorporating it, so this is not a contradiction.")
        else:
            outcome = CONTRADICTED
            rec.detail = (f"Claims {claim.role} of {record.get('name')} since {claim.since}, but the "
                          f"commercial register shows the company was only incorporated in {founded}, "
                          f"with no predecessor business, name change or takeover on record.")
    elif on_record:
        outcome = CONFIRMED
        rec.detail = f"The subject is named in {record.get('name')}'s commercial register entries."
    else:
        outcome = EXISTS
        rec.detail = (f"{record.get('name')} is registered, but the subject is not named in the register "
                      f"entries available — existence alone does not confirm the role.")

    gated = gate(outcome, rec.identity, implies_footprint=True, source_complete=source.complete)
    if gated != outcome:
        rec.detail += (" Not counted: the role is attributed to someone else in the text ("
                       + ", ".join(claim.named_before[:2]) + ")." if about_someone_else else
                       " Not counted: the entry could not be tied to this subject with confidence — no "
                       "Swiss location is stated with the claim, and the subject is not named in it.")
    rec.outcome = gated
    return rec


# ── Publication-volume claims against OpenAlex ──────────────────────────
# Below this, "a record consistent with 'published extensively'" means little.
VAGUE_MINIMUM_WORKS = 20
# "Over 200 papers" against 170 indexed works is consistent: indexes lag, and
# conference abstracts or book chapters are counted unevenly.
CONFIRM_RATIO = 0.8
# More records than this under one name at one stated institution is a crowd
# of namesakes, not one person split up; summing them would inflate the count.
MAX_TIED_RECORDS = 3

_PUB_NOUN = (r"(?:papers|articles|publications|Publikationen|Ver[öo]ffentlichungen|Fachartikel|"
             r"Artikel|articles\s+scientifiques)")
_PUB_ADJ = (r"(?:(?:peer[- ]reviewed|refereed|scientific|scholarly|academic|research|journal|"
            r"conference|wissenschaftliche[n]?|internationale[n]?|international)\s+)*")
_PUB_COUNT_RE = re.compile(r"(?<![\d.,])(\d{1,4})\s*\+?\s+" + _PUB_ADJ + _PUB_NOUN + r"\b", re.I)
_PUB_VAGUE_RE = re.compile(
    r"\bpublished\s+(?:extensively|widely|prolifically)\b|\bwidely\s+published\b|"
    r"\b(?:extensive|numerous)\s+(?:peer[- ]reviewed\s+)?publications\b|"
    r"\bprolific\s+(?:author|researcher|scholar|scientist|writer)\b|"
    r"\bzahlreiche\s+(?:Publikationen|Ver[öo]ffentlichungen)\b|\bnombreuses\s+publications\b", re.I)
# Handling other people's papers is not writing them. ("My supervisor ...
# has published" is a claim about the supervisor, caught by named_before.)
_NOT_AUTHORING_RE = re.compile(
    r"\b(?:review(?:ed|er|ing)?|referee(?:d|ing)?|edit(?:ed|or|ing)|supervis(?:ed|ing)|read|"
    r"cited|handled|evaluated|graded|translated|begutachtet|betreut)\b", re.I)
# "12 papers in Nature" is a count in one venue, not a total. "... at ETH" is
# an affiliation, so only "in" marks a venue.
_VENUE_AFTER_RE = re.compile(r"\s+in\s+(?:the\s+)?[A-Z]")
_CLAUSE_END_RE = re.compile(r"[.;:,!?\n]")
_QUANTIFIER_BEFORE_RE = re.compile(
    r"(?:over|more\s+than|at\s+least|nearly|almost|about|around|some|approximately|[üu]ber|mehr\s+als|"
    r"plus\s+de|published|authored|wrote)\s*$", re.I)
# Capitalised words that make a title or an institution look like a personal
# name ("Senior Lecturer at University College London").
_NOT_PERSON_WORDS = {
    "university", "college", "institute", "school", "department", "faculty", "hospital", "clinic",
    "lab", "labs", "laboratory", "center", "centre", "group", "foundation", "academy", "society",
    "professor", "prof", "senior", "junior", "lecturer", "researcher", "research", "scientist",
    "director", "head", "chair", "fellow", "associate", "assistant", "principal", "chief", "lead",
    "science", "sciences", "engineering", "medicine", "technology", "computer", "the", "of", "and"}
_ORCID_RE = re.compile(r"\b(\d{4}-\d{4}-\d{4}-\d{3}[\dX])\b")


@dataclass
class PublicationClaim:
    count: Optional[int]     # None for a vague claim ("published extensively")
    vague: bool
    text: str
    named_before: list = field(default_factory=list)


def _people_before(text, start):
    return [n for n in _names_before(text, start)
            if not any(w.casefold() in _NOT_PERSON_WORDS for w in n.split())]


def extract_publication_claim(text):
    """The strongest publication-volume claim in `text`, or None."""
    text = text or ""
    best = None
    for m in _PUB_COUNT_RE.finditer(text):
        n = int(m.group(1))
        # "Our 2019 papers" is a year; "over 2000 papers" is a count.
        looks_like_year = (1900 <= n <= 2099 and "+" not in m.group(0)
                           and not _QUANTIFIER_BEFORE_RE.search(text[max(0, m.start() - 16):m.start()]))
        if n < 5 or looks_like_year:
            continue
        clause = text[max(0, m.start() - 60):m.start()]
        cut = None
        for cut in _CLAUSE_END_RE.finditer(clause):
            pass
        clause = clause[cut.end():] if cut else clause
        if _NOT_AUTHORING_RE.search(clause) or _VENUE_AFTER_RE.match(text, m.end()):
            continue
        if best is None or n > best.count:
            best = PublicationClaim(n, False, re.sub(r"\s+", " ", text[m.start():m.end() + 40]).strip(),
                                    _people_before(text, m.start()))
    if best:
        return best
    m = _PUB_VAGUE_RE.search(text)
    if m:
        return PublicationClaim(None, True, re.sub(r"\s+", " ", text[m.start():m.end() + 40]).strip(),
                                _people_before(text, m.start()))
    return None


class OpenAlexAuthors:
    """OpenAlex author records under a name. Keyless: $0.10 a day at $0.001 a
    search (live-measured 2026-09-22). A free account key in OPENALEX_API_KEY
    raises that tenfold; it is sent as a header, never in the URL, so it stays
    out of the cache key and any logged URL."""

    name = "OpenAlex"
    # One person's output is spread over however many records OpenAlex split
    # them into, so no single lookup is complete for anyone.
    complete = False
    SEARCH = ("https://api.openalex.org/authors?search={}&per_page=25"
              "&select=id,display_name,orcid,works_count,affiliations,last_known_institutions")

    def __init__(self, cache_dir):
        self.cache_dir = cache_dir

    def search(self, full_name):
        key = os.environ.get("OPENALEX_API_KEY", "").strip()
        headers = {"Authorization": "Bearer " + key} if key else {}
        ok, status, body = _fetch(self.cache_dir, self.SEARCH.format(urllib.parse.quote(full_name)),
                                  headers=headers)
        if not ok or status != 200:
            return None
        try:
            return list(json.loads(body).get("results") or [])
        except Exception:
            return None


def _institutions(author):
    return [(a.get("institution") or {}).get("display_name") or "" for a in author.get("affiliations") or []] \
        or [i.get("display_name") or "" for i in author.get("last_known_institutions") or []]


def _tie(author, flat_text, orcids):
    """What ties this record to the profile: a stated institution or ORCID."""
    orcid = (author.get("orcid") or "").rsplit("/", 1)[-1]
    if orcid and orcid in orcids:
        return "ORCID " + orcid
    for inst_name in _institutions(author):
        flat = _norm(inst_name)
        if len(flat) >= 4 and f" {flat} " in flat_text:
            return inst_name
    return None


def _reconcile_publications(claim, subject, text, source):
    wanted = claim.count if claim.count else VAGUE_MINIMUM_WORKS
    rec = Reconciliation(kind="publications", claim=claim.text, source=source.name)
    rows = source.search(subject)
    if rows is None:
        rec.outcome, rec.detail = UNCHECKABLE, f"{source.name} could not be reached."
        return rec
    named = [a for a in rows if names.name_matches(subject, [a.get("display_name") or ""]) is True]
    if not named:
        rec.outcome = NO_RECORD
        rec.detail = (f"{source.name} has no author record under '{subject}'. A different publishing "
                      f"name, a transliteration or a field it indexes poorly would also miss.")
        return rec
    flat_text = f" {_norm(text)} "
    orcids = set(_ORCID_RE.findall(text))
    tied = [(a, t) for a in named for t in [_tie(a, flat_text, orcids)] if t]
    rec.evidence = [f"{a.get('id', '').rsplit('/', 1)[-1]} — {a.get('display_name')}, "
                    f"{a.get('works_count', 0)} works, tied by {t}" for a, t in tied[:4]]
    merged = [a for a, _t in tied if _affiliation_institution_count(a) >= MERGE_RISK_INSTITUTION_COUNT]
    if not tied:
        rec.outcome = AMBIGUOUS
        rec.detail = (f"{len(named)} {source.name} author record(s) under '{subject}', none tied to an "
                      f"institution or ORCID the profile states — cannot tell whether any is the subject.")
        rec.evidence = [f"{a.get('id', '').rsplit('/', 1)[-1]} — {a.get('display_name')}, "
                        f"{a.get('works_count', 0)} works" for a in named[:4]]
        return rec
    if merged or len(tied) > MAX_TIED_RECORDS:
        rec.outcome = AMBIGUOUS
        rec.detail = (f"{len(tied)} {source.name} record(s) under '{subject}' share a stated institution"
                      + (", and at least one lists so many institutions that it likely merges several "
                         "people" if merged else "") + " — the works cannot be attributed to one person.")
        return rec
    rec.identity = CONFIDENT
    total = sum(int(a.get("works_count") or 0) for a, _t in tied)
    asked = f"over {claim.count}" if claim.count else "an extensive record"
    if total >= wanted * CONFIRM_RATIO:
        outcome = CONFIRMED
        rec.detail = (f"{source.name} holds {total} works across {len(tied)} record(s) tied to the subject "
                      f"by a stated institution or ORCID, consistent with the claim of {asked}.")
    else:
        outcome = CONTRADICTED
        rec.detail = (f"{source.name} holds {total} works across {len(tied)} record(s) tied to the subject, "
                      f"against a claim of {asked}.")
    gated = gate(outcome, rec.identity, implies_footprint=True, source_complete=source.complete)
    if gated != outcome:
        rec.detail += (f" Not counted: {source.name} often splits one researcher across several records, "
                       f"and indexes books and some fields thinly, so a shortfall is worth a manual look "
                       f"but is not evidence.")
    rec.outcome = gated
    return rec


def reconcile_text(text, subject_name="", cache_dir="."):
    """Check every register-implying claim in `text`. Returns Reconciliations."""
    subject = subject_name or ""
    source = ZefixWeb(cache_dir)
    out = [_reconcile_company(c, subject, source) for c in extract_company_claims(text)]
    pub = extract_publication_claim(text)
    # Every OpenAlex search costs budget: spend it only on a claim that is the
    # subject's own, about a subject we can name.
    if pub and subject and not any(names.name_matches(subject, [n]) is not True for n in pub.named_before):
        out.append(_reconcile_publications(pub, subject, text, OpenAlexAuthors(cache_dir)))
    return out
