import unittest

from larp_meter import TRIGGERED, PASSED, UNKNOWN
from larp_meter.flags import FlagResult, REGISTRY, TOTAL_WEIGHT
from larp_meter.scoring import score, MIN_COVERAGE


def build(statuses):
    """statuses: {flag_id: status}. Unlisted flags are UNKNOWN."""
    return {s["id"]: FlagResult(statuses.get(s["id"], UNKNOWN)) for s in REGISTRY}


class TestScoring(unittest.TestCase):
    def test_unknown_never_counts_as_passed(self):
        """The core v1 defect: an empty profile scored GREEN."""
        verdict = score(build({}))
        self.assertEqual(verdict["level"], "INSUFFICIENT DATA")
        self.assertEqual(verdict["coverage"], 0)

    def test_all_triggered_is_red(self):
        verdict = score(build({s["id"]: TRIGGERED for s in REGISTRY}))
        self.assertEqual(verdict["score"], 100)
        self.assertEqual(verdict["level"], "RED")
        self.assertEqual(verdict["coverage"], 100)

    def test_all_passed_is_green(self):
        verdict = score(build({s["id"]: PASSED for s in REGISTRY}))
        self.assertEqual(verdict["score"], 0)
        self.assertEqual(verdict["level"], "GREEN")

    def test_score_ignores_unknown_flags_entirely(self):
        """Two triggered + two passed scores the same whether or not others are unknown."""
        a = score({1: FlagResult(TRIGGERED), 2: FlagResult(TRIGGERED),
                   3: FlagResult(PASSED), 6: FlagResult(PASSED)})
        b = score({**{s["id"]: FlagResult(UNKNOWN) for s in REGISTRY},
                   1: FlagResult(TRIGGERED), 2: FlagResult(TRIGGERED),
                   3: FlagResult(PASSED), 6: FlagResult(PASSED)})
        self.assertEqual(a["score"], b["score"])

    def test_weights_matter(self):
        """Flag 11 (weight 2.5) must move the score more than flag 4 (weight 1.0)."""
        heavy = score({11: FlagResult(TRIGGERED), 4: FlagResult(PASSED),
                       1: FlagResult(PASSED), 2: FlagResult(PASSED), 6: FlagResult(PASSED)})
        light = score({4: FlagResult(TRIGGERED), 11: FlagResult(PASSED),
                       1: FlagResult(PASSED), 2: FlagResult(PASSED), 6: FlagResult(PASSED)})
        self.assertGreater(heavy["score"], light["score"])

    def test_coverage_threshold_is_enforced(self):
        """Just under the coverage floor must refuse to grade."""
        # flag 4 alone = weight 1.0 of TOTAL_WEIGHT — far below the floor
        verdict = score({4: FlagResult(TRIGGERED)})
        self.assertLess(1.0 / TOTAL_WEIGHT, MIN_COVERAGE)
        self.assertEqual(verdict["level"], "INSUFFICIENT DATA")

    def test_category_breakdown(self):
        verdict = score(build({s["id"]: TRIGGERED for s in REGISTRY}))
        self.assertIn("credentials", verdict["categories"])
        self.assertEqual(verdict["categories"]["credentials"]["score"], 100)

    def test_levels_are_monotonic(self):
        """More triggered weight can never lower the score."""
        ids = [s["id"] for s in sorted(REGISTRY, key=lambda x: x["id"])]
        last = -1
        for i in range(len(ids) + 1):
            statuses = {fid: (TRIGGERED if n < i else PASSED) for n, fid in enumerate(ids)}
            s = score(build(statuses))["score"]
            self.assertGreaterEqual(s, last)
            last = s


class TestScoreGating(unittest.TestCase):
    """A report can hit 100 on a single decided flag. Exposing that as larp_score
    would let a consumer filtering on the number alone read 'not enough evidence'
    as 'maximum risk'."""

    def test_ungraded_report_exposes_no_score(self):
        verdict = score({4: FlagResult(TRIGGERED)})
        self.assertEqual(verdict["level"], "INSUFFICIENT DATA")
        self.assertIsNone(verdict["score"])
        self.assertFalse(verdict["scored"])
        self.assertEqual(verdict["raw_score"], 100)

    def test_graded_report_exposes_the_score(self):
        verdict = score(build({s["id"]: TRIGGERED for s in REGISTRY}))
        self.assertTrue(verdict["scored"])
        self.assertEqual(verdict["score"], 100)

    def test_renderers_show_na_rather_than_a_number(self):
        from larp_meter.audit import run_audit
        from larp_meter.report import render_terminal, render_markdown, render_html, score_text
        r = run_audit("tiny", "Founder. Building things.", mode="text")
        self.assertIsNone(r["larp_score"])
        self.assertEqual(score_text(r), "n/a")
        self.assertIn("n/a", render_terminal(r))
        self.assertIn("larp_score: null", render_markdown(r))
        self.assertIn("n/a", render_html(r))


class TestContradictionFloor(unittest.TestCase):
    """A registry contradicting a claim is evidence about the world; the other
    flags mostly read self-presentation. Without a floor, a fabricated profile
    absorbed one contradiction under a pile of unverified assertions and still
    came out GREEN — observed at GREEN 18/100 on a wholly invented bio citing a
    nonexistent repository and a patent belonging to someone else."""

    def _all_passed_except(self, fid):
        results = {s["id"]: FlagResult(PASSED) for s in REGISTRY}
        results[fid] = FlagResult(TRIGGERED)
        return results

    def test_a_contradiction_cannot_be_averaged_away(self):
        verdict = score(self._all_passed_except(11))
        self.assertLess(verdict["raw_score"], 20)        # numerically GREEN
        self.assertEqual(verdict["level"], "ORANGE")     # but held
        self.assertIn("Held at ORANGE", verdict["summary"])

    def test_an_ordinary_flag_has_no_floor(self):
        verdict = score(self._all_passed_except(4))
        self.assertEqual(verdict["level"], "GREEN")

    def test_the_floor_never_lowers_a_worse_verdict(self):
        results = {s["id"]: FlagResult(TRIGGERED) for s in REGISTRY}
        verdict = score(results)
        self.assertEqual(verdict["level"], "RED")        # not pulled down to ORANGE

    def test_only_flag_11_carries_a_floor(self):
        floored = [s["id"] for s in REGISTRY if s.get("floor")]
        self.assertEqual(floored, [11])

    def test_the_floor_does_not_fabricate_a_score_below_the_coverage_gate(self):
        """A single triggered flag is still too little evidence to grade."""
        verdict = score({11: FlagResult(TRIGGERED)})
        self.assertEqual(verdict["level"], "INSUFFICIENT DATA")
        self.assertIsNone(verdict["score"])


if __name__ == "__main__":
    unittest.main()
