"""Reverse path, Belgium: company roles against the KBO/BCE register.

Belgium's Crossroads Bank for Enterprises (KBO/BCE) is complete for Belgian
legal entities, and its public search shows what Zefix's gazette cannot for
older companies: every entity's start date, its current directors, and its
links to other entities (absorptions, splits). The markup below is copied
from the live public search on 2026-09-22 with invented names; the suite
stays offline.

Belgium adds one way to hurt an honest founder that Switzerland's gazette
makes visible and KBO does not: running the business as a sole trader under
one's own name before incorporating it. So a contradiction also needs a
search that finds no sole-trader enterprise under the subject's name older
than the company.
"""

import tempfile
import unittest
from unittest import mock

from larp_meter import reconcile as rc
from larp_meter import TRIGGERED


def search_page(rows):
    """KBO exact-name search results: rows of (number, start, name, form, status)."""
    if not rows:
        # Live markup: no banner and no table, just a heading.
        return ('<div>Zoekwoord: x<span class="upd">(inclusief oude namen)</span></div><br/>'
                '<h1>Geen gegevens gevonden voor dit zoekwoord.</h1><br/>')
    else:
        banner = "Eén entiteit gevonden." if len(rows) == 1 else f"{len(rows)} entiteiten gevonden, van 1 tot {len(rows)} getoond."
    body = "".join(
        f'<tr class="{"odd" if i % 2 == 0 else "even"}">\n<td>{i + 1}</td>\n<td>\n\t\t\t\t\t\t{status}\n\t\t\t\t\t</td>\n'
        f'<td style="width: 17%"><a href="toonondernemingps.html?ondernemingsnummer={int(number.replace(".", ""))}">{number}</a>'
        f'<br/><span class="upd">{start}</span><br/></td>\n<td class="benaming" style="width: 12%">{name}</td>\n'
        f'<td class="nowrap"><span class="upd">Adres van de zetel:</span><br/>Kerkstraat&nbsp;\n 1<br/>1000&nbsp;\n Brussel<br/></td>\n'
        f'<td>{kind}<br/>{form}</td>\n<td class="nowrap"></td></tr>'
        for i, (number, start, name, form, status, kind) in enumerate(
            (r + ("Rechtspersoon",)) if len(r) == 5 else r for r in rows))
    return (f'<html><body><span class="pagebanner">{banner}</span>'
            f'<table><tbody>{body}</tbody></table><span class="pagebanner">{banner}</span></body></html>')


def detail_page(name="VANE SYSTEMS", start="3 maart 2019", form="Naamloze vennootschap",
                people=(("Bestuurder", "Vane", "Marcus"),), links=(), status="Actief"):
    rows = "".join(
        f'<tr><td class="RL">{role}\n\t\t\t\t\t\t\t\t\t\t\t</td><td class="RL">\n\t\t\t\t\t\t\t\t\t\t\t\t\t {surname} ,&nbsp;  {given}&nbsp;\n'
        f'\t\t\t\t\t\t\t\t\t\t\t\t</td><td class="RL"><span class="upd">Sinds 3 maart 2019</span></td></tr>'
        for role, surname, given in people)
    rows += ('<tr><td class="QL">Bestuurder\n</td><td class="QL"><a href="toonondernemingps.html?ondernemingsnummer=470622224">'
             '0470.622.224</a>&nbsp;&nbsp;\t\t\t</td><td class="QL"><span class="upd">Sinds 28 april 2026</span></td></tr>')
    link_rows = "".join(
        f'<tr><td class="QL" colspan="4"><a href="toonondernemingps.html?ondernemingsnummer=403174065" class="QL">0403.174.065</a>'
        f' ({other})\n\t\t\t\t\t\t\t\t\t\t\n&nbsp;\n is opgeslorpt door deze entiteit&nbsp;\n sinds 20 juni 2003<br/></td></tr>'
        for other in links)
    link_section = (f'<tr><td class="I" colspan="4"><h2>Linken tussen entiteiten</h2></td></tr>{link_rows}' if links else "")
    return (
        '<h1>Gegevens van de geregistreerde entiteit</h1><div id="table"><table>'
        '<tr><td class="I" colspan="4"><h2>Algemeen</h2></td></tr>'
        '<tr><td class="QL">Ondernemingsnummer:</td><td class="QL" colspan="3">0712.345.678\n</td></tr>'
        f'<tr><td class="RL">Status:</td><td class="RL" colspan="3"><strong><span class="pageactief">{status}</span></strong></td></tr>'
        f'<tr><td class="RL">Begindatum:</td><td class="RL" colspan="3">{start}<br/></td></tr>'
        f'<tr><td class="QL">Naam:</td><td class="QL" colspan="3">{name}<br/><span class="upd">Naam in het Nederlands, sinds {start}</span><br/></td></tr>'
        '<tr><td class="RL">Type entiteit:\n</td><td class="RL" colspan="3">Rechtspersoon</td></tr>'
        f'<tr><td class="QL">Rechtsvorm:\n</td><td class="QL" colspan="3">\n\t\t\t\t\t\t\t{form}\n\n\t\t\t\t\t\t\t<br/><span class="upd">Sinds {start}</span></td></tr>'
        '<tr><td class="I" colspan="4"><h2>Functies</h2></td></tr>'
        f'<tr><td colspan="3"><table style="display: none" id="toonfctie" cellspacing="0" cellpadding="7" width="100%">{rows}</table></td></tr>'
        f'<tr><td class="I" colspan="4"><h2>Hoedanigheden</h2></td></tr>{link_section}'
        '</table></div>')


def kbo(companies=(), detail=None, sole_traders=(), fail=False, people_fail=False):
    """A stand-in for rc._http answering like the KBO public search."""
    calls = []

    def fake(url, payload=None, headers=None):
        calls.append(url)
        if fail:
            return False, 0, ""
        if "zefix" in url or "openalex" in url:
            raise AssertionError("wrong register: " + url)
        if "natuurlijkPersoon=natuurlijkPersoon" in url:
            if people_fail:
                return False, 503, ""
            return True, 200, search_page([(n, s, nm, "", st, "Natuurlijk Persoon") for n, s, nm, st in sole_traders])
        if "natuurlijkPersoon=rechtsPersoon" in url:
            return True, 200, search_page(list(companies))
        if "toonondernemingps.html" in url:
            return True, 200, detail or detail_page()
        raise AssertionError(url)
    fake.calls = calls
    return fake


VANE = ("0712.345.678", "3 maart 2019", "VANE SYSTEMS", "Naamloze vennootschap", "Actief")


def run(text, subject, http):
    with mock.patch.object(rc, "_http", http):
        return [r for r in rc.reconcile_text(text, subject, tempfile.mkdtemp()) if r.kind == "company"]


class TestExtraction(unittest.TestCase):
    def test_dutch_board_role_and_form(self):
        [c] = rc.extract_company_claims("Gedelegeerd bestuurder van Vane Systems NV, Gent, sinds 2004.")
        self.assertEqual((c.company, c.legal_form, c.since, c.belgian, c.swiss), ("Vane Systems", "NV", 2004, True, False))
        self.assertTrue(c.board_role)

    def test_french_forms(self):
        [c] = rc.extract_company_claims("Gérant de Vane Conseil SPRL à Liège depuis 2010.")
        self.assertEqual((c.company, c.legal_form, c.since, c.belgian), ("Vane Conseil", "SPRL", 2010, True))
        self.assertTrue(c.board_role)
        [c] = rc.extract_company_claims("Administrateur délégué de Vane S.A., Bruxelles, depuis 2004.")
        self.assertEqual((c.company, c.legal_form, c.belgian), ("Vane", "SA", True))

    def test_new_and_dotted_forms(self):
        for text, form in (("Zaakvoerder van Vane BV sinds 2019.", "BV"),
                           ("Zaakvoerder van Vane B.V.B.A. sinds 2009.", "BVBA"),
                           ("Voorzitter van Vane vzw sinds 2001.", "VZW"),
                           ("Director of Vane SRL since 2021.", "SRL")):
            with self.subTest(text=text):
                self.assertEqual(rc.extract_company_claims(text)[0].legal_form, form)

    def test_enterprise_number_and_be_domain_are_belgian_markers(self):
        self.assertTrue(rc.extract_company_claims("CEO of Vane NV (BE 0712.345.678) since 2019.")[0].belgian)
        self.assertTrue(rc.extract_company_claims("Director of Vane NV, vane.be, since 2019.")[0].belgian)

    def test_a_curriculum_vitae_is_not_a_company(self):
        self.assertEqual(rc.extract_company_claims("Founder of Acme. Full CV on request."), [])


class TestRouting(unittest.TestCase):
    def test_belgian_forms_go_to_kbo(self):
        http = kbo([VANE])
        run("Bestuurder van Vane Systems NV, Gent, sinds 2019.", "Marcus Vane", http)
        self.assertTrue(http.calls and all("kbopub" in u for u in http.calls))

    def test_a_dutch_company_is_not_looked_up_in_belgium(self):
        http = kbo([VANE])
        self.assertEqual(run("Director of Vane Systems N.V., Amsterdam, since 2004.", "Marcus Vane", http), [])
        self.assertEqual(http.calls, [])

    def test_an_sa_in_belgium_goes_to_kbo_and_in_switzerland_to_zefix(self):
        http = kbo([VANE])
        run("Administrateur de Vane Systems SA, Bruxelles, depuis 2019.", "Marcus Vane", http)
        self.assertTrue(all("kbopub" in u for u in http.calls))
        swiss_calls = []

        def zefix_only(url, payload=None, headers=None):
            swiss_calls.append(url)
            return True, 404, "{}"
        run("Administrateur de Vane Systems SA, Genève, depuis 2019.", "Marcus Vane", zefix_only)
        self.assertTrue(swiss_calls and all("zefix" in u for u in swiss_calls))


class TestBelgianReconciliation(unittest.TestCase):
    CLAIM = "Marcus Vane, Gedelegeerd bestuurder van Vane Systems NV, Gent, sinds 2004."

    def test_a_board_role_before_the_company_existed_is_contradicted(self):
        [r] = run(self.CLAIM, "Marcus Vane", kbo([VANE]))
        self.assertEqual((r.outcome, r.identity), (rc.CONTRADICTED, rc.CONFIDENT))
        self.assertIn("2019", r.detail)
        self.assertIn("KBO", r.source)

    def test_a_sole_trader_under_the_subjects_name_blocks_it(self):
        """Running the business in one's own name, then incorporating it, is
        the honest version of exactly this date gap."""
        http = kbo([VANE], sole_traders=[("0612.111.222", "1 mei 2003", "Vane, Marcus", "Stopgezet")])
        [r] = run(self.CLAIM, "Marcus Vane", http)
        self.assertEqual(r.outcome, rc.AMBIGUOUS)
        self.assertIn("sole", r.detail)

    def test_a_later_sole_trader_does_not_explain_the_gap(self):
        http = kbo([VANE], sole_traders=[("0612.111.222", "1 mei 2021", "Vane, Marcus", "Actief")])
        [r] = run(self.CLAIM, "Marcus Vane", http)
        self.assertEqual(r.outcome, rc.CONTRADICTED)

    def test_an_unanswered_sole_trader_search_blocks_it(self):
        [r] = run(self.CLAIM, "Marcus Vane", kbo([VANE], people_fail=True))
        self.assertEqual(r.outcome, rc.AMBIGUOUS)

    def test_more_sole_traders_than_one_page_shows_blocks_it(self):
        """Only the first page is read; an older one could be on the next."""
        page = [(f"0612.111.{i:03d}", "1 mei 2022", "Vane, Marcus", "Actief") for i in range(20)]
        http = kbo([VANE], sole_traders=page)
        with mock.patch.object(rc, "_kbo_count", lambda html: 75):
            [r] = run(self.CLAIM, "Marcus Vane", http)
        self.assertEqual(r.outcome, rc.AMBIGUOUS)

    def test_an_absorbed_predecessor_blocks_it(self):
        http = kbo([VANE], detail=detail_page(links=("VANE CONSULTING",)))
        [r] = run(self.CLAIM, "Marcus Vane", http)
        self.assertEqual(r.outcome, rc.AMBIGUOUS)
        self.assertIn("VANE CONSULTING", " ".join(r.evidence) + r.detail)

    def test_a_founder_claim_is_not_an_accusation(self):
        [r] = run("Oprichter van Vane Systems NV, Gent, sinds 2004.", "Marcus Vane", kbo([VANE]))
        self.assertEqual(r.outcome, rc.AMBIGUOUS)

    def test_a_non_profit_board_can_predate_its_registration(self):
        """A de facto association often runs for years before becoming a vzw."""
        vzw = ("0712.345.678", "3 maart 2019", "VANE SYSTEMS", "Vereniging zonder winstoogmerk", "Actief")
        http = kbo([vzw], detail=detail_page(form="Vereniging zonder winstoogmerk"))
        [r] = run("Voorzitter van Vane Systems vzw, Gent, sinds 2004.", "Marcus Vane", http)
        self.assertEqual(r.outcome, rc.AMBIGUOUS)

    def test_a_different_legal_form_on_record_is_not_the_claimed_entity(self):
        http = kbo([VANE], detail=detail_page(form="Commanditaire vennootschap"))
        [r] = run(self.CLAIM, "Marcus Vane", http)
        self.assertEqual(r.outcome, rc.AMBIGUOUS)

    def test_a_converted_bvba_matches_a_bv_on_record(self):
        bv = ("0712.345.678", "3 maart 2019", "VANE SYSTEMS", "Besloten vennootschap", "Actief")
        http = kbo([bv], detail=detail_page(form="Besloten vennootschap"))
        [r] = run("Zaakvoerder van Vane Systems BVBA, Gent, sinds 2004.", "Marcus Vane", http)
        self.assertEqual(r.outcome, rc.CONTRADICTED)

    def test_one_year_of_slack(self):
        [r] = run("Marcus Vane, Bestuurder van Vane Systems NV, Gent, sinds 2018.", "Marcus Vane", kbo([VANE]))
        self.assertNotEqual(r.outcome, rc.CONTRADICTED)

    def test_the_subject_as_director_is_confirmed(self):
        [r] = run("Bestuurder van Vane Systems NV, Gent, sinds 2019.", "Marcus Vane", kbo([VANE]))
        self.assertEqual(r.outcome, rc.CONFIRMED)

    def test_the_subject_as_permanent_representative_is_confirmed(self):
        """Belgian directors often sit through a management company, with
        themselves registered as its permanent representative."""
        http = kbo([VANE], detail=detail_page(people=(("Vaste vertegenwoordiger", "Vane", "Marcus"),)))
        [r] = run("Bestuurder van Vane Systems NV, Gent, sinds 2019.", "Marcus Vane", http)
        self.assertEqual(r.outcome, rc.CONFIRMED)

    def test_someone_else_as_director_is_only_existence(self):
        http = kbo([VANE], detail=detail_page(people=(("Bestuurder", "Peeters", "Jan"),)))
        [r] = run("Bestuurder van Vane Systems NV, Gent, sinds 2019.", "Marcus Vane", http)
        self.assertEqual(r.outcome, rc.EXISTS)

    def test_no_entry_is_a_note(self):
        [r] = run(self.CLAIM, "Marcus Vane", kbo([]))
        self.assertEqual(r.outcome, rc.NO_RECORD)

    def test_several_entries_are_ambiguous(self):
        other = ("0798.765.432", "1 januari 2001", "VANE SYSTEMS", "Naamloze vennootschap", "Stopgezet")
        [r] = run(self.CLAIM, "Marcus Vane", kbo([VANE, other]))
        self.assertEqual(r.outcome, rc.AMBIGUOUS)

    def test_a_different_name_on_the_entry_is_not_used(self):
        http = kbo([VANE], detail=detail_page(name="VANE SYSTEMS INTERNATIONAL"))
        [r] = run(self.CLAIM, "Marcus Vane", http)
        self.assertEqual(r.outcome, rc.AMBIGUOUS)

    def test_an_unrecognised_page_is_uncheckable_not_empty(self):
        """If the markup changes, the answer is 'could not check', never 'no such company'."""
        def changed(url, payload=None, headers=None):
            return True, 200, "<html><body>Onderhoud</body></html>"
        [r] = run(self.CLAIM, "Marcus Vane", changed)
        self.assertEqual(r.outcome, rc.UNCHECKABLE)

    def test_unreachable_is_uncheckable(self):
        [r] = run(self.CLAIM, "Marcus Vane", kbo(fail=True))
        self.assertEqual(r.outcome, rc.UNCHECKABLE)

    def test_no_belgian_marker_and_not_on_record_cannot_accuse(self):
        http = kbo([VANE], detail=detail_page(people=(("Bestuurder", "Peeters", "Jan"),)))
        [r] = run("Marcus Vane, Bestuurder van Vane Systems NV sinds 2004.", "Marcus Vane", http)
        self.assertEqual(r.outcome, rc.AMBIGUOUS)

    def test_someone_elses_role_is_not_the_subjects(self):
        [r] = run("I worked with Hans Muster, Bestuurder van Vane Systems NV, Gent, sinds 2004.",
                  "Marcus Vane", kbo([VANE]))
        self.assertNotEqual(r.outcome, rc.CONTRADICTED)

    def test_the_sole_trader_search_runs_only_for_a_would_be_contradiction(self):
        http = kbo([VANE])
        run("Bestuurder van Vane Systems NV, Gent, sinds 2019.", "Marcus Vane", http)
        self.assertFalse(any("natuurlijkPersoon=natuurlijkPersoon" in u for u in http.calls))


class TestEndToEnd(unittest.TestCase):
    def test_a_vague_belgian_profile_is_caught_by_its_company_claim(self):
        from larp_meter.audit import run_audit
        text = ("Marcus Vane is Gedelegeerd bestuurder van Vane Systems NV, Gent, sinds 2004, pioneering "
                "revolutionary, groundbreaking, world class, disruptive edge AI. Seeking investment of 10 "
                "million. MoU signed, NDA in place. 40 years of experience.")
        with mock.patch.object(rc, "_http", kbo([VANE])):
            report = run_audit("t", text, verify=True, subject_name="Marcus Vane", cache_dir=tempfile.mkdtemp())
        flag11 = next(f for f in report["flags"] if f["id"] == 11)
        self.assertEqual(flag11["status"], TRIGGERED)


class TestInstitutionAliases(unittest.TestCase):
    """Profiles say 'UGent' or 'ULB'; OpenAlex says 'Ghent University'."""

    def test_local_names_tie_to_openalex_names(self):
        from larp_meter.reconcile import _tie, _norm
        for said, openalex_name in (("Professor aan de UGent", "Ghent University"),
                                    ("Chercheur à l'ULB", "Université Libre de Bruxelles"),
                                    ("Hoogleraar aan de Universiteit Antwerpen", "University of Antwerp"),
                                    ("Professeur à l'UCLouvain", "UCLouvain"),
                                    ("Professorin an der Universität Zürich", "University of Zurich"),
                                    ("Professeur à l'EPFL", "École Polytechnique Fédérale de Lausanne")):
            with self.subTest(said=said):
                rec = {"affiliations": [{"institution": {"display_name": openalex_name}}]}
                self.assertEqual(_tie(rec, f" {_norm(said)} ", set()), openalex_name)

    def test_an_ambiguous_local_name_is_not_an_alias(self):
        """'Universität Freiburg' is also Freiburg im Breisgau, in Germany."""
        from larp_meter.reconcile import _tie, _norm
        rec = {"affiliations": [{"institution": {"display_name": "University of Fribourg"}}]}
        self.assertIsNone(_tie(rec, f" {_norm('Professor an der Universität Freiburg')} ", set()))


if __name__ == "__main__":
    unittest.main()
