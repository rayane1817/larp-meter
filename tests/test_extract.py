import unittest

from larp_meter import extract as ex


class TestArtifactExtraction(unittest.TestCase):
    def test_doi(self):
        claims = ex.extract_claims("See 10.1038/s41586-020-2649-2 for details.")
        dois = ex.claims_by(claims, "artifact", "doi")
        self.assertEqual([c.value for c in dois], ["10.1038/s41586-020-2649-2"])

    def test_orcid_patent_github_arxiv_nct(self):
        text = ("orcid.org/0000-0002-1825-0097, patent US10123456, "
                "github.com/acme/slam, arxiv.org/abs/2101.00001, trial NCT01234567")
        claims = ex.extract_claims(text)
        found = {(c.subtype, c.value) for c in claims if c.kind == "artifact"}
        self.assertIn(("orcid", "0000-0002-1825-0097"), found)
        self.assertIn(("patent", "US10123456"), found)
        self.assertIn(("github", "acme/slam"), found)
        self.assertIn(("arxiv", "2101.00001"), found)
        self.assertIn(("nct", "NCT01234567"), found)

    def test_no_artifacts_in_plain_prose(self):
        claims = ex.extract_claims("I am building an innovative platform for everyone.")
        self.assertEqual(ex.claims_by(claims, "artifact"), [])


class TestDegreeExtraction(unittest.TestCase):
    def test_degree_with_institution(self):
        claims = ex.extract_claims("MSc Electrical Engineering, Delft University of Technology, 2015.")
        degrees = ex.claims_by(claims, "degree", "degree")
        institutions = ex.claims_by(claims, "degree", "institution")
        self.assertTrue(any("MSc" in d.value for d in degrees))
        self.assertTrue(institutions, "institution should be captured")

    def test_degree_without_institution(self):
        claims = ex.extract_claims("I hold an MSc in European public health policy.")
        self.assertTrue(ex.claims_by(claims, "degree", "degree"))
        self.assertFalse(ex.claims_by(claims, "degree", "institution"))


class TestOrgExtraction(unittest.TestCase):
    def test_self_referential_overlap_detected_generically(self):
        """No hardcoded org names — v2 shipped one person's orgs in the source."""
        text = ("Founder of AetherLink. We announced a partnership with AetherLink "
                "to validate the technology.")
        overlap, owned, partners = ex.owned_and_partner_orgs(ex.extract_claims(text))
        self.assertTrue(overlap)
        self.assertIn("aetherlink", {ex.norm_org(o) for o in owned})

    def test_independent_partner_is_not_flagged(self):
        text = "Founder of Marrow Robotics. Partnership with Port of Rotterdam."
        overlap, _owned, partners = ex.owned_and_partner_orgs(ex.extract_claims(text))
        self.assertFalse(overlap)
        self.assertTrue(partners)

    def test_legal_suffix_normalisation(self):
        self.assertEqual(ex.norm_org("Helix Systems GmbH"), ex.norm_org("Helix Systems"))


class TestTimelineAndTraction(unittest.TestCase):
    def test_experience_years(self):
        claims = ex.extract_claims("40 years of experience in propulsion.")
        self.assertEqual([c.value for c in ex.claims_by(claims, "timeline", "claimed_experience_years")],
                         ["40"])

    def test_traction_numbers(self):
        claims = ex.extract_claims("We serve 40 customers and 12,000 users.")
        values = [c.value for c in ex.claims_by(claims, "traction")]
        self.assertTrue(any("customers" in v for v in values))

    def test_specificity_index_separates_vague_from_concrete(self):
        vague = "We are building a revolutionary platform that will change everything forever."
        concrete = ("MSc Electrical Engineering, Delft University of Technology, 2015. "
                    "Patent US10123456. 40 customers, 2.1M revenue.")
        self.assertGreater(ex.specificity_index(concrete), ex.specificity_index(vague))


if __name__ == "__main__":
    unittest.main()
