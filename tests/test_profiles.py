"""Profile URLs as identity anchors.

A name is not an identifier. This module exists because auditing a bare name
merged several different people into one report; a URL names one account.
All network access is stubbed.
"""

import io
import json
import unittest
from contextlib import redirect_stdout, redirect_stderr

from larp_meter import profiles
from larp_meter.cli import main
from larp_meter.profiles import UnsupportedProfileURL, parse_profile_url


def stub(mapping):
    def fetch(url, browser=False):
        for needle, body in mapping.items():
            if needle in url:
                return body
        return ""
    return fetch


LINKEDIN_PREVIEW = (
    '<html><head>'
    '<meta property="og:title" content="Jan Fictief - Chief Widget Officer at ExampleCo | LinkedIn"/>'
    '<meta property="og:description" content="Chief Widget Officer at ExampleCo &middot; Building widgets since 2015."/>'
    '<meta property="profile:first_name" content="Jan"/>'
    '<meta property="profile:last_name" content="Fictief"/>'
    '</head><body>Sign in</body></html>')

GITHUB_USER = json.dumps({
    "login": "someuser", "name": "Jan Fictief", "bio": "Builds underwater robots",
    "public_repos": 12, "followers": 40, "created_at": "2011-09-03T00:00:00Z",
    "company": "ExampleCo", "blog": "https://example.org"})


class TestUrlParsing(unittest.TestCase):
    def test_linkedin_profile(self):
        ref = parse_profile_url("https://be.linkedin.com/in/jan-fictief")
        self.assertEqual((ref.platform, ref.handle), ("linkedin", "jan-fictief"))
        self.assertIn("be.linkedin.com", ref.url)   # country subdomain is part of the address

    def test_bare_host_is_accepted(self):
        self.assertEqual(parse_profile_url("linkedin.com/in/jan-fictief").platform, "linkedin")

    def test_github_and_orcid(self):
        self.assertEqual(parse_profile_url("https://github.com/someuser").platform, "github")
        ref = parse_profile_url("https://orcid.org/0000-0002-1825-0097")
        self.assertEqual((ref.platform, ref.handle), ("orcid", "0000-0002-1825-0097"))

    def test_a_directory_page_is_refused(self):
        """The exact page that proves a name is shared. Accepting it would
        reintroduce the bug this module exists to fix."""
        with self.assertRaises(UnsupportedProfileURL) as cm:
            parse_profile_url("https://www.linkedin.com/pub/dir/john/smith")
        self.assertIn("several people share the name", str(cm.exception))

    def test_company_school_and_search_pages_are_refused(self):
        for url in ("https://www.linkedin.com/company/acme",
                    "https://www.linkedin.com/school/some-university",
                    "https://www.linkedin.com/search?q=x"):
            with self.subTest(url=url):
                self.assertRaises(UnsupportedProfileURL, parse_profile_url, url)

    def test_github_reserved_paths_are_not_users(self):
        for url in ("https://github.com/settings", "https://github.com/orgs",
                    "https://github.com/owner/repo"):
            with self.subTest(url=url):
                self.assertRaises(UnsupportedProfileURL, parse_profile_url, url)

    def test_unknown_host_explains_the_alternative(self):
        with self.assertRaises(UnsupportedProfileURL) as cm:
            parse_profile_url("https://example.com/someone")
        self.assertIn("--text", str(cm.exception))

    def test_non_http_schemes_are_refused(self):
        for url in ("file:///etc/passwd", "ftp://example.com/x", "javascript:alert(1)"):
            with self.subTest(url=url):
                self.assertRaises(UnsupportedProfileURL, parse_profile_url, url)

    def test_empty_input(self):
        self.assertRaises(UnsupportedProfileURL, parse_profile_url, "")


class TestNameFromHandle(unittest.TestCase):
    def test_slug_becomes_a_name(self):
        self.assertEqual(profiles.name_from_handle("jan-fictief"), "Jan Fictief")

    def test_linkedin_uniqueness_suffixes_are_dropped(self):
        """LinkedIn appends a hash to disambiguate; it is not part of a name."""
        self.assertEqual(profiles.name_from_handle("jan-fictief-1a2b3c4"), "Jan Fictief")
        self.assertEqual(profiles.name_from_handle("jan-fictief-12345678"), "Jan Fictief")

    def test_underscores_and_dots(self):
        self.assertEqual(profiles.name_from_handle("jan_fictief.dev"), "Jan Fictief Dev")


class TestProfileReading(unittest.TestCase):
    def test_linkedin_preview_yields_name_and_headline(self):
        ref = parse_profile_url("https://www.linkedin.com/in/jan-fictief")
        data = profiles.read_profile(ref, stub({"linkedin.com": LINKEDIN_PREVIEW}))
        self.assertTrue(data.reachable)
        self.assertEqual(data.name, "Jan Fictief")
        self.assertIn("Chief Widget Officer", data.headline)
        self.assertIn("Building widgets", data.text)

    def test_a_block_is_reported_as_a_block(self):
        """LinkedIn answers automated requests with HTTP 999. That is a refusal,
        not an absence of substance, and the URL still anchors the identity."""
        ref = parse_profile_url("https://be.linkedin.com/in/jan-fictief")
        data = profiles.read_profile(ref, stub({}))
        self.assertFalse(data.reachable)
        self.assertEqual(data.name, "Jan Fictief")      # derived from the slug
        self.assertIn("--text", data.note)
        self.assertEqual(data.text, "")

    def test_github_returns_real_account_facts(self):
        ref = parse_profile_url("https://github.com/someuser")
        data = profiles.read_profile(ref, stub({"api.github.com": GITHUB_USER}))
        self.assertTrue(data.reachable)
        self.assertEqual(data.name, "Jan Fictief")
        self.assertEqual(data.facts["public_repos"], 12)
        self.assertEqual(data.facts["account_created"], "2011-09-03")

    def test_a_missing_github_user_is_reported(self):
        ref = parse_profile_url("https://github.com/nobody")
        data = profiles.read_profile(ref, stub({"api.github.com": json.dumps({})}))
        self.assertFalse(data.reachable)
        self.assertIn("No GitHub user", data.note)

    def test_orcid_with_a_private_name(self):
        ref = parse_profile_url("https://orcid.org/0000-0002-1825-0097")
        data = profiles.read_profile(ref, stub({"pub.orcid.org": json.dumps({"name": None})}))
        self.assertTrue(data.reachable)
        self.assertIn("private", data.note)

    def test_a_reader_error_never_propagates(self):
        def explode(url, browser=False):
            raise RuntimeError("boom")
        ref = parse_profile_url("https://github.com/someuser")
        data = profiles.read_profile(ref, explode)
        self.assertFalse(data.reachable)
        self.assertIn("error", data.note)


class TestUrlModeCli(unittest.TestCase):
    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        return code or 0, out.getvalue() + err.getvalue()

    def test_a_directory_url_exits_with_an_explanation(self):
        code, out = self._run(["--url", "https://www.linkedin.com/pub/dir/john/smith", "--no-save"])
        self.assertEqual(code, 2)
        self.assertIn("not one person's profile", out)

    def test_url_plus_pasted_text_is_scored_against_the_anchor(self):
        code, out = self._run([
            "--url", "https://be.linkedin.com/in/jan-fictief", "--no-save", "--json",
            "--text", "President at ExampleCo building radiation tolerant edge AI hardware. "
                      "MSc European Public Health. Seeking 8-12M funding. Visionary thought "
                      "leader delivering a world class paradigm shift."])
        self.assertEqual(code, 0)
        report = json.loads(out[out.index("{"):])
        self.assertEqual(report["subject_url"], "https://be.linkedin.com/in/jan-fictief")
        self.assertEqual(report["signals"]["profile_anchor"], "linkedin:jan-fictief")
        self.assertTrue(report["mode"].startswith("profile:"))

    def test_the_report_states_what_the_anchor_does_not_cover(self):
        from larp_meter.audit import run_audit
        from larp_meter.report import caveats
        report = run_audit("Jan Fictief", "Founder building AI hardware.", mode="profile:linkedin",
                           signals={"profile_anchor": "linkedin:jan-fictief",
                                    "profile_reachable": False})
        note = " ".join(caveats(report))
        self.assertIn("anchored to linkedin:jan-fictief", note)
        self.assertIn("BY NAME", note)          # corroboration is still name-based
        self.assertIn("only what you pasted", note)


if __name__ == "__main__":
    unittest.main()
