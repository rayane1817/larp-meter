"""Regression tests for defects found by adversarial review of v3.

Each test names the harm it prevents. The theme is one failure mode: the tool
turning an absence of evidence — a placeholder name, an empty author list, a
blocked network, a regex that did not match — into a statement about a real
person.
"""

import json
import tempfile
import unittest
from pathlib import Path

from larp_meter import TRIGGERED, PASSED, UNKNOWN, names
from larp_meter import extract as ex
from larp_meter.audit import run_audit
from larp_meter.extract import Claim, VERIFIED, MISMATCH, NOT_FOUND, UNCHECKABLE
from larp_meter.matching import host_matches
from larp_meter.report import render_html, save_all
from tests.test_verify import StubVerifier, CROSSREF_OK


def flag(text, fid, **kw):
    return next(f for f in run_audit("t", text, mode="text", **kw)["flags"] if f["id"] == fid)


class TestNoAccusationFromAbsence(unittest.TestCase):
    """The verifier must never manufacture a MISMATCH out of missing data."""

    def test_placeholder_target_is_not_used_as_a_subject_name(self):
        """`--verify --text` passed the UI label "pasted-text" as the person's
        name, so every genuine artifact came back MISMATCH."""
        r = run_audit("pasted-text", "Our paper: 10.1000/xyz.", mode="text")
        self.assertEqual(r["target"], "pasted-text")
        # subject_name is not defaulted from target anywhere in the pipeline
        self.assertNotIn("pasted", json.dumps(r["claims"]))

    def test_empty_author_list_is_unanswerable_not_a_mismatch(self):
        body = json.dumps({"message": {"title": ["A Book"], "author": []}})
        v = StubVerifier({"api.crossref.org": (body, True)}, subject_name="Ada Lovelace")
        claim = Claim(kind="artifact", subtype="doi", value="10.1000/xyz")
        v.verify_doi(claim)
        self.assertEqual(claim.status, UNCHECKABLE)

    def test_private_orcid_name_is_not_a_mismatch(self):
        body = json.dumps({"name": None})
        v = StubVerifier({"pub.orcid.org": (body, True)}, subject_name="Ada Lovelace")
        claim = Claim(kind="artifact", subtype="orcid", value="0000-0002-1825-0097")
        v.verify_orcid(claim)
        self.assertEqual(claim.status, UNCHECKABLE)

    def test_arxiv_error_feed_is_not_a_mismatch(self):
        """arXiv serves errors as a 200 OK feed titled 'Error'."""
        body = ("<feed xmlns='http://www.w3.org/2005/Atom'><entry>"
                "<id>http://arxiv.org/api/errors#bad_id</id><title>Error</title>"
                "<author><name>arXiv api core</name></author></entry></feed>")
        v = StubVerifier({"arxiv.org": (body, True)}, subject_name="Ada Lovelace")
        claim = Claim(kind="artifact", subtype="arxiv", value="9999.99999")
        v.verify_arxiv(claim)
        self.assertEqual(claim.status, NOT_FOUND)

    def test_patent_scrape_failure_is_not_a_mismatch(self):
        """If Google's markup drifts, no inventors parse — that is our failure."""
        body = "<html><title>US10123456 - A Widget - Google Patents</title><body></body></html>"
        v = StubVerifier({"patents.google.com": (body, True)}, subject_name="Ada Lovelace")
        claim = Claim(kind="artifact", subtype="patent", value="US10123456")
        v.verify_patent(claim)
        self.assertEqual(claim.status, UNCHECKABLE)

    def test_patent_inventor_entities_are_decoded_before_comparison(self):
        body = ("<html><title>US10123456 - A Widget</title>"
                "<dd itemprop=\"inventor\">Jos&#233; &#193;lvarez</dd></html>")
        v = StubVerifier({"patents.google.com": (body, True)}, subject_name="Jose Alvarez")
        claim = Claim(kind="artifact", subtype="patent", value="US10123456")
        v.verify_patent(claim)
        self.assertEqual(claim.status, VERIFIED)

    def test_name_matches_returns_none_for_empty_candidates(self):
        self.assertIsNone(names.name_matches("Ada Lovelace", []))
        self.assertIsNone(names.name_matches("Ada Lovelace", ["", "  "]))

    def test_a_genuine_mismatch_still_reports(self):
        """The guard rails must not disarm the actual signal."""
        v = StubVerifier({"api.crossref.org": (CROSSREF_OK, True)}, subject_name="Rex Falsum")
        claim = Claim(kind="artifact", subtype="doi", value="10.1000/xyz")
        v.verify_doi(claim)
        self.assertEqual(claim.status, MISMATCH)


class TestNoDoubleCounting(unittest.TestCase):
    def test_one_registry_result_moves_one_flag(self):
        """A MISMATCH triggered flags 6 and 11 on the same fact — 4.0 of 17.0
        total weight, with the evidence printed twice."""
        text = "Founder building AI. Our paper: 10.1000/xyz."
        r = run_audit("t", text, mode="text", verify=False)
        f6 = next(f for f in r["flags"] if f["id"] == 6)
        self.assertEqual(f6["status"], PASSED)   # presence, not verification outcome


class TestInstitutionMatching(unittest.TestCase):
    def test_inflected_name_is_not_called_a_different_organization(self):
        """'Karolinska Institute' vs the registry's 'Karolinska Institutet'."""
        body = json.dumps({"items": [{
            "id": "https://ror.org/056d84691",
            "names": [{"value": "Karolinska Institutet", "types": ["ror_display"]}],
            "locations": [{"geonames_details": {"country_name": "Sweden"}}]}]})
        v = StubVerifier({"api.ror.org": (body, True)})
        claim = Claim(kind="degree", subtype="institution", value="Karolinska Institute")
        v.verify_institution(claim)
        self.assertEqual(claim.status, VERIFIED)

    def test_absence_is_phrased_as_a_lead_not_a_finding(self):
        body = json.dumps({"items": [{
            "id": "x", "names": [{"value": "Institute of Advanced Studies"}], "locations": []}]})
        v = StubVerifier({"api.ror.org": (body, True)})
        claim = Claim(kind="degree", subtype="institution",
                      value="Institute of Advanced Fictional Studies")
        v.verify_institution(claim)
        self.assertEqual(claim.status, NOT_FOUND)
        self.assertNotIn("different organization", claim.detail)
        self.assertIn("confirm", claim.detail.lower())


class TestCredentialFlagFairness(unittest.TestCase):
    def test_unparsed_institution_is_undecidable(self):
        self.assertEqual(flag("I hold an MSc in public health policy.", 8)["status"], UNKNOWN)

    def test_employer_does_not_satisfy_a_degree_claim(self):
        text = ("Jan holds an MBA. He spent two years as a communications officer at the "
                "Fraunhofer Institute.")
        self.assertEqual(flag(text, 8)["status"], UNKNOWN)

    def test_ror_absence_only_counts_when_verification_ran(self):
        self.assertNotEqual(
            flag("MSc Physics, Nowhere University, 2010.", 8)["status"], TRIGGERED)

    def test_a_doctorate_alone_does_not_clear_a_domain_claim(self):
        """'phd'/'doctorate'/'postdoc' sat in the SCIENCE *field* list, so a
        doctorate in anything cleared the deep-tech credential check via
        science->technology adjacency."""
        unrecognised_field = ("Founder building semiconductor and neural network hardware. "
                              "PhD in medieval history, University of Ghent, 2011.")
        self.assertEqual(flag(unrecognised_field, 1)["status"], UNKNOWN)

        wrong_field = ("Founder building semiconductor and neural network hardware. "
                       "PhD in marketing, University of Ghent, 2011.")
        self.assertEqual(flag(wrong_field, 1)["status"], TRIGGERED)

    def test_a_real_science_doctorate_still_clears_it(self):
        text = ("Founder building semiconductor and neural network hardware. "
                "PhD in physics, University of Ghent, 2011.")
        self.assertEqual(flag(text, 1)["status"], PASSED)

    def test_education_trigger_needs_a_word_boundary(self):
        """'read' matched inside 'already'/'spread', inventing an education context."""
        from larp_meter import domains as dom
        spans = " ".join(dom.education_spans(
            "We already spread our bread thin across physics and chemistry projects."))
        self.assertEqual(spans, "")


class TestTimelineFlag(unittest.TestCase):
    def test_forward_looking_target_is_not_a_fabricated_date(self):
        text = ("Founder building satellite hardware. Full deployment is targeted for 2030. "
                "MSc Aerospace Engineering, Delft University of Technology, 2015.")
        self.assertNotEqual(flag(text, 12)["status"], TRIGGERED)

    def test_units_are_not_years(self):
        text = ("Engineer building radiation tolerant hardware. Our device operates at 2040 MHz. "
                "MSc Electrical Engineering, Delft University of Technology, 2012.")
        self.assertNotEqual(flag(text, 12)["status"], TRIGGERED)

    def test_identifier_digits_are_not_career_dates(self):
        text = ("Engineer with 22 years of experience building semiconductor hardware; "
                "see doi 10.1109/TNS.2023.3241234. MSc Electrical Engineering, 1999.")
        self.assertNotEqual(flag(text, 12)["status"], TRIGGERED)

    def test_a_genuine_impossible_span_still_triggers(self):
        text = ("Founder and CEO building satellite propulsion. 40 years of experience. "
                "MSc Aerospace Engineering, Delft University of Technology, 2019.")
        self.assertEqual(flag(text, 12)["status"], TRIGGERED)


class TestHostMatching(unittest.TestCase):
    def test_substring_lookalikes_are_not_self_published(self):
        """'x.com' in the bank matched vox.com, xerox.com and netflix.com, so
        genuine press was reported as the subject's own platform."""
        bank = ["x.com", "linkedin.com", "medium.com"]
        for url in ("https://www.vox.com/a", "https://www.xerox.com/b", "https://netflix.com/c"):
            self.assertFalse(host_matches(url, bank), url)

    def test_real_controlled_hosts_still_match(self):
        bank = ["x.com", "linkedin.com", "medium.com"]
        for url in ("https://x.com/u", "https://www.linkedin.com/in/u", "https://sub.medium.com/p"):
            self.assertTrue(host_matches(url, bank), url)

    def test_independent_press_passes_the_validation_flag(self):
        text = ("Founder and chief executive building satellite hardware and machine learning "
                "systems for a deep tech venture with a substantial engineering team today.")
        r = run_audit("t", text, mode="web", source_urls=["https://www.vox.com/article"])
        self.assertEqual(next(f for f in r["flags"] if f["id"] == 10)["status"], PASSED)


class TestSearchFailureIsNotEvidence(unittest.TestCase):
    def test_unreachable_search_layer_makes_validation_undecidable(self):
        text = ("Founder and chief executive building satellite hardware and machine learning "
                "systems for a deep tech venture with a substantial engineering team today.")
        r = run_audit("t", text, mode="web", source_urls=[], signals={"search_ok": False})
        self.assertEqual(next(f for f in r["flags"] if f["id"] == 10)["status"], UNKNOWN)


class TestHtmlSafety(unittest.TestCase):
    def _attrs(self, html):
        from html.parser import HTMLParser
        found = []

        class P(HTMLParser):
            def handle_starttag(_self, tag, attrs):
                found.extend((tag, k, v) for k, v in attrs)
        P().feed(html)
        return found

    def test_single_quote_cannot_break_out_of_an_attribute(self):
        """Every attribute in the report is single-quoted; _esc did not escape '."""
        r = run_audit("x' onmouseover='alert(1)", "Founder building AI.")
        attrs = self._attrs(render_html(r))
        self.assertFalse([a for a in attrs if a[1].startswith("on")],
                         "a live event handler was injected into the report")

    def test_javascript_urls_are_not_linked(self):
        r = run_audit("t", "Founder building AI.")
        r["sources"] = ["javascript:alert(1)", "https://good.example/ok"]
        attrs = self._attrs(render_html(r))
        self.assertFalse([a for a in attrs
                          if a[1] == "href" and str(a[2]).lower().startswith("javascript:")])

    def test_escaping_is_actually_exercised(self):
        """The previous XSS test passed with escaping disabled entirely."""
        from larp_meter.report import _esc
        self.assertEqual(_esc("<a href='x' title=\"y\">&"),
                         "&lt;a href=&#x27;x&#x27; title=&quot;y&quot;&gt;&amp;")


class TestFileOutputs(unittest.TestCase):
    def test_no_save_still_writes_explicitly_requested_files(self):
        r = run_audit("t", "Founder building AI.")
        with tempfile.TemporaryDirectory() as d:
            out, html = Path(d) / "out", Path(d) / "r.html"
            written = save_all(r, out, html_path=html, write_json=False)
            self.assertEqual([Path(p).name for p in written], ["r.html"])
            self.assertFalse(out.exists())

    def test_batch_runs_do_not_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out"
            for i, name in enumerate(("Jan de Vries", "Jan De Vries!"), 1):
                r = run_audit(name, "Founder building AI.")
                save_all(r, out, unique_suffix=f"{i:03d}")
            self.assertEqual(len(list(out.glob("*.json"))), 2)


if __name__ == "__main__":
    unittest.main()


class TestRemainingReviewFindings(unittest.TestCase):
    def test_domain_ties_do_not_default_to_technology(self):
        """Ties resolved by dict order, and technology is declared first — so any
        mixed-field professional was pulled into the domain scored hardest."""
        from larp_meter import domains as dom
        prof = {"technology": {"claims": ["hardware"], "credentials": [], "roles": []},
                "finance": {"claims": ["hedge fund"], "credentials": [], "roles": ["trader"]}}
        self.assertEqual(dom._top(prof, "claims")[0], "finance")  # role support breaks the tie

    def test_reporting_on_a_field_is_not_claiming_to_work_in_it(self):
        text = ("Technology journalist covering artificial intelligence and semiconductor "
                "hardware. MA in journalism, University of Ghent, 2012. Ten years as a "
                "reporter and press officer.")
        self.assertEqual(flag(text, 1)["status"], PASSED)

    def test_but_a_senior_title_in_the_domain_still_counts_as_a_claim(self):
        text = ("Chief Medical Officer of Helix Diagnostics, delivering clinical treatment and "
                "patient care. MBA in management. Former account manager and press officer.")
        self.assertEqual(flag(text, 1)["status"], TRIGGERED)

    def test_nested_buzzwords_are_counted_once(self):
        from larp_meter.matching import find_non_overlapping
        distinct, hits = find_non_overlapping("A true paradigm shift.",
                                              ["paradigm", "paradigm shift"])
        self.assertEqual((distinct, hits), (["paradigm shift"], 1))

    def test_honorifics_are_not_partner_organizations(self):
        claims = ex.extract_claims("Partnership with Dr. Smith and partnership with Orion Systems.")
        self.assertEqual([c.value for c in ex.claims_by(claims, "partnership", "partner_org")],
                         ["Orion Systems"])

    def test_arxiv_is_queried_over_tls(self):
        """On plaintext an on-path attacker could forge an attribution result."""
        v = StubVerifier({})
        claim = Claim(kind="artifact", subtype="arxiv", value="2101.00001")
        v.verify_arxiv(claim)
        self.assertTrue(v.requested and v.requested[0].startswith("https://"))

    def test_github_token_is_never_sent_to_another_host(self):
        """The token was attached on a substring test of the whole URL, so a
        path or query containing the API hostname leaked the credential."""
        import os
        import urllib.request
        from larp_meter.verify import Verifier

        captured = []

        class FakeResponse:
            headers = {"Content-Type": "application/json"}

            def read(self, *a):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            captured.append((req.full_url, dict(req.headers)))
            return FakeResponse()

        real_urlopen = urllib.request.urlopen
        os.environ["GITHUB_TOKEN"] = "secret-token"
        urllib.request.urlopen = fake_urlopen
        try:
            v = Verifier(tempfile.mkdtemp())
            v._get("https://evil.example/api.github.com/steal")
            v._get("https://api.github.com/users/someone")
        finally:
            urllib.request.urlopen = real_urlopen
            os.environ.pop("GITHUB_TOKEN", None)

        headers_by_host = {url: hdrs for url, hdrs in captured}
        evil = headers_by_host["https://evil.example/api.github.com/steal"]
        good = headers_by_host["https://api.github.com/users/someone"]
        self.assertNotIn("Authorization", {k.title(): v for k, v in evil.items()})
        self.assertIn("Authorization", {k.title(): v for k, v in good.items()})

    def test_user_errors_are_messages_not_tracebacks(self):
        from larp_meter.cli import main
        self.assertEqual(main(["--file", "/definitely/not/here.txt"]), 2)
