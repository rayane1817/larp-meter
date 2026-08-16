"""Calibration: pin the verdict bands against a labelled fictional corpus.

These tests are the regression net for the *methodology*. Tweaking a weight or a
keyword bank is allowed; silently turning a RED profile GREEN is not.
"""

import unittest

from larp_meter import TRIGGERED, PASSED, UNKNOWN
from larp_meter.audit import run_audit
from tests.fixtures import CORPUS


def audit(text, name="fixture"):
    return run_audit(name, text, mode="text", verify=False)


class TestCalibration(unittest.TestCase):
    def test_corpus_lands_in_expected_bands(self):
        for fid, text, expected in CORPUS:
            with self.subTest(fixture=fid):
                r = audit(text, fid)
                self.assertIn(
                    r["level"], expected,
                    f"{fid}: got {r['level']} (score {r['larp_score']}, "
                    f"coverage {r['evidence_coverage_pct']}%); expected one of {sorted(expected)}")

    def test_larp_outscores_legitimate(self):
        """The ordering must hold even if absolute thresholds are retuned."""
        by_id = {fid: audit(text, fid) for fid, text, _ in CORPUS}
        self.assertGreater(by_id["pure-larp"]["larp_score"], by_id["solid-engineer"]["larp_score"])
        self.assertGreater(by_id["logo-wall"]["larp_score"], by_id["academic-no-hype"]["larp_score"])
        self.assertGreater(by_id["pure-larp"]["larp_score"], by_id["borderline-founder"]["larp_score"])

    def test_specificity_tracks_substance(self):
        by_id = {fid: audit(text, fid) for fid, text, _ in CORPUS}
        self.assertGreater(by_id["solid-engineer"]["specificity_index"],
                           by_id["pure-larp"]["specificity_index"])

    def test_short_profile_refuses_to_grade(self):
        r = audit("Founder. Building things. Ask me about AI.", "tiny")
        self.assertEqual(r["level"], "INSUFFICIENT DATA")

    def test_honest_non_technical_profile_is_not_punished(self):
        """A policy person who never claims to be an engineer must not read as a LARP."""
        r = audit(dict((f, t) for f, t, _ in CORPUS)["policy-person-honest"], "policy")
        self.assertLess(r["larp_score"], 40)


class TestReportShape(unittest.TestCase):
    def setUp(self):
        self.report = audit(CORPUS[0][1], "pure-larp")

    def test_report_is_json_serialisable(self):
        import json
        json.loads(json.dumps(self.report))

    def test_all_flags_present_with_valid_status(self):
        self.assertEqual(len(self.report["flags"]), 13)
        for f in self.report["flags"]:
            self.assertIn(f["status"], (TRIGGERED, PASSED, UNKNOWN))
            self.assertTrue(f["description"], f"flag {f['id']} has no justification")

    def test_triggered_flags_always_explain_themselves(self):
        for f in self.report["flags"]:
            if f["status"] == TRIGGERED:
                self.assertGreater(len(f["description"]), 30,
                                   f"flag {f['id']} justification is too thin to act on")

    def test_categories_cover_decided_flags_only(self):
        decided = {f["category"] for f in self.report["flags"]
                   if f["status"] in (TRIGGERED, PASSED)}
        self.assertEqual(set(self.report["categories"]), decided)


class TestRenderers(unittest.TestCase):
    def setUp(self):
        self.report = audit(CORPUS[0][1], "pure-larp")

    def test_terminal_renderer(self):
        from larp_meter.report import render_terminal
        out = render_terminal(self.report)
        self.assertIn("LARP score", out)
        self.assertIn("TRIGGERED", out)

    def test_markdown_renderer_has_frontmatter(self):
        from larp_meter.report import render_markdown
        md = render_markdown(self.report)
        self.assertTrue(md.startswith("---"))
        self.assertIn("larp_score:", md)

    def test_html_renderer_is_self_contained_and_escaped(self):
        from larp_meter.report import render_html
        html = render_html(audit("<script>alert(1)</script> Founder of Evil Corp.", "xss<test>"))
        self.assertIn("<!doctype html>", html.lower())
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("http://", html.split("</style>")[0])  # no external assets in CSS

    def test_renderers_survive_every_fixture(self):
        from larp_meter.report import render_terminal, render_markdown, render_html
        for fid, text, _ in CORPUS:
            r = audit(text, fid)
            for renderer in (render_terminal, render_markdown, render_html):
                with self.subTest(fixture=fid, renderer=renderer.__name__):
                    self.assertTrue(renderer(r))


if __name__ == "__main__":
    unittest.main()
