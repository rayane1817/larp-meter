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

    def test_family_name_first_author_is_not_falsely_mismatched(self):
        """Regression, exercised through the real verify_doi dispatch rather
        than names.name_matches in isolation: an honest researcher whose
        family name comes first ('Zhang Wei', abbreviated by Crossref as
        'W. Zhang') used to fall through to MISMATCH -- floored at ORANGE by
        flag 11 -- purely because the surname-position check only ever
        looked at the LAST token of the subject's name."""
        body = json.dumps({"message": {
            "title": ["A Sparse Attention Kernel for Edge Inference"],
            "author": [{"given": "W.", "family": "Zhang"},
                       {"given": "M.", "family": "Chen"}]}})
        v = StubVerifier({"api.crossref.org": (body, True)}, subject_name="Zhang Wei")
        claim = Claim(kind="artifact", subtype="doi", value="10.1145/xyz")
        v.verify_doi(claim)
        self.assertEqual(claim.status, VERIFIED)

    def test_unanswerable_name_comparison_is_not_a_mismatch(self):
        """`_attribute` had `elif match: VERIFIED / else: MISMATCH` — the exact
        two-outcome conflation its own docstring warns against. name_matches
        can return None (unanswerable), and None is exactly as falsy as
        False, so it fell straight into the else branch. A Hispanic surname
        published under only its first half ('J. Ramirez' for 'Jose Ramirez
        Ortega') was reported as contradicting its own author's paper --
        floored at ORANGE by flag 11, the tool's strongest verdict, on a
        citation that was entirely genuine."""
        body = json.dumps({"message": {
            "title": ["Some Paper"], "author": [{"given": "J.", "family": "Ramirez"}]}})
        v = StubVerifier({"api.crossref.org": (body, True)}, subject_name="Jose Ramirez Ortega")
        claim = Claim(kind="artifact", subtype="doi", value="10.1000/xyz")
        v.verify_doi(claim)
        self.assertEqual(claim.status, UNCHECKABLE)
        self.assertNotEqual(claim.status, MISMATCH)

    def test_non_latin_registry_record_is_not_a_mismatch(self):
        """Same conflation, via the script-mismatch branch of name_matches:
        a record held in Cyrillic cannot be compared to a Latin subject name
        by a tool that folds diacritics but does not transliterate. That is
        a limit of what the tool can read, not evidence of a different
        author, and must not resolve to the accusation."""
        body = json.dumps({"message": {
            "title": ["Some Paper"],
            "author": [{"given": "Михаил", "family": "Иванов"}]}})
        v = StubVerifier({"api.crossref.org": (body, True)}, subject_name="Mikhail Ivanov")
        claim = Claim(kind="artifact", subtype="doi", value="10.1000/xyz")
        v.verify_doi(claim)
        self.assertEqual(claim.status, UNCHECKABLE)
        self.assertNotEqual(claim.status, MISMATCH)


class TestRegistries(unittest.TestCase):
    def test_github_repo_records_existence_without_claiming_attribution(self):
        """Owning a repo is not writing it, and citing an employer's repo is
        normal. Existence must not be reported as confirmation — doing so let a
        subject cite a stranger's famous repository and be credited with it."""
        body = json.dumps({"stargazers_count": 12, "pushed_at": "2024-03-01T00:00:00Z",
                           "size": 900, "owner": {"login": "acme"}})
        v = StubVerifier({"api.github.com/repos": (body, True)}, subject_name="Ada Lovelace")
        claim = Claim(kind="artifact", subtype="github", value="acme/slam")
        v.verify_github(claim)
        self.assertEqual(claim.status, UNCHECKABLE)
        self.assertIn("12 stars", claim.detail)
        self.assertIn("acme", claim.detail)

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
        claim = Claim(kind="degree", subtype="degree_institution", value="Fictional Diploma Mill")
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
        claim = Claim(kind="degree", subtype="degree_institution", value="Delft University of Technology")
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
        claim = Claim(kind="degree", subtype="degree_institution", value="University of Ghent")
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
        claim = Claim(kind="degree", subtype="degree_institution",
                      value="Institute of Advanced Fictional Studies")
        v.verify_institution(claim)
        self.assertEqual(claim.status, NOT_FOUND)
        self.assertIn("Institute of Advanced Studies", claim.detail)  # names the near miss

    def test_registry_name_is_never_echoed_from_the_claim(self):
        """Old bug: .get('name', claim.value) reported the claim back as proof."""
        body = json.dumps({"items": [{"id": "x", "names": [], "locations": []}]})
        v = StubVerifier({"api.ror.org": (body, True)})
        claim = Claim(kind="degree", subtype="degree_institution", value="Totally Made Up University")
        v.verify_institution(claim)
        self.assertEqual(claim.status, NOT_FOUND)
        self.assertNotIn("Real institution: Totally Made Up University", claim.detail)

    def test_short_acronym_match_is_reported_as_ambiguous(self):
        body = json.dumps({"items": [{
            "id": "https://ror.org/xyz",
            "names": [{"value": "MIT", "types": ["acronym"]}],
            "locations": [{"geonames_details": {"country_name": "Philippines"}}]}]})
        v = StubVerifier({"api.ror.org": (body, True)})
        claim = Claim(kind="degree", subtype="degree_institution", value="MIT")
        v.verify_institution(claim)
        self.assertEqual(claim.status, VERIFIED)
        self.assertIn("ambiguous", claim.detail)

    def test_clinical_trial_records_existence_without_claiming_attribution(self):
        """A trial's officials are its PIs, not a roster of every contributor,
        so the record cannot confirm or refute a person's involvement."""
        body = json.dumps({"protocolSection": {
            "identificationModule": {"briefTitle": "A Trial of Something"},
            "statusModule": {"overallStatus": "COMPLETED"},
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": "NCI"}},
            "contactsLocationsModule": {"overallOfficials": [{"name": "Jane Roe, MD"}]}}})
        v = StubVerifier({"clinicaltrials.gov": (body, True)}, subject_name="Ada Lovelace")
        claim = Claim(kind="artifact", subtype="nct", value="NCT01234567")
        v.verify_nct(claim)
        self.assertEqual(claim.status, UNCHECKABLE)
        self.assertIn("COMPLETED", claim.detail)
        self.assertIn("Jane Roe", claim.detail)   # named for a human to judge

    def test_verify_all_only_touches_checkable_subtypes(self):
        v = StubVerifier({"api.ror.org": (json.dumps({"items": []}), True)})
        claims = [Claim(kind="degree", subtype="degree_institution", value="Nowhere University"),
                  Claim(kind="timeline", subtype="year", value="2015")]
        v.verify_all(claims)
        self.assertEqual(claims[0].status, NOT_FOUND)
        self.assertEqual(claims[1].status, "UNCHECKED")


class TestExistenceIsNotAttribution(unittest.TestCase):
    """Design rule #2 in verify.py's own docstring, which two handlers broke.

    verify_github and verify_nct set VERIFIED on existence alone, so flag 11 —
    the heaviest flag in the registry — reported "All 2 checked identifier(s)
    confirmed by their registries" for a subject who had cited a stranger's
    repository and an unrelated NIH trial.
    """

    GH_REPO = json.dumps({"stargazers_count": 190000, "pushed_at": "2026-08-01",
                          "size": 4200000, "owner": {"login": "torvalds"}})
    NCT = json.dumps({"protocolSection": {
        "identificationModule": {"briefTitle": "Unrelated Study"},
        "statusModule": {"overallStatus": "COMPLETED"}}})

    def _flag11(self, claims, subject):
        from larp_meter.flags import AuditContext, FLAG_BY_ID
        from larp_meter.matching import load_banks
        ctx = AuditContext(text="I built things. " * 20, claims=claims, source_urls=[],
                           subject_name=subject, banks=load_banks(), verified=True, signals={})
        return FLAG_BY_ID[11]["fn"](ctx)

    def test_a_strangers_repo_and_trial_do_not_confirm_anything(self):
        v = StubVerifier({"api.github.com": (self.GH_REPO, True),
                          "clinicaltrials.gov": (self.NCT, True)},
                         subject_name="Marcus Vane")
        claims = [Claim(kind="artifact", subtype="github", value="torvalds/linux"),
                  Claim(kind="artifact", subtype="nct", value="NCT00000102")]
        v.verify_all(claims)
        self.assertEqual([c.status for c in claims], [UNCHECKABLE, UNCHECKABLE])

        result = self._flag11(claims, "Marcus Vane")
        self.assertNotEqual(result.status, "PASSED",
                            "existence-only checks were counted as confirmation")
        self.assertNotIn("confirmed by their registries", result.description)

    def test_a_real_authored_paper_still_confirms(self):
        """The fix must not make genuine attribution unreportable."""
        v = StubVerifier({"api.crossref.org": (CROSSREF_OK, True)}, subject_name="Ada Lovelace")
        claims = [Claim(kind="artifact", subtype="doi", value="10.1000/xyz")]
        v.verify_all(claims)
        self.assertEqual(claims[0].status, VERIFIED)
        self.assertEqual(self._flag11(claims, "Ada Lovelace").status, "PASSED")

    def test_github_user_with_a_full_published_name_is_attributed(self):
        body = json.dumps({"name": "Ada Lovelace", "public_repos": 12, "followers": 3})
        v = StubVerifier({"api.github.com/users": (body, True)}, subject_name="Ada Lovelace")
        claim = Claim(kind="artifact", subtype="github", value="adalovelace")
        v.verify_github(claim)
        self.assertEqual(claim.status, VERIFIED)

    def test_github_user_whose_account_names_someone_else_is_a_mismatch(self):
        body = json.dumps({"name": "Grace Hopper", "public_repos": 12, "followers": 3})
        v = StubVerifier({"api.github.com/users": (body, True)}, subject_name="Ada Lovelace")
        claim = Claim(kind="artifact", subtype="github", value="ghopper")
        v.verify_github(claim)
        self.assertEqual(claim.status, MISMATCH)

    def test_a_bare_handle_never_founds_a_mismatch(self):
        """Pseudonymous accounts are normal. No published name, no accusation."""
        for payload in ({"public_repos": 4}, {"name": "Marcus"}):
            with self.subTest(payload=payload):
                v = StubVerifier({"api.github.com/users": (json.dumps(payload), True)},
                                 subject_name="Ada Lovelace")
                claim = Claim(kind="artifact", subtype="github", value="mvane")
                v.verify_github(claim)
                self.assertEqual(claim.status, UNCHECKABLE)

    def test_a_missing_repo_is_still_a_real_finding(self):
        v = StubVerifier({"api.github.com": ("", True)}, subject_name="Marcus Vane")
        claim = Claim(kind="artifact", subtype="github", value="acme/ghost")
        v.verify_github(claim)
        self.assertEqual(claim.status, NOT_FOUND)


class TestExtractVerifyContract(unittest.TestCase):
    """The seam where a registry went dead without anyone noticing.

    `verify_all` dispatches on `claim.subtype` and silently drops anything it
    does not recognise. When extraction split "institution" into
    "degree_institution"/"mentioned_institution", HANDLERS kept the old key, so
    ROR was never contacted for any real audit — and a fabricated university
    came back as a *satisfied* credential flag. Every ROR test constructed the
    dead subtype by hand, so the suite stayed green throughout.
    """

    RICH_CORPUS = (
        "Dr. Ada Lovelace, CEO of Analytical Engines, holds an MSc Computer Science "
        "from Delft University of Technology and studied at the Fraunhofer Institute. "
        "See 10.1038/s41586-020-2649-2 and arxiv.org/abs/2101.00001, "
        "orcid.org/0000-0002-1825-0097, github.com/acme/slam, patent US10123456, "
        "trial NCT01234567. FDA-cleared. Partnership with Port of Rotterdam. "
        "40 customers and 2.1M revenue since 2015, with 12 years of experience."
    )

    def test_every_handler_key_is_a_subtype_extraction_can_emit(self):
        """A handler keyed on a subtype nothing produces is a dead registry."""
        from larp_meter.extract import EMITTED_SUBTYPES
        orphaned = set(Verifier.HANDLERS) - EMITTED_SUBTYPES
        self.assertEqual(orphaned, set(),
                         f"HANDLERS dispatches on subtypes extraction never emits: {sorted(orphaned)}")

    def test_declared_subtypes_match_what_extraction_really_produces(self):
        """Guards the other direction: a stale declaration would hide the above."""
        from larp_meter.extract import extract_claims, EMITTED_SUBTYPES
        produced = {c.subtype for c in extract_claims(self.RICH_CORPUS)}
        undeclared = produced - EMITTED_SUBTYPES
        self.assertEqual(undeclared, set(),
                         f"extraction emits undeclared subtypes: {sorted(undeclared)}")

    def test_a_degree_institution_actually_reaches_the_ror_verifier(self):
        """End-to-end across the seam — no hand-built Claim."""
        from larp_meter.extract import extract_claims, claims_by
        claims = extract_claims("MSc Physics, Delft University of Technology, 2015.")
        self.assertTrue(claims_by(claims, "degree", "degree_institution"),
                        "fixture did not produce a degree_institution claim")

        v = StubVerifier({"api.ror.org": (json.dumps({"items": []}), True)})
        v.verify_all(claims)
        self.assertTrue(any("api.ror.org" in u for u in v.requested),
                        "ROR was never contacted for a degree institution")

    def test_skipped_subtypes_are_reported_not_silently_dropped(self):
        """'Never checked' must be distinguishable from 'checked and clean'."""
        from larp_meter.extract import extract_claims
        claims = extract_claims("MSc Physics, Delft University of Technology, 2015.")
        v = StubVerifier({"api.ror.org": (json.dumps({"items": []}), True)})
        v.verify_all(claims)
        self.assertIn("degree", v.skipped)
        self.assertNotIn("degree_institution", v.skipped)


if __name__ == "__main__":
    unittest.main()
