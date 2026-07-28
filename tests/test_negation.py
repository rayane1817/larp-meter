"""Negation handling.

Reading a term as evidence when the text denies it inverts the finding. The
worst case found in v3 development: "We are seeking investment. We have no
customers and no revenue" cleared the fundraising-without-traction flag — the
exact profile that flag exists to catch.
"""

import unittest

from larp_meter import TRIGGERED, PASSED, UNKNOWN
from larp_meter.audit import run_audit
from larp_meter.matching import is_negated, find_terms, has_term, count_occurrences


def flag(text, fid):
    return next(f for f in run_audit("t", text, mode="text")["flags"] if f["id"] == fid)


class TestIsNegated(unittest.TestCase):
    def test_direct_negators(self):
        for phrase in ("we have no customers", "there is not any revenue",
                       "without revenue", "we never had revenue",
                       "we have zero revenue", "we have 0 revenue"):
            with self.subTest(phrase=phrase):
                idx = phrase.index("revenue") if "revenue" in phrase else phrase.index("customers")
                self.assertTrue(is_negated(phrase, idx), phrase)

    def test_contractions(self):
        self.assertTrue(is_negated("we don't have revenue", "we don't have ".index("revenue")
                                   if False else len("we don't have ")))

    def test_plain_assertion_is_not_negated(self):
        for phrase in ("we have 40 customers", "recurring revenue since 2019",
                       "our revenue grew"):
            with self.subTest(phrase=phrase):
                idx = phrase.index("revenue") if "revenue" in phrase else phrase.index("customers")
                self.assertFalse(is_negated(phrase, idx), phrase)

    def test_negation_does_not_reach_across_a_long_distance(self):
        text = "We have no legacy systems at all, and we serve 40 customers today."
        self.assertFalse(is_negated(text, text.index("customers")))

    def test_find_terms_respects_skip_negated(self):
        text = "We have no revenue."
        self.assertEqual(find_terms(text, ["revenue"]), ["revenue"])
        self.assertEqual(find_terms(text, ["revenue"], skip_negated=True), [])

    def test_count_occurrences_respects_skip_negated(self):
        text = "We have revenue. We have no revenue."
        self.assertEqual(count_occurrences(text, ["revenue"]), 2)
        self.assertEqual(count_occurrences(text, ["revenue"], skip_negated=True), 1)

    def test_has_term_respects_skip_negated(self):
        self.assertTrue(has_term("no revenue", "revenue"))
        self.assertFalse(has_term("no revenue", "revenue", skip_negated=True))


class TestFundraisingFlag(unittest.TestCase):
    RAISING = "Founder building deep tech AI hardware. Seeking investment. "

    def test_denied_traction_still_triggers(self):
        self.assertEqual(flag(self.RAISING + "We have no customers and no revenue yet.", 7)["status"],
                         TRIGGERED)

    def test_zero_traction_still_triggers(self):
        self.assertEqual(flag(self.RAISING + "We have 0 customers and 0 revenue.", 7)["status"],
                         TRIGGERED)

    def test_real_traction_passes(self):
        self.assertEqual(flag(self.RAISING + "We have 40 customers and recurring revenue.", 7)["status"],
                         PASSED)

    def test_denied_fundraising_is_not_treated_as_fundraising(self):
        text = ("Founder building deep tech AI hardware for satellites. We are not seeking "
                "investment and are not raising. We have 40 customers.")
        self.assertEqual(flag(text, 7)["status"], UNKNOWN)


class TestOtherFlags(unittest.TestCase):
    def test_denied_mou_does_not_read_as_vague_dealmaking(self):
        text = ("Founder building AI hardware. No MoU has been signed and there is no NDA in "
                "place; we hold a signed contract and a grant instead.")
        self.assertEqual(flag(text, 5)["status"], PASSED)

    def test_disclaimed_domain_is_not_a_claim(self):
        """'I do not build technology' is a disclaimer, not a claim to expertise."""
        text = ("Secretary General of a patient advocacy alliance. I do not build technology "
                "or hardware; I represent patient interests in regulatory consultations. "
                "MSc Public Health, University of Ghent, 2009.")
        self.assertNotEqual(flag(text, 1)["status"], TRIGGERED)

    def test_quoted_criticism_of_buzzwords_is_not_buzzword_use(self):
        text = ("We avoid paradigm shift, avoid world class, avoid game changing and avoid "
                "visionary language. Instead we publish measured quarterly results with "
                "audited figures and let independent reviewers assess the work in detail.")
        self.assertEqual(flag(text, 4)["status"], PASSED)

    def test_genuine_buzzword_use_still_triggers(self):
        text = ("A revolutionary, groundbreaking, world class paradigm shift — truly "
                "disruptive, cutting edge, next generation thought leadership for a "
                "visionary team building the future of everything today.")
        self.assertEqual(flag(text, 4)["status"], TRIGGERED)


if __name__ == "__main__":
    unittest.main()
