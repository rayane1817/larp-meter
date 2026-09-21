"""Verification tests — fully offline. Every registry call is stubbed."""

import json
import tempfile
import unittest
from pathlib import Path

from larp_meter.extract import (Claim, VERIFIED, MISMATCH, NOT_FOUND, UNCHECKABLE)
from larp_meter.verify import Verifier, _disclaims_authorship


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

    def test_patent_prosecuted_for_a_client_is_not_a_mismatch(self):
        """BACKLOG.md: 'Any identifier appearing anywhere in the text is
        treated as a personal authorship claim.' extract_claims harvests
        every DOI/ORCID/arXiv/patent number with no ownership context at
        all, and `_attribute` asked only 'does the registry list the
        subject' -- so a patent attorney writing 'I prosecuted US 9876543
        for a client' got the same MISMATCH, floored at ORANGE by flag 11,
        as an actual fabricator claiming someone else's invention. The
        surrounding text explicitly disclaims authorship here; `_attribute`
        must record existence without asserting -- or refuting -- that the
        subject invented it."""
        v = StubVerifier({}, subject_name="Sofia Almeida")
        claim = Claim(kind="artifact", subtype="patent", value="US9876543",
                      context="I prosecuted US 9876543 for a client in the sensor space.")
        v._attribute(claim, ["Someone Else"], "Patent US9876543 (Sensor Array)", "https://x")
        self.assertEqual(claim.status, UNCHECKABLE)
        self.assertNotEqual(claim.status, MISMATCH)

    def test_doi_cited_as_prior_art_is_not_a_mismatch(self):
        """Same failure, the other everyday phrasing: 'our approach builds
        on <doi>' cites prior work, it does not claim authorship of it."""
        v = StubVerifier({}, subject_name="Sofia Almeida")
        claim = Claim(kind="artifact", subtype="doi", value="10.5555/xyz",
                      context="our approach builds on prior work (10.5555/xyz) in the field")
        v._attribute(claim, ["Someone Else"], 'Paper "X"', "https://x")
        self.assertEqual(claim.status, UNCHECKABLE)
        self.assertNotEqual(claim.status, MISMATCH)

    def test_doi_without_disclaiming_context_is_still_checked_normally(self):
        """The guard must not swallow the ordinary, common case: an
        identifier with no surrounding disclaimer (or none captured at all,
        as when a Claim is hand-built without a context) is still fully
        attributable -- this is not a blanket downgrade of every DOI/ORCID/
        arXiv/patent claim to UNCHECKABLE."""
        v = StubVerifier({}, subject_name="Rex Falsum")
        claim = Claim(kind="artifact", subtype="doi", value="10.1000/xyz",
                      context="Our published work: 10.1000/xyz.")
        v._attribute(claim, ["Someone Else"], 'Paper "X"', "https://x")
        self.assertEqual(claim.status, MISMATCH)

    def test_a_paper_being_cited_by_others_is_not_a_disclaimer(self):
        """`_NON_ATTRIBUTION_CONTEXT_RE`'s citation alternative was written
        for the active voice ('citing prior art', 'cited in the literature
        review') but also matched the passive 'is cited BY' -- a sentence
        saying OTHER people cite the subject's own paper, the opposite of a
        disclaimer. Widening `_context()` to the whole sentence (see
        extract.py) made this reachable much more often than the old
        60-character window ever allowed: 'His landmark paper, <doi>, is
        considered foundational... and is cited by thousands of researchers
        worldwide' let a real fabrication (a fake author's name attached to
        someone else's real paper) escape to UNCHECKABLE purely because the
        word 'cited' appeared 83 characters away, describing the paper's own
        reception rather than anything the subject said about its origin."""
        context = ("His landmark paper, 10.1038/nphys1170, is considered foundational to the "
                   "field of optomechanics and is cited by thousands of researchers worldwide.")
        self.assertFalse(_disclaims_authorship(context))

    def test_citing_something_as_prior_art_is_still_a_disclaimer(self):
        """The fix above must not overcorrect: the active voice this
        alternative exists for -- the subject citing someone else's work --
        still has to disclaim."""
        context = "our approach builds on prior work, citing the original paper 10.5555/xyz throughout"
        self.assertTrue(_disclaims_authorship(context))

    def test_end_to_end_patent_citation_does_not_trigger_the_contradiction_floor(self):
        """Full pipeline, not `_attribute` in isolation: extract_claims's
        60-character context window must actually reach the guard, and flag
        11 -- this tool's only floor-carrying flag -- must not TRIGGER on a
        citation the subject's own text explicitly disclaims."""
        from larp_meter.audit import run_audit
        from larp_meter import UNKNOWN, TRIGGERED

        class PatchedVerifier(StubVerifier):
            pass

        import larp_meter.audit as audit_mod
        real_verifier = audit_mod.Verifier
        try:
            audit_mod.Verifier = lambda cache_dir, subject_name=None: StubVerifier(
                {"patents.google.com": (
                    "<title>Sensor Array Patent</title>"
                    "<dd itemprop=\"inventor\">Someone Else</dd>", True)},
                subject_name=subject_name)
            text = ("I prosecuted patent US 9876543 for a client in the sensor "
                    "space. I was not the inventor on this filing.")
            report = run_audit("t", text, verify=True, subject_name="Sofia Almeida")
        finally:
            audit_mod.Verifier = real_verifier

        claim = next(c for c in report["claims"] if c["subtype"] == "patent")
        self.assertEqual(claim["status"], UNCHECKABLE)
        flag11 = next(f for f in report["flags"] if f["id"] == 11)
        self.assertNotEqual(flag11["status"], TRIGGERED)

    def test_end_to_end_disclaiming_phrase_far_from_the_identifier_is_not_missed(self):
        """Same guard, more realistic distance: a real sentence puts its
        disclaiming phrase near the start and the identifier near the end,
        further apart than the fixed 60-character window `_context()` used
        to capture. Confirmed live before this fix: 'I have spent my career
        as outside patent counsel prosecuting numerous filings on behalf of
        corporate clients, including for instance US9876543 which I filed
        for a sensor startup.' captured only 'ients, including for instance
        US9876543 which I filed for a sensor st' as `claim.context` -- the
        'on behalf of' disclaimer had already scrolled out of the window --
        so a real client filing came back MISMATCH, floored at ORANGE by
        flag 11, instead of UNCHECKABLE. `_context()` must scope to the
        whole sentence, not a fixed character count, for the guard in
        `_attribute` to ever see a disclaimer that doesn't sit within 30
        characters of the identifier it qualifies."""
        from larp_meter.audit import run_audit
        from larp_meter import TRIGGERED

        import larp_meter.audit as audit_mod
        real_verifier = audit_mod.Verifier
        try:
            audit_mod.Verifier = lambda cache_dir, subject_name=None: StubVerifier(
                {"patents.google.com": (
                    "<title>Sensor Array Patent</title>"
                    "<dd itemprop=\"inventor\">Someone Else</dd>", True)},
                subject_name=subject_name)
            text = ("I have spent my career as outside patent counsel prosecuting numerous "
                    "filings on behalf of corporate clients, including for instance "
                    "US9876543 which I filed for a sensor startup.")
            report = run_audit("t", text, verify=True, subject_name="Sofia Almeida")
        finally:
            audit_mod.Verifier = real_verifier

        claim = next(c for c in report["claims"] if c["subtype"] == "patent")
        self.assertEqual(claim["status"], UNCHECKABLE)
        flag11 = next(f for f in report["flags"] if f["id"] == 11)
        self.assertNotEqual(flag11["status"], TRIGGERED)


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

    def test_a_non_english_word_for_university_is_not_discarded_as_a_stopword(self):
        """`_ORG_STOPWORDS` used to list 'universite' (the accent-stripped
        form of 'université') outright, so a claim like 'Universite Paris
        Sud' reduced to just {'paris', 'sud'} -- trivially a subset of ANY
        registry hit that happens to share those two geographic words,
        university or not. Live-measured against the real ROR API before
        this fix: 'Universite Paris Sud' verified against 'Geosciences
        Paris Sud', an unrelated research unit that is not a university at
        all. Every other language's word for university/institute/school
        already folds to a common stem via `_ORG_STEMS` instead of being
        discarded -- 'universite' and 'università' were the sole
        stopword-listed exceptions, inconsistent with this file's own
        stated design ("folded to a common stem before matching")."""
        body = json.dumps({"items": [{
            "id": "https://ror.org/unrelated",
            "names": [{"value": "Geosciences Paris Sud", "types": ["ror_display"]}],
            "locations": [{"geonames_details": {"country_name": "France"}}]}]})
        v = StubVerifier({"api.ror.org": (body, True)})
        claim = Claim(kind="degree", subtype="degree_institution", value="Universite Paris Sud")
        v.verify_institution(claim)
        self.assertNotEqual(claim.status, VERIFIED)

    def test_a_genuine_non_english_university_name_still_verifies(self):
        """The fix above must not overcorrect: 'universite' now stems to
        'univ', exactly like the English 'university' already does, so a
        real French university matched against ROR's own French-language
        display name must still verify."""
        body = json.dumps({"items": [{
            "id": "https://ror.org/03083nz45",
            "names": [{"value": "Université Paris-Saclay", "types": ["ror_display"]}],
            "locations": [{"geonames_details": {"country_name": "France"}}]}]})
        v = StubVerifier({"api.ror.org": (body, True)})
        claim = Claim(kind="degree", subtype="degree_institution", value="Universite Paris-Saclay")
        v.verify_institution(claim)
        self.assertEqual(claim.status, VERIFIED)

    def test_stopword_only_claim_is_not_verified_by_the_first_hit(self):
        """An empty `wanted` set (a claim value that decomposes to nothing
        but stopwords) is a subset of ANY non-empty registry name, by
        definition of subset. Without the `wanted and` guard on the match
        check, the very first ROR hit -- any real institution the registry
        happens to return for a near-empty query -- would silently "verify"
        a claim that named nothing at all, manufacturing coverage from a
        query with no institution in it."""
    def test_a_stopword_only_institution_claim_cannot_verify_against_any_hit(self):
        """Mutation guard: `_significant_tokens` strips stopwords, so a claim
        value that is entirely stopwords ('of the and') reduces to an empty
        `wanted` set. An empty set is a subset of ANY set by definition --
        without the `wanted and` guard, the very first ROR hit, named nothing
        like the claim, would 'verify' a claim that named nothing at all."""
        body = json.dumps({"items": [{
            "id": "https://ror.org/00cv9y106",
            "names": [{"value": "Ghent University", "types": ["ror_display"]}],
            "locations": [{"geonames_details": {"country_name": "Belgium"}}]}]})
        v = StubVerifier({"api.ror.org": (body, True)})
        claim = Claim(kind="degree", subtype="degree_institution", value="Of The And")
        claim = Claim(kind="degree", subtype="degree_institution", value="of the and")
        v.verify_institution(claim)
        self.assertEqual(claim.status, NOT_FOUND)

    def test_registry_name_is_never_echoed_from_the_claim(self):
        """Old bug: .get('name', claim.value) reported the claim back as proof."""
        body = json.dumps({"items": [{"id": "x", "names": [], "locations": []}]})
        v = StubVerifier({"api.ror.org": (body, True)})
        claim = Claim(kind="degree", subtype="degree_institution", value="Totally Made Up University")
        v.verify_institution(claim)
        self.assertEqual(claim.status, NOT_FOUND)
        self.assertNotIn("Real institution: Totally Made Up University", claim.detail)

    def test_a_claim_of_nothing_but_stopwords_cannot_be_verified(self):
        """`wanted` is the set of significant tokens in the claim; when a value
        decomposes to nothing but stopwords ("of", "the", ...) `wanted` is
        empty, and an empty set is a subset of ANY registry hit's tokens by
        definition. Without the `wanted and` guard, the first ROR item
        returned — regardless of what it actually is — would satisfy
        `wanted <= have` and come back VERIFIED, manufacturing a confirmed
        credential from a query that named nothing at all."""
        body = json.dumps({"items": [{
            "id": "https://ror.org/unrelated",
            "names": [{"value": "Some Unrelated University", "types": ["ror_display"]}],
            "locations": [{"geonames_details": {"country_name": "Norway"}}]}]})
        v = StubVerifier({"api.ror.org": (body, True)})
        claim = Claim(kind="degree", subtype="degree_institution", value="Of The A")
        v.verify_institution(claim)
        self.assertEqual(claim.status, NOT_FOUND)

    def test_nearest_name_tie_break_is_deterministic_not_last_writer_wins(self):
        """Mutation `if overlap > best_overlap:` -> `if overlap >= best_overlap:`
        survived. Neither hit here clears `wanted <= have`, so both fall
        through to the "nearest listed name" tie-break — and both score the
        exact same overlap fraction (each shares exactly one significant
        token with the claim, against an equal-size union). `>` keeps
        whichever item ROR listed first on a tie; `>=` would silently let a
        later, equally-relevant item overwrite it. Which real organization
        gets quoted back to the reader as the "nearest" one is exactly the
        kind of detail this tool must be able to explain deterministically,
        not by an accident of iteration order."""
        body = json.dumps({"items": [
            {"id": "https://ror.org/first",
             "names": [{"value": "Alderbrook Zeppelin", "types": ["ror_display"]}],
             "locations": [{"geonames_details": {"country_name": "Norway"}}]},
            {"id": "https://ror.org/second",
             "names": [{"value": "Marine Quokka", "types": ["ror_display"]}],
             "locations": [{"geonames_details": {"country_name": "Australia"}}]},
        ]})
        v = StubVerifier({"api.ror.org": (body, True)})
        claim = Claim(kind="degree", subtype="degree_institution",
                       value="Alderbrook Institute of Marine Studies")
        v.verify_institution(claim)
        self.assertEqual(claim.status, NOT_FOUND)
        self.assertIn("Alderbrook Zeppelin", claim.detail)
        self.assertNotIn("Marine Quokka", claim.detail)

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

    def test_nearest_name_tie_break_is_deterministic_not_last_writer_wins(self):
        """Mutation guard: `if overlap > best_overlap` -> `>=` survived with
        the suite green. On a tie, `>=` lets every later equally-good
        candidate keep overwriting `best_name`, so the "Nearest listed
        name" hint in a NOT_FOUND report becomes an artifact of ROR's
        arbitrary result ordering rather than a stable answer -- the same
        claim against the same registry could report a different "nearest"
        institution on a re-run if ROR reorders ties. With strict `>`, the
        first candidate reached at the best overlap seen so far wins and
        stays won."""
        body = json.dumps({"items": [
            {"id": "https://ror.org/alpha",
             "names": [{"value": "Institute of Advanced Alpha Studies", "types": ["ror_display"]}],
             "locations": [{"geonames_details": {"country_name": "Norway"}}]},
            {"id": "https://ror.org/beta",
             "names": [{"value": "Institute of Advanced Beta Studies", "types": ["ror_display"]}],
             "locations": [{"geonames_details": {"country_name": "Sweden"}}]},
        ]})
        v = StubVerifier({"api.ror.org": (body, True)})
        claim = Claim(kind="degree", subtype="degree_institution",
                      value="Institute of Advanced Fictional Studies")
        v.verify_institution(claim)
        self.assertEqual(claim.status, NOT_FOUND)
        self.assertIn("Institute of Advanced Alpha Studies", claim.detail)
        self.assertNotIn("Beta", claim.detail)

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
