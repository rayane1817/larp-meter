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
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


def _silent():
    """Swallow whatever a cmd_* call prints, on any platform's console encoding."""
    return contextlib.redirect_stdout(io.StringIO())


class TestTextModeReachesTheRegistry(unittest.TestCase):
    def test_text_mode_with_verify_and_name_queries_openalex_and_wikipedia(self):
        """Flag 6 must be able to see an independent scholarly record even when
        the pasted bio itself carries no DOI, ORCID or other identifier."""
        args = build_parser().parse_args([
            "--text", BIO_NO_IDENTIFIERS, "--name", "Ada Lovelace",
            "--verify", "--quiet", "--no-save",
        ])
        fetcher = _stub_fetcher({"wikipedia.org": WIKI_BODY, "openalex.org": OPENALEX_BODY})
        with mock.patch("larp_meter.cli.make_fetcher", fetcher), _silent():
            report = cmd_text(args, "Ada Lovelace", BIO_NO_IDENTIFIERS)
        flag6 = next(f for f in report["flags"] if f["id"] == 6)
        self.assertEqual(flag6["status"], "PASSED")
        self.assertIn("OpenAlex", flag6["description"])
        self.assertEqual(report["signals"]["openalex"]["works"], 11)

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
        with mock.patch("larp_meter.cli.make_fetcher", fetcher), _silent():
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
            try:
                with mock.patch("larp_meter.cli.make_fetcher", fetcher), \
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
        import larp_meter.cli as cli_mod
        captured = {}
        orig_emit = cli_mod._emit
        cli_mod._emit = lambda report, a: captured.setdefault("report", report)
        try:
            with mock.patch("larp_meter.cli.make_fetcher", fetcher), _silent():
                cmd_url(args)
        finally:
            cli_mod._emit = orig_emit
        self.assertEqual(captured["report"]["signals"]["openalex"]["works"], 11)


if __name__ == "__main__":
    unittest.main()
