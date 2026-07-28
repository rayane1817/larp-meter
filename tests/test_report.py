"""Renderers and the pre-action caveat block."""

import json
import tempfile
import unittest
from pathlib import Path

from larp_meter.audit import run_audit
from larp_meter.report import (caveats, render_terminal, render_markdown, render_html, save_all)

SUBSTANTIVE = ("Founder of NimbusForge building radiation tolerant edge AI hardware for "
               "satellites. Work at 10.1038/nature14539 and github.com/acme/slam. "
               "MSc in European public health policy. Seeking investment.")


def audit(text=SUBSTANTIVE, **kw):
    return run_audit("subject", text, **kw)


class TestCaveats(unittest.TestCase):
    def test_unverified_identifiers_are_called_out(self):
        notes = " ".join(caveats(audit()))
        self.assertIn("--verify", notes)

    def test_ambiguous_identity_warning(self):
        r = audit(signals={"ambiguous_identity": 3})
        self.assertIn("3 different people", " ".join(caveats(r)))

    def test_failed_providers_are_not_framed_as_evidence(self):
        r = audit()
        r["providers_failed"] = ["duckduckgo"]
        note = next(n for n in caveats(r) if "duckduckgo" in n)
        self.assertIn("not evidence against", note)

    def test_discarded_sources_reported(self):
        r = audit()
        r["sources_discarded"] = ["https://a", "https://b"]
        self.assertIn("2 search result(s)", " ".join(caveats(r)))

    def test_low_coverage_flagged_as_provisional(self):
        self.assertIn("provisional", " ".join(caveats(audit("Founder. Building things."))))

    def test_clean_high_coverage_report_has_fewer_caveats(self):
        rich = ("CTO at Marrow Robotics. MSc Electrical Engineering, Delft University of "
                "Technology, 2015. Ten years of experience as an engineer. Patent US10123456. "
                "40 customers, 2.1M revenue in 2024. Funded by a grant; contract with a port "
                "authority. Featured in Reuters. Partnership with Orion Systems; we co-authored "
                "a joint paper. Not fundraising.")
        self.assertLess(len(caveats(audit(rich, verify=False))), len(caveats(audit())))

    def test_caveats_never_raise_on_a_minimal_report(self):
        self.assertIsInstance(caveats({}), list)


class TestRenderers(unittest.TestCase):
    def setUp(self):
        self.report = audit()

    def test_terminal_includes_caveats(self):
        self.assertIn("Read this before acting", render_terminal(self.report))

    def test_markdown_includes_caveats_and_frontmatter(self):
        md = render_markdown(self.report)
        self.assertTrue(md.startswith("---"))
        self.assertIn("## Read this before acting", md)

    def test_html_escapes_hostile_content(self):
        r = run_audit("<img src=x onerror=alert(1)>", "Founder of <script>alert('xss')</script>.")
        html = render_html(r)
        self.assertNotIn("<script>alert('xss')</script>", html)
        self.assertNotIn("onerror=alert(1)>", html)

    def test_html_has_no_external_resources(self):
        """A strict-CSP or offline viewer must render it fully."""
        html = render_html(self.report)
        for needle in ("src=\"http", "href=\"http://cdn", "@import", "<script"):
            self.assertNotIn(needle, html)

    def test_html_renders_in_both_themes(self):
        html = render_html(self.report)
        self.assertIn("prefers-color-scheme:dark", html)


class TestSaveAll(unittest.TestCase):
    def test_writes_json_html_md(self):
        r = audit()
        with tempfile.TemporaryDirectory() as d:
            written = save_all(r, Path(d) / "out",
                               html_path=Path(d) / "r.html", md_path=Path(d) / "r.md")
            self.assertEqual(len(written), 3)
            for p in written:
                self.assertTrue(Path(p).exists() and Path(p).stat().st_size > 0)

    def test_json_roundtrips(self):
        r = audit()
        with tempfile.TemporaryDirectory() as d:
            written = save_all(r, Path(d) / "out")
            loaded = json.loads(Path(written[0]).read_text(encoding="utf-8"))
        self.assertEqual(loaded["larp_score"], r["larp_score"])

    def test_hostile_target_name_cannot_escape_the_output_directory(self):
        r = audit()
        r["target"] = "../../../../etc/passwd"
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out"
            written = save_all(r, out)
            self.assertEqual(Path(written[0]).parent.resolve(), out.resolve())

    def test_unicode_target_name_is_survivable(self):
        r = audit()
        r["target"] = "Ada Lovelace 数学者 🚀"
        with tempfile.TemporaryDirectory() as d:
            written = save_all(r, Path(d) / "out")
            self.assertTrue(Path(written[0]).exists())


if __name__ == "__main__":
    unittest.main()
