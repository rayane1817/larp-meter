"""Reverse path, step 3: publication-volume claims against OpenAlex.

"Published over 200 papers" implies a scholarly record. With no DOI or ORCID
in the profile there is nothing for verify.py to look up, so this asks
OpenAlex for authors under the subject's name, keeps only the ones tied to the
subject by an institution the profile itself names (or by an ORCID it cites),
and compares their works with the claim.

OpenAlex splits one real person into several author entities far more often
than it merges them, so a record holding fewer works than claimed is shown as
a note and never counted against the subject. Every call is stubbed with
response shapes captured from the live API on 2026-09-22 (keyless, $0.001 per
author search); the suite stays offline.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from larp_meter import reconcile as rc
from larp_meter import PASSED, UNKNOWN
from larp_meter import extract as ex
from larp_meter.flags import AuditContext, evaluate
from larp_meter.matching import load_banks

BANKS = load_banks(path="/nonexistent")


def inst(name, iid, country="CH"):
    return {"id": f"https://openalex.org/I{iid}", "ror": f"https://ror.org/0{iid}",
            "display_name": name, "country_code": country, "type": "education",
            "lineage": [f"https://openalex.org/I{iid}"]}


ETH = inst("ETH Zurich", 35440088)
PRINCETON = inst("Princeton University", 20089843, "US")
UCLA = inst("University of California, Los Angeles", 161318765, "US")


def author(aid, name, works, institutions=(), orcid=None, alternatives=()):
    return {"id": f"https://openalex.org/A{aid}", "display_name": name,
            "display_name_alternatives": list(alternatives), "orcid": orcid,
            "works_count": works, "cited_by_count": works * 40,
            "affiliations": [{"institution": i, "years": [2020, 2010]} for i in institutions],
            "last_known_institutions": list(institutions[:1])}


def openalex(results=(), fail=False):
    """A stand-in for rc._http that answers like OpenAlex's /authors search."""
    calls = []

    def fake(url, payload=None, headers=None):
        calls.append((url, dict(headers or {})))
        if fail:
            return False, 429, ""
        assert "api.openalex.org/authors" in url, url
        return True, 200, json.dumps({"meta": {"count": len(results), "cost_usd": 0.001},
                                      "results": list(results)})
    fake.calls = calls
    return fake


# Live shape, 2026-09-22: the real Ueli Maurer is split across entities, one
# of them with his name reversed, next to an unrelated namesake at UCLA.
MAURER = [author(5064085132, "Ueli Maurer", 297, (inst("Institute of Science and Technology Austria", 157556583, "AT"),
                                                  PRINCETON, ETH),
                 alternatives=("Maurer U.", "U. Maurer", "Ueli M. Maurer")),
          author(5142736269, "Ueli Maurer", 2, (UCLA,)),
          author(5109012816, "Maurer Ueli", 2, (ETH,))]


def run(text, subject, http):
    with mock.patch.object(rc, "_http", http), mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OPENALEX_API_KEY", None)
        return [r for r in rc.reconcile_text(text, subject, tempfile.mkdtemp())
                if r.kind == "publications"]


class TestExtraction(unittest.TestCase):
    def test_a_counted_claim(self):
        c = rc.extract_publication_claim("She has published over 120 peer-reviewed papers on catalysis.")
        self.assertEqual((c.count, c.vague), (120, False))

    def test_plus_suffix_and_other_nouns(self):
        self.assertEqual(rc.extract_publication_claim("Author of 150+ scientific publications.").count, 150)
        self.assertEqual(rc.extract_publication_claim("Wrote 45 journal articles.").count, 45)

    def test_german(self):
        self.assertEqual(rc.extract_publication_claim("Autor von über 80 Publikationen.").count, 80)

    def test_a_vague_claim(self):
        c = rc.extract_publication_claim("He has published extensively in leading journals.")
        self.assertEqual((c.count, c.vague), (None, True))

    def test_the_largest_count_is_the_claim(self):
        c = rc.extract_publication_claim("Published extensively: 30 papers as first author, over 90 papers in total.")
        self.assertEqual(c.count, 90)

    def test_reviewing_papers_is_not_writing_them(self):
        for text in ("Reviewer for over 200 papers a year.", "Has reviewed more than 50 papers.",
                     "Supervised 30 papers by master's students.", "Edited 40 articles for the magazine."):
            with self.subTest(text=text):
                self.assertIsNone(rc.extract_publication_claim(text))

    def test_a_count_in_one_venue_is_not_a_total(self):
        """'12 papers in Nature' says nothing about the total; comparing it
        with the total would confirm almost anyone."""
        self.assertIsNone(rc.extract_publication_claim("12 papers in Nature and Science."))

    def test_a_year_is_not_a_count(self):
        self.assertIsNone(rc.extract_publication_claim("Our 2019 papers set the agenda."))

    def test_a_quantified_count_in_the_year_range_is_still_a_count(self):
        """Found live: the year rule silently skipped an inflated 'over 2000'."""
        self.assertEqual(rc.extract_publication_claim("Has published over 2000 peer-reviewed papers.").count, 2000)
        self.assertEqual(rc.extract_publication_claim("Author of 2000+ publications.").count, 2000)

    def test_no_claim(self):
        self.assertIsNone(rc.extract_publication_claim("Serial entrepreneur and investor."))

    def test_names_before_the_claim_are_recorded(self):
        c = rc.extract_publication_claim("My supervisor Hans Muster has published over 300 papers.")
        self.assertIn("Hans Muster", c.named_before)


class TestPublicationReconciliation(unittest.TestCase):
    TEXT = "Professor of Computer Science at ETH Zürich. Has published over 200 papers in cryptography."

    def test_a_record_tied_by_a_stated_institution_confirms_the_volume(self):
        [r] = run(self.TEXT, "Ueli Maurer", openalex(MAURER))
        self.assertEqual((r.outcome, r.identity), (rc.CONFIRMED, rc.CONFIDENT))
        # Both ETH-tied entities count, the UCLA namesake does not.
        self.assertIn("299", r.detail)
        self.assertNotIn("A5142736269", " ".join(r.evidence))

    def test_a_shortfall_is_a_note_never_a_contradiction(self):
        """The honest researcher OpenAlex split into ten pieces looks exactly
        like this, so it can never count against anyone."""
        http = openalex([author(1, "Ueli Maurer", 12, (ETH,))])
        [r] = run(self.TEXT, "Ueli Maurer", http)
        self.assertEqual(r.outcome, rc.AMBIGUOUS)
        self.assertEqual(r.identity, rc.CONFIDENT)
        self.assertIn("12", r.detail)
        self.assertIn("200", r.detail)

    def test_the_source_is_never_complete_for_one_persons_output(self):
        self.assertFalse(rc.OpenAlexAuthors.complete)

    def test_no_stated_institution_means_no_confirmation(self):
        """A prolific namesake is not the subject just because the name matches."""
        http = openalex([author(1, "Ueli Maurer", 297, (PRINCETON,))])
        [r] = run("Professor at Acme Labs. Has published over 200 papers.", "Ueli Maurer", http)
        self.assertEqual((r.outcome, r.identity), (rc.AMBIGUOUS, rc.UNCERTAIN))

    def test_an_orcid_in_the_profile_ties_the_record_without_an_institution(self):
        http = openalex([author(1, "Ueli Maurer", 297, (PRINCETON,),
                                orcid="https://orcid.org/0000-0002-1825-0097")])
        [r] = run("ORCID 0000-0002-1825-0097. Has published over 200 papers.", "Ueli Maurer", http)
        self.assertEqual((r.outcome, r.identity), (rc.CONFIRMED, rc.CONFIDENT))

    def test_a_merged_looking_record_cannot_confirm(self):
        """Twenty institutions is several people under one ID, which inflates
        the works count in the subject's favour."""
        many = tuple(inst(f"University {i}", 1000 + i, "CN") for i in range(20)) + (ETH,)
        [r] = run(self.TEXT, "Ueli Maurer", openalex([author(1, "Ueli Maurer", 2400, many)]))
        self.assertNotEqual(r.outcome, rc.CONFIRMED)
        self.assertEqual(r.identity, rc.UNCERTAIN)

    def test_many_namesakes_at_the_stated_institution_cannot_confirm(self):
        crowd = [author(i, "Wei Wang", 60, (ETH,)) for i in range(4)]
        [r] = run("Researcher at ETH Zurich with over 200 papers.", "Wei Wang", openalex(crowd))
        self.assertNotEqual(r.outcome, rc.CONFIRMED)

    def test_the_name_must_match(self):
        http = openalex([author(1, "Stefan Wolf", 297, (ETH,))])
        [r] = run(self.TEXT, "Ueli Maurer", http)
        self.assertEqual(r.outcome, rc.NO_RECORD)

    def test_a_vague_claim_confirmed_by_a_substantial_record(self):
        http = openalex([author(1, "Ueli Maurer", 40, (ETH,))])
        [r] = run("Professor at ETH Zurich; published extensively.", "Ueli Maurer", http)
        self.assertEqual(r.outcome, rc.CONFIRMED)

    def test_a_vague_claim_with_a_thin_record_is_a_note(self):
        http = openalex([author(1, "Ueli Maurer", 3, (ETH,))])
        [r] = run("Professor at ETH Zurich; published extensively.", "Ueli Maurer", http)
        self.assertEqual(r.outcome, rc.AMBIGUOUS)

    def test_an_unreachable_api_is_uncheckable_and_not_cached(self):
        cache = tempfile.mkdtemp()
        with mock.patch.object(rc, "_http", openalex(fail=True)):
            [r] = [x for x in rc.reconcile_text(self.TEXT, "Ueli Maurer", cache) if x.kind == "publications"]
        self.assertEqual(r.outcome, rc.UNCHECKABLE)
        http = openalex(MAURER)
        with mock.patch.object(rc, "_http", http):
            [r] = [x for x in rc.reconcile_text(self.TEXT, "Ueli Maurer", cache) if x.kind == "publications"]
        self.assertEqual(r.outcome, rc.CONFIRMED)
        self.assertEqual(len(http.calls), 1)



class TestMutationSurvivors(unittest.TestCase):
    TEXT = TestPublicationReconciliation.TEXT

    def test_a_name_that_cannot_be_compared_is_not_a_match(self):
        """A record in another script is unanswerable (None), not the subject."""
        [r] = run("Researcher at ETH Zurich with over 50 papers.", "Wei Wang",
                  openalex([author(1, "王伟", 80, (ETH,))]))
        self.assertNotEqual(r.outcome, rc.CONFIRMED)

    def test_an_institution_ties_only_by_its_whole_name(self):
        http = openalex([author(1, "Ueli Maurer", 297, (inst("Zurich University of Applied Sciences", 1),))])
        [r] = run("Professor at the University of Zurich. Has published over 200 papers.", "Ueli Maurer", http)
        self.assertEqual(r.identity, rc.UNCERTAIN)
        self.assertNotEqual(r.outcome, rc.CONFIRMED)

    def test_an_error_status_is_uncheckable_not_an_empty_answer(self):
        def not_found(url, payload=None, headers=None):
            return True, 404, "{}"
        [r] = run(self.TEXT, "Ueli Maurer", not_found)
        self.assertEqual(r.outcome, rc.UNCHECKABLE)

    def test_a_job_title_before_the_claim_is_not_another_person(self):
        http = openalex(MAURER)
        [r] = run("Senior Lecturer at ETH Zurich, author of over 200 papers.", "Ueli Maurer", http)
        self.assertEqual(r.outcome, rc.CONFIRMED)

class TestBudget(unittest.TestCase):
    """Keyless OpenAlex allows $0.10 a day at $0.001 a search: spend it only
    when there is a claim that is the subject's to check."""

    def test_no_claim_no_call(self):
        http = openalex(MAURER)
        self.assertEqual(run("Professor at ETH Zurich.", "Ueli Maurer", http), [])
        self.assertEqual(http.calls, [])

    def test_no_subject_name_no_call(self):
        http = openalex(MAURER)
        self.assertEqual(run("Has published over 200 papers.", "", http), [])
        self.assertEqual(http.calls, [])

    def test_someone_elses_output_is_not_looked_up(self):
        http = openalex(MAURER)
        self.assertEqual(run("My supervisor Hans Muster has published over 300 papers.", "Ueli Maurer", http), [])
        self.assertEqual(http.calls, [])

    def test_the_subjects_own_name_before_the_claim_is_still_their_claim(self):
        http = openalex(MAURER)
        [r] = run("Ueli Maurer has published over 200 papers at ETH Zurich.", "Ueli Maurer", http)
        self.assertEqual(r.outcome, rc.CONFIRMED)

    def test_a_free_key_is_sent_as_a_header_never_in_the_url(self):
        http = openalex(MAURER)
        with mock.patch.object(rc, "_http", http), mock.patch.dict(os.environ, {"OPENALEX_API_KEY": "k-123"}):
            rc.reconcile_text(TestPublicationReconciliation.TEXT, "Ueli Maurer", tempfile.mkdtemp())
        [(url, headers)] = http.calls
        self.assertNotIn("k-123", url)
        self.assertEqual(headers.get("Authorization"), "Bearer k-123")

    def test_without_a_key_no_authorization_header_is_sent(self):
        http = openalex(MAURER)
        run(TestPublicationReconciliation.TEXT, "Ueli Maurer", http)
        [(_url, headers)] = http.calls
        self.assertNotIn("Authorization", headers)


class TestFlag11(unittest.TestCase):
    def _ctx(self, *recs):
        text = "A profile with no identifiers at all."
        return AuditContext(text=text, claims=ex.extract_claims(text), banks=BANKS,
                            subject_name="Ueli Maurer", verified=True, reconciliations=list(recs))

    def test_a_confirmed_publication_record_passes_flag_11(self):
        r = rc.Reconciliation(kind="publications", outcome=rc.CONFIRMED, source="OpenAlex",
                              detail="299 works")
        res = evaluate(self._ctx(r))[11]
        self.assertEqual(res.status, PASSED)
        self.assertIn("OpenAlex", res.description)
        self.assertNotIn("compan", res.description)

    def test_a_publication_note_leaves_flag_11_undecided_and_is_shown(self):
        r = rc.Reconciliation(kind="publications", outcome=rc.AMBIGUOUS, source="OpenAlex",
                              detail="holds 12 works against 200 claimed")
        res = evaluate(self._ctx(r))[11]
        self.assertEqual(res.status, UNKNOWN)
        self.assertIn("12 works", " ".join(res.evidence))
        self.assertNotIn("company", " ".join(res.evidence))



class TestFlag6(unittest.TestCase):
    """A publication claim is an output claim; flag 6 must not call it absent."""

    def _ctx(self, rec, signals=None):
        text = "Professor at ETH Zurich. Has published over 200 papers."
        return AuditContext(text=text, claims=ex.extract_claims(text), banks=BANKS,
                            subject_name="Ueli Maurer", verified=True, reconciliations=[rec],
                            signals=signals or {})

    def test_a_tied_record_is_verifiable_output_even_among_namesakes(self):
        """The name search alone cannot pick among namesakes; the institution tie can."""
        r = rc.Reconciliation(kind="publications", outcome=rc.CONFIRMED, source="OpenAlex",
                              identity=rc.CONFIDENT, detail="OpenAlex holds 299 works")
        res = evaluate(self._ctx(r, {"ambiguous_identity": 4}))[6]
        self.assertEqual(res.status, PASSED)
        self.assertIn("299", " ".join(res.evidence))

    def test_an_unconfirmed_publication_claim_is_not_called_absent(self):
        r = rc.Reconciliation(kind="publications", outcome=rc.AMBIGUOUS, source="OpenAlex",
                              detail="none tied to a stated institution")
        res = evaluate(self._ctx(r))[6]
        self.assertEqual(res.status, UNKNOWN)
        self.assertNotIn("No output is claimed", res.description)

class TestEndToEnd(unittest.TestCase):
    def test_a_researcher_with_no_identifiers_is_corroborated(self):
        from larp_meter.audit import run_audit
        http = openalex(MAURER)
        with mock.patch.object(rc, "_http", http):
            report = run_audit("t", TestPublicationReconciliation.TEXT, verify=True,
                               subject_name="Ueli Maurer", cache_dir=tempfile.mkdtemp())
        [rec] = [r for r in report["reconciliations"] if r["kind"] == "publications"]
        self.assertEqual(rec["outcome"], rc.CONFIRMED)
        flag11 = next(f for f in report["flags"] if f["id"] == 11)
        self.assertEqual(flag11["status"], PASSED)


if __name__ == "__main__":
    unittest.main()
