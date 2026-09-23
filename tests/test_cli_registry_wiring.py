"""End-to-end: does --verify --name actually reach a registry from every entry
point, or only from the ones a unit test happens to exercise directly?

The ROR dead-code bug (fixed in an earlier commit) had this exact signature:
HANDLERS pointed at a real, well-tested verifier, and every test that touched
it called the verifier directly — none of them ran the claim through the
pipeline production actually uses, so a renamed subtype silently orphaned it
for months. The same shape of bug was true here one layer up: providers.py's
OpenAlex/Wikipedia lookups were fully unit-tested in isolation
(test_providers.py), but cmd_text, cmd_from_json, cmd_url and the batch-text
branch of cmd_batch never called them — only cmd_web and batch-web did. A
person who pastes their own bio, which is the ordinary way this tool gets
used, got zero registry contact even under --verify --name unless their bio
happened to contain a DOI or ORCID.

These tests run the real CLI command functions, with only the network layer
stubbed, and check that the registry evidence actually lands in the report.
Terminal output is captured, not left to hit the real stdout: cmd_* is
normally only reached via main(), which calls cli._fix_console() first to
force a UTF-8-safe stream. Calling cmd_* directly, as these tests do, skips
that, and a console whose default encoding cannot represent the report's own
glyphs (the ASCII-incompatible code page pytest/unittest hit on the Windows
CI runners) would otherwise crash the test on the report's own bullet glyph
rather than on anything this file is trying to check.

`--verify` reaches the network through TWO independent layers, not one:
`cli.make_fetcher` (used by providers.py's Wikipedia/OpenAlex signals path)
and `reconcile._http` (used by reconcile.py's Zefix/KBO/OpenAlex reverse-path
check, added 2026-09-22, well after this file). A test whose bio contains a
company-role or publication-volume claim reaches `reconcile.reconcile_text`
from `run_audit` regardless of whether `cli.make_fetcher` was stubbed — live-
confirmed: stubbing only `cli.make_fetcher` let six tests below silently
issue a real `https://api.openalex.org/authors?search=...` request apiece,
observed live hitting OpenAlex's own rate limit. That is exactly the
project's scarcest resource ($0.10/day keyless budget the whole reverse path
depends on), spent by nothing more than running the test suite. Every test
whose text can carry a company-role or publication-volume claim must stub
`reconcile._http` too, via `_stub_http` below -- see
`test_every_verify_path_stays_fully_offline`, which pins this for the file
as a whole rather than one test at a time.
"""

import contextlib
import io
import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from larp_meter import reconcile
from larp_meter.cli import build_parser, cmd_batch, cmd_from_json, cmd_text, cmd_url

WIKI_BODY = json.dumps({"query": {"search": [
    {"title": "Ada Lovelace", "snippet": "an English <b>mathematician</b>"},
]}})

OPENALEX_BODY = json.dumps({"results": [
    {"id": "https://openalex.org/A1", "display_name": "Ada Lovelace", "works_count": 11,
     "cited_by_count": 429, "last_known_institutions": [{"display_name": "Analytical Society"}]},
]})

OPENALEX_AMBIGUOUS_BODY = json.dumps({"results": [
    {"id": "https://openalex.org/A1", "display_name": "Wei Wang", "works_count": 40,
     "cited_by_count": 100, "last_known_institutions": [{"display_name": "University A"}]},
    {"id": "https://openalex.org/A2", "display_name": "Wei Wang", "works_count": 12,
     "cited_by_count": 10, "last_known_institutions": [{"display_name": "University B"}]},
]})

OPENALEX_MERGED_BODY = json.dumps({"results": [
    {"id": "https://openalex.org/A1", "display_name": "Ada Lovelace", "works_count": 900,
     "cited_by_count": 50000,
     "affiliations": [{"institution": {"id": f"https://openalex.org/I{i}",
                                       "display_name": f"Institution {i}"}, "years": [2020]}
                      for i in range(20)]}]})

BIO_NO_IDENTIFIERS = ("Ada Lovelace is a mathematician who has published extensively on "
                      "computing and the Analytical Engine.")


def _stub_fetcher(mapping, calls=None):
    """Mimics search.make_fetcher's signature: (cache_dir, refresh=...) -> fetch(url, browser=)."""
    def make_fetcher(cache_dir, refresh=False):
        def fetch(url, browser=False):
            if calls is not None:
                calls.append(url)
            for needle, body in mapping.items():
                if needle in url:
                    return body
            return ""
        return fetch
    return make_fetcher


def _stub_http(mapping):
    """Stand-in for reconcile._http, matching cli.make_fetcher's stub by the
    same substring mapping so both layers agree on what the world looks like."""
    def http(url, payload=None, headers=None):
        for needle, body in mapping.items():
            if needle in url:
                return True, 200, body
        return False, 0, ""
    return http


def _silent():
    """Swallow whatever a cmd_* call prints, on any platform's console encoding."""
    return contextlib.redirect_stdout(io.StringIO())


class TestNoRealNetworkEscapesTheStub(unittest.TestCase):
    def test_a_publication_claim_reaches_reconcile_without_touching_the_real_network(self):
        """Live-confirmed 2026-09-23: with only cli.make_fetcher stubbed (the
        state every test in this file was in before this fix), a bio
        containing a vague publication-volume claim ("published extensively")
        makes run_audit's reconcile.reconcile_text call reconcile._http for
        real -- observed hitting the live OpenAlex API and its own rate
        limit. That path is invisible to every assertion in this file, so
        nothing failed; it just silently spent the project's scarcest shared
        resource on every test run in a networked environment. Patching
        urllib.request.urlopen to fail loudly, with reconcile._http properly
        stubbed via _stub_http, is what pins the fix: this must raise nothing."""
        args = build_parser().parse_args([
            "--text", BIO_NO_IDENTIFIERS, "--name", "Ada Lovelace",
            "--verify", "--quiet", "--no-save",
        ])
        fetcher = _stub_fetcher({"wikipedia.org": WIKI_BODY, "openalex.org": OPENALEX_BODY})
        http = _stub_http({"wikipedia.org": WIKI_BODY, "openalex.org": OPENALEX_BODY})

        def _forbidden(*a, **kw):
            raise AssertionError("a real network request escaped both stubs")

        with mock.patch("larp_meter.cli.make_fetcher", fetcher), \
             mock.patch.object(reconcile, "_http", http), \
             mock.patch("urllib.request.urlopen", _forbidden), _silent():
            report = cmd_text(args, "Ada Lovelace", BIO_NO_IDENTIFIERS)
        self.assertEqual(report["signals"]["openalex"]["works"], 11)
        # AMBIGUOUS, not UNCHECKABLE: the stub answered (no institution/ORCID
        # tie in this bio, which is a separate, correct outcome) rather than
        # the request being blocked or falling through to a real, unmocked
        # network call -- see the docstring above for what UNCHECKABLE here
        # would actually mean.
        pubs = [r for r in report["reconciliations"] if r["kind"] == "publications"]
        self.assertEqual(pubs[0]["outcome"], "AMBIGUOUS")
        self.assertNotEqual(pubs[0]["detail"], "OpenAlex could not be reached.")


class TestTextModeReachesTheRegistry(unittest.TestCase):
    def test_text_mode_with_verify_and_name_queries_openalex_and_wikipedia(self):
        """Flag 6 must be able to see an independent scholarly record even when
        the pasted bio itself carries no DOI, ORCID or other identifier."""
        args = build_parser().parse_args([
            "--text", BIO_NO_IDENTIFIERS, "--name", "Ada Lovelace",
            "--verify", "--quiet", "--no-save",
        ])
        fetcher = _stub_fetcher({"wikipedia.org": WIKI_BODY, "openalex.org": OPENALEX_BODY})
        http = _stub_http({"wikipedia.org": WIKI_BODY, "openalex.org": OPENALEX_BODY})
        with mock.patch("larp_meter.cli.make_fetcher", fetcher), \
             mock.patch.object(reconcile, "_http", http), _silent():
            report = cmd_text(args, "Ada Lovelace", BIO_NO_IDENTIFIERS)
        flag6 = next(f for f in report["flags"] if f["id"] == 6)
        self.assertEqual(flag6["status"], "PASSED")
        self.assertIn("OpenAlex", flag6["description"])
        self.assertEqual(report["signals"]["openalex"]["works"], 11)

    def test_a_real_openalex_hit_silences_the_own_account_caveat(self):
        """Real pipeline, not report.py's `caveats()` tested in isolation:
        report.caveats' "Nothing here was checked against an outside source"
        disclaimer only ever checked `signals["wikipedia_about_subject"]`,
        never `signals["openalex"]` -- so a subject with no identifiers at
        all, but a genuine matching OpenAlex author record (flag 6 PASSED,
        "Independent scholarly record found... (OpenAlex)"), still got told
        nothing had been checked against an outside source. This runs the
        real `cmd_text` -> `run_audit` -> `caveats` chain end to end to
        confirm `_subject_registry_signals`'s OpenAlex signal actually reaches
        `caveats()` in the shape it expects (`{"works": N, ...}`), not just
        that report.py's own unit tests pass a hand-built dict of that shape."""
        bio = ("CTO at Marrow Robotics. Ten years of experience as an engineer. "
               "40 customers, 2.1M revenue in 2024. Funded by a grant; contract with a "
               "port authority. Featured in Reuters. Partnership with Orion Systems; we "
               "co-authored a joint paper. Not fundraising.")
        args = build_parser().parse_args([
            "--text", bio, "--name", "Sofia Almeida", "--verify", "--quiet", "--no-save",
        ])
        sofia_openalex_body = json.dumps({"results": [
            {"id": "https://openalex.org/A9", "display_name": "Sofia Almeida", "works_count": 11,
             "cited_by_count": 429, "last_known_institutions": [{"display_name": "Marrow Robotics"}]},
        ]})
        fetcher = _stub_fetcher({"wikipedia.org": json.dumps({"query": {"search": []}}),
                                 "openalex.org": sofia_openalex_body})
        with mock.patch("larp_meter.cli.make_fetcher", fetcher), _silent():
            report = cmd_text(args, "Sofia Almeida", bio)
        # Confirms this test actually exercises the gap: no identifier-keyed
        # claim was dispatched, and no Wikipedia hit either -- OpenAlex is the
        # only source of any outside corroboration in this report.
        self.assertFalse(report["verification_effective"])
        self.assertFalse(report["signals"].get("wikipedia_about_subject"))
        self.assertEqual(report["signals"]["openalex"]["works"], 11)
        self.assertIn(report["level"], ("GREEN", "YELLOW"))
        from larp_meter.report import caveats
        self.assertFalse([c for c in caveats(report) if "own account" in c])

    def test_duckduckgo_is_not_queried_from_text_mode(self):
        """DuckDuckGo returns hits for the NAME, not the subject. Pulling its
        general web-search results into a text audit's evidence would credit
        the subject with material never confirmed to be about them."""
        calls = []
        args = build_parser().parse_args([
            "--text", BIO_NO_IDENTIFIERS, "--name", "Ada Lovelace",
            "--verify", "--quiet", "--no-save",
        ])
        fetcher = _stub_fetcher({}, calls=calls)
        with mock.patch("larp_meter.cli.make_fetcher", fetcher), \
             mock.patch.object(reconcile, "_http", _stub_http({})), _silent():
            cmd_text(args, "Ada Lovelace", BIO_NO_IDENTIFIERS)
        self.assertFalse(any("duckduckgo" in u for u in calls))

    def test_no_name_means_no_registry_call(self):
        """--verify with no --name (and no derivable name) has nothing to
        anchor a subject-lookup to, so it must not fire one."""
        calls = []
        args = build_parser().parse_args([
            "--text", BIO_NO_IDENTIFIERS, "--verify", "--quiet", "--no-save",
        ])
        fetcher = _stub_fetcher({"wikipedia.org": WIKI_BODY, "openalex.org": OPENALEX_BODY}, calls=calls)
        with mock.patch("larp_meter.cli.make_fetcher", fetcher), _silent():
            cmd_text(args, "pasted-text", BIO_NO_IDENTIFIERS)
        self.assertEqual(calls, [])

    def test_ambiguous_identity_is_surfaced_not_silently_resolved(self):
        """Several distinct researchers sharing a name must never collapse into
        a single silent answer — the human needs to know the record is
        contested before trusting anything derived from it."""
        args = build_parser().parse_args([
            "--text", "Wei Wang works in materials science.", "--name", "Wei Wang",
            "--verify", "--quiet", "--no-save",
        ])
        fetcher = _stub_fetcher({"openalex.org": OPENALEX_AMBIGUOUS_BODY})
        with mock.patch("larp_meter.cli.make_fetcher", fetcher), _silent():
            report = cmd_text(args, "Wei Wang", "Wei Wang works in materials science.")
        self.assertEqual(report["signals"]["ambiguous_identity"], 2)

    def test_a_genuine_empty_registry_search_reaches_flag_6_through_the_real_pipeline(self):
        """The core-gap archetype from BACKLOG.md, run end-to-end rather than
        unit-tested against flags.py in isolation: a subject with a soft
        'peer-reviewed' output claim and no identifiers at all, where a real
        OpenAlex author-name search genuinely completes and finds no match.

        This is deliberately NOT a test_flags.py-only check. The standing
        review discipline this repo keeps re-learning the hard way (see the
        ROR/HANDLERS dead-code bug and the module docstring above) is that a
        component can be perfectly correct in isolation while the real
        pipeline never reaches it — cli.py has to actually thread a `None`
        (as opposed to an absent key) through `_subject_registry_signals`
        into `ctx.signals` for flags.py's distinction to mean anything."""
        bio = ("Dr. Marcus Vane is a researcher who has published extensively "
               "in peer-reviewed venues over a long career.")
        args = build_parser().parse_args([
            "--text", bio, "--name", "Marcus Vane", "--verify", "--quiet", "--no-save",
        ])
        fetcher = _stub_fetcher({"wikipedia.org": WIKI_BODY,
                                 "openalex.org": json.dumps({"results": []})})
        http = _stub_http({"openalex.org": json.dumps({"results": []})})
        with mock.patch("larp_meter.cli.make_fetcher", fetcher), \
             mock.patch.object(reconcile, "_http", http), _silent():
            report = cmd_text(args, "Marcus Vane", bio)
        self.assertIsNone(report["signals"]["openalex"])
        flag6 = next(f for f in report["flags"] if f["id"] == 6)
        self.assertEqual(flag6["status"], "UNKNOWN")
        self.assertIn("OpenAlex", flag6["description"])

    def test_a_merged_openalex_entity_reaches_flag_6_with_a_caution_through_the_real_pipeline(self):
        """End-to-end version of the merge-risk caveat: the raw JSON shape a
        real OpenAlex response actually has (an 'affiliations' array of
        {institution, years} pairs, not the pre-summarised dict the
        flags.py-level unit test constructs by hand) must actually produce
        the caveat once it goes through the real provider -> signal -> flag
        pipeline, not just when a test hand-builds the signals dict flags.py
        expects -- the same reachability lesson this module's docstring
        names, one layer further in."""
        args = build_parser().parse_args([
            "--text", BIO_NO_IDENTIFIERS, "--name", "Ada Lovelace",
            "--verify", "--quiet", "--no-save",
        ])
        fetcher = _stub_fetcher({"wikipedia.org": WIKI_BODY, "openalex.org": OPENALEX_MERGED_BODY})
        http = _stub_http({"openalex.org": OPENALEX_MERGED_BODY})
        with mock.patch("larp_meter.cli.make_fetcher", fetcher), \
             mock.patch.object(reconcile, "_http", http), _silent():
            report = cmd_text(args, "Ada Lovelace", BIO_NO_IDENTIFIERS)
        flag6 = next(f for f in report["flags"] if f["id"] == 6)
        self.assertEqual(flag6["status"], "PASSED")
        self.assertIn("20 distinct institutions", flag6["description"])
        self.assertTrue(report["signals"]["openalex"]["merge_risk"])

    def test_without_verify_no_registry_call_is_made(self):
        """--verify is the network opt-in; omitting it must not silently phone
        out to OpenAlex/Wikipedia anyway."""
        calls = []
        args = build_parser().parse_args([
            "--text", BIO_NO_IDENTIFIERS, "--name", "Ada Lovelace", "--quiet", "--no-save",
        ])
        fetcher = _stub_fetcher({"wikipedia.org": WIKI_BODY, "openalex.org": OPENALEX_BODY}, calls=calls)
        with mock.patch("larp_meter.cli.make_fetcher", fetcher), _silent():
            cmd_text(args, "Ada Lovelace", BIO_NO_IDENTIFIERS)
        self.assertEqual(calls, [])


class TestFromJsonModeReachesTheRegistry(unittest.TestCase):
    def test_structured_profile_mode_queries_openalex(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            path.write_text(json.dumps({
                "name": "Ada Lovelace",
                "headline": "Mathematician",
                "experiences": [{"title": "Analyst", "org": "Analytical Society"}],
            }), encoding="utf-8")
            args = build_parser().parse_args([
                "--from-json", str(path), "--verify", "--quiet", "--no-save",
            ])
            fetcher = _stub_fetcher({"wikipedia.org": WIKI_BODY, "openalex.org": OPENALEX_BODY})
            with mock.patch("larp_meter.cli.make_fetcher", fetcher), _silent():
                # cmd_from_json returns an exit code, not the report — capture
                # what it hands to _emit instead.
                import larp_meter.cli as cli_mod
                captured = {}
                orig_emit = cli_mod._emit
                cli_mod._emit = lambda report, a: captured.setdefault("report", report)
                try:
                    cmd_from_json(args)
                finally:
                    cli_mod._emit = orig_emit
            self.assertEqual(captured["report"]["signals"]["openalex"]["works"], 11)

    def test_placeholder_subject_unknown_does_not_trigger_a_registry_call(self):
        """A profile JSON with no name and no --name override falls back to the
        literal string "unknown" — that must not be sent to OpenAlex as if it
        were a real subject."""
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            path.write_text(json.dumps({"headline": "Someone"}), encoding="utf-8")
            args = build_parser().parse_args([
                "--from-json", str(path), "--verify", "--quiet", "--no-save",
            ])
            fetcher = _stub_fetcher({"wikipedia.org": WIKI_BODY, "openalex.org": OPENALEX_BODY}, calls=calls)
            with mock.patch("larp_meter.cli.make_fetcher", fetcher), _silent():
                cmd_from_json(args)
        self.assertEqual(calls, [])


class TestBatchTextModeReachesTheRegistry(unittest.TestCase):
    def test_batch_text_entries_query_openalex(self):
        import larp_meter.cli as cli_mod
        captured = []
        orig_save_all = cli_mod.save_all
        cli_mod.save_all = lambda report, *a, **kw: captured.append(report) or []
        with tempfile.TemporaryDirectory() as tmp:
            batch_path = Path(tmp) / "batch.jsonl"
            batch_path.write_text(
                json.dumps({"name": "Ada Lovelace", "text": BIO_NO_IDENTIFIERS}) + "\n",
                encoding="utf-8")
            args = build_parser().parse_args([
                "--batch", str(batch_path), "--verify", "--no-save",
                "--csv", str(Path(tmp) / "out.csv"),
            ])
            fetcher = _stub_fetcher({"wikipedia.org": WIKI_BODY, "openalex.org": OPENALEX_BODY})
            http = _stub_http({"openalex.org": OPENALEX_BODY})
            try:
                with mock.patch("larp_meter.cli.make_fetcher", fetcher), \
                     mock.patch.object(reconcile, "_http", http), \
                     mock.patch("larp_meter.cli.OUTPUT_DIR", Path(tmp) / "output"), _silent():
                    cmd_batch(args)
            finally:
                cli_mod.save_all = orig_save_all
            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0]["signals"]["openalex"]["works"], 11)


class TestUrlModeReachesTheRegistry(unittest.TestCase):
    def test_url_mode_queries_openalex_for_the_named_subject(self):
        args = build_parser().parse_args([
            "--url", "https://github.com/adalovelace", "--name", "Ada Lovelace",
            "--text", BIO_NO_IDENTIFIERS, "--verify", "--quiet", "--no-save",
        ])
        fetcher = _stub_fetcher({"wikipedia.org": WIKI_BODY, "openalex.org": OPENALEX_BODY,
                                 "api.github.com": ""})
        http = _stub_http({"openalex.org": OPENALEX_BODY})
        import larp_meter.cli as cli_mod
        captured = {}
        orig_emit = cli_mod._emit
        cli_mod._emit = lambda report, a: captured.setdefault("report", report)
        try:
            with mock.patch("larp_meter.cli.make_fetcher", fetcher), \
                 mock.patch.object(reconcile, "_http", http), _silent():
                cmd_url(args)
        finally:
            cli_mod._emit = orig_emit
        self.assertEqual(captured["report"]["signals"]["openalex"]["works"], 11)


if __name__ == "__main__":
    unittest.main()
