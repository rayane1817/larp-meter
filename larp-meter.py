#!/usr/bin/env python3
"""
LARP Meter v2 — Claim-vs-Evidence Auditor
=========================================
Audits professional self-presentation (LinkedIn bios, pitch decks, "About"
pages) against verifiable substance. A due-diligence triage tool: it surfaces
red flags worth investigating — it does not render verdicts about people.

Usage:
    python larp-meter.py --text "President @ DeepTech Corp. MoU with MIT..."
    python larp-meter.py --file bio.txt
    python larp-meter.py "Jane Doe"              # web-search mode
    python larp-meter.py --interactive
    python larp-meter.py --list
    python larp-meter.py --selftest

Key methodology (v2):
    - Three-state flags: TRIGGERED / PASSED / UNKNOWN. Absence of evidence is
      never counted as innocence — undecidable flags reduce *coverage*, not risk.
    - Weighted scoring: structural deception signals (self-referential
      partners, credential mismatch) weigh more than stylistic ones (buzzwords).
    - Word-boundary matching: "ai" no longer matches "said" or "email".
    - Normalized buzzword density (per 100 words), so long texts aren't punished.
    - Generic self-referential-partner detection (no hardcoded org names).
    - Specificity index: dates, numbers, DOIs, patent IDs, named institutions.
"""

import argparse
import hashlib
import html as html_lib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────
VAULT_PATH = os.environ.get("OBSIDIAN_VAULT_PATH", str(Path.home() / "Documents" / "Obsidian Vault"))
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
CACHE_DIR = BASE_DIR / "cache"
CACHE_TTL = 7 * 24 * 3600  # 7 days

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

TRIGGERED, PASSED, UNKNOWN = "TRIGGERED", "PASSED", "UNKNOWN"

# Windows consoles often default to cp1252, which can't print the report glyphs
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# ANSI colors (disabled when not a tty)
def _c(code):
    return code if sys.stdout.isatty() else ""

RED_C, YELLOW_C, GREEN_C, GREY_C, BOLD, RESET = (
    _c("\033[91m"), _c("\033[93m"), _c("\033[92m"), _c("\033[90m"), _c("\033[1m"), _c("\033[0m"))


# ── Term matching (word-boundary, not substring) ────────────────────────
_TERM_CACHE = {}

def _term_re(term):
    """Compile a word-boundary regex for a term/phrase. Cached."""
    rx = _TERM_CACHE.get(term)
    if rx is None:
        # Allow flexible whitespace/hyphens inside multi-word terms
        parts = [re.escape(p) for p in re.split(r"[\s\-]+", term.strip()) if p]
        rx = re.compile(r"\b" + r"[\s\-]+".join(parts) + r"\b", re.IGNORECASE)
        _TERM_CACHE[term] = rx
    return rx

def has_term(text, term):
    return bool(_term_re(term).search(text))

def find_terms(text, terms):
    """Return the subset of terms present (word-boundary matched)."""
    return [t for t in terms if has_term(text, t)]

def count_occurrences(text, terms):
    return sum(len(_term_re(t).findall(text)) for t in terms)


# ── Keyword banks ────────────────────────────────────────────────────────
TECH_EDU = [
    "engineering", "computer science", "physics", "electrical engineering",
    "mechanical engineering", "biomedical engineering", "mathematics",
    "informatics", "robotics", "aerospace", "data science", "machine learning",
    "electronics", "telecommunications", "nuclear engineering", "chemistry",
    "bioinformatics", "computational",
]
NONTECH_EDU = [
    "public health", "policy", "governance", "advocacy", "law",
    "political science", "european studies", "international relations",
    "sociology", "psychology", "business administration", "mba",
    "humanities", "history", "philosophy", "communication studies",
    "marketing", "public administration", "journalism",
]
DEGREE_WORDS = ["msc", "bsc", "phd", "mba", "master", "bachelor",
                "doctorate", "postdoc", "llm"]
TECH_CLAIMS = [
    "artificial intelligence", "edge ai", "radiation", "hardware", "satellite",
    "dual use", "deep tech", "nuclear", "rocket", "machine learning",
    "neural network", "semiconductor", "biometric", "genomics", "robotics",
    "blockchain", "quantum", "aerospace", "cybersecurity", "photonics",
]
LEADERSHIP_TITLES = ["president", "founder", "co-founder", "ceo", "cto",
                     "chief executive", "chief technology", "director", "head of"]
TECH_ROLES = ["engineer", "developer", "chief technology", "research scientist",
              "scientist", "software architect", "lead developer",
              "principal engineer", "researcher"]
POLICY_ROLES = ["patient advocacy", "secretary general", "policy officer",
                "public health", "governance", "board member", "consultant",
                "advisor", "lobbyist", "ambassador"]
BUZZWORDS = [
    "synergy", "paradigm", "paradigm shift", "disruption", "disruptive",
    "game changing", "revolutionary", "groundbreaking", "pioneering",
    "cutting edge", "bleeding edge", "next generation", "state of the art",
    "world class", "visionary", "thought leader", "thought leadership",
    "exponential", "moonshot", "transformative", "trailblazing",
    "space grade", "future proof", "hypergrowth", "unicorn",
]
VAGUE_PARTNERSHIP = [
    "mou", "memorandum of understanding", "nda", "non-disclosure",
    "in discussion", "discussions ongoing", "in talks", "preliminary",
    "exploratory", "letter of intent", "loi", "heads of terms",
    "term sheet", "early conversations",
]
CONCRETE_PARTNERSHIP = [
    "grant", "funded by", "contract", "joint venture", "joint development",
    "co-development", "collaboration agreement", "investment", "series a",
    "series b", "seed round closed", "revenue", "paying customer",
    "pilot deployed", "acquired", "licensing agreement",
]
BUILDING_CLAIMS = ["building", "developing", "creating", "working on",
                   "patent pending", "stealth", "coming soon", "pre-launch"]
TRACTION = ["customers", "revenue", "clients", "paying users", "arr", "mrr",
            "contracts signed", "deployed in production", "units sold",
            "subscribers", "bookings"]
FUNDING_ASK = ["seeking investment", "seeking funding", "raising", "funding round",
               "looking for investors", "seeking partners and investors",
               "open to investors", "seed round", "funding ask"]
DEEP_COLLAB = ["co-authored", "joint paper", "joint research", "co-developed",
               "integration partner", "technology partner", "reseller",
               "oem", "distributor", "system integrator", "joint publication"]
EXTERNAL_VALIDATION = [
    "featured in", "as seen on", "interviewed by", "published in",
    "recognized by", "awarded", "award winner", "keynote", "covered by",
    "profiled in", "cited by",
]
PRESS_OUTLETS = ["techcrunch", "forbes", "wired", "reuters", "bloomberg",
                 "financial times", "the economist", "bbc", "nature",
                 "ieee spectrum", "mit technology review", "wall street journal"]
SELF_PUBLISHED_DOMAINS = ["medium.com", "substack.com", "linkedin.com/pulse",
                          "wordpress.com", "blogspot.com", "wixsite.com",
                          "facebook.com", "x.com", "twitter.com"]

# Hard-evidence patterns: things that can be independently verified
HARD_EVIDENCE_PATTERNS = [
    (re.compile(r"\b10\.\d{4,9}/[-.;()/:\w]+", re.I), "DOI"),
    (re.compile(r"\b(?:US|EP|WO)\s?\d{7,}(?:\s?[AB]\d)?\b"), "patent number"),
    (re.compile(r"github\.com/[\w.-]+", re.I), "GitHub repository"),
    (re.compile(r"arxiv\.org/abs/\d{4}\.\d{4,5}", re.I), "arXiv paper"),
    (re.compile(r"\borcid\.org/\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b", re.I), "ORCID"),
    (re.compile(r"\b(?:FDA|CE)[\s-](?:cleared|approved|marking|certified)\b", re.I), "regulatory clearance"),
    (re.compile(r"clinicaltrials\.gov/(?:ct2/show/)?NCT\d+", re.I), "clinical trial"),
    (re.compile(r"\bpeer[\s-]reviewed\b", re.I), "peer-review claim"),
]

ORG_SUFFIX = re.compile(r"\s+(?:gmbh|ltd|llc|inc|bv|nv|sa|ag|foundation|association|institute)\.?$", re.I)


# ── Flag definitions: (id, name, weight, question) ──────────────────────
FLAG_DEFS = [
    (1,  "Education ≠ Claimed Domain",        1.5, "Does educational background match the claimed field of expertise?"),
    (2,  "Experience ≠ Declared Title",       1.5, "Does work history support the self-declared role?"),
    (3,  "Self-Referential Partners",         2.0, "Are claimed 'partners' the person's own organizations?"),
    (4,  "Buzzword Density",                  1.0, "Is the language hype-heavy relative to its length?"),
    (5,  "Vague Partnerships Only",           1.0, "Are collaborations only MoUs/NDAs rather than contracts or grants?"),
    (6,  "No Verifiable Output",              1.5, "Is there any independently checkable output (papers, patents, code, products)?"),
    (7,  "Fundraising Without Traction",      1.5, "Is money being raised with zero evidence of customers or revenue?"),
    (8,  "Unverifiable Credentials",          1.0, "Are claimed degrees tied to a named, checkable institution?"),
    (9,  "Logo Wall Syndrome",                1.0, "Many partner names but no evidence of deep collaboration?"),
    (10, "No Independent Validation",         1.0, "Any third-party coverage not originating from the subject?"),
]
FLAG_BY_ID = {f[0]: f for f in FLAG_DEFS}
TOTAL_WEIGHT = sum(f[2] for f in FLAG_DEFS)


def flag_result(status, description="", evidence=None):
    return {"status": status, "description": description, "evidence": evidence or []}


# ── Generic self-referential org detection ──────────────────────────────
OWNED_ORG_RE = re.compile(
    r"(?i:founder|co-founder|founded|president|created|established|my company|"
    r"chairman|owner|ceo)\s+(?i:(?:and\s+\w+\s+)?(?:of|at|@))\s+([A-Z][\w&-]*(?:[ \t][A-Z][\w&-]*){0,3})")
PARTNER_ORG_RE = re.compile(
    r"(?i:partner(?:ship|ed)?|collaborat\w+|mou|alliance|consortium|agreement)\s+"
    r"(?i:with|between)\s+([A-Z][\w&-]*(?:[ \t][A-Z][\w&-]*){0,3})")

def _norm_org(name):
    return ORG_SUFFIX.sub("", name.strip()).casefold()

def detect_self_referential(text):
    """Find orgs the subject leads that also appear as their 'partners'."""
    owned = {_norm_org(m): m.strip() for m in OWNED_ORG_RE.findall(text)}
    partners = {_norm_org(m): m.strip() for m in PARTNER_ORG_RE.findall(text)}
    overlap = [partners[k] for k in owned.keys() & partners.keys()]
    return overlap, list(owned.values()), list(partners.values())


# ── Specificity index ────────────────────────────────────────────────────
def specificity_index(text):
    """Verifiable-detail signals per 100 words. Legit profiles are specific."""
    words = max(len(text.split()), 1)
    signals = 0
    signals += len(re.findall(r"\b(?:19|20)\d{2}\b", text))                  # years
    signals += len(re.findall(r"\b\d[\d,.]*\s?(?:%|€|\$|£|k\b|m\b|users|employees|patients|units)", text, re.I))
    signals += len(re.findall(r"\bhttps?://\S+", text))
    signals += len(re.findall(r"\b(?:university|institute|hospital|laboratory)\s+of\s+[A-Z]\w+", text))
    signals += len(re.findall(r"\b[A-Z]\w+\s+(?:university|institute)\b", text))
    for rx, _label in HARD_EVIDENCE_PATTERNS:
        signals += len(rx.findall(text))
    return round(signals / words * 100, 2)


# ── The analysis engine (shared by text / web / interactive modes) ──────
def analyze(text, source_urls=None):
    """Evaluate all 10 flags against a text corpus. Returns dict id -> result."""
    source_urls = source_urls or []
    results = {}
    word_count = len(text.split())

    # F1: Education vs claimed domain
    tech_claims = find_terms(text, TECH_CLAIMS)
    tech_edu = find_terms(text, TECH_EDU)
    nontech_edu = find_terms(text, NONTECH_EDU)
    has_degree_mention = bool(find_terms(text, DEGREE_WORDS))
    if not tech_claims:
        results[1] = flag_result(UNKNOWN, "No technical-domain claims to check against.")
    elif not (tech_edu or nontech_edu or has_degree_mention):
        results[1] = flag_result(UNKNOWN, "No education background found in available text.")
    elif nontech_edu and not tech_edu:
        results[1] = flag_result(
            TRIGGERED,
            f"Claims expertise in {', '.join(tech_claims[:3])} but stated education is "
            f"non-technical ({', '.join(nontech_edu[:3])}); no technical degree found.")
    elif tech_edu:
        results[1] = flag_result(PASSED, f"Technical background ({', '.join(tech_edu[:3])}) supports domain claims.")
    else:
        results[1] = flag_result(UNKNOWN, "Degree mentioned but field of study unclear.")

    # F2: Experience vs declared title
    titles = find_terms(text, LEADERSHIP_TITLES)
    tech_roles = find_terms(text, TECH_ROLES)
    policy_roles = find_terms(text, POLICY_ROLES)
    if not titles or not tech_claims:
        results[2] = flag_result(UNKNOWN, "No leadership title in a technical domain to verify.")
    elif policy_roles and not tech_roles:
        results[2] = flag_result(
            TRIGGERED,
            f"Holds title '{titles[0]}' in a technical venture, but visible work history is "
            f"{', '.join(policy_roles[:3])} — no technical roles found.")
    elif tech_roles:
        results[2] = flag_result(PASSED, f"Work history includes technical roles ({', '.join(tech_roles[:3])}).")
    else:
        results[2] = flag_result(UNKNOWN, "Insufficient work-history detail to judge.")

    # F3: Self-referential partners (generic detection, no hardcoded names)
    overlap, owned, partners = detect_self_referential(text)
    if overlap:
        results[3] = flag_result(
            TRIGGERED,
            f"Organization(s) led by the subject also appear as their 'partners': "
            f"{', '.join(sorted(set(overlap))[:4])}. Circular-validation pattern.",
            evidence=sorted(set(overlap)))
    elif partners and owned:
        results[3] = flag_result(PASSED, "Claimed partners are distinct from the subject's own organizations.")
    else:
        results[3] = flag_result(UNKNOWN, "No partnership claims (or no ownership info) to cross-check.")

    # F4: Buzzword density — normalized per 100 words
    if word_count < 25:
        results[4] = flag_result(UNKNOWN, "Text too short to measure buzzword density meaningfully.")
    else:
        distinct = find_terms(text, BUZZWORDS)
        occurrences = count_occurrences(text, BUZZWORDS)
        density = occurrences / word_count * 100
        if len(distinct) >= 4 and density >= 2.0:
            results[4] = flag_result(
                TRIGGERED,
                f"{len(distinct)} distinct buzzwords, density {density:.1f} per 100 words "
                f"(e.g. {', '.join(distinct[:5])}). Hype-to-substance ratio is high.",
                evidence=distinct)
        else:
            results[4] = flag_result(PASSED, f"Buzzword density acceptable ({density:.1f}/100 words).")

    # F5: Vague vs concrete partnerships
    vague = find_terms(text, VAGUE_PARTNERSHIP)
    concrete = find_terms(text, CONCRETE_PARTNERSHIP)
    if not vague and not concrete:
        results[5] = flag_result(UNKNOWN, "No partnership/deal language present to classify.")
    elif len(vague) >= 2 and len(vague) > len(concrete):
        results[5] = flag_result(
            TRIGGERED,
            f"Deal language is predominantly non-binding ({', '.join(vague[:4])}) with little "
            f"concrete backing ({len(concrete)} concrete term(s)).", evidence=vague)
    else:
        results[5] = flag_result(PASSED, f"Concrete deal terms present ({', '.join(concrete[:4])}).")

    # F6: Verifiable output
    hard_hits = []
    for rx, label in HARD_EVIDENCE_PATTERNS:
        m = rx.search(text)
        if m:
            hard_hits.append(f"{label}: {m.group(0)[:60]}")
    building = find_terms(text, BUILDING_CLAIMS)
    if hard_hits:
        results[6] = flag_result(PASSED, "Independently checkable output found.", evidence=hard_hits)
    elif building:
        results[6] = flag_result(
            TRIGGERED,
            f"Claims to be {building[0]} but offers no checkable artifact — no DOI, patent "
            f"number, repository, trial registration, or certification.")
    else:
        results[6] = flag_result(UNKNOWN, "No output claims made; nothing to verify.")

    # F7: Fundraising without traction
    asks = find_terms(text, FUNDING_ASK)
    traction = find_terms(text, TRACTION)
    if not asks:
        results[7] = flag_result(UNKNOWN, "Not visibly fundraising; flag not applicable.")
    elif traction:
        results[7] = flag_result(PASSED, f"Fundraising with stated traction ({', '.join(traction[:3])}).")
    else:
        results[7] = flag_result(
            TRIGGERED,
            f"Actively raising ({asks[0]}) with zero mention of customers, revenue, or usage.")

    # F8: Credential verifiability
    degree_claims = find_terms(text, DEGREE_WORDS)
    named_institution = bool(re.search(
        r"\b(?:university|université|universiteit|college|institute|school)\b", text, re.I))
    if not degree_claims:
        results[8] = flag_result(UNKNOWN, "No degree claims made.")
    elif named_institution:
        results[8] = flag_result(PASSED, "Degree claims name an institution and are checkable.")
    else:
        results[8] = flag_result(
            TRIGGERED,
            f"Degree claimed ({', '.join(degree_claims[:2])}) without naming any institution — unverifiable as stated.")

    # F9: Logo wall
    deep = find_terms(text, DEEP_COLLAB)
    distinct_partners = sorted(set(_norm_org(p) for p in partners))
    if len(distinct_partners) >= 4 and not deep:
        results[9] = flag_result(
            TRIGGERED,
            f"{len(distinct_partners)} partner organizations named with no evidence of deep "
            f"collaboration (no joint papers, integrations, co-development).",
            evidence=partners[:6])
    elif deep:
        results[9] = flag_result(PASSED, f"Deep-collaboration evidence present ({', '.join(deep[:3])}).")
    elif distinct_partners:
        results[9] = flag_result(PASSED, "Few partners named; no logo-wall pattern.")
    else:
        results[9] = flag_result(UNKNOWN, "No partner list present.")

    # F10: Independent validation
    ext_markers = find_terms(text, EXTERNAL_VALIDATION)
    outlets = find_terms(text, PRESS_OUTLETS)
    independent_urls = [u for u in source_urls
                        if not any(d in u.lower() for d in SELF_PUBLISHED_DOMAINS)]
    if ext_markers or outlets or independent_urls:
        ev = outlets or ext_markers or independent_urls[:3]
        results[10] = flag_result(PASSED, "Third-party validation signals found.", evidence=ev)
    elif word_count >= 40 and (titles or tech_claims):
        results[10] = flag_result(
            TRIGGERED,
            "Substantial claims but zero third-party validation — no press, awards, or independent coverage detected.")
    else:
        results[10] = flag_result(UNKNOWN, "Too little material to expect validation signals.")

    return results


# ── Scoring ──────────────────────────────────────────────────────────────
def score(results):
    """Weighted LARP score over decidable flags + coverage of evidence."""
    trig_w = sum(FLAG_BY_ID[i][2] for i, r in results.items() if r["status"] == TRIGGERED)
    pass_w = sum(FLAG_BY_ID[i][2] for i, r in results.items() if r["status"] == PASSED)
    decided_w = trig_w + pass_w
    coverage = decided_w / TOTAL_WEIGHT
    larp_score = round(100 * trig_w / decided_w) if decided_w else 0

    if coverage < 0.35:
        level, summary = "INSUFFICIENT DATA", ("Not enough decidable evidence to score. "
                                               "Provide a longer text or run web mode.")
    elif larp_score < 20:
        level, summary = "GREEN", "Claims and verifiable substance broadly align."
    elif larp_score < 40:
        level, summary = "YELLOW", "Some image-vs-substance gap. Verify specifics before engaging."
    elif larp_score < 65:
        level, summary = "ORANGE", "Significant concerns: multiple weighted red flags. Deep due diligence required."
    else:
        level, summary = "RED", "Strong LARP pattern: claims structurally unsupported by any verifiable evidence."

    return {"score": larp_score, "coverage": round(coverage * 100),
            "level": level, "summary": summary}


# ── Web search (DuckDuckGo HTML + cache) ─────────────────────────────────
def fetch_url(url, data=None, timeout=15):
    try:
        import urllib.request
        req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return ""

def _cache_path(query):
    return CACHE_DIR / (hashlib.sha1(query.encode()).hexdigest()[:16] + ".json")

def search_web(query, limit=6):
    """DuckDuckGo HTML endpoint (no JS, no API key), with 7-day disk cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp = _cache_path(query)
    if cp.exists() and time.time() - cp.stat().st_mtime < CACHE_TTL:
        try:
            return json.loads(cp.read_text(encoding="utf-8"))[:limit]
        except Exception:
            pass

    import urllib.parse
    html = fetch_url("https://html.duckduckgo.com/html/",
                     data=urllib.parse.urlencode({"q": query}).encode())
    results = []
    if html:
        for m in re.finditer(
                r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL):
            href, title_html = m.group(1), m.group(2)
            # DDG wraps results in a redirect: extract uddg param
            uddg = re.search(r"uddg=([^&]+)", href)
            url = urllib.parse.unquote(uddg.group(1)) if uddg else href
            title = html_lib.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
            if url.startswith("http") and title:
                results.append({"url": url, "title": title, "snippet": ""})
            if len(results) >= limit:
                break
        # Snippets live in separate elements; grab them in document order
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
        for i, s in enumerate(snippets[:len(results)]):
            results[i]["snippet"] = html_lib.unescape(re.sub(r"<[^>]+>", "", s)).strip()
    try:
        cp.write_text(json.dumps(results), encoding="utf-8")
    except Exception:
        pass
    return results


def gather_web_corpus(name):
    """Run targeted queries and build a corpus + source URL list."""
    queries = [
        f'"{name}"',
        f'"{name}" founder OR president OR CEO',
        f'"{name}" university OR degree OR MSc OR PhD',
        f'"{name}" partnership OR MoU OR grant OR contract',
        f'"{name}" news OR interview OR award',
        f'"{name}" patent OR publication OR github',
    ]
    seen, corpus_parts, urls = set(), [], []
    for q in queries:
        print(f"  {GREY_C}searching: {q}{RESET}")
        for r in search_web(q):
            if r["url"] in seen:
                continue
            seen.add(r["url"])
            urls.append(r["url"])
            corpus_parts.append(f"{r['title']}. {r['snippet']}")
        time.sleep(0.8)  # be polite to the search endpoint
    return "\n".join(corpus_parts), urls


# ── Reporting ────────────────────────────────────────────────────────────
LEVEL_ICON = {"GREEN": "🟢", "YELLOW": "🟡", "ORANGE": "🟠", "RED": "🔴",
              "INSUFFICIENT DATA": "⚪"}
LEVEL_COLOR = {"GREEN": GREEN_C, "YELLOW": YELLOW_C, "ORANGE": YELLOW_C,
               "RED": RED_C, "INSUFFICIENT DATA": GREY_C}

def print_report(results, verdict, spec_idx, source_urls=None):
    lvl = verdict["level"]
    col = LEVEL_COLOR.get(lvl, "")
    print(f"\n  {'─' * 56}")
    print(f"  {LEVEL_ICON.get(lvl, '⚪')} {col}{BOLD}{lvl}{RESET}  |  "
          f"LARP score: {verdict['score']}/100  |  evidence coverage: {verdict['coverage']}%")
    print(f"  {'─' * 56}")
    print(f"  {verdict['summary']}")
    print(f"  Specificity index: {spec_idx} verifiable details per 100 words "
          f"({'low — vague profile' if spec_idx < 2 else 'reasonable'})\n")

    buckets = {TRIGGERED: [], PASSED: [], UNKNOWN: []}
    for fid, _name, _w, _q in FLAG_DEFS:
        r = results.get(fid)
        if r:
            buckets[r["status"]].append((fid, r))

    if buckets[TRIGGERED]:
        print(f"  {RED_C}{BOLD}🔴 TRIGGERED ({len(buckets[TRIGGERED])}):{RESET}")
        for fid, r in buckets[TRIGGERED]:
            _, name, w, _ = FLAG_BY_ID[fid]
            print(f"  [{fid}] {name}  (weight {w})")
            print(f"      {r['description']}")
            for ev in r["evidence"][:3]:
                print(f"      → {ev}")
        print()
    if buckets[PASSED]:
        print(f"  {GREEN_C}✅ PASSED ({len(buckets[PASSED])}):{RESET}")
        for fid, r in buckets[PASSED]:
            print(f"  [{fid}] {FLAG_BY_ID[fid][1]} — {r['description']}")
        print()
    if buckets[UNKNOWN]:
        print(f"  {GREY_C}❔ UNDECIDABLE ({len(buckets[UNKNOWN])}) — not counted as passed:{RESET}")
        for fid, r in buckets[UNKNOWN]:
            print(f"  {GREY_C}[{fid}] {FLAG_BY_ID[fid][1]} — {r['description']}{RESET}")
        print()
    if source_urls:
        print(f"  {GREY_C}Sources consulted: {len(source_urls)}{RESET}")
        for u in source_urls[:5]:
            print(f"  {GREY_C}  • {u}{RESET}")
    print(f"\n  ⚖️  Triage output, not a verdict. Flags mark items to verify by hand.")


def build_report_dict(target, mode, results, verdict, spec_idx, source_urls=None):
    return {
        "version": 2,
        "target": target,
        "mode": mode,
        "timestamp": datetime.now().isoformat(),
        "level": verdict["level"],
        "larp_score": verdict["score"],
        "evidence_coverage_pct": verdict["coverage"],
        "specificity_index": spec_idx,
        "summary": verdict["summary"],
        "flags": [
            {"id": fid, "name": FLAG_BY_ID[fid][1], "weight": FLAG_BY_ID[fid][2],
             "status": r["status"], "description": r["description"],
             "evidence": r["evidence"]}
            for fid, r in sorted(results.items())
        ],
        "sources": source_urls or [],
    }


def save_reports(report):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", report["target"].lower()).strip("-")[:40] or "audit"
    json_path = OUTPUT_DIR / f"{ts}_{slug}.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  💾 JSON report: {json_path}")

    vault_research = Path(VAULT_PATH) / "research"
    if vault_research.exists():
        md_path = vault_research / f"{ts[:8]}-larp-{slug}.md"
        lines = [
            "---",
            f"created: {report['timestamp'][:19]}",
            "source: larp-meter",
            "tags: [larp, osint, research]",
            "status: final",
            "---",
            "",
            f"# LARP Audit: {report['target']}",
            "",
            f"**Level:** {report['level']}  ",
            f"**LARP score:** {report['larp_score']}/100  ",
            f"**Evidence coverage:** {report['evidence_coverage_pct']}%  ",
            f"**Specificity index:** {report['specificity_index']}  ",
            f"**Summary:** {report['summary']}",
            "",
        ]
        for status, heading in ((TRIGGERED, "## 🔴 Triggered"), (PASSED, "## ✅ Passed"),
                                (UNKNOWN, "## ❔ Undecidable")):
            flags = [f for f in report["flags"] if f["status"] == status]
            if flags:
                lines.append(heading)
                lines.append("")
                for f in flags:
                    lines.append(f"- **[{f['id']}] {f['name']}** — {f['description']}")
                    for ev in f["evidence"][:3]:
                        lines.append(f"    - {ev}")
                lines.append("")
        if report["sources"]:
            lines += ["## Sources", ""] + [f"- {u}" for u in report["sources"][:15]] + [""]
        lines.append(f"*Generated by LARP Meter v2 on {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
        md_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  📝 Obsidian note: {md_path}")


# ── Modes ────────────────────────────────────────────────────────────────
def run_text_audit(target, text, as_json=False, save=True):
    results = analyze(text)
    verdict = score(results)
    spec_idx = specificity_index(text)
    report = build_report_dict(target, "text", results, verdict, spec_idx)
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"\n{'=' * 60}\n  LARP METER v2 — TEXT ANALYSIS\n  Target: {target}"
              f"\n  Words: {len(text.split())}\n{'=' * 60}")
        print_report(results, verdict, spec_idx)
    if save:
        save_reports(report)
    return report


def run_web_audit(target, as_json=False, save=True):
    print(f"\n{'=' * 60}\n  LARP METER v2 — WEB AUDIT\n  Target: {target}\n{'=' * 60}")
    print(f"  🔍 Gathering public footprint...")
    corpus, urls = gather_web_corpus(target)
    if len(corpus.split()) < 20:
        print(f"\n  {YELLOW_C}⚠ Web search returned almost nothing (engines may be blocking "
              f"automated requests from this network).{RESET}")
        print(f"  Fall back to text mode: python larp-meter.py --text \"<paste bio here>\"")
    results = analyze(corpus, source_urls=urls)
    verdict = score(results)
    spec_idx = specificity_index(corpus)
    report = build_report_dict(target, "web", results, verdict, spec_idx, source_urls=urls)
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_report(results, verdict, spec_idx, source_urls=urls)
    if save:
        save_reports(report)
    return report


def run_interactive():
    """Answer 10 structured questions; each maps directly to one flag."""
    print("\n  LARP METER v2 — INTERACTIVE MODE")
    print("  Answer from what the profile CLAIMS and what you can VERIFY.\n")

    def ask(q):
        print(f"  {q}")
        return input("  > ").strip()

    def yn_flag(q, good_is_yes=True):
        """Returns PASSED for the 'healthy' answer, TRIGGERED for the red-flag one."""
        a = ask(q + " (y/n/unknown)").lower()
        if a in ("y", "yes"):
            return PASSED if good_is_yes else TRIGGERED
        if a in ("n", "no"):
            return TRIGGERED if good_is_yes else PASSED
        return UNKNOWN

    results = {}
    results[1] = flag_result(yn_flag("[1/10] Does their education match the domain they claim expertise in?"))
    results[2] = flag_result(yn_flag("[2/10] Does their work history include real roles in that domain?"))
    partners = ask("[3/10] List claimed partners (comma-separated, empty if none):")
    owned = ask("        List organizations they founded/lead (comma-separated):")
    p_set = {p.strip().casefold() for p in partners.split(",") if p.strip()}
    o_set = {o.strip().casefold() for o in owned.split(",") if o.strip()}
    inter = p_set & o_set
    results[3] = flag_result(TRIGGERED if inter else (PASSED if p_set else UNKNOWN),
                             f"Own org listed as partner: {', '.join(inter)}" if inter else "")
    results[4] = flag_result(yn_flag("[4/10] Is the language mostly concrete rather than hype/buzzwords?"))
    results[5] = flag_result(yn_flag("[5/10] Are partnerships backed by contracts/grants (not just MoU/NDA)?"))
    results[6] = flag_result(yn_flag("[6/10] Any verifiable output — papers, patents, code, shipped product?"))
    fundraising = ask("[7/10] Are they fundraising? (y/n)").lower() in ("y", "yes")
    if fundraising:
        results[7] = flag_result(yn_flag("        Do they show customers/revenue/traction?"))
    else:
        results[7] = flag_result(UNKNOWN, "Not fundraising.")
    results[8] = flag_result(yn_flag("[8/10] Are claimed degrees tied to a named institution?"))
    results[9] = flag_result(yn_flag("[9/10] Evidence of DEEP collaboration with listed partners?"))
    results[10] = flag_result(yn_flag("[10/10] Any independent press/third-party coverage?"))

    verdict = score(results)
    print_report(results, verdict, spec_idx=0.0)


def list_audits():
    files = sorted(OUTPUT_DIR.glob("*.json"), reverse=True) if OUTPUT_DIR.exists() else []
    if not files:
        print("No audits found. Run: python larp-meter.py --text \"<bio>\"")
        return
    print(f"\n{'=' * 70}\n  RECENT LARP AUDITS\n{'=' * 70}\n")
    for f in files[:15]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            lvl = data.get("level", "?")
            icon = LEVEL_ICON.get(lvl, "⚪")
            scr = data.get("larp_score", data.get("red_flags_count", "?"))
            cov = data.get("evidence_coverage_pct", "—")
            print(f"  {icon} {data['target'][:28]:28s} | {lvl:17s} | score {scr!s:>3} | "
                  f"cov {cov!s:>3}% | {data['timestamp'][:10]}")
        except Exception:
            continue
    print()


# ── Self-test ────────────────────────────────────────────────────────────
def selftest():
    failures = []

    def check(cond, msg):
        if cond:
            print(f"  OK   {msg}")
        else:
            failures.append(msg)
            print(f"  FAIL {msg}")

    # Word-boundary matching: the v1 killer bug
    check(not has_term("she said hello via email", "ai"), "'ai' does not match 'said'/'email'")
    check(has_term("edge-AI hardware", "edge ai"), "hyphen/space variants match")
    check(has_term("Expert in artificial intelligence.", "artificial intelligence"), "multiword phrase matches")

    # Hype profile scores worse than substance profile
    hype = ("Visionary Founder and President of QuantumLeap. Building revolutionary, "
            "game-changing, groundbreaking dual-use deep tech artificial intelligence. "
            "Paradigm shift in radiation-tolerant edge AI hardware. MoU signed, NDA in "
            "place, discussions ongoing with major partners. Seeking investment — join "
            "the moonshot. MSc in public health policy. Founder of HelixNet. "
            "Partnership with HelixNet announced. Thought leader, world class team, "
            "patent pending, product coming soon.")
    real = ("CTO at Acme Robotics. MSc Electrical Engineering, Delft University of "
            "Technology (2015). Previously research scientist at imec; engineer at "
            "ASML. Co-authored 12 peer-reviewed papers "
            "(orcid.org/0000-0002-1825-0097), holder of patent US10123456. Robots "
            "deployed in production at 40 customers, generated €2.1M revenue in 2024. "
            "Code at github.com/acme/underwater-slam. Funded by an EIC grant, "
            "contract with Port of Rotterdam.")
    s_hype = score(analyze(hype))
    s_real = score(analyze(real))
    check(s_hype["score"] >= 60, f"hype profile scores high (got {s_hype['score']})")
    check(s_real["score"] <= 20, f"substantive profile scores low (got {s_real['score']})")
    check(s_hype["level"] in ("ORANGE", "RED"), f"hype level ORANGE/RED (got {s_hype['level']})")
    check(s_real["level"] == "GREEN", f"substantive level GREEN (got {s_real['level']})")

    # Self-referential detection is generic (no hardcoded names)
    check(analyze(hype)[3]["status"] == TRIGGERED,
          "self-referential partner (HelixNet) detected generically")

    # Unknown != passed: sparse text must be INSUFFICIENT DATA, not GREEN
    s_empty = score(analyze("Hello, I like dogs."))
    check(s_empty["level"] == "INSUFFICIENT DATA", "sparse text yields INSUFFICIENT DATA, not GREEN")

    # Specificity index separates the two
    check(specificity_index(real) > specificity_index(hype), "specificity index: real > hype")

    print(f"\n  {'ALL TESTS PASSED' if not failures else str(len(failures)) + ' FAILURE(S)'}")
    return 0 if not failures else 1


# ── CLI ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="LARP Meter v2 — audit self-presentation vs verifiable substance. "
                    "Triage tool for due diligence on public professional claims.")
    parser.add_argument("name", nargs="?", help="Person/company name (web-search mode), or 'list'")
    parser.add_argument("--text", "-t", help="Paste bio/pitch/About text to analyze")
    parser.add_argument("--file", "-f", help="Read text to analyze from a file")
    parser.add_argument("--interactive", "-i", action="store_true", help="Guided 10-question assessment")
    parser.add_argument("--list", action="store_true", help="List recent audits")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON to stdout")
    parser.add_argument("--no-save", action="store_true", help="Don't write report files")
    parser.add_argument("--selftest", action="store_true", help="Run built-in methodology tests")
    args = parser.parse_args()

    if args.selftest:
        sys.exit(selftest())
    if args.list or (args.name in ("list", "ls")):
        list_audits()
        return
    if args.interactive:
        run_interactive()
        return
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
        run_text_audit(args.name or Path(args.file).stem, text,
                       as_json=args.json, save=not args.no_save)
        return
    if args.text:
        run_text_audit(args.name or "pasted-text", args.text,
                       as_json=args.json, save=not args.no_save)
        return
    if args.name:
        run_web_audit(args.name, as_json=args.json, save=not args.no_save)
        return
    parser.print_help()


if __name__ == "__main__":
    main()
