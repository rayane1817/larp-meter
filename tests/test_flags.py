import unittest

from larp_meter import TRIGGERED, PASSED, UNKNOWN
from larp_meter import extract as ex
from larp_meter.flags import AuditContext, evaluate
from larp_meter.matching import load_banks

BANKS = load_banks(path="/nonexistent")


def ctx_for(text, **kw):
    return AuditContext(text=text, claims=ex.extract_claims(text), banks=BANKS, **kw)


def status_of(text, flag_id, **kw):
    return evaluate(ctx_for(text, **kw))[flag_id].status


class TestIndividualFlags(unittest.TestCase):
    def test_education_mismatch(self):
        text = ("Building radiation-tolerant edge AI hardware for satellites. "
                "MSc in European public health policy.")
        self.assertEqual(status_of(text, 1), TRIGGERED)

    def test_education_match_passes(self):
        text = "Building satellite hardware. MSc Electrical Engineering."
        self.assertEqual(status_of(text, 1), PASSED)

    def test_education_unknown_when_no_tech_claim(self):
        text = "I run a bakery in Antwerp and I studied public health."
        self.assertEqual(status_of(text, 1), UNKNOWN)

    def test_self_referential_partner(self):
        text = "Founder of AetherLink. Announced a partnership with AetherLink this quarter."
        self.assertEqual(status_of(text, 3), TRIGGERED)

    def test_buzzword_density_needs_both_variety_and_rate(self):
        one_word_long_text = ("We are innovative. " + "The team ships software every week. " * 30)
        self.assertEqual(status_of(one_word_long_text, 4), PASSED)

    def test_buzzword_density_triggers_on_hype(self):
        text = ("A revolutionary, groundbreaking, world class paradigm shift — truly "
                "disruptive, cutting edge, next generation thought leadership for a "
                "visionary team building the future of everything today.")
        self.assertEqual(status_of(text, 4), TRIGGERED)

    def test_vague_partnerships(self):
        text = ("MoU signed and NDA in place, discussions ongoing with several groups. "
                "Exploratory talks continue.")
        self.assertEqual(status_of(text, 5), TRIGGERED)

    def test_concrete_partnerships_pass(self):
        text = "Funded by a research grant; contract signed with a hospital; revenue growing."
        self.assertEqual(status_of(text, 5), PASSED)

    def test_no_verifiable_output(self):
        text = "We are building a next generation platform. Patent pending. Coming soon."
        self.assertEqual(status_of(text, 6), TRIGGERED)

    def test_verifiable_output_passes(self):
        text = "We are building tooling; code at github.com/acme/slam and patent US10123456."
        self.assertEqual(status_of(text, 6), PASSED)

    def test_fundraising_without_traction(self):
        text = "Seeking investment for our deep tech venture. Building the future."
        self.assertEqual(status_of(text, 7), TRIGGERED)

    def test_fundraising_with_traction_passes(self):
        text = "Seeking investment. We have 40 customers and recurring revenue."
        self.assertEqual(status_of(text, 7), PASSED)

    def test_fundraising_flag_unknown_when_not_raising(self):
        text = "We build robots for ports and have done so for a decade with our team."
        self.assertEqual(status_of(text, 7), UNKNOWN)

    def test_degree_without_institution_is_undecidable_not_an_accusation(self):
        """Failure to parse an institution is not concealment. Institution names
        this extractor cannot read are common outside English, and triggering on
        them scored people on how their university spells itself."""
        self.assertEqual(status_of("I hold an MSc in public health policy.", 8), UNKNOWN)

    def test_degree_with_institution_passes(self):
        self.assertEqual(
            status_of("MSc Electrical Engineering, Delft University of Technology.", 8), PASSED)

    def test_logo_wall(self):
        text = ("Partnership with Orion Systems. Partnership with Caldera Group. "
                "Collaboration with Ridgeway Institute. Alliance with Northwind Labs. "
                "Consortium with Solaris Federation.")
        self.assertEqual(status_of(text, 9), TRIGGERED)

    def test_deep_collaboration_passes_logo_wall(self):
        text = ("Partnership with Orion Systems. Partnership with Caldera Group. "
                "Collaboration with Ridgeway Institute. Alliance with Northwind Labs. "
                "We co-authored a joint paper with each of them.")
        self.assertEqual(status_of(text, 9), PASSED)

    def test_echo_chamber_sources_trigger_validation_flag(self):
        text = "Founder building quantum satellites, seeking partners for our venture today."
        c = ctx_for(text, source_urls=["https://linkedin.com/in/x", "https://medium.com/@x"])
        self.assertEqual(evaluate(c)[10].status, TRIGGERED)

    def test_independent_sources_pass_validation_flag(self):
        text = "Founder building quantum satellites, seeking partners for our venture today."
        c = ctx_for(text, source_urls=["https://linkedin.com/in/x", "https://reuters.com/article/y"])
        self.assertEqual(evaluate(c)[10].status, PASSED)

    def test_validation_triggers_at_exactly_40_words(self):
        """Mutation-tested (2026-08-17): `ctx.word_count >= 40` survived as
        `> 40` with the suite still green — nothing pinned the boundary
        itself, only values comfortably past it. A profile landing on
        exactly 40 words with real leadership/tech language and zero
        press must still get the substantial-claims warning, not silently
        fall through to 'too little material to expect validation
        signals' one word early."""
        text = " ".join(["founder"] + ["building"] * 38 + ["hardware"])
        self.assertEqual(len(text.split()), 40)
        self.assertEqual(status_of(text, 10), TRIGGERED)

    def test_a_mid_length_bio_below_40_words_stays_undecided(self):
        """Mutation-tested (2026-09-17): `ctx.word_count >= 40` survived as
        `>= 20` with the suite still green. The two existing pins only
        anchor the extremes — a 9-word one-liner (well below any
        threshold) and exactly 40 words (right at the real one) — neither
        rules out a lowered boundary in between. A 29-word bio with a
        real leadership/tech claim and no press must still read as 'too
        little material to expect validation signals', not get
        prematurely condemned for a silence that a genuinely short
        profile has no room to fill."""
        text = ("Founder building satellite hardware to serve customers around the world "
                "every single day of the year with our growing team right now across "
                "every region we operate in today.")
        self.assertEqual(len(text.split()), 29)
        self.assertEqual(status_of(text, 10), UNKNOWN)

    def test_buzzword_density_and_variety_trigger_at_the_exact_thresholds(self):
        """Mutation-tested (2026-08-17): both `len(distinct) >= 4` and
        `density >= 2.0` survived as `>` with the suite green — every
        existing fixture sat comfortably past the cut, none exactly on
        it. A profile landing on precisely 4 distinct buzzwords at
        precisely 2.0 per 100 words must still TRIGGER, not fall through
        to 'density is normal' by one word or one buzzword."""
        text = "synergy paradigm disruption pioneering " + "team " * 196
        self.assertEqual(len(text.split()), 200)
        self.assertEqual(status_of(text, 4), TRIGGERED)

    def test_buzzword_flag_does_not_use_the_short_text_carve_out_at_25_words(self):
        """Mutation-tested (2026-08-17): `ctx.word_count < 25` survived as
        `<= 25` with the suite green. At exactly 25 words the flag must
        already be judged on ordinary density, not routed into the
        short-text 'too short to judge' carve-out meant only for text
        shorter than that."""
        text = " ".join(["synergy"] + ["team"] * 24)
        self.assertEqual(len(text.split()), 25)
        self.assertEqual(status_of(text, 4), PASSED)

    def test_vague_partnerships_trigger_at_exactly_two_with_zero_concrete(self):
        """Mutation-tested (2026-08-17): `len(vague) >= 2` survived as `> 2`
        with the suite green — every fixture used 3+ vague terms."""
        text = "We have an MoU in place and an NDA signed with several partners."
        self.assertEqual(status_of(text, 5), TRIGGERED)

    def test_vague_partnerships_do_not_trigger_on_a_tie_with_concrete(self):
        """Mutation-tested (2026-08-17): `len(vague) > len(concrete)` survived
        as `>=` with the suite green. At a 2-vague/2-concrete tie the flag
        must PASS, not accuse someone of an "overwhelmingly non-binding"
        pattern their own concrete terms equally balance out."""
        text = ("We have an MoU in place and an NDA signed, alongside a "
                "signed contract and grant funding.")
        self.assertEqual(status_of(text, 5), PASSED)

    def test_logo_wall_triggers_at_exactly_four_partners(self):
        """Mutation-tested (2026-08-17): `len(distinct) >= 4` survived as
        `> 4` with the suite green — the existing fixture used 5."""
        text = ("Partnership with Orion Systems. Partnership with Caldera Group. "
                "Collaboration with Ridgeway Institute. Alliance with Northwind Labs.")
        self.assertEqual(status_of(text, 9), TRIGGERED)

    def test_unsourced_assertion_alone_does_not_pass_as_checkable_output(self):
        """Mutation-tested (2026-08-17): dropping the `c.subtype != "assertion"`
        filter from flag 6's `hard` artifact list survived with the suite
        green. `assertion` claims come from SOFT_EVIDENCE phrases like
        'peer-reviewed' that carry no identifier any registry could ever
        look up. Letting them count as a checkable artifact is exactly the
        top-priority evasion this tool exists to close: a fabricator who
        writes vague, identifier-free output language would PASS the flag
        meant to catch that, instead of landing in the UNKNOWN bucket
        that flags 'nothing here is actually checkable'."""
        text = "My research is peer-reviewed and widely cited in the field."
        self.assertEqual(status_of(text, 6), UNKNOWN)

    def test_credential_flag_triggers_on_a_verified_ror_miss(self):
        """Mutation-tested (2026-08-17): comparing against `ex.UNCHECKED`
        instead of `ex.NOT_FOUND` survived with the suite green — every
        flag-8 test in this file only ever exercises the PASSED/UNKNOWN
        branches (no test here ever sets `verified=True` with a
        registry-refuted institution), even though this is the exact
        dead-ROR-check bug shape this repo has hit before: the TRIGGERED
        branch existing in the source without any test ever reaching it
        through `evaluate()`."""
        text = "PhD in Astrophysics from the Institute of Advanced Fictional Studies."
        claims = ex.extract_claims(text)
        for cl in claims:
            if cl.subtype == "degree_institution":
                cl.status, cl.detail = ex.NOT_FOUND, "ROR has no match for this name."
        c = ctx_for(text, verified=True)
        c.claims = claims
        self.assertEqual(evaluate(c)[8].status, TRIGGERED)

    def test_timeline_does_not_trigger_at_exactly_the_three_year_slack_boundary(self):
        """Mutation-tested (2026-08-17): `claimed > available + 3` survived
        as `>=` with the suite green. At exactly the documented 3-year
        slack the timeline must PASS, not accuse someone whose claimed
        experience lands precisely on the tolerance the flag itself
        grants."""
        text = "9 years of experience in robotics. Founded the lab in 2020."
        c = ctx_for(text, now_year=2026)
        self.assertEqual(evaluate(c)[12].status, PASSED)

    def test_timeline_does_not_treat_the_current_year_as_a_future_date(self):
        """Mutation-tested (2026-08-17): `y > ctx.now_year` survived as `>=`
        with the suite green. A date claimed as the current year is not
        "stated as past but in the future" — it is today."""
        text = ("6 years of experience in robotics. Deployed our system in 2026. "
                "Founded the lab in 2020.")
        c = ctx_for(text, now_year=2026)
        self.assertEqual(evaluate(c)[12].status, PASSED)


class TestContradictionFlag(unittest.TestCase):
    def test_unknown_without_verification_pass(self):
        text = "Our work is at 10.1038/s41586-020-2649-2 and github.com/acme/slam."
        self.assertEqual(status_of(text, 11), UNKNOWN)

    def test_unknown_when_nothing_checkable(self):
        text = "We are building an innovative platform for the future of work."
        self.assertEqual(status_of(text, 11), UNKNOWN)

    def test_triggers_on_refuted_identifier(self):
        text = "Our published work: 10.1038/fake-doi-here."
        c = ctx_for(text, verified=True)
        for claim in c.claims:
            if claim.subtype == "doi":
                claim.status, claim.detail = ex.NOT_FOUND, "Crossref has no record of this DOI."
        self.assertEqual(evaluate(c)[11].status, TRIGGERED)

    def test_passes_when_all_confirmed(self):
        text = "Our published work: 10.1038/s41586-020-2649-2."
        c = ctx_for(text, verified=True, subject_name="Ada Lovelace")
        for claim in c.claims:
            if claim.subtype == "doi":
                claim.status, claim.detail = ex.VERIFIED, "Paper exists and lists the subject."
        self.assertEqual(evaluate(c)[11].status, PASSED)

    def test_verified_without_a_name_is_not_confirmation(self):
        """Without --name, _attribute marks every EXISTING artifact VERIFIED
        by design (verify.py's own docstring: correct for flag 6, which only
        asks whether something checkable exists). This flag's own language
        claims the registry 'confirmed' the subject — that must not fire
        when attribution was never actually checked. Before this guard,
        citing any real DOI/repo/patent that belonged to someone else, with
        no --name at all, produced a PASSED 'confirmed by their registries'
        on the heaviest flag in the registry — no crafting required, just
        an omitted flag. This test used to pass with the OLD (buggy)
        behaviour because ctx_for() never set subject_name at all — the
        original version of test_passes_when_all_confirmed was accidentally
        exercising this exact bug rather than a real confirmation."""
        text = "Our published work: 10.1038/s41586-020-2649-2."
        c = ctx_for(text, verified=True)  # no subject_name
        for claim in c.claims:
            if claim.subtype == "doi":
                claim.status, claim.detail = ex.VERIFIED, "Paper exists (Ashish Vaswani)."
        result = evaluate(c)[11]
        self.assertEqual(result.status, UNKNOWN)
        self.assertNotIn("confirmed", result.description.casefold())

    def test_refuted_identifier_triggers_even_without_a_name(self):
        """A refuted identifier doesn't exist at all — that's independent of
        whose name was given, and must not be swallowed by the no-name
        guard that protects the CONFIRMED branch."""
        text = "Our published work: 10.1038/fake-doi-here."
        c = ctx_for(text, verified=True)  # no subject_name
        for claim in c.claims:
            if claim.subtype == "doi":
                claim.status, claim.detail = ex.NOT_FOUND, "Crossref has no record of this DOI."
        self.assertEqual(evaluate(c)[11].status, TRIGGERED)

    def test_unreachable_registries_decide_nothing(self):
        text = "Our published work: 10.1038/s41586-020-2649-2."
        c = ctx_for(text, verified=True)
        for claim in c.claims:
            if claim.subtype == "doi":
                claim.status, claim.detail = ex.UNCHECKABLE, "Crossref unreachable"
        self.assertEqual(evaluate(c)[11].status, UNKNOWN)

    def test_triggers_on_a_pure_mismatch_with_nothing_refuted(self):
        """Mutation-tested (2026-08-17): `if refuted or mismatched:` survived
        as `if refuted:` with the suite green — every existing test for
        this branch uses NOT_FOUND, none uses a claim that is only
        MISMATCHED (exists, but lists someone else). This is the flag
        with this tool's only severity floor; a MISMATCH-only profile
        silently falling through to the catch-all UNKNOWN would drop the
        ORANGE floor for a claim the registry actively contradicts."""
        text = "Our published work: 10.1038/s41586-020-2649-2."
        c = ctx_for(text, verified=True, subject_name="Someone Else")
        for claim in c.claims:
            if claim.subtype == "doi":
                claim.status, claim.detail = ex.MISMATCH, \
                    "Record lists different authors; subject not credited."
        result = evaluate(c)[11]
        self.assertEqual(result.status, TRIGGERED)
        self.assertIn("do not list the subject", result.description)


class TestTimelineFlag(unittest.TestCase):
    def test_impossible_experience_span(self):
        text = ("40 years of experience in aerospace. MSc Aerospace Engineering, "
                "Fictional Technical University, 2019.")
        self.assertEqual(status_of(text, 12), TRIGGERED)

    def test_plausible_span_passes(self):
        text = "10 years of experience in robotics. MSc Robotics, 2012. Founded the lab in 2015."
        self.assertEqual(status_of(text, 12), PASSED)

    def test_unknown_without_dates(self):
        self.assertEqual(status_of("I build robots and enjoy it a great deal.", 12), UNKNOWN)


class TestTitleInflationFlag(unittest.TestCase):
    """Flag 13. One positive fixture proving it fires on the archetype it was
    built for is not enough — every case here that must NOT fire is exactly
    as load-bearing as the one that must, per the discipline that v1's
    hard-coded flag was supposed to teach: a heuristic that only has a
    positive test is a heuristic nobody checked for false accusations."""

    def test_title_without_a_doctorate_triggers(self):
        """The motivating case: a self-applied 'Dr.' with an education list
        that stops at Master's level."""
        text = ("Dr. Anke Verstraeten, President of Example AG.\n\n"
                "Education: BASc Physiotherapy, MBA Healthcare Management, "
                "MSc European Public Health.")
        self.assertEqual(status_of(text, 13, subject_name="Anke Verstraeten"), TRIGGERED)

    def test_no_title_claimed_is_unknown_not_passed(self):
        """No title claimed means the flag does not apply — matches the
        'not visibly fundraising' pattern of flag 7, not a clean bill of
        health, since there is nothing here to have gotten right."""
        text = "Anke Verstraeten, President of Example AG. MSc European Public Health."
        self.assertEqual(status_of(text, 13, subject_name="Anke Verstraeten"), UNKNOWN)

    def test_title_with_a_phd_passes(self):
        text = "Dr. Ada Lovelace holds a PhD in Mathematics from Cambridge."
        self.assertEqual(status_of(text, 13, subject_name="Ada Lovelace"), PASSED)

    def test_title_with_doctor_of_medicine_passes(self):
        """The supplementary phrase list, not DEGREE_RE, has to catch this —
        DEGREE_RE has no MD-level token at all."""
        text = "Dr. Jane Okafor is a practicing physician (Doctor of Medicine, Lagos)."
        self.assertEqual(status_of(text, 13, subject_name="Jane Okafor"), PASSED)

    def test_title_claimed_with_no_education_at_all_is_unknown(self):
        """Absence of a doctorate is a finding; absence of ANY education
        information is not — matches flag 8's discipline exactly."""
        text = "Dr. Marcus Vane is a visionary leader transforming the industry."
        self.assertEqual(status_of(text, 13, subject_name="Marcus Vane"), UNKNOWN)

    def test_another_persons_title_is_not_the_subjects(self):
        """The core safety property: a title attached to someone ELSE named
        in the text — a named collaborator, an advisor — must never be read
        as the subject calling themselves Dr. This is what keeps the flag
        from becoming a second copy of the v1 mistake, just aimed at whoever
        happens to be quoted nearby."""
        text = ("Jan Peeters, coordinated by Dr. Maria Santos at the regional "
                "institute. MSc Public Administration.")
        self.assertEqual(status_of(text, 13, subject_name="Jan Peeters"), UNKNOWN)

    def test_no_subject_name_is_unknown(self):
        """Without a name to anchor to, a title anywhere in the text cannot
        be attributed to anyone in particular."""
        text = "Dr. Someone, President of Example AG. MBA Healthcare Management."
        self.assertEqual(status_of(text, 13), UNKNOWN)

    def test_professor_title_recognised_alongside_doctor(self):
        text = "Prof. Kwame Mensah, PhD in Physics, University of Ghana."
        self.assertEqual(status_of(text, 13, subject_name="Kwame Mensah"), PASSED)

    def test_a_legitimate_networked_professional_does_not_falsely_trigger(self):
        """Adjacent-but-honest counter-fixture: someone with several small,
        real titles and no doctorate, who simply never calls themselves Dr.
        This must stay UNKNOWN (no title claimed) rather than being swept up
        by a heuristic tuned too broadly."""
        text = ("Anke Verstraeten, Secretary of the Regional History Society; "
                "Chairman, Community Sailing Trust; Advisory Committee member, "
                "Patient Alliance Europe. BASc Physiotherapy.")
        self.assertEqual(status_of(text, 13, subject_name="Anke Verstraeten"), UNKNOWN)


class TestMutationSurvivorsFlags(unittest.TestCase):
    """Regression tests closing gaps found by a mutation sweep of flags.py.

    Each test below corresponds to a mutation that the suite did NOT catch —
    the mutated code passed every existing test. A surviving mutation means
    the behaviour was real but unasserted, so each of these was written to
    fail on the mutated code and pass on the restored code.
    """

    # ── flag 11: the heaviest flag, weight 2.5, floor=ORANGE ────────
    def test_a_mismatched_identifier_is_a_contradiction(self):
        """Mutation `if refuted or mismatched:` -> `if refuted:` survived.

        Nothing covered MISMATCH reaching flag 11 -- only NOT_FOUND. Yet
        MISMATCH is the classic fabricator case: the artifact is real, it
        just isn't theirs. Losing it would have silently dropped exactly
        the signal this flag exists to raise, on the tool's strongest
        verdict."""
        c = ctx_for("Our work: 10.1038/s41586-020-2649-2.",
                    verified=True, subject_name="Ada Lovelace")
        for claim in c.claims:
            if claim.subtype == "doi":
                claim.status = ex.MISMATCH
                claim.detail = "Paper exists but does NOT list the subject."
        result = evaluate(c)[11]
        self.assertEqual(result.status, TRIGGERED)
        self.assertIn("do not list the subject", result.description)

    # ── flag 12: timeline, a fairness-critical flag ─────────────────
    def test_the_current_year_is_not_a_future_date(self):
        """Mutation `y > ctx.now_year` -> `y >= ctx.now_year` survived.

        Anyone stating the current year as a past fact ('started in 2026'
        written during 2026) would be accused of an impossible timeline --
        a false accusation triggered by nothing but the calendar."""
        c = ctx_for("2 years of experience in robotics. Started in 2026.")
        c.now_year = 2026
        self.assertEqual(evaluate(c)[12].status, PASSED)

    def test_career_slack_is_exactly_three_years(self):
        """Mutation `claimed > available + 3` -> `claimed > available`
        survived. The slack exists because a career can predate the
        earliest date a bio happens to mention; removing it accuses
        honest people whose bios simply don't list their first job.
        Pinned at the exact boundary: 20 claimed against 17 available
        is the largest gap the slack still permits."""
        c = ctx_for("20 years of experience in robotics. Founded the lab in 2009.")
        c.now_year = 2026          # 2026-2009 = 17 available, +3 slack = 20
        self.assertEqual(evaluate(c)[12].status, PASSED)

        beyond = ctx_for("21 years of experience in robotics. Founded the lab in 2009.")
        beyond.now_year = 2026     # one year past what the slack allows
        self.assertEqual(evaluate(beyond)[12].status, TRIGGERED)

    # ── flag 8: only a real lookup may contradict ───────────────────
    def test_an_unverified_run_cannot_contradict_an_institution(self):
        """Mutation dropping the `if ctx.verified` guard survived, because
        without a verify pass an institution claim's status stays UNCHECKED
        and the fake-list is empty either way -- the guard is unreachable
        defensively in production. It still encodes a load-bearing
        invariant ('only an actual registry lookup can contradict'), so it
        is pinned here against a future change that sets NOT_FOUND without
        a verification pass having run."""
        c = ctx_for("MSc Physics, Fictional University.", verified=False)
        for claim in c.claims:
            if claim.subtype == "degree_institution":
                claim.status = ex.NOT_FOUND
        self.assertNotEqual(evaluate(c)[8].status, TRIGGERED)

    # ── flag 4: buzzword density boundaries ─────────────────────────
    def _buzz_text(self, distinct_words, total_words):
        filler = ("the team ships code on a regular basis every week "
                  "without fail and also ")
        pad = (filler * 40).split()[:total_words - len(distinct_words.split())]
        return distinct_words + " " + " ".join(pad)

    def test_density_of_exactly_two_per_hundred_words_triggers(self):
        """Mutation `density >= 2.0` -> `density > 2.0` survived: nothing
        landed density exactly on the threshold."""
        text = self._buzz_text("synergy paradigm disruption visionary", 200)
        self.assertEqual(len(text.split()), 200)
        self.assertEqual(status_of(text, 4), TRIGGERED)

    def test_three_distinct_buzzwords_is_below_the_variety_floor(self):
        """Mutation `len(distinct) >= 4` -> `>= 3` survived. High density
        alone must not trigger: the flag requires variety AND rate, so a
        text repeating a few stock phrases is not condemned as hype."""
        text = "synergy paradigm disruption. " + "we ship code weekly. " * 12
        self.assertEqual(status_of(text, 4), PASSED)

    # ── flag 5: vague vs concrete partnerships ──────────────────────
    def test_equal_vague_and_concrete_terms_do_not_trigger(self):
        """Mutation `len(vague) > len(concrete)` -> `>=` survived. A
        profile with as many concrete terms as vague ones is not
        'overwhelmingly non-binding' and must not be flagged."""
        text = "We signed an MoU and an NDA. We also have a grant and a contract in place."
        self.assertEqual(status_of(text, 5), PASSED)

    def test_a_single_vague_term_alone_does_not_trigger(self):
        """Mutation `and` -> `or` in the trigger condition survived. One
        MoU mentioned in passing is not a pattern of non-binding deals."""
        text = "We signed an MoU last year and have been building steadily since then."
        self.assertEqual(status_of(text, 5), PASSED)

    # ── flag 9: logo wall boundary ──────────────────────────────────
    def test_three_partners_is_below_the_logo_wall_threshold(self):
        """Mutation `len(distinct) >= 4` -> `>= 3` survived. Naming a few
        genuine partners is ordinary; the flag targets a wall of logos."""
        text = ("Partnership with Orion Systems. Partnership with Caldera Group. "
                "Collaboration with Ridgeway Institute.")
        self.assertEqual(status_of(text, 9), PASSED)

    # ── flag 10: independent validation ─────────────────────────────
    def test_a_short_bio_is_not_condemned_for_lacking_press(self):
        """Mutation `ctx.word_count >= 40` -> `>= 0` survived. A one-line
        bio has no room to cite press coverage; treating that silence as
        'zero third-party validation' punishes brevity, not deception."""
        self.assertEqual(status_of("Founder building quantum satellites for a living.", 10),
                         UNKNOWN)

    # ── flag 6: scholarly record must actually contain works ────────
    def test_an_empty_scholarly_record_is_not_verifiable_output(self):
        """Mutation dropping `and scholar.get("works")` survived. An
        OpenAlex entity that resolves but lists zero works is not evidence
        of output -- passing on it would be the same 'existence is not
        attribution' error the verify layer is built to avoid."""
        c = ctx_for("We are building a next generation platform. Patent pending.",
                    signals={"openalex": {"works": 0, "citations": 0, "display_name": "X"}})
        self.assertEqual(evaluate(c)[6].status, TRIGGERED)

    # ── flag 6: a queried-and-empty OpenAlex search must become visible ──
    #
    # This is the task brief's own named first step on the core architectural
    # gap: "a profile that makes strong output claims while carrying zero
    # checkable identifiers should [at least] make the '0 works found' case
    # visible in the report, even as an UNKNOWN-with-evidence line." Before
    # this, ctx.signals["openalex"] was read with a bare `.get()`, which
    # cannot tell "never queried" apart from "queried, found nothing" --
    # both come back None -- so a real negative search result and a plain
    # `--verify`-less run produced byte-identical UNKNOWN text.
    def test_a_negative_openalex_search_is_surfaced_on_the_assertion_fallback(self):
        """The 'Dr. Marcus Vane... published extensively in peer-reviewed
        venues' archetype from BACKLOG.md's core-gap finding: no hard
        artifact, no building language, just a soft 'peer-review claim'
        assertion. Once a subject-anchored OpenAlex search has actually run
        and found no matching scholarly record, that fact belongs in the
        report -- still UNKNOWN, never escalated to TRIGGERED on absence
        alone, but no longer silently indistinguishable from never having
        looked."""
        c = ctx_for("Over 15 years, I have published extensively in peer-reviewed venues.",
                    signals={"openalex": None})
        result = evaluate(c)[6]
        self.assertEqual(result.status, UNKNOWN)
        self.assertIn("OpenAlex", result.description)

    def test_no_openalex_query_leaves_the_assertion_message_unchanged(self):
        """Negative control for the above: when `--verify`/`--name` never
        ran a search at all (the ordinary default-mode case, or the key
        genuinely absent), ctx.signals has no "openalex" key. The message
        must stay exactly as it always was -- mentioning a search that
        never happened would be worse than saying nothing.

        Pinned as an exact match, not just `assertNotIn("OpenAlex", ...)`:
        a first version of this test used assertNotIn and did not notice
        when a hand-mutated `_openalex_search_note` let `ctx.signals["openalex"]`
        raise `KeyError` on the very case this test exists to guard -- the
        per-flag exception guard in `evaluate()` swallowed it into a generic
        "evaluator error: KeyError: 'openalex'" UNKNOWN, which also doesn't
        contain the substring "OpenAlex" (capitalised) and so slipped past
        the loose assertion. Exact-matching the real message closes that
        gap."""
        c = ctx_for("Over 15 years, I have published extensively in peer-reviewed venues.")
        result = evaluate(c)[6]
        self.assertEqual(result.status, UNKNOWN)
        self.assertEqual(
            result.description,
            "Only unsourced assertions of output (e.g. 'peer-reviewed') — no identifiers to check.")

    def test_a_zero_work_openalex_match_is_treated_the_same_as_no_match(self):
        """A resolved OpenAlex author entity that lists zero works carries
        the same "nothing found" meaning as no entity matching at all --
        both must reach the same evidence-bearing UNKNOWN, not silently
        fall back to the plain unqualified message just because the dict
        key happened to be present with a value."""
        c = ctx_for("Over 15 years, I have published extensively in peer-reviewed venues.",
                    signals={"openalex": {"works": 0, "citations": 0, "display_name": "X"}})
        result = evaluate(c)[6]
        self.assertEqual(result.status, UNKNOWN)
        self.assertIn("OpenAlex", result.description)

    def test_negative_openalex_search_never_escalates_past_unknown(self):
        """Fairness guard, straight from the task brief's live-measured
        OpenAlex constraints: a name-based author search can under-match
        transliterated or diacritic name variants, and even a genuine zero
        result must never be reported as a standalone finding. Absence of
        a matching record is a lead for a human to check, never proof --
        this must never reach TRIGGERED on its own, no matter how the rest
        of the text reads."""
        c = ctx_for("Over 15 years, I have published extensively in peer-reviewed venues.",
                    signals={"openalex": None})
        self.assertEqual(evaluate(c)[6].status, UNKNOWN)

    # ── flag 2: both a title AND a domain are required ──────────────
    def test_a_title_without_a_claimed_domain_is_undecidable(self):
        """Mutation `not titles or not claimed` -> `and` survived. With
        `and`, a title-holder who names no domain no longer bails out
        early; execution falls through to `is_supported(None, roles)` and
        the open-entry escape hatch, and the flag reports PASSED -- a
        clean bill of health on a question it never actually tested.

        The fixture matters here: a subject with NO prior roles hits the
        second guard (`if not roles`) and returns UNKNOWN either way, so
        it cannot distinguish the two. This one has a title and real
        roles but no claimed domain, which is the only shape that
        separates them (verified: UNKNOWN originally, PASSED mutated)."""
        text = "I am the CEO. I worked as a policy officer and a board member for years."
        self.assertEqual(status_of(text, 2), UNKNOWN)

    # ── evaluate(): one broken flag must not sink the audit ─────────
    def test_a_crashing_flag_is_contained_and_reported(self):
        """Mutation narrowing `except Exception` survived because no flag
        in the suite ever raises. The guard is what keeps a single broken
        evaluator from destroying an entire audit, so it is pinned with a
        flag that deliberately raises."""
        from larp_meter.flags import REGISTRY

        def boom(ctx):
            raise ValueError("deliberate")

        spec = {"id": 999, "name": "Exploding", "weight": 1.0, "category": "rhetoric",
                "question": "?", "floor": None, "fn": boom}
        REGISTRY.append(spec)
        try:
            results = evaluate(ctx_for("Some ordinary profile text here."))
        finally:
            REGISTRY.remove(spec)
        self.assertEqual(results[999].status, UNKNOWN)
        self.assertIn("evaluator error", results[999].description)


class TestRobustness(unittest.TestCase):
    def test_every_flag_survives_empty_text(self):
        results = evaluate(ctx_for(""))
        self.assertEqual(len(results), 13)
        for fid, r in results.items():
            self.assertIn(r.status, (TRIGGERED, PASSED, UNKNOWN), fid)
            self.assertNotIn("evaluator error", r.description, f"flag {fid} crashed")

    def test_every_flag_survives_adversarial_text(self):
        weird = "🚀" * 50 + "\n\n" + "MSc " * 40 + "<script>alert(1)</script> " + "ai " * 100
        results = evaluate(ctx_for(weird))
        for fid, r in results.items():
            self.assertNotIn("evaluator error", r.description, f"flag {fid} crashed")


if __name__ == "__main__":
    unittest.main()
