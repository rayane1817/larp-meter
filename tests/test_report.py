"""Renderers and the pre-action caveat block."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from larp_meter.audit import run_audit
from larp_meter.report import (caveats, render_terminal, render_markdown, render_html, save_all)

SUBSTANTIVE = ("Founder of NimbusForge building radiation tolerant edge AI hardware for "
               "satellites. Work at 10.1038/nature14539 and github.com/acme/slam. "
               "MSc in European public health policy. Seeking investment.")

# No DOI, ORCID, GitHub URL, arXiv ID, NCT number, patent number, or named
# institution -- every claim below lands on a subtype outside verify.py's
# HANDLERS, so `--verify` has nothing to dispatch and makes zero registry
# calls, exactly the fabricator-with-no-identifiers case BACKLOG.md measured.
NO_IDENTIFIERS = ("Dr. Marcus Vane, CEO and Founder of Helion Neurotech since 2005. PhD "
                   "Neuroscience. 20 years of experience in translational neuroscience. Over "
                   "40 peer-reviewed publications and 6 granted patents. Strategic "
                   "partnerships with Siemens Healthineers, Philips and Mayo Clinic, backed "
                   "by joint development contracts. 12,000 users on our platform, generating "
                   "3M in annual revenue in 2024. We are raising a Series A. Featured in "
                   "Forbes and Nature News for our breakthrough approach to neural interfaces.")


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

    RICH = ("CTO at Marrow Robotics. MSc Electrical Engineering, Delft University of "
            "Technology, 2015. Ten years of experience as an engineer. Patent US10123456. "
            "40 customers, 2.1M revenue in 2024. Funded by a grant; contract with a port "
            "authority. Featured in Reuters. Partnership with Orion Systems; we co-authored "
            "a joint paper. Not fundraising.")

    def test_high_coverage_report_drops_the_provisional_caveat(self):
        self.assertFalse([c for c in caveats(audit(self.RICH)) if "provisional" in c])
        self.assertTrue([c for c in caveats(audit()) if "provisional" in c])

    def test_a_clean_unverified_verdict_is_marked_as_the_subjects_own_account(self):
        """The most consequential thing a reader can misread. A well-written
        fabrication passes text mode, so a clean unverified result must never
        present itself as corroboration."""
        report = audit(self.RICH)
        self.assertIn(report["level"], ("GREEN", "YELLOW"))
        self.assertTrue([c for c in caveats(report) if "own account" in c])

    def test_an_ungraded_report_does_not_get_the_self_account_caveat(self):
        """INSUFFICIENT DATA already says it cannot score; there are no passing
        flags to qualify, so the extra note would just be noise."""
        report = audit("Founder. Building things.")
        self.assertEqual(report["level"], "INSUFFICIENT DATA")
        self.assertFalse([c for c in caveats(report) if "own account" in c])

    def test_the_caveat_is_dropped_once_an_outside_source_corroborates(self):
        corroborated = audit(self.RICH, signals={"wikipedia_about_subject": ["Some Person"]})
        self.assertFalse([c for c in caveats(corroborated) if "own account" in c])

    def test_the_caveat_is_dropped_when_openalex_corroborates_and_wikipedia_does_not(self):
        """The 'own account' caveat only ever checked `wikipedia_about_subject`,
        never `signals["openalex"]` -- but flag 6's own PASSED evidence
        ("Independent scholarly record found... (OpenAlex)") is exactly the
        kind of outside-source corroboration this caveat exists to detect.
        A subject with no identifiers in their bio who genuinely has a
        matching OpenAlex author record (real works, real citations) got the
        caveat anyway, purely because nothing set `wikipedia_about_subject`
        too -- telling the reader 'nothing here was checked against an
        outside source' about a report whose flag 6 evidence, one section
        down, says the opposite."""
        scholar = {"works": 12, "citations": 340, "display_name": "Some Person"}
        corroborated = audit(self.RICH, signals={"openalex": scholar})
        self.assertFalse([c for c in caveats(corroborated) if "own account" in c])

    def test_the_caveat_survives_a_genuine_negative_openalex_search(self):
        """The fix above must not overcorrect: a completed OpenAlex search
        that found nothing (`signals["openalex"]` is `None`, the real
        "asked, and found nothing" shape from cli._subject_registry_signals)
        is not corroboration and must not silence the caveat."""
        no_hit = audit(self.RICH, signals={"openalex": None})
        self.assertTrue([c for c in caveats(no_hit) if "own account" in c])

    def test_caveats_never_raise_on_a_minimal_report(self):
        self.assertIsInstance(caveats({}), list)

    def test_verify_flag_alone_does_not_earn_the_verified_badge(self):
        """`report['verified']` used to be set from the CLI flag alone, so a
        --verify run that checked nothing still suppressed the tool's single
        most important disclaimer ('nothing here was checked against an
        outside source'). Simulating the exact state audit.py now computes
        for a claims-but-nothing-checkable profile: verified=True (the flag
        was passed) but verification_effective=False (verifier.calls stayed
        0). The 'own account' disclaimer must survive that combination."""
        report = audit(self.RICH)
        report["verified"] = True
        report["verification_effective"] = False
        self.assertTrue([c for c in caveats(report) if "own account" in c])

    def test_an_effective_verify_drops_the_own_account_disclaimer_as_before(self):
        """Guards the other direction: a run that genuinely checked something
        must keep behaving exactly as 'verified' did pre-fix."""
        report = audit(self.RICH)
        report["verified"] = True
        report["verification_effective"] = True
        self.assertFalse([c for c in caveats(report) if "own account" in c])

    def test_a_zero_identifier_profile_reports_zero_lookups_when_verify_is_passed(self):
        """The real end-to-end case: a fabricator citing no identifiers makes
        --verify a structural no-op (nothing in HANDLERS to dispatch to), and
        the report must say so plainly rather than silently behaving as if
        the flag had done something."""
        with tempfile.TemporaryDirectory() as d:
            report = audit(NO_IDENTIFIERS, verify=True, cache_dir=d,
                            subject_name="Marcus Vane")
        self.assertTrue(report["verified"])
        self.assertFalse(report["verification_effective"])
        self.assertEqual(report["verifier_stats"]["api_calls"], 0)
        self.assertIn("0 lookups", " ".join(caveats(report)))

    def test_a_dispatched_claim_is_effective_even_under_a_total_network_outage(self):
        """Effectiveness tracks whether anything was DISPATCHED to a
        registry, not whether the registry answered -- a network failure is
        never evidence of deception (verify.py's own governing rule), and it
        must not also fall back to the pre-fix 'nothing was checked' framing
        for a profile that did carry a real identifier."""
        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            with tempfile.TemporaryDirectory() as d:
                report = audit(SUBSTANTIVE, verify=True, cache_dir=d,
                               subject_name="Nobody Real")
        self.assertTrue(report["verified"])
        self.assertTrue(report["verification_effective"])
        self.assertFalse([c for c in caveats(report) if "0 lookups" in c])


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

    def test_ineffective_verify_does_not_render_the_plain_verified_badge(self):
        """The terminal/markdown/HTML badge must not read the same as a real
        registry-checked run when --verify was passed but dispatched
        nothing -- that byte-for-byte identical badge is what let a
        zero-identifier fabrication look scrutinised."""
        report = dict(self.report)
        report["verified"] = True
        report["verification_effective"] = False
        for rendered in (render_terminal(report), render_markdown(report), render_html(report)):
            self.assertNotIn("·  verified", rendered)
            self.assertNotIn("registry-verified", rendered)
            self.assertNotIn("**Registry verification:** yes", rendered)


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
