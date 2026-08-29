"""Tests written to close blind spots found by mutation testing.

Each test here corresponds to a deliberate bug that the previous 220-test suite
did not notice. A test that cannot fail is worse than no test: it reports
coverage it does not have. Several of these replace assertions that passed for
the wrong reason — notably the search-failure guard, whose original test used a
22-word bio and so returned UNKNOWN by a different branch entirely.
"""

import json
import tempfile
import unittest
import urllib.request

from larp_meter import TRIGGERED, PASSED, UNKNOWN, names
from larp_meter import extract as ex
from larp_meter.audit import run_audit
from larp_meter.extract import Claim, VERIFIED, NOT_FOUND, UNCHECKABLE
from larp_meter.verify import Verifier
from tests.test_verify import StubVerifier

# Long enough that flag 10's word-count fall-through is genuinely reachable;
# with the search-failure guard removed this text TRIGGERS.
LONG_CLAIMY_BIO = (
    "Founder and chief executive of Cindermark, building satellite hardware, radiation "
    "tolerant systems and machine learning models for orbital deployment across a range "
    "of defence and commercial customers, leading a substantial engineering team that "
    "has grown steadily every year since the company was established in this sector."
)


def flag(text, fid, **kw):
    return next(f for f in run_audit("t", text, mode="text", **kw)["flags"] if f["id"] == fid)


class TestNameMatchingStrictness(unittest.TestCase):
    def test_one_shared_token_is_not_a_match(self):
        """M07. Requiring only one matching token makes every 'Ada' the same
        person, and attribution failures are how this tool libels someone."""
        self.assertFalse(names.name_matches("Ada Lovelace", ["Ada Byron"]))
        self.assertFalse(names.name_matches("Jan Vermeulen", ["Jan Peeters"]))
        self.assertFalse(names.name_matches("Maria Garcia", ["Maria Rodriguez"]))

    def test_both_tokens_matching_is_a_match(self):
        self.assertTrue(names.name_matches("Ada Lovelace", ["Ada Lovelace"]))

    def test_surname_with_abbreviated_given_name_still_matches(self):
        self.assertTrue(names.name_matches("Ada Lovelace", ["A. Lovelace"]))


class TestNegationScope(unittest.TestCase):
    def test_negation_does_not_leak_across_a_clause_boundary(self):
        """M14. Without the boundary, one 'no' early in a bio suppresses every
        later term in the document."""
        from larp_meter.matching import is_negated
        text = "We have no legacy systems. We serve 40 customers and book real revenue."
        self.assertFalse(is_negated(text, text.index("customers")))
        self.assertFalse(is_negated(text, text.index("revenue")))

    def test_negation_still_reaches_within_its_own_clause(self):
        from larp_meter.matching import is_negated
        text = "We have no customers and no revenue."
        self.assertTrue(is_negated(text, text.index("revenue")))

    def test_a_denial_in_a_previous_sentence_does_not_clear_a_flag(self):
        text = ("Founder building deep tech AI hardware. We have no legacy technical debt. "
                "We are seeking investment. We have 40 customers and recurring revenue.")
        self.assertEqual(flag(text, 7)["status"], PASSED)


class TestRegistryAnswerVsSilence(unittest.TestCase):
    """The distinction the whole verification layer rests on."""

    def test_a_404_is_an_answer_and_means_not_found(self):
        """M16. This must drive the REAL Verifier._get: StubVerifier replaces
        _get wholesale, so a stubbed test never executes the HTTPError branch
        that decides 'the registry answered' versus 'we could not reach it'.
        Treating 404 as unreachable would silently stop the tool ever reporting
        that a cited artifact does not exist."""
        def not_found(*a, **k):
            raise urllib.error.HTTPError("https://api.crossref.org/works/x", 404,
                                         "Not Found", {}, None)

        real = urllib.request.urlopen
        urllib.request.urlopen = not_found
        try:
            v = Verifier(tempfile.mkdtemp(), subject_name="Ada Lovelace")
            claim = Claim(kind="artifact", subtype="doi", value="10.1000/nope")
            v.verify_doi(claim)
        finally:
            urllib.request.urlopen = real

        self.assertEqual(claim.status, NOT_FOUND)
        self.assertEqual(v.network_failures, 0, "a 404 is an answer, not a failure")

    def test_a_410_is_also_an_answer_and_means_not_found(self):
        """M36. `_get` treats 404 and 410 as the same signal — a registry
        saying 'gone' is exactly as much an answer as 'never existed' — but
        the tuple `(404, 410)` survived a mutation dropping the second code
        entirely with the whole suite still green, because nothing exercised
        the real HTTPError branch with anything but 404 or 5xx. Dropping 410
        would silently reclassify a permanently-removed record as an
        unreachable registry: `network_failures` climbs and the claim comes
        back UNCHECKABLE instead of NOT_FOUND, understating what the registry
        actually told us."""
        def gone(*a, **k):
            raise urllib.error.HTTPError("https://api.crossref.org/works/x", 410,
                                         "Gone", {}, None)

        real = urllib.request.urlopen
        urllib.request.urlopen = gone
        try:
            v = Verifier(tempfile.mkdtemp(), subject_name="Ada Lovelace")
            claim = Claim(kind="artifact", subtype="doi", value="10.1000/withdrawn")
            v.verify_doi(claim)
        finally:
            urllib.request.urlopen = real

        self.assertEqual(claim.status, NOT_FOUND)
        self.assertEqual(v.network_failures, 0, "a 410 is an answer, not a failure")

    def test_a_500_is_not_an_answer(self):
        """The other side of the same branch: a server error must not be read
        as the registry saying 'no such record'."""
        def server_error(*a, **k):
            raise urllib.error.HTTPError("https://api.crossref.org/works/x", 503,
                                         "Service Unavailable", {}, None)

        real = urllib.request.urlopen
        urllib.request.urlopen = server_error
        try:
            v = Verifier(tempfile.mkdtemp(), subject_name="Ada Lovelace")
            claim = Claim(kind="artifact", subtype="doi", value="10.1000/xyz")
            v.verify_doi(claim)
        finally:
            urllib.request.urlopen = real

        self.assertEqual(claim.status, UNCHECKABLE)
        self.assertEqual(v.network_failures, 1)

    def test_a_network_failure_is_not_an_answer(self):
        """M17. Reporting an unreachable registry as a successful empty response
        turns 'we could not check' into 'this does not exist' — the exact
        inversion design commitment 2 forbids."""
        boom_calls = []

        def boom(*a, **k):
            boom_calls.append(1)
            raise OSError("network down")

        real = urllib.request.urlopen
        urllib.request.urlopen = boom
        try:
            v = Verifier(tempfile.mkdtemp(), subject_name="Ada Lovelace")
            claim = Claim(kind="artifact", subtype="doi", value="10.1000/xyz")
            v.verify_doi(claim)
        finally:
            urllib.request.urlopen = real

        self.assertTrue(boom_calls, "the verifier did not attempt a request")
        self.assertEqual(claim.status, UNCHECKABLE)
        self.assertNotEqual(claim.status, NOT_FOUND)
        self.assertEqual(v.network_failures, 1)


class TestInstitutionMatchGuards(unittest.TestCase):
    """verify_institution's `wanted <= have` subset check is the one thing
    standing between a fabricated institution and a false VERIFIED — ROR's
    own query endpoint is fuzzy and returns hits for almost anything."""

    def test_an_all_stopword_claim_cannot_be_verified_by_vacuous_subset(self):
        """M37. `wanted` is the set of significant words in the CLAIM. When a
        garbled extraction leaves nothing but stopwords, `wanted` is empty —
        and an empty set is a subset of every registry hit, so the guard
        exists specifically to stop that from reading as a match. Dropping
        the `wanted and ...` half of the condition survived the whole suite:
        nothing had ever fed verify_institution a claim this thin. Without
        the guard, ANY institution in ROR's fuzzy results would satisfy an
        empty query and come back VERIFIED — manufacturing coverage for a
        claim that named nothing at all."""
        body = json.dumps({"items": [{
            "id": "https://ror.org/00cv9y106",
            "names": [{"value": "Ghent University", "types": ["ror_display"]}],
            "locations": [{"geonames_details": {"country_name": "Belgium"}}]}]})
        v = StubVerifier({"api.ror.org": (body, True)})
        claim = Claim(kind="degree", subtype="degree_institution", value="Of The")
        v.verify_institution(claim)
        self.assertNotEqual(claim.status, VERIFIED)

    def test_ambiguous_acronym_boundary_is_inclusive_at_five_characters(self):
        """M38. `_is_ambiguous_acronym` uses `<= 5`; a five-letter acronym
        ('UCLAN', 'IIT-B'-style bare strings) is exactly as ambiguous as a
        shorter one, but nothing pinned the boundary itself — only 'MIT'
        (3 chars) was ever tried, so `<= 5` narrowing to `< 5` left the
        suite green while silently dropping the ambiguity caveat for every
        5-character acronym."""
        from larp_meter.verify import _is_ambiguous_acronym
        self.assertTrue(_is_ambiguous_acronym("UCLAN"))

    def test_single_character_fragments_are_not_significant_tokens(self):
        """M39. Real registry entries and claims alike can decompose into
        single-letter fragments around initials and ampersands ('A&M' ->
        'a', 'm'). `_significant_tokens` filters anything shorter than two
        characters for exactly this reason — without it, an institution
        whose name happens to share stray single letters with an unrelated
        ROR entry could pick up spurious overlap toward the 'nearest listed
        name' hint, or spurious membership in `wanted`/`have` sets that were
        never actually about the same word."""
        from larp_meter.verify import _significant_tokens
        self.assertEqual(_significant_tokens("A & M"), set())
        self.assertIn("texas", _significant_tokens("Texas A & M University"))


class TestArxivErrorSignalsAreIndependent(unittest.TestCase):
    """arXiv serves a bad-id error as a 200 OK Atom feed. The check for it
    ORs two independent tells (the `api/errors` id and the 'Error' title)
    on purpose — each is sufficient on its own, because either one drifting
    out of sync with the other must not turn an error page into an
    attributed paper."""

    def _entry(self, entry_id, title):
        return (f"<feed xmlns='http://www.w3.org/2005/Atom'><entry>"
                f"<id>{entry_id}</id><title>{title}</title>"
                f"<author><name>Someone Else</name></author></entry></feed>")

    def test_the_error_id_alone_is_enough(self):
        """M40a. `or` collapsed to `and` still passes the existing test, which
        always supplies both tells together. A title arXiv happens to phrase
        differently on a future error page must not defeat this on its own."""
        body = self._entry("http://arxiv.org/api/errors#bad_id", "Bad Request")
        v = StubVerifier({"arxiv.org": (body, True)}, subject_name="Ada Lovelace")
        claim = Claim(kind="artifact", subtype="arxiv", value="9999.99999")
        v.verify_arxiv(claim)
        self.assertEqual(claim.status, NOT_FOUND)

    def test_the_error_title_alone_is_enough(self):
        """M40b. The other half of the same OR: an id that does not happen to
        contain 'api/errors' must not be required alongside the title."""
        body = self._entry("http://arxiv.org/abs/9999.99999v1", "Error")
        v = StubVerifier({"arxiv.org": (body, True)}, subject_name="Ada Lovelace")
        claim = Claim(kind="artifact", subtype="arxiv", value="9999.99999")
        v.verify_arxiv(claim)
        self.assertEqual(claim.status, NOT_FOUND)


class TestYearExtraction(unittest.TestCase):
    def test_digits_inside_an_identifier_are_not_years(self):
        """M34. Loose year matching turned DOI and quantity digits into claimed
        career dates and produced 'impossible timeline' accusations."""
        claims = ex.extract_claims("See doi 10.1109/TNS.2023.3241234 for the method.")
        self.assertEqual([c.value for c in ex.claims_by(claims, "timeline", "year")], [])

    def test_a_year_embedded_in_a_longer_number_is_not_a_year(self):
        """M19. Masking covers identifiers it recognises; the word boundary is
        the second line of defence for numbers it does not."""
        self.assertEqual(ex.YEAR_RE.findall("employee id 12015 joined the team"), [])
        self.assertEqual(ex.YEAR_RE.findall("part number 20241X"), [])
        claims = ex.extract_claims("Badge 12015 was issued to the new hire.")
        self.assertEqual([c.value for c in ex.claims_by(claims, "timeline", "year")], [])

    def test_traction_quantities_are_not_years(self):
        claims = ex.extract_claims("We booked 2019 customers last quarter.")
        self.assertEqual([c.value for c in ex.claims_by(claims, "timeline", "year")], [])

    def test_a_real_date_is_still_read(self):
        claims = ex.extract_claims("MSc Electrical Engineering, 2015.")
        self.assertEqual([c.value for c in ex.claims_by(claims, "timeline", "year")], ["2015"])


class TestFlagBranchesWithoutCoverage(unittest.TestCase):
    def test_no_education_information_says_so_explicitly(self):
        """M21. Two branches both reach UNKNOWN here, so status alone cannot
        detect the guard being removed — but they give different explanations,
        and 'a degree is mentioned but its field is unclear' would be a lie
        about a profile that mentions no degree at all."""
        text = ("Founder and chief executive building semiconductor and neural network "
                "hardware for satellites, leading a growing engineering organisation.")
        result = flag(text, 1)
        self.assertEqual(result["status"], UNKNOWN)
        self.assertIn("no education information", result["description"])

    def test_distinct_partners_pass_the_self_referential_flag(self):
        """M22. Inverting this branch accuses everyone with a real partner."""
        text = "Founder of Marrow Robotics. Partnership with Port of Rotterdam."
        self.assertEqual(flag(text, 3)["status"], PASSED)

    def test_fundraising_with_unquantified_traction_passes(self):
        """M24. The numeric-traction branch masked this one entirely, so the
        prose-only path ('we have paying customers') was never exercised."""
        text = ("Founder building deep tech AI hardware and seeking investment. "
                "We have paying customers and recurring revenue today.")
        self.assertEqual(flag(text, 7)["status"], PASSED)

    def test_logo_wall_needs_several_partners(self):
        """M29. Dropping the threshold to one turns any single partnership into
        'logo wall syndrome'."""
        text = ("Founder of Marrow Robotics building satellite hardware. "
                "Partnership with Orion Systems.")
        self.assertEqual(flag(text, 9)["status"], PASSED)

    def test_buzzword_flag_needs_both_variety_and_density(self):
        """M30. Collapsing the thresholds flags ordinary confident writing."""
        # Two buzzwords in ~55 words: real writing, well under both thresholds.
        text = ("We build underwater inspection robots for port authorities. The team has "
                "shipped three generations of hardware and our approach has kept deployment "
                "costs falling year on year across every customer site we operate. It is a "
                "pioneering programme in a demanding sector and the results are best in class "
                "for reliability, which we consider a solid engineering outcome overall.")
        from larp_meter.matching import find_non_overlapping, load_banks
        distinct, _hits = find_non_overlapping(text, load_banks(path="/nonexistent")["buzzwords"])
        self.assertTrue(1 <= len(distinct) <= 3, f"fixture drifted: {distinct}")
        self.assertEqual(flag(text, 4)["status"], PASSED)

    def test_a_past_event_dated_in_the_future_is_caught(self):
        """M32. Removing the check silently drops the one thing flag 12 detects
        that is not a duration mismatch."""
        # No duration claim, so only the future-date branch can fire.
        text = ("Founder building satellite hardware. MSc Aerospace Engineering, "
                "Delft University of Technology, 2039.")
        result = flag(text, 12)
        self.assertEqual(result["status"], TRIGGERED)
        self.assertIn("in the future", result["description"])
        self.assertIn("2039", result["description"])

    def test_unverified_identifiers_never_accuse(self):
        """M35. Without the guard, citing a DOI and not running --verify would
        itself be scored as a contradicted claim."""
        text = "Founder building AI hardware. Our paper: 10.1038/s41586-020-2649-2."
        result = flag(text, 11)
        self.assertEqual(result["status"], UNKNOWN)
        self.assertIn("--verify", result["description"])


class TestSearchFailureGuard(unittest.TestCase):
    """M28. The original test used a 22-word bio, so flag 10 returned UNKNOWN
    through the 'too little material' branch whether or not the guard existed."""

    def test_the_bio_is_long_enough_to_reach_the_accusing_branch(self):
        healthy = run_audit("t", LONG_CLAIMY_BIO, mode="web", source_urls=[],
                            signals={"search_ok": True})
        self.assertEqual(next(f for f in healthy["flags"] if f["id"] == 10)["status"], TRIGGERED)

    def test_a_failed_search_makes_validation_undecidable(self):
        broken = run_audit("t", LONG_CLAIMY_BIO, mode="web", source_urls=[],
                           signals={"search_ok": False})
        self.assertEqual(next(f for f in broken["flags"] if f["id"] == 10)["status"], UNKNOWN)


if __name__ == "__main__":
    unittest.main()


class TestPhrasingParity(unittest.TestCase):
    """The verdict must track the facts, not the fluency of the writing."""

    POLISHED = ("Founder building machine learning hardware. I hold an MSc in Computer "
                "Science from Delft University of Technology and have spent eight years "
                "as a software architect.")
    PLAINER = ("Founder building machine learning hardware. I have MSc Computer Science "
               "from Delft University of Technology. I am working as software architect "
               "since eight years.")

    def test_same_facts_reach_the_same_verdict(self):
        a = run_audit("a", self.POLISHED, mode="text")
        b = run_audit("b", self.PLAINER, mode="text")
        self.assertEqual(a["level"], b["level"])
        self.assertEqual(a["evidence_coverage_pct"], b["evidence_coverage_pct"])

    def test_duration_is_recognised_however_it_is_phrased(self):
        for phrasing in ("eight years of experience",
                         "spent eight years as a design engineer",
                         "eight years working on satellite systems",
                         "with 10 years in hardware design",
                         "twelve years leading engineering teams"):
            with self.subTest(phrasing=phrasing):
                claims = ex.extract_claims(phrasing)
                self.assertTrue(ex.claims_by(claims, "timeline", "claimed_experience_years"),
                                f"duration not recognised in: {phrasing}")

    def test_no_length_cliff_around_the_buzzword_threshold(self):
        """A one-word difference used to flip the whole verdict, because flag 4
        went undecidable below 25 words and that moved evidence coverage across
        the scoring floor."""
        base = ("Engineer building satellite hardware. MSc Electrical Engineering, "
                "Delft University of Technology, 2015. Eight years as a design engineer")
        short = base + "."
        long_ = base + " working on radiation tolerant systems for the space sector."
        self.assertLess(len(short.split()), 25, "fixture drifted: short side")
        self.assertGreaterEqual(len(long_.split()), 25, "fixture drifted: long side")
        self.assertEqual(flag(short, 4)["status"], PASSED)
        self.assertEqual(flag(long_, 4)["status"], PASSED)

    def test_short_text_with_hype_stays_undecidable(self):
        """Absence of hype is answerable at any length; its proportion is not."""
        self.assertEqual(flag("A revolutionary, world class, game changing paradigm shift.", 4)
                         ["status"], UNKNOWN)

    def test_institution_language_does_not_change_the_verdict(self):
        anglo = ("Engineer building satellite hardware. MSc Electrical Engineering, "
                 "University of Cambridge, 2015. Eight years as a design engineer.")
        german = ("Engineer building satellite hardware. MSc Electrical Engineering, "
                  "Technische Universitat Munchen, 2015. Eight years as a design engineer.")
        a, b = run_audit("a", anglo, mode="text"), run_audit("b", german, mode="text")
        self.assertEqual(a["level"], b["level"])
        self.assertEqual(a["evidence_coverage_pct"], b["evidence_coverage_pct"])
