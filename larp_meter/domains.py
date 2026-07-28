"""Domain taxonomy: generalizes credential-matching beyond "tech LARP".

v2 and early v3 hardcoded a single archetype — someone with a non-technical
degree claiming deep-tech expertise. That made the instrument blind to a finance
LARP, a medical LARP or a legal LARP, and left honest non-technical
professionals unscoreable (every credential flag came back UNKNOWN).

Here each domain carries three marker sets:
    claims      — what the subject says they DO or BUILD
    credentials — training that qualifies someone for it
    roles       — job titles that constitute real experience in it

A mismatch is only evidence when the claimed domain is CREDENTIAL-GATED. In
open-entry fields (business, marketing, design, policy) no formal credential is
expected, so a "mismatch" there says nothing about honesty — flagging it would
punish career changers and self-taught practitioners.
"""

import re

from .matching import find_terms

TECHNOLOGY = "technology"
SCIENCE = "science"
MEDICINE = "medicine"
FINANCE = "finance"
LAW = "law"
POLICY = "policy"
BUSINESS = "business"
MARKETING = "marketing"
DESIGN = "design"
EDUCATION = "education"

DOMAINS = {
    TECHNOLOGY: {
        "label": "technology & engineering",
        "claims": [
            "artificial intelligence", "machine learning", "neural network", "edge ai",
            "deep tech", "hardware", "semiconductor", "software platform", "algorithm",
            "robotics", "satellite", "spacecraft", "rocket", "quantum computing",
            "cybersecurity", "blockchain", "photonics", "radiation tolerant",
            "embedded systems", "cloud infrastructure", "data pipeline", "dual use",
        ],
        "credentials": [
            "computer science", "engineering", "electrical engineering",
            "mechanical engineering", "software engineering", "informatics",
            "aerospace engineering", "nuclear engineering", "electronics",
            "telecommunications", "robotics", "data science", "mathematics",
            "applied mathematics", "materials science",
        ],
        "roles": [
            "engineer", "developer", "programmer", "software architect",
            "chief technology officer", "technical lead", "principal engineer",
            "lead developer", "systems architect", "devops", "data engineer",
        ],
    },
    SCIENCE: {
        "label": "science & research",
        "claims": [
            "peer reviewed research", "scientific discovery", "laboratory research",
            "clinical study", "genomics", "biotechnology", "materials research",
            "computational modelling", "experimental validation", "trl",
        ],
        # Fields only. "phd"/"doctorate"/"postdoc" are degree LEVELS, not
        # subjects: listing them here meant a doctorate in any subject counted
        # as a science credential — and since science is adjacent to technology,
        # any PhD whatsoever cleared the deep-tech credential check.
        "credentials": [
            "physics", "chemistry", "biology", "bioinformatics", "biochemistry",
            "neuroscience", "computational science", "molecular biology",
            "astrophysics", "genetics", "ecology",
        ],
        "roles": [
            "research scientist", "researcher", "postdoctoral", "principal investigator",
            "lab director", "professor", "lecturer", "research fellow",
        ],
    },
    MEDICINE: {
        "label": "medicine & clinical practice",
        "claims": [
            "clinical treatment", "patient care", "diagnosis", "therapeutic",
            "medical device", "surgery", "clinical trial", "drug development",
            "diagnostic assay", "health outcomes",
        ],
        "credentials": [
            "medicine", "medical degree", "nursing", "pharmacy", "public health",
            "epidemiology", "physiotherapy", "clinical psychology", "dentistry",
        ],
        "roles": [
            "physician", "doctor", "surgeon", "nurse", "clinician", "pharmacist",
            "medical director", "consultant physician", "general practitioner",
        ],
    },
    FINANCE: {
        "label": "finance & investment",
        "claims": [
            "asset management", "portfolio management", "hedge fund", "venture capital",
            "private equity", "trading strategy", "quantitative finance",
            "investment thesis", "fund management", "market making", "derivatives",
            "wealth management", "capital markets",
        ],
        # An MBA lives in `business`, which is adjacent to finance — adjacency
        # carries the transfer, so the marker must not be duplicated here.
        "credentials": [
            "finance", "economics", "accounting", "actuarial science", "cfa",
            "financial engineering", "econometrics",
        ],
        # Deliberately no bare "analyst": data/policy/business analysts are not
        # finance experience, and generic tokens leak across domains.
        "roles": [
            "financial analyst", "investment analyst", "equity analyst",
            "portfolio manager", "trader", "investment banker", "fund manager",
            "chief financial officer", "controller", "auditor", "actuary",
            "financial advisor", "wealth manager",
        ],
    },
    LAW: {
        "label": "law & regulation",
        "claims": [
            "legal representation", "litigation", "regulatory compliance",
            "intellectual property law", "contract law", "arbitration",
            "legal opinion", "patent prosecution",
        ],
        "credentials": ["law", "juris doctor", "llm", "llb", "bar admission", "legal studies"],
        "roles": ["lawyer", "attorney", "solicitor", "barrister", "general counsel",
                  "legal counsel", "paralegal", "judge", "compliance officer"],
    },
    POLICY: {
        "label": "policy & advocacy",
        "claims": [
            "policy reform", "public affairs", "advocacy campaign", "regulatory affairs",
            "stakeholder engagement", "position paper", "governance framework",
            "public consultation", "lobbying", "patient advocacy", "health policy",
        ],
        "credentials": [
            "public policy", "political science", "international relations",
            "european studies", "public administration", "governance", "sociology",
        ],
        "roles": [
            "policy officer", "secretary general", "director general", "lobbyist",
            "public affairs manager", "advocacy lead", "diplomat", "ambassador",
            "board member", "programme manager",
        ],
    },
    BUSINESS: {
        "label": "business & management",
        "claims": [
            "business strategy", "operations", "go to market", "supply chain",
            "profit and loss", "organisational transformation", "management consulting",
            "scaling operations",
        ],
        "credentials": ["business administration", "mba", "management", "commerce",
                        "entrepreneurship", "operations research"],
        # No bare "manager"/"consultant" — they appear in every other domain's
        # job titles ("brand manager", "clinical consultant") and would let any
        # background masquerade as business experience.
        "roles": ["chief executive", "chief operating officer", "operations director",
                  "general manager", "management consultant", "project manager",
                  "account manager", "business development"],
    },
    MARKETING: {
        "label": "marketing & communications",
        "claims": ["brand strategy", "growth marketing", "content strategy",
                   "public relations", "campaign", "audience growth", "social media strategy"],
        "credentials": ["marketing", "communication studies", "journalism",
                        "media studies", "advertising"],
        "roles": ["marketer", "communications manager", "brand manager",
                  "content strategist", "press officer", "copywriter", "spokesperson"],
    },
    DESIGN: {
        "label": "design & creative",
        "claims": ["user experience", "product design", "industrial design",
                   "architecture", "design system", "creative direction"],
        "credentials": ["design", "fine arts", "architecture", "industrial design",
                        "graphic design", "humanities"],
        "roles": ["designer", "art director", "creative director", "architect",
                  "illustrator", "ux researcher"],
    },
    EDUCATION: {
        "label": "education & training",
        "claims": ["curriculum", "pedagogy", "training programme", "learning outcomes",
                   "educational reform"],
        "credentials": ["education", "pedagogy", "teaching", "educational science"],
        "roles": ["teacher", "instructor", "trainer", "headmaster", "dean",
                  "education officer"],
    },
}

# Domains where formal training is genuinely expected. A credential gap only
# counts as a signal here; elsewhere it would just penalise self-taught people.
CREDENTIAL_GATED = {TECHNOLOGY, SCIENCE, MEDICINE, FINANCE, LAW}

# Neighbouring fields whose training legitimately transfers.
_ADJACENT = {
    TECHNOLOGY: {SCIENCE},
    SCIENCE: {TECHNOLOGY, MEDICINE},
    MEDICINE: {SCIENCE, POLICY},
    FINANCE: {BUSINESS},
    BUSINESS: {FINANCE, MARKETING},
    MARKETING: {BUSINESS, DESIGN},
    DESIGN: {MARKETING},
    LAW: {POLICY},
    POLICY: {LAW, MEDICINE},
    EDUCATION: {SCIENCE},
}
ADJACENT = {d: set(v) for d, v in _ADJACENT.items()}
for _d, _peers in _ADJACENT.items():          # make adjacency symmetric
    for _p in _peers:
        ADJACENT.setdefault(_p, set()).add(_d)
for _d in DOMAINS:
    ADJACENT.setdefault(_d, set())


# A credential only counts inside an educational context. Without this, a bare
# domain noun in an ordinary sentence ("we run a quantitative finance fund")
# reads as a qualification and silently clears the credential flag.
# Word-boundary anchored throughout: without \b, "read" matched inside
# "already" and "spread", fabricating an education context out of ordinary
# prose and letting any nearby field word count as a qualification.
_EDU_TRIGGER_RE = re.compile(
    r"\b(?:(?i:msc|bsc|phd|mba|meng|beng|llm|llb|master's|master of|master in|"
    r"bachelor's|bachelor of|bachelor in|doctorate|doctor of|degree|diploma|"
    r"studied|studying|graduated|graduate of|alumnus|alumna|educated at|"
    r"trained as|trained at|postdoctoral|postdoc|read\s+\w+\s+at)"
    r"|(?:MA|BA|MS|BS|MD|JD))\b")
_SENTENCE_SPLIT_RE = re.compile(r"[.;\n•|]")


def education_spans(text):
    """Sentence-level windows around education markers."""
    spans = []
    for m in _EDU_TRIGGER_RE.finditer(text):
        left = max((mm.end() for mm in _SENTENCE_SPLIT_RE.finditer(text, 0, m.start())), default=0)
        right_m = _SENTENCE_SPLIT_RE.search(text, m.end())
        right = right_m.start() if right_m else min(len(text), m.end() + 160)
        spans.append(text[left:right])
    return spans


def education_text(text):
    return " ; ".join(education_spans(text))


def _hits(text, domain, facet, edu_text=None):
    if facet == "credentials":
        text = edu_text if edu_text is not None else education_text(text)
    # "I do not build technology" is a disclaimer, not a claim to expertise.
    return find_terms(text, DOMAINS[domain][facet], skip_negated=True)


def profile(text):
    """Marker hits per domain per facet: {domain: {claims: [...], credentials: [...], roles: [...]}}"""
    edu = education_text(text)
    out = {}
    for domain in DOMAINS:
        facets = {facet: _hits(text, domain, facet, edu_text=edu)
                  for facet in ("claims", "credentials", "roles")}
        if any(facets.values()):
            out[domain] = facets
    return out


def _top(prof, facet, minimum=1):
    ranked = sorted(prof.items(), key=lambda kv: len(kv[1][facet]), reverse=True)
    for domain, facets in ranked:
        if len(facets[facet]) >= minimum:
            return domain, facets[facet]
    return None, []


def claimed_domain(text, prof=None):
    """The domain the subject presents themselves as working in, with its markers."""
    prof = profile(text) if prof is None else prof
    return _top(prof, "claims")


def supporting_domains(text, facet, prof=None):
    """Every domain with at least one marker for `facet` ('credentials' or 'roles')."""
    prof = profile(text) if prof is None else prof
    return {d: f[facet] for d, f in prof.items() if f[facet]}


def is_supported(claimed, supporters):
    """Does any supporting domain match the claim, directly or as an adjacent field?"""
    if claimed in supporters:
        return True, claimed
    for d in supporters:
        if d in ADJACENT.get(claimed, set()):
            return True, d
    return False, None


def label(domain):
    return DOMAINS.get(domain, {}).get("label", domain or "unknown")
