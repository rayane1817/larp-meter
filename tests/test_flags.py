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
        c = ctx_for(text, verified=True)
        for claim in c.claims:
            if claim.subtype == "doi":
                claim.status, claim.detail = ex.VERIFIED, "Paper exists and lists the subject."
        self.assertEqual(evaluate(c)[11].status, PASSED)

    def test_unreachable_registries_decide_nothing(self):
        text = "Our published work: 10.1038/s41586-020-2649-2."
        c = ctx_for(text, verified=True)
        for claim in c.claims:
            if claim.subtype == "doi":
                claim.status, claim.detail = ex.UNCHECKABLE, "Crossref unreachable"
        self.assertEqual(evaluate(c)[11].status, UNKNOWN)


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


class TestRobustness(unittest.TestCase):
    def test_every_flag_survives_empty_text(self):
        results = evaluate(ctx_for(""))
        self.assertEqual(len(results), 12)
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
