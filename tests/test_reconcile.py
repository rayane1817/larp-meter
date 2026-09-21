"""Subject-anchored reconciliation: the first slice of the reverse path.

verify.py only checks identifiers a subject chose to type in, so a profile
that cites none has nothing checkable and comes back INSUFFICIENT DATA --
vagueness beats the tool. reconcile.py starts from what the profile CLAIMS
("President of Vane Systems AG since 2004") and asks a register what it holds.

Every registry call here is stubbed with response shapes captured from the
live Zefix API on 2026-09-22; the suite stays fully offline.
"""

import json
import tempfile
import unittest
from unittest import mock

from larp_meter import reconcile as rc
from larp_meter import TRIGGERED, PASSED, UNKNOWN
from larp_meter import extract as ex
from larp_meter.flags import AuditContext, evaluate
from larp_meter.matching import load_banks

BANKS = load_banks(path="/nonexistent")


def zefix(rows=None, details=None, fail=False):
    """A stand-in for rc._http that answers like the Zefix web API."""
    calls = []

    def fake(url, payload=None):
        calls.append(url)
        if fail:
            return False, 0, ""
        if url.endswith("/firm/search.json"):
            if not rows:
                return True, 404, json.dumps({"error": {"code": "API.ZFR.SEARCH.NORESULT"}})
            return True, 200, json.dumps({"list": rows, "hasMoreResults": False})
        ehraid = int(url.rsplit("/", 1)[1].split(".")[0])
        return True, 200, json.dumps(details[ehraid])
    fake.calls = calls
    return fake


def row(name, ehraid=1, status="EXISTIEREND"):
    return {"name": name, "ehraid": ehraid, "uid": "CHE123456789",
            "uidFormatted": "CHE-123.456.789", "legalSeat": "Zürich", "status": status}


def new_registration(name, statuten="20.06.2019", persons=None, extra=""):
    persons = persons or ("Vane, Marcus, deutscher Staatsangehöriger, in Zürich, "
                          "Präsident des Verwaltungsrates, mit Einzelunterschrift")
    return {"shabDate": "2019-07-01",
            "message": (f'<FT TYPE="F">{name}</FT>, in <FT TYPE="S">Zürich</FT>, '
                        f'<FT TYPE="A">CHE-123.456.789</FT>, Aktiengesellschaft (Neueintragung). '
                        f"Statutendatum: {statuten}. Zweck: Software. {extra}"
                        f"Eingetragene Personen: {persons}.")}


def mutation_only(name, persons="Muster, Hans, von Bern, in Bern, Mitglied des Verwaltungsrates"):
    """A company older than the gazette window: only later changes are on record."""
    return {"shabDate": "2017-03-02",
            "message": (f'<FT TYPE="F">{name}</FT>, in Zürich, CHE-123.456.789, Aktiengesellschaft '
                        f"(SHAB Nr. 1 vom 02.01.2017). Eingetragene Personen neu oder mutierend: {persons}.")}


def detail(name, pubs, old_names=None, has_taken_over=None, translation=None, status="EXISTIEREND"):
    return {"name": name, "ehraid": 1, "uid": "CHE123456789", "uidFormatted": "CHE-123.456.789",
            "legalSeat": "Zürich", "status": status, "shabPub": pubs,
            "oldNames": old_names, "hasTakenOver": has_taken_over,
            "translation": translation or [], "wasTakenOverBy": None}


def run(text, subject, http):
    with mock.patch.object(rc, "_http", http):
        return rc.reconcile_text(text, subject, tempfile.mkdtemp())


class TestExtraction(unittest.TestCase):
    def test_board_role_company_and_since_year(self):
        [c] = rc.extract_company_claims("Marcus Vane, President of DocSWISS AG (Zürich) since 2004.")
        self.assertEqual((c.company, c.legal_form, c.since, c.swiss), ("DocSWISS", "AG", 2004, True))
        self.assertTrue(c.board_role)

    def test_a_german_location_is_not_a_swiss_marker(self):
        [c] = rc.extract_company_claims("CEO at Vane Deep Tech GmbH, Berlin, since 2012.")
        self.assertEqual((c.company, c.legal_form, c.since, c.swiss), ("Vane Deep Tech", "GmbH", 2012, False))
        self.assertFalse(c.board_role)

    def test_french_form_and_open_ended_range(self):
        [c] = rc.extract_company_claims("Founder of Acme S.A., Geneva (2015 - present).")
        self.assertEqual((c.company, c.legal_form, c.since, c.swiss), ("Acme", "SA", 2015, True))

    def test_german_board_title(self):
        [c] = rc.extract_company_claims("Präsident des Verwaltungsrates der Muster AG in Bern seit 2010.")
        self.assertEqual((c.company, c.legal_form, c.since), ("Muster", "AG", 2010))
        self.assertTrue(c.board_role)

    def test_no_legal_form_means_no_register_claim(self):
        self.assertEqual(rc.extract_company_claims("President of Acme since 2004, based in Zürich."), [])

    def test_a_swiss_word_inside_the_company_name_is_not_a_location(self):
        """'DocSWISS' names the company; it says nothing about where it is registered."""
        [c] = rc.extract_company_claims("President of DocSWISS AG since 2004.")
        self.assertFalse(c.swiss)


class TestGate(unittest.TestCase):
    """The one function allowed to let a reconciliation become an accusation."""

    def test_all_three_conditions_let_a_contradiction_through(self):
        self.assertEqual(rc.gate(rc.CONTRADICTED, rc.CONFIDENT, True, True), rc.CONTRADICTED)

    def test_uncertain_identity_blocks_it(self):
        self.assertEqual(rc.gate(rc.CONTRADICTED, rc.UNCERTAIN, True, True), rc.AMBIGUOUS)

    def test_a_claim_with_no_footprint_blocks_it(self):
        self.assertEqual(rc.gate(rc.CONTRADICTED, rc.CONFIDENT, False, True), rc.AMBIGUOUS)

    def test_an_incomplete_register_blocks_it(self):
        self.assertEqual(rc.gate(rc.CONTRADICTED, rc.CONFIDENT, True, False), rc.AMBIGUOUS)

    def test_non_accusing_outcomes_pass_untouched(self):
        for outcome in (rc.CONFIRMED, rc.EXISTS, rc.NO_RECORD, rc.UNCHECKABLE, rc.AMBIGUOUS):
            self.assertEqual(rc.gate(outcome, rc.UNCERTAIN, False, False), outcome)


class TestCompanyReconciliation(unittest.TestCase):
    NAME = "Vane Systems AG"

    def _registered_2019(self, **kw):
        return zefix([row(self.NAME)], {1: detail(self.NAME, [new_registration(self.NAME, **kw)])})

    def test_a_board_role_claimed_before_the_company_existed_is_contradicted(self):
        """The case the reverse path exists for: no identifier anywhere, but a
        claim that implies a register entry, and the entry disagrees."""
        [r] = run("President of Vane Systems AG, Zürich, since 2004.", "Marcus Vane",
                  self._registered_2019())
        self.assertEqual(r.outcome, rc.CONTRADICTED)
        self.assertIn("2019", r.detail)

    def test_a_founder_claim_predating_incorporation_is_not_an_accusation(self):
        """Founders routinely work for years before incorporating. Only a role
        that cannot exist without the company -- a board seat -- can be
        contradicted by its founding date."""
        [r] = run("Founder of Vane Systems AG, Zürich, since 2004.", "Marcus Vane",
                  self._registered_2019())
        self.assertEqual(r.outcome, rc.AMBIGUOUS)

    def test_a_predecessor_business_in_the_record_is_not_an_accusation(self):
        """A Swiss AG formed by taking over a sole proprietorship carries the
        earlier business's history in substance but not in its founding date."""
        [r] = run("President of Vane Systems AG, Zürich, since 2004.", "Marcus Vane",
                  self._registered_2019(extra="Sacheinlage: übernimmt die Aktiven und Passiven "
                                              "der Einzelunternehmung Vane Consulting. "))
        self.assertEqual(r.outcome, rc.AMBIGUOUS)

    def test_a_recorded_name_change_is_not_an_accusation(self):
        http = zefix([row(self.NAME)], {1: detail(self.NAME, [new_registration(self.NAME)],
                                                  old_names=[{"name": "Vane Holding AG"}])})
        [r] = run("President of Vane Systems AG, Zürich, since 2004.", "Marcus Vane", http)
        self.assertEqual(r.outcome, rc.AMBIGUOUS)

    def test_one_year_of_slack_for_articles_signed_before_registration(self):
        [r] = run("President of Vane Systems AG, Zürich, since 2018.", "Marcus Vane",
                  self._registered_2019())
        self.assertNotEqual(r.outcome, rc.CONTRADICTED)

    def test_a_company_older_than_the_gazette_window_cannot_be_contradicted(self):
        """Zefix's gazette entries reach back to about April 2016. With no
        new-registration entry the founding year is simply unknown."""
        http = zefix([row(self.NAME)], {1: detail(self.NAME, [mutation_only(self.NAME)])})
        [r] = run("President of Vane Systems AG, Zürich, since 2004.", "Marcus Vane", http)
        self.assertEqual(r.outcome, rc.EXISTS)

    def test_the_subject_named_in_the_register_is_confirmed(self):
        [r] = run("President of Vane Systems AG, Zürich, since 2019.", "Marcus Vane",
                  self._registered_2019())
        self.assertEqual(r.outcome, rc.CONFIRMED)

    def test_someone_else_in_the_register_is_not_confirmation(self):
        [r] = run("President of Vane Systems AG, Zürich, since 2019.", "Ada Lovelace",
                  self._registered_2019())
        self.assertEqual(r.outcome, rc.EXISTS)

    def test_no_register_entry_is_a_note_never_a_contradiction(self):
        [r] = run("President of Vane Systems AG, Zürich, since 2004.", "Marcus Vane", zefix([]))
        self.assertEqual(r.outcome, rc.NO_RECORD)

    def test_several_matching_entries_are_ambiguous(self):
        http = zefix([row(self.NAME, 1), row(self.NAME, 2, status="GELOESCHT")], {})
        [r] = run("President of Vane Systems AG, Zürich, since 2004.", "Marcus Vane", http)
        self.assertEqual(r.outcome, rc.AMBIGUOUS)

    def test_an_unreachable_register_is_uncheckable_and_not_cached(self):
        cache = tempfile.mkdtemp()
        with mock.patch.object(rc, "_http", zefix(fail=True)):
            [r] = rc.reconcile_text("President of Vane Systems AG, Zürich, since 2004.", "Marcus Vane", cache)
        self.assertEqual(r.outcome, rc.UNCHECKABLE)
        http = self._registered_2019()
        with mock.patch.object(rc, "_http", http):
            [r] = rc.reconcile_text("President of Vane Systems AG, Zürich, since 2004.", "Marcus Vane", cache)
        self.assertEqual(r.outcome, rc.CONTRADICTED, "a failed lookup must not be served from cache")

    def test_no_swiss_marker_and_subject_not_on_record_cannot_accuse(self):
        """An 'AG' could be German or Austrian. Without a Swiss location and
        without the subject appearing in the entry, a same-named Swiss company
        may simply be a different firm."""
        [r] = run("President of Vane Systems AG since 2004.", "Ada Lovelace", self._registered_2019())
        self.assertEqual(r.outcome, rc.AMBIGUOUS)

    def test_the_subject_on_record_establishes_identity_without_a_location(self):
        [r] = run("President of Vane Systems AG since 2004.", "Marcus Vane", self._registered_2019())
        self.assertEqual(r.outcome, rc.CONTRADICTED)


class TestMutationSurvivors(unittest.TestCase):
    """Three behaviours the first mutation sweep of reconcile.py found
    unasserted. Each test was watched failing on its mutant."""

    NAME = "Vane Systems AG"

    def test_an_unanswerable_name_comparison_is_not_being_on_record(self):
        """name_matches returns None when it cannot decide -- here the subject
        shares only a middle surname with someone in the register. Counting
        that as 'on record' would make the identity confident with no Swiss
        location stated, and unlock a contradiction for a stranger's company."""
        pub = new_registration(self.NAME, persons="Ramirez, Luis, von Bern, in Bern, "
                                                  "Präsident des Verwaltungsrates, mit Einzelunterschrift")
        http = zefix([row(self.NAME)], {1: detail(self.NAME, [pub])})
        [r] = run("President of Vane Systems AG since 2004.", "Jose Ramirez Ortega", http)
        self.assertEqual(r.outcome, rc.AMBIGUOUS)

    def test_an_entry_whose_name_differs_from_the_claim_is_not_used(self):
        """Zefix's 'exact' search also returns translations and near-names. A
        founding date borrowed from a different company must never contradict
        the subject's claim about their own."""
        other = "Vane Systems Holding AG"
        http = zefix([row(other)], {1: detail(other, [new_registration(other)])})
        [r] = run("President of Vane Systems AG, Zürich, since 2004.", "Marcus Vane", http)
        self.assertEqual(r.outcome, rc.AMBIGUOUS)

    def test_a_company_that_merely_exists_does_not_count_as_verification(self):
        """The report's 'nothing here was checked against an outside source'
        caveat is keyed on verification_effective. Finding that a company
        exists says nothing about the subject, so it must not switch it off."""
        from larp_meter.audit import run_audit
        pub = new_registration(self.NAME, persons="Muster, Hans, von Bern, in Bern, Mitglied")
        http = zefix([row(self.NAME)], {1: detail(self.NAME, [pub])})
        with mock.patch.object(rc, "_http", http):
            report = run_audit("t", "Marcus Vane is President of Vane Systems AG, Zürich, since 2019.",
                               verify=True, subject_name="Marcus Vane", cache_dir=tempfile.mkdtemp())
        self.assertEqual(report["reconciliations"][0]["outcome"], rc.EXISTS)
        self.assertFalse(report["verification_effective"])


class TestWhoseClaimItIs(unittest.TestCase):
    """A role claim in the text is only the subject's if the subject made it."""

    NAME = "Vane Systems AG"

    def _http(self):
        return zefix([row(self.NAME)], {1: detail(self.NAME, [new_registration(
            self.NAME, persons="Muster, Hans, von Bern, in Bern, Präsident des Verwaltungsrates")])})

    def test_someone_elses_role_named_in_the_bio_is_not_the_subjects(self):
        """'I worked with Hans Muster, President of ...' is a claim about Hans
        Muster. A false date in it must not be scored against the subject."""
        [r] = run("I worked closely with Hans Muster, President of Vane Systems AG, Zürich, since 2004.",
                  "Marcus Vane", self._http())
        self.assertNotEqual(r.outcome, rc.CONTRADICTED)

    def test_the_subjects_own_name_before_the_role_is_still_their_claim(self):
        http = zefix([row(self.NAME)], {1: detail(self.NAME, [new_registration(self.NAME)])})
        [r] = run("Marcus Vane, President of Vane Systems AG, Zürich, since 2004.", "Marcus Vane", http)
        self.assertEqual(r.outcome, rc.CONTRADICTED)

    def test_a_first_person_claim_is_the_subjects(self):
        [r] = run("I am President of Vane Systems AG, Zürich, since 2004.", "Ada Lovelace", self._http())
        self.assertEqual(r.outcome, rc.CONTRADICTED)

    def test_web_mode_never_reconciles(self):
        """Web mode's corpus is search results about many people, not the
        subject's own account -- none of its role claims are theirs by default."""
        from larp_meter.audit import run_audit
        http = self._http()
        with mock.patch.object(rc, "_http", http):
            report = run_audit("t", "Jane Doe, President of Vane Systems AG, Zürich, since 2004.",
                               mode="web", verify=True, subject_name="Marcus Vane",
                               cache_dir=tempfile.mkdtemp())
        self.assertEqual(report["reconciliations"], [])
        self.assertEqual(http.calls, [])


class TestFlag11UsesReconciliation(unittest.TestCase):
    def _ctx(self, *recs):
        text = "A profile with no identifiers at all."
        return AuditContext(text=text, claims=ex.extract_claims(text), banks=BANKS,
                            subject_name="Marcus Vane", verified=True, reconciliations=list(recs))

    def test_a_contradicted_company_role_triggers_flag_11(self):
        r = rc.Reconciliation(company="Vane Systems AG", outcome=rc.CONTRADICTED,
                              detail="incorporated 2019")
        self.assertEqual(evaluate(self._ctx(r))[11].status, TRIGGERED)

    def test_a_confirmed_company_role_passes_flag_11_without_any_identifier(self):
        r = rc.Reconciliation(company="Vane Systems AG", outcome=rc.CONFIRMED, detail="named")
        self.assertEqual(evaluate(self._ctx(r))[11].status, PASSED)

    def test_notes_alone_leave_flag_11_undecided(self):
        for outcome in (rc.EXISTS, rc.NO_RECORD, rc.AMBIGUOUS, rc.UNCHECKABLE):
            with self.subTest(outcome=outcome):
                r = rc.Reconciliation(company="Vane Systems AG", outcome=outcome, detail="x")
                res = evaluate(self._ctx(r))[11]
                self.assertEqual(res.status, UNKNOWN)
                self.assertIn("Vane Systems AG", " ".join(res.evidence))


class TestEndToEnd(unittest.TestCase):
    """Through run_audit, the path production takes -- not the pieces alone."""

    FABRICATED = ("Marcus Vane is President of Vane Systems AG, Zürich, since 2004, pioneering "
                  "revolutionary, groundbreaking, world class, disruptive edge AI. Seeking investment "
                  "of 10 million. MoU signed, NDA in place, discussions ongoing. Education: MBA "
                  "Healthcare Management, MSc European Public Health. 40 years of experience.")

    def _audit(self, text, http):
        from larp_meter.audit import run_audit
        with mock.patch.object(rc, "_http", http):
            return run_audit("t", text, verify=True, subject_name="Marcus Vane",
                             cache_dir=tempfile.mkdtemp())

    def test_a_vague_profile_with_no_identifiers_is_caught_by_its_company_claim(self):
        http = zefix([row("Vane Systems AG")],
                     {1: detail("Vane Systems AG", [new_registration("Vane Systems AG")])})
        report = self._audit(self.FABRICATED, http)
        flag11 = next(f for f in report["flags"] if f["id"] == 11)
        self.assertEqual(flag11["status"], TRIGGERED)
        self.assertEqual(report["reconciliations"][0]["outcome"], rc.CONTRADICTED)

    def test_the_honest_version_of_the_same_founder_passes(self):
        honest = ("Marcus Vane is President of Vane Systems AG, Zürich, since 2019, building edge AI "
                  "for industrial sensors. MSc Electrical Engineering.")
        http = zefix([row("Vane Systems AG")],
                     {1: detail("Vane Systems AG", [new_registration("Vane Systems AG")])})
        report = self._audit(honest, http)
        flag11 = next(f for f in report["flags"] if f["id"] == 11)
        self.assertEqual(flag11["status"], PASSED)

    def test_without_verify_no_register_is_contacted(self):
        from larp_meter.audit import run_audit
        http = zefix([row("Vane Systems AG")], {})
        with mock.patch.object(rc, "_http", http):
            report = run_audit("t", self.FABRICATED, subject_name="Marcus Vane")
        self.assertEqual(http.calls, [])
        self.assertEqual(report["reconciliations"], [])


if __name__ == "__main__":
    unittest.main()
