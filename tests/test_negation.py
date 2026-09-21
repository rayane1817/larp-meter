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


class TestNewlineClauseBoundary(unittest.TestCase):
    """A bare '\\n' is not always a clause boundary. v4 treated every newline
    as a hard stop, which meant an ordinary word-wrap ("We are not\\nraising a
    Series A") silently dropped "not" from the negator's lookback window —
    the identical text with the wrap removed was correctly read as denied.
    That is a false accusation waiting to happen: any plain-text paste, PDF
    extraction, or hard-wrapped email that denies a claim across a line break
    would have the denial ignored and the claim counted as asserted.

    The fix has to hold in both directions: a mid-sentence wrap must not
    break negation scope, but a genuine paragraph or list-item break must
    still stop it, or "no revenue" in one bullet would wrongly suppress a
    real, unrelated claim asserted in the next one.
    """

    def test_word_wrapped_negation_still_applies(self):
        text = "We are not\nraising a Series A at this time."
        self.assertTrue(is_negated(text, text.index("raising")))

    def test_word_wrap_mid_phrase_still_applies(self):
        text = "We have no\ncustomers or revenue to speak of yet."
        self.assertTrue(is_negated(text, text.index("customers")))
        self.assertTrue(is_negated(text, text.index("revenue")))

    def test_paragraph_break_still_stops_negation(self):
        # No other punctuation before the blank line, and "no" sits inside the
        # 6-token lookback window so the boundary — not the window cap — has
        # to be what stops it.
        text = "No revenue here\n\nWe are raising a round"
        self.assertFalse(is_negated(text, text.index("raising")))

    def test_hyphen_bullet_list_item_stops_negation(self):
        # A hyphen isn't itself one of _CLAUSE_END_CHARS, so this can only
        # pass via the newline's own bullet-start check, not by accident.
        text = "- No revenue yet\n- Raising a Series A"
        self.assertFalse(is_negated(text, text.index("Raising")))

    def test_numbered_list_item_stops_negation(self):
        # A closing paren, not a period, so the boundary can't come from an
        # unrelated _CLAUSE_END_CHARS hit on the list marker itself.
        text = "1) No revenue yet\n2) Raising a Series A"
        self.assertFalse(is_negated(text, text.index("Raising")))

    def test_find_terms_respects_word_wrapped_negation(self):
        text = "We are not\nraising a Series A at this time."
        self.assertEqual(find_terms(text, ["raising"], skip_negated=True), [])


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

    def test_word_wrapped_denial_of_fundraising_is_not_treated_as_fundraising(self):
        """Same denial as above, wrapped across an ordinary line break — the
        input shape a hard-wrapped paste or PDF extraction actually produces.
        Before the newline-boundary fix this read as an active, traction-free
        raise and TRIGGERED instead of UNKNOWN."""
        text = ("Founder building deep tech AI hardware for satellites. We are not\n"
                "seeking investment and are not raising. We have 40 customers.")
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
