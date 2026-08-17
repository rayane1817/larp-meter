import unittest

from larp_meter import TRIGGERED, PASSED, UNKNOWN
from larp_meter import scoring
from larp_meter.flags import FlagResult, REGISTRY, TOTAL_WEIGHT
from larp_meter.scoring import score, MIN_COVERAGE, category_scores


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


class TestLevelBoundaries(unittest.TestCase):
    """Pin the LEVELS cut values exactly — a `<` vs `<=` mutation at
    `next((lv, s) for cut, lv, s in LEVELS if larp < cut)` survived a full
    mutation-testing sweep with every other existing test still green,
    because nothing constructed a scenario landing exactly ON a cut value
    (20, 40, 65). Off by one there silently reclassifies every profile
    scoring precisely at a boundary into the wrong severity band.

    Each combination uses flags with no floor (never flag 11), so these
    stay isolated from `_apply_floors` and test LEVELS alone.
    """

    # Every combination below also has to clear MIN_COVERAGE (0.35 of
    # TOTAL_WEIGHT=18.5, i.e. decided_w >= 6.475) or the report never reaches
    # LEVELS at all — INSUFFICIENT DATA masks the boundary being tested.
    # decided_w=10.0 satisfies that with room to spare for every case here.

    def test_larp_of_exactly_20_is_yellow_not_green(self):
        """GREEN's own cut is 20 — 20 must fail `larp < 20` and fall to YELLOW."""
        results = {3: FlagResult(TRIGGERED),
                   1: FlagResult(PASSED), 2: FlagResult(PASSED), 6: FlagResult(PASSED),
                   7: FlagResult(PASSED), 4: FlagResult(PASSED), 5: FlagResult(PASSED)}
        verdict = score(results)
        self.assertEqual(verdict["raw_score"], 20)
        self.assertEqual(verdict["level"], "YELLOW")

    def test_larp_of_exactly_40_is_orange_not_yellow(self):
        results = {3: FlagResult(TRIGGERED), 4: FlagResult(TRIGGERED), 5: FlagResult(TRIGGERED),
                   1: FlagResult(PASSED), 2: FlagResult(PASSED),
                   6: FlagResult(PASSED), 7: FlagResult(PASSED)}
        verdict = score(results)
        self.assertEqual(verdict["raw_score"], 40)
        self.assertEqual(verdict["level"], "ORANGE")

    def test_larp_of_exactly_65_is_red_not_orange(self):
        results = {1: FlagResult(TRIGGERED), 2: FlagResult(TRIGGERED),
                   3: FlagResult(TRIGGERED), 6: FlagResult(TRIGGERED),
                   7: FlagResult(PASSED), 8: FlagResult(PASSED), 9: FlagResult(PASSED)}
        verdict = score(results)
        self.assertEqual(verdict["raw_score"], 65)
        self.assertEqual(verdict["level"], "RED")

    def test_zero_percent_is_green(self):
        """Complementary sanity check that the lower band still exists at
        all after pinning the boundaries above."""
        results = {1: FlagResult(PASSED), 2: FlagResult(PASSED), 3: FlagResult(PASSED),
                   4: FlagResult(PASSED), 5: FlagResult(PASSED)}
        verdict = score(results)
        self.assertEqual(verdict["raw_score"], 0)
        self.assertEqual(verdict["level"], "GREEN")


class TestCoverageBoundaryIsInclusive(unittest.TestCase):
    def test_coverage_exactly_at_min_coverage_is_still_scored(self):
        """`scored = coverage >= MIN_COVERAGE` survived a mutation to `>`
        untouched by every other test in the suite. Real REGISTRY weights
        cannot produce coverage of EXACTLY 0.35 (TOTAL_WEIGHT * 0.35 is not a
        multiple of the smallest flag weight), so MIN_COVERAGE is
        monkeypatched to a threshold flag 4 alone reaches exactly, and
        restored immediately after — this tests the `>=` semantics
        regardless of what the real constant happens to be."""
        exact_coverage = 1.0 / TOTAL_WEIGHT  # flag 4's weight, exactly
        original = scoring.MIN_COVERAGE
        scoring.MIN_COVERAGE = exact_coverage
        try:
            verdict = score({4: FlagResult(PASSED)})
        finally:
            scoring.MIN_COVERAGE = original
        self.assertTrue(verdict["scored"], "coverage exactly at the threshold must still be scored")
        self.assertIsNotNone(verdict["score"])

    def test_coverage_just_under_min_coverage_is_not_scored(self):
        """The complementary direction, to confirm the monkeypatch technique
        itself is sound and not accidentally always-true."""
        exact_coverage = 1.0 / TOTAL_WEIGHT
        original = scoring.MIN_COVERAGE
        scoring.MIN_COVERAGE = exact_coverage + 0.0001
        try:
            verdict = score({4: FlagResult(PASSED)})
        finally:
            scoring.MIN_COVERAGE = original
        self.assertFalse(verdict["scored"])


class TestFloorTieBreak(unittest.TestCase):
    """`_apply_floors`' `<=` vs `<` tie-break survived the same sweep. At an
    EXACT tie (the naturally-computed level already equals the floor), the
    level itself is identical either way -- the only observable difference
    is which SUMMARY TEXT is shown, which is exactly why no existing test
    caught it: every test checks `level`, and `level` doesn't move at a tie.
    """

    def test_exact_tie_keeps_the_ordinary_summary_not_the_floor_message(self):
        """Natural weighted score lands on ORANGE (50%) at the same time
        flag 11 (floor=ORANGE) triggers -- an exact tie. Pinned intent:
        the ordinary weighted-score summary wins, not 'Held at ORANGE by
        ...', since the floor didn't actually change anything here."""
        results = {11: FlagResult(TRIGGERED), 1: FlagResult(TRIGGERED), 8: FlagResult(TRIGGERED),
                   2: FlagResult(PASSED), 6: FlagResult(PASSED),
                   9: FlagResult(PASSED), 10: FlagResult(PASSED)}
        verdict = score(results)
        self.assertEqual(verdict["raw_score"], 50)
        self.assertEqual(verdict["level"], "ORANGE")
        self.assertNotIn("Held at", verdict["summary"])

    def test_floor_worse_than_natural_level_does_apply_and_names_itself(self):
        """The non-tie case, for contrast: when the floor is strictly worse
        than the natural level, the floor DOES apply and says so."""
        # Built by mutation rather than `a | b`: the dict-merge operator is
        # 3.9+, and pyproject declares requires-python >= 3.8 with a 3.8 row
        # in the CI matrix. It parses fine on 3.8 and fails at runtime, so
        # neither a syntax check nor a local run on a newer interpreter
        # catches it.
        results = {s["id"]: FlagResult(PASSED) for s in REGISTRY}
        results[11] = FlagResult(TRIGGERED)
        verdict = score(results)
        self.assertEqual(verdict["level"], "ORANGE")
        self.assertIn("Held at ORANGE", verdict["summary"])


class TestCategoryScoresExcludeUndecided(unittest.TestCase):
    def test_unknown_flags_are_excluded_from_category_denominators(self):
        """category_scores' own filter (`r.status not in (TRIGGERED, PASSED)`
        -> continue) survived a mutation that stopped excluding UNKNOWN
        results. Left in, an UNKNOWN flag's weight would dilute its
        category's decided-weight denominator without ever being decided,
        silently understating how bad (or good) that category actually is,
        and inflating 'flags_decided' with flags that were never decided."""
        results = {s["id"]: FlagResult(UNKNOWN) for s in REGISTRY}
        results[1] = FlagResult(TRIGGERED)   # credentials: 1 decided, triggered
        cats = category_scores(results)
        self.assertEqual(cats["credentials"]["score"], 100)
        self.assertEqual(cats["credentials"]["flags_decided"], 1)


class TestInsufficientDataSummaryAccuracy(unittest.TestCase):
    def test_decided_count_in_the_summary_matches_the_actual_decided_flags(self):
        """`decided_flags` (used only in the INSUFFICIENT DATA prose) survived
        a mutation that dropped PASSED from its own count -- a real,
        user-visible inaccuracy ('Only 1 of 13 flags could be decided' when
        3 actually were) that doesn't touch `scored`/`level`/`score` at all,
        which is exactly why nothing else in the suite noticed."""
        results = {4: FlagResult(TRIGGERED), 5: FlagResult(PASSED), 8: FlagResult(PASSED)}
        # Still below MIN_COVERAGE with only 3 of 13 flags decided.
        verdict = score(results)
        self.assertEqual(verdict["level"], "INSUFFICIENT DATA")
        self.assertIn("Only 3 of", verdict["summary"])


if __name__ == "__main__":
    unittest.main()
