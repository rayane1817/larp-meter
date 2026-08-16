"""Round 4: negation scope, credential-transfer direction, determinism,
pathological input, and the CLI surface.

The theme this round is the mirror of round 3's. Round 3 asked whether the tool
could be fooled; this one asks where it quietly punishes honest text — a word
list that read "grew beyond 40 customers" as a denial, and a taxonomy that let
a policy degree stand in for a medical one.
"""

import io
import json
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from larp_meter import TRIGGERED, PASSED, UNKNOWN
from larp_meter import domains as dom
from larp_meter import extract as ex
from larp_meter.audit import run_audit
from larp_meter.cli import main
from larp_meter.matching import is_negated, find_non_overlapping


def flag(text, fid, **kw):
    return next(f for f in run_audit("t", text, mode="text", **kw)["flags"] if f["id"] == fid)


class TestNegationScope(unittest.TestCase):
    """Not every negator governs the rest of the sentence. Treating them alike
    suppressed real evidence, which makes an honest profile score worse."""

    ASSERTED = [
        ("free software and 40 customers", "customers"),
        ("we ship free trials to 40 customers", "customers"),
        ("grew beyond 40 customers last year", "customers"),
        ("we have yet to lose a customer, revenue is up", "revenue"),
        ("besides revenue we track retention", "retention"),
        ("rather than churn we grew revenue", "revenue"),
        ("unlike competitors we have revenue", "revenue"),
        ("our lack of debt helped revenue", "revenue"),
    ]
    DENIED = [
        ("we have no customers and no revenue", "revenue"),
        ("I do not build technology or hardware", "hardware"),
        ("we have 0 customers", "customers"),
        ("our lack of debt", "debt"),
        ("rather than churn", "churn"),
        ("we avoid paradigm shift", "paradigm"),
    ]

    def test_local_negators_do_not_reach_the_whole_clause(self):
        for text, term in self.ASSERTED:
            with self.subTest(text=text):
                self.assertFalse(is_negated(text, text.index(term)),
                                 f"{term!r} wrongly read as denied in {text!r}")

    def test_genuine_denials_are_still_caught(self):
        for text, term in self.DENIED:
            with self.subTest(text=text):
                self.assertTrue(is_negated(text, text.index(term)),
                                f"{term!r} wrongly read as asserted in {text!r}")

    def test_clause_negators_still_cross_coordination(self):
        text = "I do not build technology or hardware or satellites"
        self.assertTrue(is_negated(text, text.index("satellites")))

    def test_negation_still_stops_at_a_sentence_boundary(self):
        text = "We have no legacy systems. We serve 40 customers."
        self.assertFalse(is_negated(text, text.index("customers")))

    def test_an_honest_profile_is_not_penalised_by_a_stray_local_negator(self):
        text = ("Founder building deep tech AI hardware and seeking investment. "
                "Unlike most of our competitors we have 40 paying customers and "
                "recurring revenue today.")
        self.assertEqual(flag(text, 7)["status"], PASSED)

    def test_a_window_cut_mid_word_cannot_invent_a_negator(self):
        """The lookback is capped in characters; slicing 'cannot' into 'not'
        would fabricate a denial."""
        text = "x" * 300 + "cannot" + " " * 190 + "revenue"
        self.assertFalse(is_negated(text, text.index("revenue")))


class TestCredentialTransferDirection(unittest.TestCase):
    def test_a_policy_degree_does_not_clear_a_clinical_claim(self):
        text = ("Chief Medical Officer of Helix Diagnostics, delivering clinical treatment, "
                "therapeutic diagnosis and patient care pathways. MSc Public Policy, "
                "University of Ghent, 2011. Former policy officer and lobbyist.")
        self.assertEqual(flag(text, 1)["status"], TRIGGERED)

    def test_a_doctor_may_move_into_health_policy(self):
        text = ("Director general driving health policy reform and regulatory affairs. "
                "Doctor of Medicine, University of Ghent, 2006. Fifteen years as a "
                "consultant physician before moving into public affairs.")
        self.assertNotEqual(flag(text, 1)["status"], TRIGGERED)

    def test_an_education_degree_does_not_make_a_research_scientist(self):
        text = ("Principal investigator running laboratory research and experimental "
                "validation in genomics. MSc Education, University of Ghent, 2011. "
                "Former teacher and education officer.")
        self.assertEqual(flag(text, 1)["status"], TRIGGERED)

    def test_a_physicist_may_lead_an_engineering_venture(self):
        text = ("Founder of Nimbus Compute building semiconductor and neural network "
                "hardware. PhD in physics, University of Ghent, 2012.")
        self.assertEqual(flag(text, 1)["status"], PASSED)


class TestDeterminism(unittest.TestCase):
    BASE = ("Founder and CEO of Cindermark building neural network hardware. MSc "
            "Electrical Engineering, Delft University of Technology, 2014. Previously a "
            "research scientist. 40 customers and recurring revenue. Seeking investment.")

    def test_repeated_runs_are_identical(self):
        scores = {run_audit("x", self.BASE, mode="text")["larp_score"] for _ in range(5)}
        self.assertEqual(len(scores), 1)

    def test_cosmetic_variation_does_not_move_the_verdict(self):
        """A due-diligence verdict that wobbles on whitespace or case is not
        one anybody should act on."""
        baseline = run_audit("x", self.BASE, mode="text")
        variants = {
            "trailing space": self.BASE + "  ",
            "crlf": self.BASE.replace(". ", ".\r\n"),
            "double spaces": self.BASE.replace(" ", "  "),
            "uppercase": self.BASE.upper(),
            "lowercase": self.BASE.lower(),
            "no final period": self.BASE.rstrip("."),
        }
        for label, text in variants.items():
            with self.subTest(variant=label):
                r = run_audit("x", text, mode="text")
                self.assertEqual(r["level"], baseline["level"])
                self.assertEqual(r["larp_score"], baseline["larp_score"])


class TestPathologicalInput(unittest.TestCase):
    def test_hostile_input_neither_crashes_nor_hangs(self):
        for label, text in [("nested parens", "(" * 3000 + "AI" + ")" * 3000),
                            ("null bytes", "Founder\x00building\x00AI"),
                            ("many years", " ".join(str(1950 + i % 90) for i in range(2000))),
                            ("long word", "a" * 50000)]:
            with self.subTest(case=label):
                started = time.time()
                report = run_audit("x", text, mode="text")
                self.assertIn("level", report)
                self.assertLess(time.time() - started, 20, f"{label} took too long")

    def test_a_hype_heavy_document_stays_tractable(self):
        """Overlap resolution was quadratic in the number of matches, and the
        negation lookback re-tokenized the whole prefix per match: together
        these cost 19s on a 50k-character document."""
        started = time.time()
        run_audit("x", "revolutionary paradigm shift " * 1500, mode="text")
        self.assertLess(time.time() - started, 10)

    def test_overlap_resolution_is_still_correct(self):
        distinct, hits = find_non_overlapping(
            "A true paradigm shift and world class work.",
            ["paradigm", "paradigm shift", "world class"])
        self.assertEqual((distinct, hits), (["paradigm shift", "world class"], 2))

    def test_adjacent_non_overlapping_spans_are_both_counted(self):
        distinct, hits = find_non_overlapping("world class visionary team",
                                              ["world class", "visionary"])
        self.assertEqual(hits, 2)
        self.assertEqual(sorted(distinct), ["visionary", "world class"])


class TestCommandLine(unittest.TestCase):
    """cli.py had no direct coverage: argument routing, exit codes and file
    outputs were only ever exercised by hand."""

    def _run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(argv)
        return code or 0, buf.getvalue()

    def test_explain_prints_the_methodology(self):
        code, out = self._run(["--explain"])
        self.assertEqual(code, 0)
        self.assertIn("LARP score", out)
        self.assertIn("INSUFFICIENT DATA", out)

    def test_text_mode_json_is_machine_readable(self):
        code, out = self._run(["--text", "Founder building AI. MSc public health.",
                               "--no-save", "--json"])
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual(len(report["flags"]), 13)
        self.assertIn("level", report)

    def test_missing_file_is_a_message_not_a_traceback(self):
        self.assertEqual(main(["--file", "/definitely/not/here.txt"]), 2)

    def test_file_mode_reads_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bio.txt"
            p.write_text("Founder building AI hardware. MSc public health policy.",
                         encoding="utf-8")
            code, out = self._run(["--file", str(p), "--no-save", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["target"], "bio")

    def test_html_and_md_are_written_even_with_no_save(self):
        with tempfile.TemporaryDirectory() as d:
            html, md = Path(d) / "r.html", Path(d) / "r.md"
            code, _out = self._run(["--text", "Founder building AI.", "--no-save",
                                    "--html", str(html), "--md", str(md)])
            self.assertEqual(code, 0)
            self.assertTrue(html.is_file() and html.stat().st_size > 0)
            self.assertTrue(md.is_file() and md.stat().st_size > 0)

    def test_batch_mode_writes_a_summary_row_per_subject(self):
        with tempfile.TemporaryDirectory() as d:
            src, csv_path = Path(d) / "in.tsv", Path(d) / "out.csv"
            src.write_text(
                "Alpha Fictional\tFounder building AI hardware. MSc public health. Seeking investment.\n"
                "Beta Fictional\tCTO at Marrow Robotics. MSc Electrical Engineering, Delft "
                "University of Technology, 2015. 40 customers.\n", encoding="utf-8")
            code, _out = self._run(["--batch", str(src), "--csv", str(csv_path), "--no-save"])
            self.assertEqual(code, 0)
            rows = csv_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(rows), 3)          # header + two subjects
        self.assertIn("Alpha Fictional", rows[1])

    def test_no_arguments_prints_help_without_error(self):
        code, out = self._run([])
        self.assertEqual(code, 0)
        self.assertIn("usage", out.lower())


if __name__ == "__main__":
    unittest.main()


class TestSharedNameDetection(unittest.TestCase):
    """Found by running the tool on a real name rather than a synthetic one.

    The round-2 namesake guard asked "is this material about someone with this
    name?" — which every namesake satisfies. A search for one real person
    returned two obituaries, a people-search page, a LinkedIn disambiguation
    directory, an Instagram account and an allergy researcher's publications,
    and all of it was scored as a single individual.
    """

    from larp_meter import providers as _p

    def _findings(self, *urls):
        return [self._p.Finding(u, "Jan Fictief") for u in urls]

    def test_an_obituary_alongside_a_live_profile_signals_a_shared_name(self):
        reasons = self._p.shared_name_evidence(self._findings(
            "https://www.legacy.com/us/obituaries/name/jan-fictief-obituary?id=1",
            "https://example.org/about"))
        self.assertIn("an obituary record", reasons)

    def test_people_search_listings_signal_a_shared_name(self):
        reasons = self._p.shared_name_evidence(self._findings("https://www.spokeo.com/Jan-Fictief"))
        self.assertIn("a people-search listing", reasons)

    def test_a_linkedin_directory_page_signals_a_shared_name(self):
        reasons = self._p.shared_name_evidence(
            self._findings("https://www.linkedin.com/pub/dir/jan/fictief"))
        self.assertIn("a LinkedIn directory page listing multiple people", reasons)

    def test_an_ordinary_linkedin_profile_does_not(self):
        reasons = self._p.shared_name_evidence(
            self._findings("https://www.linkedin.com/in/some-specific-person"))
        self.assertEqual(reasons, {})

    def test_a_clean_corpus_raises_nothing(self):
        reasons = self._p.shared_name_evidence(self._findings(
            "https://en.wikipedia.org/wiki/Ada_Lovelace", "https://doi.org/10.1000/x"))
        self.assertEqual(reasons, {})

    def test_the_report_warns_before_the_reader_acts(self):
        from larp_meter.report import caveats
        report = run_audit("John Doe", "Founder building AI hardware.", mode="web",
                           signals={"shared_name_evidence": {"an obituary record": "u"}})
        note = " ".join(caveats(report))
        self.assertIn("shared by more than one person", note)
        self.assertIn("A name is not an identifier", note)

    def test_aggregators_are_not_third_party_validation(self):
        """A people-search page exists for almost everyone and an obituary
        aggregator indexes the dead; neither is editorial coverage."""
        claimy = ("Founder and chief executive of Cindermark, building satellite hardware "
                  "and machine learning models for orbital deployment across defence and "
                  "commercial customers, leading an engineering team that has grown every "
                  "year since the company was established in this sector.")
        aggregators = ["https://www.spokeo.com/John-Doe",
                       "https://www.legacy.com/obituaries/name/doe/john"]
        r = run_audit("t", claimy, mode="web", source_urls=aggregators,
                      signals={"search_ok": True})
        self.assertEqual(next(f for f in r["flags"] if f["id"] == 10)["status"], TRIGGERED)

    def test_real_press_still_validates(self):
        claimy = ("Founder and chief executive of Cindermark, building satellite hardware "
                  "and machine learning models for orbital deployment across defence and "
                  "commercial customers, leading an engineering team that has grown every "
                  "year since the company was established in this sector.")
        r = run_audit("t", claimy, mode="web",
                      source_urls=["https://www.reuters.com/article/x"],
                      signals={"search_ok": True})
        self.assertEqual(next(f for f in r["flags"] if f["id"] == 10)["status"], PASSED)
