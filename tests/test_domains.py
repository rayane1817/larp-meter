"""Domain taxonomy: generalization beyond the 'tech LARP' archetype, and fairness."""

import unittest

from larp_meter import TRIGGERED, PASSED, UNKNOWN
from larp_meter import domains as dom
from larp_meter.audit import run_audit


def audit(text):
    return run_audit("t", text, mode="text")


def flag(text, fid):
    return next(f for f in audit(text)["flags"] if f["id"] == fid)


class TestEducationContext(unittest.TestCase):
    def test_credentials_only_count_inside_an_education_context(self):
        """'a quantitative finance fund' is a claim, not a qualification."""
        text = "We run a quantitative finance hedge fund. BA in fine arts."
        creds = dom.supporting_domains(text, "credentials")
        self.assertIn(dom.DESIGN, creds)
        self.assertNotIn(dom.FINANCE, creds)

    def test_credential_inside_degree_phrase_counts(self):
        text = "MSc Financial Engineering, University of Ghent, 2011."
        self.assertIn(dom.FINANCE, dom.supporting_domains(text, "credentials"))

    def test_education_span_stops_at_sentence_boundary(self):
        text = "We build satellites and radiation tolerant hardware. BA in fine arts."
        spans = " ".join(dom.education_spans(text))
        self.assertIn("fine arts", spans)
        self.assertNotIn("satellites", spans)

    def test_no_education_context_yields_no_credentials(self):
        self.assertEqual(dom.supporting_domains("I build rockets for a living.", "credentials"), {})


class TestNonTechArchetypes(unittest.TestCase):
    """v2 could only see one kind of fabricator. These must all be caught."""

    FINANCE_LARP = ("Managing Partner at Meridian Capital. We run a hedge fund with a "
                    "proprietary trading strategy and derivatives portfolio management. "
                    "BA in fine arts. Previously a brand manager and content strategist.")
    MEDICAL_LARP = ("Chief Medical Officer of Helix Diagnostics, delivering clinical "
                    "treatment, diagnosis and therapeutic patient care. MBA in management. "
                    "Former account manager and press officer.")
    LEGAL_LARP = ("General Counsel at Vantage Group, handling litigation, arbitration and "
                  "regulatory compliance for the group. Bachelor of marketing. Previously a "
                  "copywriter and brand manager.")

    def test_finance_larp_credentials_flagged(self):
        self.assertEqual(flag(self.FINANCE_LARP, 1)["status"], TRIGGERED)

    def test_medical_larp_credentials_flagged(self):
        self.assertEqual(flag(self.MEDICAL_LARP, 1)["status"], TRIGGERED)

    def test_legal_larp_credentials_flagged(self):
        self.assertEqual(flag(self.LEGAL_LARP, 1)["status"], TRIGGERED)

    def test_experience_flag_catches_domain_gap(self):
        self.assertEqual(flag(self.MEDICAL_LARP, 2)["status"], TRIGGERED)

    def test_generic_role_tokens_do_not_bridge_domains(self):
        """'brand manager' must not read as finance experience."""
        roles = dom.supporting_domains(self.FINANCE_LARP, "roles")
        self.assertNotIn(dom.FINANCE, roles)


class TestLegitimateProfilesPass(unittest.TestCase):
    def test_real_quant(self):
        text = ("Managing Partner at Meridian Capital running a quantitative finance "
                "strategy. MSc Financial Engineering, University of Ghent, 2011. Twelve "
                "years as a trader and portfolio manager.")
        self.assertEqual(flag(text, 1)["status"], PASSED)
        self.assertEqual(flag(text, 2)["status"], PASSED)

    def test_real_physician(self):
        text = ("Chief Medical Officer of Helix Diagnostics working on diagnosis and "
                "patient care. Doctor of Medicine, University of Ghent, 2006. Fifteen "
                "years as a consultant physician.")
        self.assertEqual(flag(text, 1)["status"], PASSED)

    def test_adjacent_field_is_accepted(self):
        """A physicist leading an AI hardware venture is not a fabricator."""
        text = ("Founder of Nimbus Compute, building semiconductor and neural network "
                "hardware. PhD in physics, University of Ghent, 2012.")
        self.assertEqual(flag(text, 1)["status"], PASSED)
        self.assertIn("adjacent", flag(text, 1)["description"])


class TestFairness(unittest.TestCase):
    def test_open_entry_fields_are_never_credential_flagged(self):
        """Self-taught marketers and designers must not be penalised for lacking a degree."""
        for text in (
            "Head of brand strategy and growth marketing at Nimbus. PhD in physics.",
            "Creative director doing product design and creative direction. MSc chemistry.",
            "Director general driving policy reform and stakeholder engagement. BSc biology.",
        ):
            with self.subTest(text=text[:40]):
                self.assertEqual(flag(text, 1)["status"], PASSED)

    def test_credential_gated_set_is_deliberate(self):
        self.assertEqual(dom.CREDENTIAL_GATED,
                         {dom.TECHNOLOGY, dom.SCIENCE, dom.MEDICINE, dom.FINANCE, dom.LAW})
        for open_field in (dom.MARKETING, dom.DESIGN, dom.BUSINESS, dom.POLICY, dom.EDUCATION):
            self.assertNotIn(open_field, dom.CREDENTIAL_GATED)

    def test_career_changer_is_not_flagged(self):
        """Engineer who moved into policy work: no deception, must not trigger."""
        text = ("Policy officer driving regulatory affairs and public consultation at a "
                "health NGO. MSc Electrical Engineering, 2008.")
        self.assertEqual(flag(text, 1)["status"], PASSED)

    def test_no_domain_claim_is_undecidable_not_clean(self):
        self.assertEqual(flag("I enjoy long walks and good bread.", 1)["status"], UNKNOWN)


class TestTaxonomyIntegrity(unittest.TestCase):
    def test_credential_transfer_is_directional(self):
        """Symmetric transfer let a public-policy degree clear a claim to
        deliver clinical treatment. Training flows from the more demanding
        field to the applied one, not back."""
        self.assertIn(dom.POLICY, dom.SUPPORTS[dom.MEDICINE])      # doctor -> health policy
        self.assertNotIn(dom.MEDICINE, dom.SUPPORTS[dom.POLICY])   # policy grad -/-> clinician
        self.assertIn(dom.TECHNOLOGY, dom.SUPPORTS[dom.SCIENCE])   # physicist -> engineering
        self.assertIn(dom.EDUCATION, dom.SUPPORTS[dom.SCIENCE])    # scientist -> teaching
        self.assertNotIn(dom.SCIENCE, dom.SUPPORTS[dom.EDUCATION])  # teacher -/-> scientist

    def test_every_domain_supports_itself(self):
        for name in dom.DOMAINS:
            self.assertIn(name, dom.SUPPORTS[name])

    def test_transfer_is_not_transitive(self):
        """technology -> science -> medicine must not chain into
        technology -> medicine."""
        self.assertIn(dom.SCIENCE, dom.SUPPORTS[dom.TECHNOLOGY])
        self.assertIn(dom.MEDICINE, dom.SUPPORTS[dom.SCIENCE])
        supported, _via = dom.is_supported(dom.MEDICINE, {dom.TECHNOLOGY: ["engineering"]})
        self.assertFalse(supported)

    def test_every_domain_has_all_facets(self):
        for name, spec in dom.DOMAINS.items():
            for facet in ("claims", "credentials", "roles"):
                self.assertTrue(spec.get(facet), f"{name} missing {facet}")

    def test_every_domain_has_a_support_entry(self):
        for name in dom.DOMAINS:
            self.assertIn(name, dom.SUPPORTS)

    def test_a_non_qualifying_degree_cannot_clear_a_gated_claim(self):
        """The evasion this closed: naming a policy degree instead of an MBA
        made a fabricated Chief Medical Officer profile pass flag 1."""
        text = ("Chief Medical Officer of Helix Diagnostics, delivering clinical treatment, "
                "therapeutic diagnosis and patient care pathways. MSc Public Policy, "
                "University of Ghent, 2011. Former policy officer and lobbyist.")
        self.assertEqual(flag(text, 1)["status"], TRIGGERED)

    def test_a_doctor_moving_into_policy_is_not_flagged(self):
        text = ("Director general driving health policy reform and regulatory affairs. "
                "Doctor of Medicine, University of Ghent, 2006. Fifteen years as a "
                "consultant physician before moving into public affairs.")
        self.assertNotEqual(flag(text, 1)["status"], TRIGGERED)

    def test_no_marker_is_shared_by_two_domains_in_the_same_facet(self):
        """Shared markers make domain attribution ambiguous and let claims cross-validate."""
        for facet in ("claims", "credentials", "roles"):
            seen = {}
            for name, spec in dom.DOMAINS.items():
                for marker in spec[facet]:
                    if marker in seen:
                        self.fail(f"'{marker}' appears in both {seen[marker]} and {name} ({facet})")
                    seen[marker] = name


if __name__ == "__main__":
    unittest.main()
