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


class TestPeerReviewClaimProximity(unittest.TestCase):
    """verify.py can tell a genuine journal article from a Crossref
    `posted-content` (preprint) record, but only extraction sees the text —
    it has to mark which DOI, if any, the subject's own words claim as
    peer-reviewed, so verify.py knows which claim to hold that word against."""

    def test_peer_reviewed_far_from_the_doi_in_the_same_sentence_is_still_caught(self):
        """BACKLOG.md's own motivating example: 'peer-reviewed' sits well
        outside a fixed 60-character radius of the identifier it qualifies."""
        text = ("My peer-reviewed work on room-temperature superconductivity "
                "(10.1038/s41586-023-06774-2) established the field.")
        claims = ex.extract_claims(text)
        doi = ex.claims_by(claims, "artifact", "doi")[0]
        self.assertTrue(doi.claimed_peer_reviewed)

    def test_peer_reviewed_in_a_different_sentence_is_not_linked(self):
        """A subject who genuinely has separate peer-reviewed work must not
        have that claim pinned onto an unrelated identifier elsewhere in the
        bio — that would accuse an honest preprint citation of being a lie
        about a completely different paper."""
        text = ("I have several peer-reviewed publications in my field. "
                "Preliminary results are also up at 10.1101/2020.03.22.20040758.")
        claims = ex.extract_claims(text)
        doi = ex.claims_by(claims, "artifact", "doi")[0]
        self.assertFalse(doi.claimed_peer_reviewed)

    def test_self_disclosed_preprint_is_not_a_false_peer_review_claim(self):
        """Naming something a preprint in the same breath as 'peer-reviewed'
        is transparency, not deception — e.g. 'peer-reviewed elsewhere; this
        preprint (DOI) covers early results.' The guard only ever removes a
        potential trigger, never adds one, per this file's own guiding rule."""
        text = ("Our peer-reviewed methodology is also available as a preprint "
                "at 10.1101/2020.03.22.20040758 for early access.")
        claims = ex.extract_claims(text)
        doi = ex.claims_by(claims, "artifact", "doi")[0]
        self.assertFalse(doi.claimed_peer_reviewed)

    def test_ordinary_doi_citation_defaults_to_false(self):
        claims = ex.extract_claims("See 10.1038/s41586-020-2649-2 for details.")
        doi = ex.claims_by(claims, "artifact", "doi")[0]
        self.assertFalse(doi.claimed_peer_reviewed)


class TestDegreeExtraction(unittest.TestCase):
    def test_degree_with_institution(self):
        claims = ex.extract_claims("MSc Electrical Engineering, Delft University of Technology, 2015.")
        degrees = ex.claims_by(claims, "degree", "degree")
        institutions = ex.claims_by(claims, "degree", "degree_institution")
        self.assertEqual([d.value for d in degrees], ["MSc Electrical Engineering"])
        self.assertEqual([i.value for i in institutions], ["Delft University of Technology"])

    def test_field_of_study_is_not_truncated(self):
        """The lazy field group used to settle for one letter: 'MSc A', 'MBA f'."""
        claims = ex.extract_claims("MSc in Aerospace Engineering from TU Delft.")
        self.assertEqual([d.value for d in ex.claims_by(claims, "degree", "degree")],
                         ["MSc Aerospace Engineering"])

    def test_degree_without_institution(self):
        claims = ex.extract_claims("I hold an MSc in European public health policy.")
        self.assertTrue(ex.claims_by(claims, "degree", "degree"))
        self.assertFalse(ex.claims_by(claims, "degree", "degree_institution"))

    def test_employer_institution_is_not_a_degree_institution(self):
        """Binding a degree to any institution in the document cleared the
        credential flag for 'holds an MBA; worked at the Fraunhofer Institute'."""
        claims = ex.extract_claims(
            "Jan holds an MBA. He spent two years as a communications officer at the "
            "Fraunhofer Institute.")
        self.assertFalse(ex.claims_by(claims, "degree", "degree_institution"))
        self.assertTrue(ex.claims_by(claims, "degree", "mentioned_institution"))

    def test_non_anglophone_institutions_are_recognised(self):
        for name in ("Technische Universitat Munchen", "Universidad de Sevilla",
                     "Politecnico di Milano", "Ecole Polytechnique",
                     "Hogeschool Odisee", "Hogeschool van Amsterdam",
                     "Fachhochschule Aachen", "Fachhochschule für Technik",
                     "Lycee Henri IV", "Conservatoire de Paris",
                     "Gymnasium der Stadt", "Collège de France"):
            with self.subTest(name=name):
                claims = ex.extract_claims(f"Studied at {name} for four years.")
                found = ex.claims_by(claims, "degree", "mentioned_institution")
                self.assertTrue(found, f"{name} not recognised as an institution")

    def test_institution_capture_stops_at_a_sentence_boundary(self):
        claims = ex.extract_claims("Based in Wilrijk. Karolinska Institutet fellow.")
        values = [c.value for c in ex.claims_by(claims, "degree", "mentioned_institution")]
        self.assertIn("Karolinska Institutet", values)
        for v in values:
            self.assertNotIn("Wilrijk", v)

    def test_degree_institution_is_not_corrupted_by_case_insensitive_overrun(self):
        """DEGREE_RE is compiled with re.I so the field-of-study can be matched
        regardless of case, but that flag leaked into _INSTITUTION_CORE's
        [A-Z]-anchored continuation group: 'Rotterdam School of Management and
        a BSc' let the lowercase words 'and a' satisfy [A-Z][\\w-]* under
        IGNORECASE and got folded into the institution claim. The corrupted
        string is what gets sent to ROR and printed back to the reader as the
        subject's own credential — a name they never wrote. A case-sensitive
        re-scan of the source text must reproduce whatever is sent."""
        claims = ex.extract_claims(
            "She earned an MBA from Rotterdam School of Management and a BSc "
            "in Industrial Engineering.")
        institutions = [c.value for c in ex.claims_by(claims, "degree", "degree_institution")]
        self.assertEqual(institutions, ["Rotterdam School of Management"])

    def test_degree_institution_does_not_swallow_a_lowercase_connector_word(self):
        """Same overrun, different shape: the connector alternation itself
        ('of|de|des|der|van|voor|di|du|und|et|en|för|für') is matched
        case-insensitively when nested inside DEGREE_RE, so a lowercase verb
        immediately after the institution phrase can be misread as one of
        those connectors and pull the next capitalised word in too."""
        claims = ex.extract_claims(
            "PhD from Universidad de Sevilla and Roberto Diaz co-authored the paper.")
        institutions = [c.value for c in ex.claims_by(claims, "degree", "degree_institution")]
        self.assertEqual(institutions, ["Universidad de Sevilla"])


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


class TestContextExtendsToTheFullSentence(unittest.TestCase):
    """`claim.context` exists to answer one question -- verify.py's
    `_disclaims_authorship`, "does this identifier's own sentence say it
    belongs to someone else?" A fixed character-count window around the
    match clipped a disclaiming phrase sitting near the start of a longer
    sentence when the identifier itself landed further along: an honest
    patent attorney's own sentence lost its "on behalf of" disclaimer purely
    because it started more than 30 characters before the patent number,
    and a real client filing came back MISMATCH instead of UNCHECKABLE."""

    def test_a_distant_disclaiming_phrase_in_the_same_sentence_is_captured(self):
        text = ("I have spent my career as outside patent counsel prosecuting numerous "
                "filings on behalf of corporate clients, including for instance "
                "US9876543 which I filed for a sensor startup.")
        claims = ex.extract_claims(text)
        patent = ex.claims_by(claims, "artifact", "patent")[0]
        self.assertIn("on behalf of", patent.context)

    def test_context_does_not_cross_a_preceding_sentence_boundary(self):
        """The other direction: pulling in an unrelated *preceding* sentence
        would let its disclaiming language mask a real, unqualified claim
        made in the sentence that actually contains the identifier."""
        text = ("I have never filed a patent on behalf of anyone else. "
                "US9876543 is entirely my own invention and I am its sole inventor.")
        claims = ex.extract_claims(text)
        patent = ex.claims_by(claims, "artifact", "patent")[0]
        self.assertNotIn("on behalf of", patent.context)

    def test_an_ordinary_word_wrap_does_not_sever_the_sentence(self):
        """A bare '\\n' is what ordinary word-wrap produces in a plain-text
        paste, a PDF-extracted CV, or a hard-wrapped email -- it is not a
        paragraph break, and treating every one as a hard sentence boundary
        reintroduces this exact bug one line-length away from where it
        started: the disclaiming phrase and the identifier can land in the
        same sentence yet on different physical lines purely because of
        where the subject's editor happened to wrap the text."""
        text = ("I have spent my career as outside patent counsel prosecuting numerous\n"
                "filings on behalf of corporate clients, including for instance\n"
                "US9876543 which I filed for a sensor startup.")
        claims = ex.extract_claims(text)
        patent = ex.claims_by(claims, "artifact", "patent")[0]
        self.assertIn("on behalf of", patent.context)

    def test_context_does_not_cross_a_following_sentence_boundary(self):
        """Same failure, the forward direction: the identifier's own
        sentence claims it outright, and only a *later*, unrelated sentence
        happens to mention filing on behalf of clients. That later disclaimer
        must not leak backward and excuse an unqualified claim it was never
        talking about."""
        text = ("US9876543 is entirely my own invention. I have also prosecuted other "
                "patents on behalf of clients over the years.")
        claims = ex.extract_claims(text)
        patent = ex.claims_by(claims, "artifact", "patent")[0]
        self.assertNotIn("on behalf of", patent.context)


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

    def test_ascending_range_end_is_a_target_not_a_past_date(self):
        """'2025 - 2027' states an in-progress degree's expected end point, not
        a career date the subject already lived through. Before this test, the
        end year of any ascending "YYYY - YYYY" range was read exactly like an
        ordinary claimed-history year, so a current student's own study dates
        made flag 12 accuse them of stating a past event that is still in the
        future."""
        claims = ex.extract_claims("Pursuing an MSc Computer Science, TU Munchen, 2025 - 2027.")
        years = [c.value for c in ex.claims_by(claims, "timeline", "year")]
        targets = [c.value for c in ex.claims_by(claims, "timeline", "year_target")]
        self.assertNotIn("2027", years)
        self.assertIn("2027", targets)
        # The range's own start year is an ordinary, already-past date and
        # must still be readable as career history.
        self.assertIn("2025", years)

    def test_descending_or_unrelated_years_are_not_treated_as_a_range(self):
        """Only an ASCENDING adjacent pair reads as a range boundary. Two
        unrelated years that happen to sit near each other, or a range typed
        with the later year first, must not be swept into the same exemption
        — that would let a fabricator hide any inconvenient future date by
        simply preceding it with a smaller, unrelated year and a dash."""
        claims = ex.extract_claims("The prototype shipped in 2030. A separate grant ran 2015 - 2010.")
        years = [c.value for c in ex.claims_by(claims, "timeline", "year")]
        # 2030 is not preceded by any marker or ascending range and must stay
        # a plain, checkable year; "2015 - 2010" is descending (a synthetic
        # probe, not a realistic date range), so it must not exempt 2010 either.
        self.assertIn("2030", years)
        self.assertIn("2010", years)

    def test_equal_year_range_boundary_still_exempts_the_second_year(self):
        """Mutation-tested (2026-09-08): the range-start comparison `<=`
        survived as `<` with the suite green, because an ordinary ascending
        range always has two distinct years and never exercises the boundary
        where they're equal. A single-year program written 'YYYY - YYYY' is
        the same boundary case and must still exempt the second year."""
        self.assertTrue(ex._is_forward_year("2027 - 2027", 7, "2027"))
        self.assertFalse(ex._is_forward_year("2028 - 2027", 7, "2027"))

    def test_class_of_is_a_target_not_a_past_date(self):
        """'Class of 2027' is a standard way to state an expected graduating
        cohort. Without a recognised cue it read as a claimed-past date in the
        future, the same false accusation as the range case above."""
        claims = ex.extract_claims("Class of 2027, Computer Science, Colorado State University.")
        self.assertNotIn("2027", [c.value for c in ex.claims_by(claims, "timeline", "year")])


if __name__ == "__main__":
    unittest.main()
