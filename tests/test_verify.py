"""Verification tests — fully offline. Every registry call is stubbed."""

import json
import tempfile
import unittest
from pathlib import Path

from larp_meter.extract import (Claim, VERIFIED, MISMATCH, NOT_FOUND, UNCHECKABLE)
from larp_meter.verify import Verifier


class StubVerifier(Verifier):
    """Verifier with the network replaced by a canned {url_substring: (body, ok)} map."""

    def __init__(self, responses, **kw):
        kw.setdefault("cache_dir", tempfile.mkdtemp())
        super().__init__(**kw)
        self.responses = responses
        self.requested = []

    def _get(self, url, accept="application/json"):
        self.requested.append(url)
        for needle, value in self.responses.items():
            if needle in url:
                return value
        return "", False


CROSSREF_OK = json.dumps({"message": {
    "title": ["A Study of Underwater SLAM"],
    "author": [{"given": "Ada", "family": "Lovelace"},
               {"given": "Grace", "family": "Hopper"}]}})


class TestOfflineSafety(unittest.TestCase):
    def test_network_failure_is_never_evidence(self):
        """An unreachable registry must yield UNCHECKABLE, not NOT_FOUND."""
        v = StubVerifier({}, subject_name="Ada Lovelace")
        claim = Claim(kind="artifact", subtype="doi", value="10.1000/xyz")
        v.verify_doi(claim)
        self.assertEqual(claim.status, UNCHECKABLE)

    def test_disabled_verifier_makes_no_calls(self):
        v = Verifier(cache_dir=tempfile.mkdtemp(), enabled=False)
        claim = Claim(kind="artifact", subtype="doi", value="10.1000/xyz")
        v.verify_doi(claim)
        self.assertEqual(claim.status, UNCHECKABLE)
        self.assertEqual(v.calls, 0)

    def test_verifier_exception_does_not_propagate(self):
        class Exploding(StubVerifier):
            def verify_doi(self, claim):
                raise RuntimeError("boom")

        v = Exploding({})
        claims = [Claim(kind="artifact", subtype="doi", value="10.1/x")]
        v.verify_all(claims)
        self.assertEqual(claims[0].status, UNCHECKABLE)
        self.assertIn("verifier error", claims[0].detail)


class TestAttribution(unittest.TestCase):
    def test_existing_doi_with_matching_author_is_verified(self):
        v = StubVerifier({"api.crossref.org": (CROSSREF_OK, True)}, subject_name="Ada Lovelace")
        claim = Claim(kind="artifact", subtype="doi", value="10.1000/xyz")
        v.verify_doi(claim)
        self.assertEqual(claim.status, VERIFIED)

    def test_existing_doi_without_the_subject_is_a_mismatch(self):
        """Existence is not attribution — the point of the whole verification layer."""
        v = StubVerifier({"api.crossref.org": (CROSSREF_OK, True)}, subject_name="Rex Falsum")
        claim = Claim(kind="artifact", subtype="doi", value="10.1000/xyz")
        v.verify_doi(claim)
        self.assertEqual(claim.status, MISMATCH)

    def test_without_subject_name_attribution_is_not_asserted(self):
        v = StubVerifier({"api.crossref.org": (CROSSREF_OK, True)}, subject_name="")
        claim = Claim(kind="artifact", subtype="doi", value="10.1000/xyz")
        v.verify_doi(claim)
        self.assertEqual(claim.status, VERIFIED)
        self.assertIn("--name", claim.detail)

    def test_404_means_not_found(self):
        v = StubVerifier({"api.crossref.org": ("", True)}, subject_name="Ada Lovelace")
        claim = Claim(kind="artifact", subtype="doi", value="10.1000/nope")
        v.verify_doi(claim)
        self.assertEqual(claim.status, NOT_FOUND)


class TestRegistries(unittest.TestCase):
    def test_github_repo(self):
        body = json.dumps({"stargazers_count": 12, "pushed_at": "2024-03-01T00:00:00Z", "size": 900})
        v = StubVerifier({"api.github.com/repos": (body, True)})
        claim = Claim(kind="artifact", subtype="github", value="acme/slam")
        v.verify_github(claim)
        self.assertEqual(claim.status, VERIFIED)
        self.assertIn("12 stars", claim.detail)

    def test_github_empty_repo_is_reported(self):
        body = json.dumps({"stargazers_count": 0, "pushed_at": "2024-01-01T00:00:00Z", "size": 0})
        v = StubVerifier({"api.github.com/repos": (body, True)})
        claim = Claim(kind="artifact", subtype="github", value="acme/vapor")
        v.verify_github(claim)
        self.assertIn("EMPTY", claim.detail)

    def test_missing_github_repo(self):
        v = StubVerifier({"api.github.com": ("", True)})
        claim = Claim(kind="artifact", subtype="github", value="acme/ghost")
        v.verify_github(claim)
        self.assertEqual(claim.status, NOT_FOUND)

    def test_institution_not_in_registry(self):
        v = StubVerifier({"api.ror.org": (json.dumps({"items": []}), True)})
        claim = Claim(kind="degree", subtype="institution", value="Fictional Diploma Mill")
        v.verify_institution(claim)
        self.assertEqual(claim.status, NOT_FOUND)

    def test_institution_found_v2_schema(self):
        """ROR v2 returns `names` (a list), not `name`."""
        body = json.dumps({"items": [{
            "id": "https://ror.org/02e2c7k09",
            "names": [{"value": "Delft University of Technology", "types": ["ror_display"]},
                      {"value": "TU Delft", "types": ["alias"]}],
            "locations": [{"geonames_details": {"country_name": "Netherlands"}}]}]})
        v = StubVerifier({"api.ror.org": (body, True)})
        claim = Claim(kind="degree", subtype="institution", value="Delft University of Technology")
        v.verify_institution(claim)
        self.assertEqual(claim.status, VERIFIED)
        self.assertIn("Netherlands", claim.detail)

    def test_word_order_and_stopwords_do_not_break_the_match(self):
        """'University of Ghent' must match the registry's 'Ghent University'."""
        body = json.dumps({"items": [{
            "id": "https://ror.org/00cv9y106",
            "names": [{"value": "Ghent University", "types": ["ror_display"]}],
            "locations": [{"geonames_details": {"country_name": "Belgium"}}]}]})
        v = StubVerifier({"api.ror.org": (body, True)})
        claim = Claim(kind="degree", subtype="institution", value="University of Ghent")
        v.verify_institution(claim)
        self.assertEqual(claim.status, VERIFIED)

    def test_fabricated_institution_is_not_verified_by_a_fuzzy_hit(self):
        """The bug this guards: ROR fuzzy-matches anything, so items[0] existing
        proves nothing. An invented word in the claim must be disqualifying."""
        body = json.dumps({"items": [{
            "id": "https://ror.org/abc",
            "names": [{"value": "Institute of Advanced Studies", "types": ["ror_display"]}],
            "locations": [{"geonames_details": {"country_name": "Brazil"}}]}]})
        v = StubVerifier({"api.ror.org": (body, True)})
        claim = Claim(kind="degree", subtype="institution",
                      value="Institute of Advanced Fictional Studies")
        v.verify_institution(claim)
        self.assertEqual(claim.status, NOT_FOUND)
        self.assertIn("Institute of Advanced Studies", claim.detail)  # names the near miss

    def test_registry_name_is_never_echoed_from_the_claim(self):
        """Old bug: .get('name', claim.value) reported the claim back as proof."""
        body = json.dumps({"items": [{"id": "x", "names": [], "locations": []}]})
        v = StubVerifier({"api.ror.org": (body, True)})
        claim = Claim(kind="degree", subtype="institution", value="Totally Made Up University")
        v.verify_institution(claim)
        self.assertEqual(claim.status, NOT_FOUND)
        self.assertNotIn("Real institution: Totally Made Up University", claim.detail)

    def test_short_acronym_match_is_reported_as_ambiguous(self):
        body = json.dumps({"items": [{
            "id": "https://ror.org/xyz",
            "names": [{"value": "MIT", "types": ["acronym"]}],
            "locations": [{"geonames_details": {"country_name": "Philippines"}}]}]})
        v = StubVerifier({"api.ror.org": (body, True)})
        claim = Claim(kind="degree", subtype="institution", value="MIT")
        v.verify_institution(claim)
        self.assertEqual(claim.status, VERIFIED)
        self.assertIn("ambiguous", claim.detail)

    def test_clinical_trial(self):
        body = json.dumps({"protocolSection": {
            "identificationModule": {"briefTitle": "A Trial of Something"},
            "statusModule": {"overallStatus": "COMPLETED"}}})
        v = StubVerifier({"clinicaltrials.gov": (body, True)})
        claim = Claim(kind="artifact", subtype="nct", value="NCT01234567")
        v.verify_nct(claim)
        self.assertEqual(claim.status, VERIFIED)
        self.assertIn("COMPLETED", claim.detail)

    def test_verify_all_only_touches_checkable_subtypes(self):
        v = StubVerifier({"api.ror.org": (json.dumps({"items": []}), True)})
        claims = [Claim(kind="degree", subtype="institution", value="Nowhere University"),
                  Claim(kind="timeline", subtype="year", value="2015")]
        v.verify_all(claims)
        self.assertEqual(claims[0].status, NOT_FOUND)
        self.assertEqual(claims[1].status, "UNCHECKED")


if __name__ == "__main__":
    unittest.main()
