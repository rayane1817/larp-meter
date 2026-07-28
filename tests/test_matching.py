import unittest

from larp_meter.matching import has_term, find_terms, count_occurrences, load_banks


class TestTermMatching(unittest.TestCase):
    def test_no_substring_false_positives(self):
        """v1's fatal bug: 'ai' matched said/email/airline, corrupting every flag."""
        text = "She said hello via email before the airline chairman arrived."
        self.assertFalse(has_term(text, "ai"))
        self.assertFalse(has_term(text, "ml"))

    def test_matches_real_occurrence(self):
        self.assertTrue(has_term("We work on AI systems", "ai"))
        self.assertTrue(has_term("expertise in Artificial Intelligence today",
                                 "artificial intelligence"))

    def test_hyphen_and_space_variants_are_equivalent(self):
        for variant in ("edge-AI hardware", "edge AI hardware", "Edge  ai hardware"):
            self.assertTrue(has_term(variant, "edge ai"), variant)

    def test_case_insensitive(self):
        self.assertTrue(has_term("DEEP TECH investing", "deep tech"))

    def test_find_terms_preserves_order_and_filters(self):
        found = find_terms("quantum robotics only", ["quantum", "blockchain", "robotics"])
        self.assertEqual(found, ["quantum", "robotics"])

    def test_count_occurrences_counts_repeats(self):
        self.assertEqual(count_occurrences("synergy synergy paradigm", ["synergy", "paradigm"]), 3)

    def test_punctuation_boundaries(self):
        self.assertTrue(has_term("expertise: AI, robotics.", "ai"))
        self.assertFalse(has_term("chairmanship", "chairman"))


class TestBanks(unittest.TestCase):
    def test_defaults_load(self):
        banks = load_banks(path="/nonexistent/keywords.json")
        self.assertIn("buzzwords", banks)
        self.assertGreater(len(banks["buzzwords"]), 10)

    def test_user_overrides(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "kw.json"
            p.write_text(json.dumps({"buzzwords": ["blorptastic"], "+tech_claims": ["fusion"]}))
            banks = load_banks(path=str(p))
        self.assertEqual(banks["buzzwords"], ["blorptastic"])
        self.assertIn("fusion", banks["tech_claims"])
        self.assertIn("quantum", banks["tech_claims"])  # '+' appends, does not replace


if __name__ == "__main__":
    unittest.main()
