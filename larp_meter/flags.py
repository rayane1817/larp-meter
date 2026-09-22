"""The flag battery.

Each flag is a function of an AuditContext returning TRIGGERED / PASSED /
UNKNOWN plus a human-readable justification. Flags are registered with a weight
and a category so the score can be broken down by dimension rather than
collapsing everything into one number.

UNKNOWN is a first-class outcome: a flag we cannot decide must never be scored
as if the subject passed it.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime

from . import TRIGGERED, PASSED, UNKNOWN
from . import extract as ex
from . import domains as dom
from . import names
from . import reconcile as rc
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
    reconciliations: list = field(default_factory=list)   # reconcile.Reconciliation, --verify only
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


def _rec_confirmed_summary(confirmed):
    """What the confirmed reconciliations establish, by the record that did it."""
    companies = [r for r in confirmed if r.kind == "company"]
    parts = []
    if companies:
        parts.append(f"the commercial register names the subject at {len(companies)} claimed "
                     f"compan{'y' if len(companies) == 1 else 'ies'}")
    if len(companies) < len(confirmed):
        parts.append("OpenAlex holds a scholarly record consistent with the claimed publication volume, "
                     "tied to the subject by a stated institution or ORCID")
    text = "; ".join(parts)
    return text[:1].upper() + text[1:]


def _openalex_search_note(ctx):
    """Describe a subject-anchored OpenAlex search that came back empty.

    `ctx.signals.get("openalex")` alone cannot tell "no --verify/--name, so
    nothing was ever queried" apart from "queried, and no matching scholarly
    record turned up" — both read as a falsy `.get()` result. That collapse
    is the specific gap BACKLOG.md's core architectural finding names: a
    profile that makes soft output claims with no identifiers ("published
    extensively in peer-reviewed venues") looks byte-identical whether or
    not anyone ever checked. Distinguishing "key absent" (never queried, or
    a network failure — see providers.OpenAlex.search's early `if not body`
    return) from "key present" (a real, completed search) lets a genuine
    negative result become visible without turning it into an accusation.

    Deliberately returns a hedged, UNKNOWN-only note, never a verdict: per
    the task brief's own live-measured OpenAlex constraints, a name-based
    author search under-matches transliterated and diacritic name variants,
    so an empty result is a lead for a human to check, not proof of
    anything. Callers must never let this string alone move a flag past
    UNKNOWN.
    """
    if "openalex" not in ctx.signals:
        return ""
    scholar = ctx.signals["openalex"]
    if scholar and scholar.get("works"):
        if ctx.signals.get("ambiguous_identity"):
            return (f" An OpenAlex author-name search matched "
                     f"{ctx.signals['ambiguous_identity']} different scholarly-record "
                     f"entities sharing this name, so the record with the most works "
                     f"could not be confirmed as this subject's — worth checking by "
                     f"hand rather than crediting on name alone.")
        return ""  # a real record was found; nothing negative to report
    return (" An OpenAlex author-name search for this subject found no scholarly "
            "record with any published works — worth checking by hand, since "
            "name-based search can under-match transliterated or diacritic name "
            "variants.")


# ── 6. Verifiable output ─────────────────────────────────────────────────
@flag(6, "No Verifiable Output", 1.5, TRACK_RECORD,
      "Is there any independently checkable output (papers, patents, code, products)?")
def f_output(ctx):
    artifacts = ex.claims_by(ctx.claims, "artifact")
    hard = [c for c in artifacts if c.subtype != "assertion"]
    building = find_terms(ctx.text, ctx.banks["building_claims"], skip_negated=True)

    # A scholarly record found independently outsettles anything the text asserts.
    # But existence is not attribution: when several distinct OpenAlex entities
    # share this name (`ambiguous_identity`), the highest-`works_count` candidate
    # is not shown to be the subject, so it cannot be credited as their output --
    # see `_openalex_search_note` for the hedge this falls through to instead.
    scholar = ctx.signals.get("openalex")
    if scholar and scholar.get("works") and not ctx.signals.get("ambiguous_identity"):
        # An OpenAlex author ID can merge several real people sharing a name
        # (see providers.MERGE_RISK_INSTITUTION_COUNT). Existence of a real
        # record is still real corroboration -- this stays PASSED -- but
        # crediting the subject with a record that likely blends several
        # careers deserves a caveat, not silent confidence.
        caution = (f" Caution: this OpenAlex record lists {scholar.get('institution_count', 'many')} "
                   f"distinct institutions -- a common signature of several researchers "
                   f"sharing a name merged under one entity ID, not a single career. Treat "
                   f"this as evidence someone by this name has published, not confirmation "
                   f"of this subject's specific institutional history."
                   if scholar.get("merge_risk") else "")
        return FlagResult(
            PASSED,
            f"Independent scholarly record found: {scholar['works']} works with "
            f"{scholar.get('citations', 0)} citations (OpenAlex)." + caution,
            [f"{scholar.get('display_name', '')} — "
             f"{', '.join(scholar.get('institutions') or []) or 'no affiliation listed'}"])

    if hard:
        # Presence only. Whether those artifacts survive verification is flag
        # 11's job; judging it here too made a single registry result move 4.0
        # of 17.0 total weight and print the same evidence twice.
        return FlagResult(PASSED, f"{len(hard)} independently checkable artifact(s) cited.",
                          [f"{c.subtype}: {c.value}" for c in hard[:4]])
    if building:
        reason = find_terms(ctx.text, ctx.banks["confidentiality_reasons"], skip_negated=True)
        if reason:
            # NDA'd, classified and proprietary work has no public artifact by
            # construction — that describes whole industries (defense, deep
            # tech, contract engineering), not deception. The absence is
            # still real, so this stays short of PASSED; it just stops being
            # an accusation.
            return FlagResult(
                UNKNOWN,
                f"Claims to be {building[0]} something with no checkable artifact, but the text "
                f"states a reason it wouldn't have one ('{reason[0]}') — proprietary, classified "
                f"or NDA-covered work is not expected to have a public DOI, patent, repository or "
                f"trial registration.",
                building[:3] + reason[:2])
        return FlagResult(
            TRIGGERED,
            f"Claims to be {building[0]} something, yet cites no checkable artifact — no DOI, "
            f"patent number, repository, trial registration or certification appears anywhere.",
            building[:3])
    if [c for c in artifacts if c.subtype == "assertion"]:
        return FlagResult(
            UNKNOWN,
            "Only unsourced assertions of output (e.g. 'peer-reviewed') — no identifiers to check."
            + _openalex_search_note(ctx))
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
    stage = find_terms(ctx.text, ctx.banks["pre_revenue_stage"], skip_negated=True)
    if stage:
        # A pre-seed/pre-product raise has no customer or revenue figure to
        # cite by definition — that's the normal, years-long state of a deep
        # tech or biotech company, not evidence nothing is happening.
        return FlagResult(
            UNKNOWN,
            f"Actively raising ('{asks[0]}') with no traction figure, but the text states this is "
            f"a {stage[0]} raise — no customer or revenue figure is expected at this stage.",
            [asks[0], stage[0]])
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
    unresolved = [i for i in institutions if i.status == ex.NOT_FOUND] if ctx.verified else []
    if unresolved:
        # This used to TRIGGER. Live-measured against ROR's real API: a
        # faculty/sub-unit of a parent university, a school merged or
        # renamed since the subject attended (London Guildhall -> London
        # Metropolitan in 2002; Supélec -> CentraleSupélec in 2015), a
        # non-research institution (ROR indexes research organizations), or
        # simply a name spelled differently than ROR's preferred label all
        # come back NOT_FOUND — the identical signal a fabricated name
        # produces. The token-overlap ROR offers against its nearest
        # candidate does not separate the two either (real institutions
        # measured at 0.25-0.67 overlap; a fabricated "Institute of Advanced
        # Fictional Studies" measured at 0.75, higher than most of them), so
        # no threshold on this signal can catch invention without also
        # accusing real institutions. A registry that cannot settle the
        # question must not accuse — see tests/test_flags.py's
        # test_a_verified_ror_miss_is_a_lead_not_an_accusation.
        return FlagResult(
            UNKNOWN,
            f"Named institution has no exact match in the Research Organization Registry: "
            f"{', '.join(i.value for i in unresolved[:3])}. ROR indexes research organizations "
            f"under their current name, so a small, non-research, merged or renamed institution "
            f"is routinely absent — worth confirming by hand, but not itself evidence of "
            f"fabrication.",
            [f"{i.value} — {i.detail}" for i in unresolved[:3]])
    # "Named in the text" and "confirmed by a registry" are different claims,
    # and this flag used to report both as the same PASSED. It read as
    # corroboration while ROR had never been contacted.
    confirmed = [i for i in institutions if i.status == ex.VERIFIED]
    if confirmed:
        return FlagResult(
            PASSED,
            f"Degree tied to an institution confirmed in ROR ({confirmed[0].value}).",
            [i.detail for i in confirmed[:2] if i.detail])
    return FlagResult(PASSED, f"Degree tied to a named institution ({institutions[0].value}), "
                              f"not itself checked against a registry.",
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
                   if not host_matches(u, b["self_published_domains"])
                   and not host_matches(u, b.get("aggregator_domains", []))]
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
    # Register-implying claims checked without any identifier (reconcile.py).
    # Only CONTRADICTED can count against the subject, and reconcile.gate()
    # is the only thing that can produce it.
    recs = list(ctx.reconciliations or [])
    rec_contra = [r for r in recs if r.outcome == rc.CONTRADICTED]
    rec_confirmed = [r for r in recs if r.outcome == rc.CONFIRMED]
    rec_notes = [r.line() for r in recs if r.outcome not in (rc.CONTRADICTED, rc.CONFIRMED)]
    if not checkable and not recs:
        return FlagResult(UNKNOWN, "No claim carries an identifier that a registry could confirm or refute.")
    if not checkable:
        if rec_contra:
            return FlagResult(
                TRIGGERED,
                f"{len(rec_contra)} claimed company role(s) contradicted by the commercial register. A "
                f"claim contradicted by its own registry is the strongest single signal this tool can "
                f"produce.",
                [r.line() for r in rec_contra[:5]])
        if rec_confirmed:
            return FlagResult(PASSED, _rec_confirmed_summary(rec_confirmed) + ".",
                              [r.line() for r in rec_confirmed[:4]])
        return FlagResult(
            UNKNOWN,
            f"{len(recs)} claim(s) looked up in a public record (commercial register, OpenAlex); none "
            f"could be confirmed or contradicted for this subject.", rec_notes[:5])
    if not ctx.verified:
        return FlagResult(UNKNOWN,
                          f"{len(checkable)} checkable identifier(s) present but no verification pass ran "
                          f"— re-run with --verify.")
    refuted = [c for c in checkable if c.status == ex.NOT_FOUND]
    mismatched = [c for c in checkable if c.status == ex.MISMATCH]
    confirmed = [c for c in checkable if c.status == ex.VERIFIED]
    if refuted or mismatched or rec_contra:
        # A refuted identifier doesn't exist, full stop — that is independent
        # of whose name was given. This must fire regardless of --name.
        bits = []
        if refuted:
            bits.append(f"{len(refuted)} identifier(s) do not exist in the relevant registry")
        if mismatched:
            bits.append(f"{len(mismatched)} exist but do not list the subject")
        if rec_contra:
            bits.append(f"{len(rec_contra)} claimed company role(s) contradicted by the commercial register")
        return FlagResult(
            TRIGGERED,
            "; ".join(bits) + ". A claim contradicted by its own registry is the strongest "
            "single signal this tool can produce.",
            ([f"{c.subtype} {c.value}: {c.detail}" for c in (refuted + mismatched)]
             + [r.line() for r in rec_contra])[:5])
    if confirmed:
        if not ctx.subject_name:
            # Without a name, `_attribute` deliberately marks every EXISTING
            # artifact VERIFIED — correct for flag 6, which only asks
            # whether something checkable exists. It is not correct here:
            # this flag's own language claims the registry "confirmed" the
            # subject, which cannot be true when attribution was never
            # checked. Before this guard, citing any real DOI/repo/patent
            # that belonged to someone else — no crafting required, just
            # omitting --name — produced "All N checked identifier(s)
            # confirmed by their registries" on the heaviest flag here.
            return FlagResult(
                UNKNOWN,
                f"{len(confirmed)} identifier(s) exist, but no --name was given so attribution was "
                f"never checked — existence alone is not confirmation. Re-run with --name.")
        # A retraction is a fact about the paper, not a contradiction of the
        # claim: the registry has just confirmed the subject wrote it. It
        # routinely lands on honest authors (a co-author's image error, a
        # publisher's duplicate-publication mistake), and this flag carries
        # the ORANGE floor, so treating it as a refutation floored honest
        # researchers -- reproduced on one who had disclosed the retraction
        # themselves, under a summary reading "a public registry contradicts
        # a specific claim". It is surfaced for a human to weigh instead.
        retracted = [c for c in confirmed if c.retracted]
        standing = [c for c in confirmed if not c.retracted]
        if retracted and not standing:
            return FlagResult(
                UNKNOWN,
                f"{len(retracted)} identifier(s) confirmed as the subject's, but every one has since "
                f"been retracted by its publisher, so none stands as corroboration. A retraction "
                f"does not by itself mean the subject misrepresented anything — check whether the "
                f"profile discloses it.",
                [f"{c.subtype} {c.value}: {c.detail}" for c in retracted[:4]])
        # A DOI cited as peer-reviewed that Crossref types as a preprint is
        # handled the same way, for the same reason: the registry cannot
        # settle it. Work later published in a journal is often cited by its
        # preprint DOI, and Crossref does not reliably link the two -- live-
        # verified on a Nature paper whose bioRxiv record carries no
        # is-preprint-of relation at all. Authorship is still confirmed.
        preprint_claimed_reviewed = [c for c in confirmed if c.is_preprint and c.claimed_peer_reviewed]
        notes = []
        if retracted:
            notes.append(f"{len(retracted)} of them ha{'s' if len(retracted) == 1 else 've'} since been "
                         f"retracted by the publisher and no longer stand{'s' if len(retracted) == 1 else ''} "
                         f"as evidence")
        if preprint_claimed_reviewed:
            notes.append(f"{len(preprint_claimed_reviewed)} cited as peer-reviewed "
                         f"{'is' if len(preprint_claimed_reviewed) == 1 else 'are'} recorded by Crossref "
                         f"as a preprint, which a later journal version would not always be linked to")
        note = (" Note: " + "; ".join(notes) + " — worth checking by hand.") if notes else ""
        flagged = retracted + [c for c in preprint_claimed_reviewed if c not in retracted]
        rest = [c for c in confirmed if c not in flagged]
        return FlagResult(PASSED, f"All {len(confirmed)} checked identifier(s) confirmed by their "
                                  f"registries.{note}",
                          [f"{c.subtype} {c.value}: {c.detail}" for c in (flagged + rest)[:4]])
    if rec_confirmed:
        return FlagResult(
            PASSED, _rec_confirmed_summary(rec_confirmed) + "; no identifier could be attributed.",
            [r.line() for r in rec_confirmed[:4]])
    # Reaching here means nothing was refuted and nothing was attributed: the
    # registries were unreachable, or they answered about existence only
    # (a repository's owner, a trial's sponsor) which cannot confirm authorship.
    return FlagResult(UNKNOWN,
                      f"{len(checkable)} identifier(s) checked, but none could be attributed to the "
                      f"subject — the registry was unreachable or publishes no authorship to compare "
                      f"against. Existence alone is not confirmation.")


# A single "since 2021 has led the team" is not evidence the profile "plausibly
# covers the whole career" — it is the single most common CV/LinkedIn shape,
# and by itself says nothing about how long the person worked before that
# date. The duration comparison below only runs when the earliest date is
# anchored to something that plausibly marks where a career could first have
# started: an education claim (the year appears in a degree/institution
# claim's own context) or an explicit founding/origin phrase ("founded the
# lab in 2009") — or when the date already accounts for the claimed duration
# on its own, in which case there is nothing to falsify either way. Without
# one of those, an unmentioned earlier career is missing information, not a
# contradiction, per BACKLOG.md's "Timeline flag accuses ordinary CVs" finding.
_CAREER_ORIGIN_RE = re.compile(
    r"\b(?:founded|co-founded|founding|established|launched|graduated|started|began)\b", re.I)


def _is_career_start_anchor(year, year_context, degree_contexts):
    if _CAREER_ORIGIN_RE.search(year_context or ""):
        return True
    return any(str(year) in ctxt for ctxt in degree_contexts)


# ── 12. Timeline implausibility (new in v3) ──────────────────────────────
@flag(12, "Timeline Implausibility", 1.5, CREDENTIALS,
      "Do the claimed dates and durations fit into a single human career?")
def f_timeline(ctx):
    exp_claims = ex.claims_by(ctx.claims, "timeline", "claimed_experience_years")
    # Only retrospective years. Forward-looking targets ("deployment is targeted
    # for 2030") are goals, not claimed history, and were being reported as a
    # fabricated timeline.
    year_claims = ex.claims_by(ctx.claims, "timeline", "year")
    year_context = {int(c.value): c.context for c in year_claims}
    years = sorted(year_context)
    if not exp_claims and not years:
        return FlagResult(UNKNOWN, "No dates or durations stated.")

    problems = []
    future = [y for y in years if y > ctx.now_year]
    if future:
        problems.append(f"date(s) stated as past but in the future: {', '.join(map(str, future))}")

    parsed = [n for n in (ex.experience_years(c.value) for c in exp_claims) if n]
    duration_tested = False
    if parsed and years:
        claimed = max(parsed)
        earliest = min(years)
        available = ctx.now_year - earliest
        degree_contexts = [c.context for c in ex.claims_by(ctx.claims, "degree")]
        if available >= claimed or _is_career_start_anchor(earliest, year_context[earliest], degree_contexts):
            duration_tested = True
            # +3 years of slack: careers can predate the earliest date a bio happens to mention
            if claimed > available + 3:
                problems.append(
                    f"claims {claimed} years of experience, but the earliest date anywhere in the "
                    f"profile is {earliest} — at most ~{available} years are accounted for")

    if problems:
        return FlagResult(TRIGGERED, "Timeline does not add up: " + "; ".join(problems) + ".", problems)
    if duration_tested:
        return FlagResult(PASSED, "Claimed durations are consistent with the dates given.")
    if parsed and years:
        return FlagResult(UNKNOWN,
                          "A claimed duration cannot be tested against a single date that isn't "
                          "tied to an education or founding event — an earlier, undated part of "
                          "the career is missing information, not a contradiction.")
    return FlagResult(UNKNOWN, "Not enough dated detail to test the timeline.")


# ── 13. Self-applied doctoral title without a matching credential ────────
# Longer alternatives first: with "Prof" tried before "Professor", Python's re
# would still backtrack to the longer one when the short match's lookahead
# fails, but ordering it this way makes the intent readable without relying
# on that. Case-insensitive: an all-lowercase bio or an all-caps resume
# header self-applies the title exactly as much as title case does, and the
# name-adjacency check right below already gates the false-positive risk —
# case was never doing any of that work.
_DOCTORAL_HONORIFIC_RE = re.compile(r"(?<!\w)(?:Professor|Prof|Dr)\.?(?=\s)", re.I)

# Full, unambiguous doctoral-degree PHRASES that DEGREE_RE's own level
# vocabulary does not cover. Deliberately excludes bare abbreviations (MD,
# EdD, DBA, DPhil, PsyD, DSc): "MD" collides with the Maryland postal
# abbreviation and similar short tokens too often to scan a whole profile
# for safely — a real physician whose bio never spells out "Doctor of
# Medicine" or "MD" set off from their own name will not be recognised here.
# That is a narrower, deliberate gap; the alternative (matching bare "MD"
# anywhere in the text) risks the opposite and worse failure — accusing an
# honest person of a title they do hold.
_SUPPLEMENTARY_DOCTORATE_RE = re.compile(
    r"\bDoctor\s+of\s+(?:Medicine|Education|Business Administration|Psychology|Philosophy)\b",
    re.I)

_DOCTORATE_MARKERS = ("phd", "ph.d", "doctorate", "doctor")


@flag(13, "Self-Applied Doctoral Title Without a Matching Credential", 1.5, CREDENTIALS,
      "Is 'Dr.'/'Prof.' self-applied to a name with no doctorate anywhere in the stated education?")
def f_title_inflation(ctx):
    if not ctx.subject_name:
        return FlagResult(UNKNOWN, "No subject name given, so a self-applied title cannot be tied "
                                   "to anyone in particular. Pass --name.")
    name_tokens = names.tokens(ctx.subject_name)
    if not name_tokens:
        return FlagResult(UNKNOWN, "Subject name has no usable tokens to anchor a title claim to.")

    # A title only counts as SELF-applied when it sits next to the subject's
    # own name. "Grants coordinated by Dr. Schilt" must not be read as the
    # subject calling themselves Dr., however confident the surrounding text.
    claimed_near = None
    for m in _DOCTORAL_HONORIFIC_RE.finditer(ctx.text):
        # Confined to the rest of the same line: a raw character window can
        # bleed past the name into the next field ("Dr. Jane Doe\nPresident
        # of...") and quote a truncated, unrelated word as if it were part
        # of the title claim.
        line_end = ctx.text.find("\n", m.end())
        tail = ctx.text[m.end(): line_end if line_end != -1 else len(ctx.text)][:60]
        if any(re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", names.normalize(tail))
               for t in name_tokens):
            claimed_near = f"{m.group(0)} {tail.strip()}"
            break

    if not claimed_near:
        return FlagResult(UNKNOWN, "No 'Dr.'/'Prof.' title is self-applied to the subject's own "
                                   "name; nothing to check.")

    degrees = ex.claims_by(ctx.claims, "degree", "degree")
    has_doctorate = (
        any(marker in d.value.casefold() for d in degrees for marker in _DOCTORATE_MARKERS)
        or bool(_SUPPLEMENTARY_DOCTORATE_RE.search(ctx.text)))

    if has_doctorate:
        return FlagResult(PASSED, f"Self-applied title ('{claimed_near}') is supported by a "
                                  f"stated doctorate.")
    # Absence of a listed doctorate is not the same as absence of education —
    # only the second is undecidable. A profile that describes real education
    # in real detail and conspicuously stops short of a doctorate, while the
    # subject addresses themselves as Dr./Prof. regardless, is a contradiction
    # sourced entirely from the subject's own text — no registry required.
    if not degrees:
        return FlagResult(
            UNKNOWN,
            f"Self-applies '{claimed_near}', but no education is described anywhere in the text — "
            f"not enough to judge whether the title is supported.")
    return FlagResult(
        TRIGGERED,
        f"Self-applies '{claimed_near}', but the entire stated education "
        f"({', '.join(d.value for d in degrees[:3])}) contains no doctorate — the highest "
        f"credential listed does not support the title claimed.",
        [d.value for d in degrees[:4]])


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
