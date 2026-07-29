"""The flag battery.

Each flag is a function of an AuditContext returning TRIGGERED / PASSED /
UNKNOWN plus a human-readable justification. Flags are registered with a weight
and a category so the score can be broken down by dimension rather than
collapsing everything into one number.

UNKNOWN is a first-class outcome: a flag we cannot decide must never be scored
as if the subject passed it.
"""

from dataclasses import dataclass, field
from datetime import datetime

from . import TRIGGERED, PASSED, UNKNOWN
from . import extract as ex
from . import domains as dom
from .matching import (find_terms, count_occurrences, find_non_overlapping,
                       host_matches, load_banks)

CREDENTIALS = "credentials"
TRACK_RECORD = "track record"
RELATIONSHIPS = "relationships"
RHETORIC = "rhetoric"
VALIDATION = "validation"


@dataclass
class FlagResult:
    status: str
    description: str = ""
    evidence: list = field(default_factory=list)


@dataclass
class AuditContext:
    text: str
    claims: list = field(default_factory=list)
    source_urls: list = field(default_factory=list)
    subject_name: str = ""
    banks: dict = field(default_factory=load_banks)
    verified: bool = False          # did a verification pass actually run?
    signals: dict = field(default_factory=dict)   # structured facts from providers
    now_year: int = field(default_factory=lambda: datetime.now().year)
    _domain_profile: dict = field(default=None, repr=False)

    @property
    def word_count(self):
        return len(self.text.split())

    @property
    def domain_profile(self):
        if self._domain_profile is None:
            self._domain_profile = dom.profile(self.text)
        return self._domain_profile


REGISTRY = []


def flag(fid, name, weight, category, question, floor=None):
    """Register a flag.

    `floor` marks a flag whose evidence is categorically stronger than the
    rest: when it triggers, the verdict cannot come out better than that level,
    however much unverified self-assertion passes elsewhere.
    """
    def deco(fn):
        REGISTRY.append({"id": fid, "name": name, "weight": weight,
                         "category": category, "question": question,
                         "floor": floor, "fn": fn})
        return fn
    return deco


# ── 1. Education vs claimed domain ───────────────────────────────────────
@flag(1, "Education ≠ Claimed Domain", 1.5, CREDENTIALS,
      "Does educational background match the claimed field of expertise?")
def f_education(ctx):
    prof = ctx.domain_profile
    claimed, markers = dom.claimed_domain(ctx.text, prof)
    if not claimed:
        return FlagResult(UNKNOWN, "No clear domain of expertise is claimed; nothing to match against.")

    credentials = dom.supporting_domains(ctx.text, "credentials", prof)
    degrees = ex.claims_by(ctx.claims, "degree", "degree")
    if not credentials and not degrees:
        return FlagResult(UNKNOWN,
                          f"Presents as working in {dom.label(claimed)}, but the material contains "
                          f"no education information at all.")

    supported, via = dom.is_supported(claimed, credentials)
    if supported:
        detail = (f"training in {dom.label(via)}" if via == claimed
                  else f"training in the adjacent field of {dom.label(via)}")
        return FlagResult(PASSED, f"Claims {dom.label(claimed)} and holds {detail}.",
                          credentials.get(via, [])[:3])

    if claimed not in dom.CREDENTIAL_GATED:
        return FlagResult(PASSED,
                          f"{dom.label(claimed).capitalize()} is an open-entry field where formal "
                          f"credentials are not expected; no mismatch can be inferred.")

    if not credentials:
        return FlagResult(UNKNOWN,
                          f"A degree is mentioned but its field is unclear, so it cannot be matched "
                          f"against the claimed {dom.label(claimed)} expertise.")

    # Working ON a domain is not claiming to BE in it. A technology journalist,
    # a recruiter for engineers or a lawyer advising chip companies all name
    # technical subject matter without asserting technical expertise. If their
    # credentials fit the occupation their own roles describe, there is no gap.
    #
    # This does not apply to someone holding a senior title: "Chief Medical
    # Officer" is a claim to be in the domain, not to report on it.
    if not find_terms(ctx.text, ctx.banks["leadership_titles"]):
        roles = dom.supporting_domains(ctx.text, "roles", prof)
        for role_domain in roles:
            if role_domain == claimed:
                continue
            fits, via_role = dom.is_supported(role_domain, credentials)
            if fits:
                return FlagResult(
                    PASSED,
                    f"Works in {dom.label(role_domain)} with training in {dom.label(via_role)}. "
                    f"{dom.label(claimed).capitalize()} terms appear as subject matter rather "
                    f"than as a claim of expertise.")

    others = ", ".join(dom.label(d) for d in sorted(credentials))
    return FlagResult(
        TRIGGERED,
        f"Presents as an authority in {dom.label(claimed)} "
        f"({', '.join(markers[:3])}), but every credential on record is in {others} — a field that "
        f"does not qualify someone for the claimed one.",
        [f"{dom.label(d)}: {', '.join(v[:3])}" for d, v in sorted(credentials.items())][:3])


# ── 2. Experience vs declared title ──────────────────────────────────────
@flag(2, "Experience ≠ Declared Title", 1.5, CREDENTIALS,
      "Does work history support the self-declared role?")
def f_experience(ctx):
    prof = ctx.domain_profile
    titles = find_terms(ctx.text, ctx.banks["leadership_titles"])
    claimed, _markers = dom.claimed_domain(ctx.text, prof)
    if not titles or not claimed:
        return FlagResult(UNKNOWN, "No senior title tied to a specific domain to test.")

    roles = dom.supporting_domains(ctx.text, "roles", prof)
    if not roles:
        return FlagResult(UNKNOWN, "No prior roles described, so the title cannot be checked "
                                   "against a work history.")

    supported, via = dom.is_supported(claimed, roles)
    if supported:
        return FlagResult(PASSED,
                          f"Work history includes {dom.label(via)} roles "
                          f"({', '.join(roles[via][:3])}), consistent with the claimed domain.")

    if claimed not in dom.CREDENTIAL_GATED:
        return FlagResult(PASSED,
                          f"Leads in {dom.label(claimed)}, an open-entry field; a background in "
                          f"{', '.join(dom.label(d) for d in sorted(roles))} is not disqualifying.")

    others = ", ".join(f"{dom.label(d)} ({', '.join(v[:2])})" for d, v in sorted(roles.items()))
    return FlagResult(
        TRIGGERED,
        f"Holds the title '{titles[0]}' in {dom.label(claimed)}, but the entire visible work "
        f"history sits in {others} — not one role in the domain being led.",
        [f"{dom.label(d)}: {', '.join(v[:3])}" for d, v in sorted(roles.items())][:3])


# ── 3. Self-referential partners ─────────────────────────────────────────
@flag(3, "Self-Referential Partners", 2.0, RELATIONSHIPS,
      "Are the claimed 'partners' the subject's own organizations?")
def f_self_referential(ctx):
    overlap, owned, partners = ex.owned_and_partner_orgs(ctx.claims)
    if overlap:
        return FlagResult(
            TRIGGERED,
            f"Organizations the subject leads are also presented as independent 'partners': "
            f"{', '.join(sorted(set(overlap))[:4])}. This is circular validation — the endorsement "
            f"and the endorsee are the same party.",
            sorted(set(overlap)))
    if partners and owned:
        return FlagResult(PASSED, "Claimed partners are distinct from the organizations the subject leads.")
    return FlagResult(UNKNOWN, "No partnership claims, or no ownership information to cross-check them against.")


# ── 4. Buzzword density ──────────────────────────────────────────────────
@flag(4, "Buzzword Density", 1.0, RHETORIC,
      "Is the language hype-heavy relative to its length?")
def f_buzzwords(ctx):
    if not ctx.word_count:
        return FlagResult(UNKNOWN, "No text to assess.")
    distinct, hits = find_non_overlapping(ctx.text, ctx.banks["buzzwords"], skip_negated=True)

    # A hard length cliff made two versions of the same profile land on opposite
    # sides of the coverage floor over a one-word difference. Density is only
    # unreliable on a short text when there is hype in it to measure; if there
    # is none, the absence is answer enough at any length.
    if ctx.word_count < 25:
        if not distinct:
            return FlagResult(PASSED, "No hype language present.")
        return FlagResult(UNKNOWN, "Text too short to judge whether the hype is disproportionate.")

    density = hits / ctx.word_count * 100
    if len(distinct) >= 4 and density >= 2.0:
        return FlagResult(
            TRIGGERED,
            f"{len(distinct)} distinct buzzwords at {density:.1f} per 100 words "
            f"(e.g. {', '.join(distinct[:5])}) — hype outweighs specifics.",
            distinct)
    return FlagResult(PASSED, f"Buzzword density is normal ({density:.1f} per 100 words).")


# ── 5. Vague vs concrete partnerships ────────────────────────────────────
@flag(5, "Vague Partnerships Only", 1.0, RELATIONSHIPS,
      "Are collaborations only MoUs/NDAs rather than contracts or grants?")
def f_vague_partnerships(ctx):
    vague = find_terms(ctx.text, ctx.banks["vague_partnership"], skip_negated=True)
    concrete = find_terms(ctx.text, ctx.banks["concrete_partnership"], skip_negated=True)
    if not vague and not concrete:
        return FlagResult(UNKNOWN, "No partnership or deal language to classify.")
    if len(vague) >= 2 and len(vague) > len(concrete):
        return FlagResult(
            TRIGGERED,
            f"Deal language is overwhelmingly non-binding ({', '.join(vague[:4])}) against "
            f"{len(concrete)} concrete term(s). Nothing here commits a counterparty to anything.",
            vague)
    return FlagResult(PASSED, f"Concrete deal terms present ({', '.join(concrete[:4]) or 'no vague-only pattern'}).")


# ── 6. Verifiable output ─────────────────────────────────────────────────
@flag(6, "No Verifiable Output", 1.5, TRACK_RECORD,
      "Is there any independently checkable output (papers, patents, code, products)?")
def f_output(ctx):
    artifacts = ex.claims_by(ctx.claims, "artifact")
    hard = [c for c in artifacts if c.subtype != "assertion"]
    building = find_terms(ctx.text, ctx.banks["building_claims"], skip_negated=True)

    # A scholarly record found independently outsettles anything the text asserts.
    scholar = ctx.signals.get("openalex")
    if scholar and scholar.get("works"):
        return FlagResult(
            PASSED,
            f"Independent scholarly record found: {scholar['works']} works with "
            f"{scholar.get('citations', 0)} citations (OpenAlex).",
            [f"{scholar.get('display_name', '')} — "
             f"{', '.join(scholar.get('institutions') or []) or 'no affiliation listed'}"])

    if hard:
        # Presence only. Whether those artifacts survive verification is flag
        # 11's job; judging it here too made a single registry result move 4.0
        # of 17.0 total weight and print the same evidence twice.
        return FlagResult(PASSED, f"{len(hard)} independently checkable artifact(s) cited.",
                          [f"{c.subtype}: {c.value}" for c in hard[:4]])
    if building:
        return FlagResult(
            TRIGGERED,
            f"Claims to be {building[0]} something, yet cites no checkable artifact — no DOI, "
            f"patent number, repository, trial registration or certification appears anywhere.",
            building[:3])
    if [c for c in artifacts if c.subtype == "assertion"]:
        return FlagResult(UNKNOWN, "Only unsourced assertions of output (e.g. 'peer-reviewed') — no identifiers to check.")
    return FlagResult(UNKNOWN, "No output is claimed, so there is nothing to verify.")


# ── 7. Fundraising without traction ──────────────────────────────────────
@flag(7, "Fundraising Without Traction", 1.5, TRACK_RECORD,
      "Is money being raised with zero evidence of customers or revenue?")
def f_fundraising(ctx):
    asks = find_terms(ctx.text, ctx.banks["funding_ask"], skip_negated=True)
    traction_terms = find_terms(ctx.text, ctx.banks["traction"], skip_negated=True)
    traction_claims = [c for c in ex.claims_by(ctx.claims, "traction") if not c.negated]
    if not asks:
        return FlagResult(UNKNOWN, "Not visibly fundraising; the flag does not apply.")
    if traction_claims:
        return FlagResult(PASSED, "Fundraising alongside quantified traction.",
                          [c.value for c in traction_claims[:3]])
    if traction_terms:
        return FlagResult(PASSED, f"Fundraising with stated traction ({', '.join(traction_terms[:3])}).")
    return FlagResult(
        TRIGGERED,
        f"Actively raising ('{asks[0]}') with no customer, revenue or usage figure of any kind.")


# ── 8. Credential verifiability ──────────────────────────────────────────
@flag(8, "Unverifiable Credentials", 1.0, CREDENTIALS,
      "Are claimed degrees tied to a named, checkable institution?")
def f_credentials(ctx):
    degrees = ex.claims_by(ctx.claims, "degree", "degree")
    # Only an institution attached to the degree itself counts. Binding a degree
    # to any institution named elsewhere cleared this flag for "holds an MBA;
    # spent two years at the Fraunhofer Institute" — an employer, not a school.
    institutions = ex.claims_by(ctx.claims, "degree", "degree_institution")
    mentioned = ex.claims_by(ctx.claims, "degree", "mentioned_institution")
    if not degrees:
        return FlagResult(UNKNOWN, "No degree is claimed.")
    if not institutions:
        if mentioned:
            return FlagResult(
                UNKNOWN,
                f"A degree is claimed and institutions are named "
                f"({', '.join(m.value for m in mentioned[:2])}), but none is tied to the degree, "
                f"so the credential cannot be matched to a school from this text alone.")
        # Failure to parse an institution is not concealment. Institution names
        # this extractor cannot read are common outside English, and penalising
        # them would score people on how their university spells itself.
        return FlagResult(
            UNKNOWN,
            f"Degree claimed ({', '.join(d.value for d in degrees[:2])}) with no institution "
            f"identified in the text — not enough to judge either way.")
    # Only an actual registry lookup can contradict; without --verify the
    # status is UNCHECKED and says nothing.
    fake = [i for i in institutions if i.status == ex.NOT_FOUND] if ctx.verified else []
    if fake:
        # ROR indexes research organizations. A vocational school, a small
        # private college or a non-research institute can be legitimately
        # absent, so this is a lead to check by hand — not proof of invention.
        return FlagResult(
            TRIGGERED,
            f"Named institution has no match in the Research Organization Registry: "
            f"{', '.join(i.value for i in fake[:3])}. Worth confirming directly — ROR indexes "
            f"research organizations, so a small or non-research institution may be absent "
            f"legitimately.",
            [f"{i.value} — {i.detail}" for i in fake[:3]])
    return FlagResult(PASSED, f"Degree tied to a named institution ({institutions[0].value}).",
                      [i.detail for i in institutions[:2] if i.detail])


# ── 9. Logo wall ─────────────────────────────────────────────────────────
@flag(9, "Logo Wall Syndrome", 1.0, RELATIONSHIPS,
      "Many partner names but no evidence of deep collaboration?")
def f_logo_wall(ctx):
    _overlap, _owned, partners = ex.owned_and_partner_orgs(ctx.claims)
    deep = find_terms(ctx.text, ctx.banks["deep_collab"], skip_negated=True)
    distinct = sorted({ex.norm_org(p) for p in partners})
    if len(distinct) >= 4 and not deep:
        return FlagResult(
            TRIGGERED,
            f"{len(distinct)} partner organizations named with no sign of substantive joint work "
            f"(no joint papers, integrations or co-development).", partners[:6])
    if deep:
        return FlagResult(PASSED, f"Evidence of deep collaboration ({', '.join(deep[:3])}).")
    if distinct:
        return FlagResult(PASSED, "Only a handful of partners named; no logo-wall pattern.")
    return FlagResult(UNKNOWN, "No partner list to assess.")


# ── 10. Independent validation ───────────────────────────────────────────
@flag(10, "No Independent Validation", 1.0, VALIDATION,
      "Any third-party coverage not originating from the subject?")
def f_validation(ctx):
    b = ctx.banks
    markers = find_terms(ctx.text, b["external_validation"], skip_negated=True)
    outlets = find_terms(ctx.text, b["press_outlets"], skip_negated=True)
    independent = [u for u in ctx.source_urls
                   if not host_matches(u, b["self_published_domains"])]
    controlled = len(ctx.source_urls) - len(independent)

    # An encyclopedia article about the subject is unambiguous third-party coverage.
    about = ctx.signals.get("wikipedia_about_subject") or []
    if about:
        return FlagResult(PASSED,
                          f"Independent encyclopedic coverage exists "
                          f"(Wikipedia: {', '.join(about[:2])}).", about[:3])

    if outlets or independent:
        ev = outlets[:3] or independent[:3]
        note = (f" ({len(independent)} independent of {len(ctx.source_urls)} sources)"
                if ctx.source_urls else "")
        return FlagResult(PASSED, f"Third-party validation present{note}.", ev)
    # Silence from a blocked or unreachable search layer is not silence about
    # the subject. Only conclude "no independent coverage" if we could look.
    if ctx.signals.get("search_ok") is False:
        return FlagResult(UNKNOWN, "The search layer could not reach its sources, so the absence "
                                   "of third-party coverage says nothing.")

    if ctx.source_urls and not independent:
        return FlagResult(
            TRIGGERED,
            f"All {controlled} sources found sit on platforms the subject controls "
            f"(LinkedIn, own site, self-publishing). Pure echo chamber — no outside party "
            f"has independently written about this.", ctx.source_urls[:4])
    if markers:
        return FlagResult(PASSED, f"Claims third-party recognition ({', '.join(markers[:3])}).", markers[:3])
    if ctx.word_count >= 40 and find_terms(ctx.text, b["leadership_titles"] + b["tech_claims"]):
        return FlagResult(
            TRIGGERED,
            "Substantial claims with zero third-party validation — no press, award or independent "
            "coverage is referenced anywhere.")
    return FlagResult(UNKNOWN, "Too little material to expect validation signals.")


# ── 11. Contradicted verifiable claim (new in v3) ────────────────────────
@flag(11, "Contradicted Verifiable Claim", 2.5, TRACK_RECORD,
      "Did a public registry actively refute a specific claim?",
      floor="ORANGE")
def f_contradicted(ctx):
    # Hard identifiers only. An institution missing from ROR is ambiguous (the
    # registry is not exhaustive), so it is handled by flag 8 at a lower weight
    # rather than counted here as a contradiction.
    checkable = [c for c in ctx.claims if c.subtype in
                 ("doi", "orcid", "github", "arxiv", "nct", "patent")]
    if not checkable:
        return FlagResult(UNKNOWN, "No claim carries an identifier that a registry could confirm or refute.")
    if not ctx.verified:
        return FlagResult(UNKNOWN,
                          f"{len(checkable)} checkable identifier(s) present but no verification pass ran "
                          f"— re-run with --verify.")
    refuted = [c for c in checkable if c.status == ex.NOT_FOUND]
    mismatched = [c for c in checkable if c.status == ex.MISMATCH]
    confirmed = [c for c in checkable if c.status == ex.VERIFIED]
    if refuted or mismatched:
        bits = []
        if refuted:
            bits.append(f"{len(refuted)} identifier(s) do not exist in the relevant registry")
        if mismatched:
            bits.append(f"{len(mismatched)} exist but do not list the subject")
        return FlagResult(
            TRIGGERED,
            "; ".join(bits) + ". A claim contradicted by its own registry is the strongest "
            "single signal this tool can produce.",
            [f"{c.subtype} {c.value}: {c.detail}" for c in (refuted + mismatched)[:5]])
    if confirmed:
        return FlagResult(PASSED, f"All {len(confirmed)} checked identifier(s) confirmed by their registries.",
                          [f"{c.subtype} {c.value}: {c.detail}" for c in confirmed[:4]])
    return FlagResult(UNKNOWN, "Verification ran but every registry was unreachable — nothing decided.")


# ── 12. Timeline implausibility (new in v3) ──────────────────────────────
@flag(12, "Timeline Implausibility", 1.5, CREDENTIALS,
      "Do the claimed dates and durations fit into a single human career?")
def f_timeline(ctx):
    exp_claims = ex.claims_by(ctx.claims, "timeline", "claimed_experience_years")
    # Only retrospective years. Forward-looking targets ("deployment is targeted
    # for 2030") are goals, not claimed history, and were being reported as a
    # fabricated timeline.
    years = sorted({int(c.value) for c in ex.claims_by(ctx.claims, "timeline", "year")})
    if not exp_claims and not years:
        return FlagResult(UNKNOWN, "No dates or durations stated.")

    problems = []
    future = [y for y in years if y > ctx.now_year]
    if future:
        problems.append(f"date(s) stated as past but in the future: {', '.join(map(str, future))}")

    parsed = [n for n in (ex.experience_years(c.value) for c in exp_claims) if n]
    if parsed and years:
        claimed = max(parsed)
        earliest = min(years)
        available = ctx.now_year - earliest
        # +3 years of slack: careers can predate the earliest date a bio happens to mention
        if claimed > available + 3:
            problems.append(
                f"claims {claimed} years of experience, but the earliest date anywhere in the "
                f"profile is {earliest} — at most ~{available} years are accounted for")

    if problems:
        return FlagResult(TRIGGERED, "Timeline does not add up: " + "; ".join(problems) + ".", problems)
    if parsed and years:
        return FlagResult(PASSED, "Claimed durations are consistent with the dates given.")
    return FlagResult(UNKNOWN, "Not enough dated detail to test the timeline.")


FLAG_BY_ID = {f["id"]: f for f in REGISTRY}
TOTAL_WEIGHT = sum(f["weight"] for f in REGISTRY)


def evaluate(ctx):
    """Run every flag. Returns {id: FlagResult}."""
    results = {}
    for spec in REGISTRY:
        try:
            res = spec["fn"](ctx)
        except Exception as exc:  # one broken flag must not kill the audit
            res = FlagResult(UNKNOWN, f"evaluator error: {type(exc).__name__}: {exc}")
        results[spec["id"]] = res
    return results
