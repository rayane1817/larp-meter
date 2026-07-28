"""Provider chain and name matching — fully offline, every fetch stubbed."""

import json
import unittest

from larp_meter import names, providers


def stub(mapping):
    """fetch(url) -> canned body for the first matching substring."""
    def fetch(url, browser=False):
        for needle, body in mapping.items():
            if needle in url:
                return body
        return ""
    return fetch


WIKI_BODY = json.dumps({"query": {"search": [
    {"title": "Ada Lovelace", "snippet": "an English <b>mathematician</b>"},
    {"title": "Analytical Engine", "snippet": "mentions Lovelace in passing"},
]}})

OPENALEX_BODY = json.dumps({"results": [
    {"id": "https://openalex.org/A1", "display_name": "Ada Lovelace", "works_count": 11,
     "cited_by_count": 429, "last_known_institutions": [{"display_name": "Analytical Society"}]},
    {"id": "https://openalex.org/A2", "display_name": "Rex Falsum", "works_count": 900,
     "cited_by_count": 99999, "last_known_institutions": []},
]})

CROSSREF_BODY = json.dumps({"message": {"items": [
    {"title": ["On the Analytical Engine"], "DOI": "10.1000/a",
     "author": [{"given": "Ada", "family": "Lovelace"}]},
    {"title": ["Unrelated Paper"], "DOI": "10.1000/b",
     "author": [{"given": "Someone", "family": "Else"}]},
]}})


class TestNameMatching(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(names.name_matches("Ada Lovelace", ["Ada Lovelace"]))

    def test_initial_plus_surname(self):
        """Author lists are often abbreviated — this must not read as a mismatch."""
        self.assertTrue(names.name_matches("Ada Lovelace", ["A. Lovelace"]))

    def test_diacritics_are_ignored(self):
        self.assertTrue(names.name_matches("Jürgen Müller", ["Jurgen Muller"]))
        self.assertTrue(names.name_matches("Jurgen Muller", ["Jürgen Müller"]))

    def test_particles_do_not_count_as_matches(self):
        """'van' matching 'van' must not make two unrelated Dutch names equal."""
        self.assertFalse(names.name_matches("Jan van Dijk", ["Piet van Houten"]))

    def test_different_person_is_a_mismatch(self):
        self.assertFalse(names.name_matches("Ada Lovelace", ["Yann LeCun", "Geoffrey Hinton"]))

    def test_mononym(self):
        self.assertTrue(names.name_matches("Prince", ["Prince"]))
        self.assertFalse(names.name_matches("Prince", ["Madonna"]))

    def test_no_subject_name_is_unanswerable_not_false(self):
        """None means 'cannot say'; treating it as False would invent an accusation."""
        self.assertIsNone(names.name_matches("", ["Anyone"]))

    def test_empty_candidates_is_a_mismatch_not_a_crash(self):
        self.assertFalse(names.name_matches("Ada Lovelace", []))

    def test_surname_only_still_matches(self):
        self.assertTrue(names.name_matches("Ada Lovelace", ["Lovelace, A."]))

    def test_honorifics_stripped(self):
        self.assertTrue(names.name_matches("Dr. Ada Lovelace", ["Ada Lovelace"]))


class TestWikipedia(unittest.TestCase):
    def test_article_about_the_subject_is_distinguished_from_a_mention(self):
        findings, signals = providers.Wikipedia(stub({"wikipedia.org": WIKI_BODY})).search("Ada Lovelace")
        self.assertEqual(len(findings), 2)
        self.assertEqual(signals["wikipedia_about_subject"], ["Ada Lovelace"])

    def test_unreachable_wikipedia_yields_nothing(self):
        findings, signals = providers.Wikipedia(stub({})).search("Ada Lovelace")
        self.assertEqual(findings, [])
        self.assertEqual(signals, {})

    def test_malformed_json_does_not_raise(self):
        findings, _ = providers.Wikipedia(stub({"wikipedia.org": "<html>nope"})).search("Ada")
        self.assertEqual(findings, [])


class TestOpenAlex(unittest.TestCase):
    def test_only_matching_authors_are_kept(self):
        """A prolific stranger ranking highly must not become the subject's record."""
        findings, signals = providers.OpenAlex(stub({"openalex.org": OPENALEX_BODY})).search("Ada Lovelace")
        self.assertEqual(len(findings), 1)
        self.assertEqual(signals["openalex"]["works"], 11)
        self.assertNotEqual(signals["openalex"]["works"], 900)

    def test_no_match_reports_none(self):
        _findings, signals = providers.OpenAlex(stub({"openalex.org": OPENALEX_BODY})).search("Nobody Here")
        self.assertIsNone(signals["openalex"])


class TestCrossref(unittest.TestCase):
    def test_filters_to_the_subjects_papers(self):
        findings, signals = providers.Crossref(stub({"crossref.org": CROSSREF_BODY})).search("Ada Lovelace")
        self.assertEqual(signals["crossref_works"], 1)
        self.assertIn("Analytical Engine", findings[0].title)


class TestGatherChain(unittest.TestCase):
    def test_records_which_providers_answered(self):
        fetch = stub({"wikipedia.org": WIKI_BODY, "openalex.org": OPENALEX_BODY})
        bundle = providers.gather("Ada Lovelace", fetch)
        self.assertIn("wikipedia", bundle.providers_ok)
        self.assertIn("openalex", bundle.providers_ok)
        self.assertIn("duckduckgo", bundle.providers_failed)

    def test_total_provider_failure_is_survivable(self):
        bundle = providers.gather("Ada Lovelace", stub({}))
        self.assertEqual(bundle.findings, [])
        self.assertEqual(bundle.corpus, "")
        self.assertEqual(len(bundle.providers_failed), len(providers.ALL_PROVIDERS))

    def test_a_raising_provider_does_not_sink_the_chain(self):
        class Exploding(providers.Provider):
            name = "exploding"

            def search(self, subject):
                raise RuntimeError("boom")

        bundle = providers.gather("Ada Lovelace", stub({"wikipedia.org": WIKI_BODY}),
                                  providers=(Exploding, providers.Wikipedia))
        self.assertIn("exploding", bundle.providers_failed)
        self.assertIn("wikipedia", bundle.providers_ok)

    def test_urls_are_deduplicated_in_order(self):
        bundle = providers.Gathered(findings=[
            providers.Finding("https://a", "A"), providers.Finding("https://b", "B"),
            providers.Finding("https://a", "A again"), providers.Finding("", "no url")])
        self.assertEqual(bundle.urls, ["https://a", "https://b"])

    def test_controlled_hosts_are_not_independent(self):
        self.assertFalse(providers._is_independent("https://www.linkedin.com/in/someone"))
        self.assertFalse(providers._is_independent("https://medium.com/@someone/post"))
        self.assertTrue(providers._is_independent("https://www.reuters.com/article/x"))

    def test_lookalike_host_is_not_treated_as_controlled(self):
        self.assertTrue(providers._is_independent("https://notlinkedin.example.com/x"))


class TestSignalsReachFlags(unittest.TestCase):
    def test_scholarly_record_satisfies_the_output_flag(self):
        from larp_meter.audit import run_audit
        text = "Founder building neural network hardware. Coming soon."
        without = run_audit("x", text, mode="web")
        with_signal = run_audit("x", text, mode="web",
                                signals={"openalex": {"works": 11, "citations": 429,
                                                      "institutions": [], "display_name": "X"}})
        self.assertEqual(next(f for f in without["flags"] if f["id"] == 6)["status"], "TRIGGERED")
        self.assertEqual(next(f for f in with_signal["flags"] if f["id"] == 6)["status"], "PASSED")

    def test_wikipedia_article_satisfies_the_validation_flag(self):
        from larp_meter.audit import run_audit
        text = ("Founder and chief executive building satellite hardware and machine learning "
                "systems for a deep tech venture with a substantial engineering team today.")
        with_signal = run_audit("x", text, mode="web",
                                signals={"wikipedia_about_subject": ["Some Person"]})
        self.assertEqual(next(f for f in with_signal["flags"] if f["id"] == 10)["status"], "PASSED")


if __name__ == "__main__":
    unittest.main()
