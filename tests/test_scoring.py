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


if __name__ == "__main__":
    unittest.main()
