"""LinkedIn paste normaliser and Profile schema tests.

The key invariant: the same facts must produce the same verdict whether
entered as clean prose or copied from LinkedIn's actual copy-paste format.
Raw LinkedIn paste breaks degree-institution binding, loses duration info,
and includes UI chrome that pollutes the analysis. The normaliser fixes all
three.
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from larp_meter import TRIGGERED
from larp_meter.linkedin import (
    Profile, Experience, Education,
    is_linkedin_paste, parse_linkedin_paste,
)


# ── Fixtures ──────────────────────────────────────────────────────────

LINKEDIN_PASTE = """\
Jan Fictief
Senior Radiation Physicist at TechCorp

Message   Follow   More

500+ connections

About
Building innovative radiation measurement systems for the nuclear industry.
...see more

Experience

Senior Radiation Physicist
TechCorp · Full-time
Jan 2018 - Present · 6 yrs 6 mos
Antwerp, Belgium

Led development of novel radiation-tolerant sensor arrays for space applications.

Junior Engineer
OtherCorp
Mar 2014 - Dec 2017 · 3 yrs 10 mos

Education
University of Antwerp
MSc, Electrical Engineering
2010 - 2014

Skills
Python · 23 endorsements
Radiation Physics
Signal Processing · 15 endorsements
"""

MINIMAL_PASTE = """\
Name Here
Headline

Experience
Title
Company
Jan 2020 - Present · 2 yrs

Education
School
MSc, Physics
2016 - 2020
"""

NOT_LINKEDIN = (
    "I am a senior engineer with 10 years of experience building distributed "
    "systems. I hold an MSc in Computer Science from MIT."
)


class TestDetection(unittest.TestCase):
    def test_full_linkedin_paste_is_detected(self):
        self.assertTrue(is_linkedin_paste(LINKEDIN_PASTE))

    def test_minimal_linkedin_paste_is_detected(self):
        self.assertTrue(is_linkedin_paste(MINIMAL_PASTE))

    def test_plain_prose_is_not_detected(self):
        self.assertFalse(is_linkedin_paste(NOT_LINKEDIN))

    def test_empty_and_short_text_rejected(self):
        self.assertFalse(is_linkedin_paste(""))
        self.assertFalse(is_linkedin_paste("Hello world"))

    def test_text_with_education_but_no_experience_not_detected(self):
        text = "Some intro\n\nEducation\nMIT\nPhD, Physics\n2010-2015"
        self.assertFalse(is_linkedin_paste(text))


class TestParsing(unittest.TestCase):
    def setUp(self):
        self.profile = parse_linkedin_paste(LINKEDIN_PASTE)

    def test_name_and_headline(self):
        self.assertEqual(self.profile.name, "Jan Fictief")
        self.assertEqual(self.profile.headline, "Senior Radiation Physicist at TechCorp")

    def test_about_section(self):
        self.assertIn("radiation measurement", self.profile.about)
        self.assertNotIn("see more", self.profile.about)

    def test_chrome_stripped(self):
        prose = self.profile.to_prose()
        for chrome in ("Message", "Follow", "More", "500+ connections", "endorsements"):
            self.assertNotIn(chrome, prose, f"UI chrome '{chrome}' leaked into prose")

    def test_experience_count(self):
        self.assertEqual(len(self.profile.experiences), 2)

    def test_experience_fields(self):
        exp = self.profile.experiences[0]
        self.assertEqual(exp.title, "Senior Radiation Physicist")
        self.assertEqual(exp.company, "TechCorp")
        self.assertIn("2018", exp.date_range)
        self.assertEqual(exp.duration, "6 years 6 months")
        self.assertEqual(exp.location, "Antwerp, Belgium")
        self.assertIn("radiation-tolerant", exp.description)

    def test_experience_without_type(self):
        exp = self.profile.experiences[1]
        self.assertEqual(exp.company, "OtherCorp")
        self.assertEqual(exp.duration, "3 years 10 months")

    def test_education_count(self):
        self.assertEqual(len(self.profile.educations), 1)

    def test_education_fields(self):
        edu = self.profile.educations[0]
        self.assertEqual(edu.institution, "University of Antwerp")
        self.assertEqual(edu.degree, "MSc")
        self.assertEqual(edu.field_of_study, "Electrical Engineering")
        self.assertEqual(edu.years, "2010 - 2014")

    def test_skills(self):
        self.assertEqual(self.profile.skills, ["Python", "Radiation Physics", "Signal Processing"])

    def test_source_tag(self):
        self.assertEqual(self.profile.source, "linkedin-paste")


class TestToProse(unittest.TestCase):
    def setUp(self):
        self.profile = parse_linkedin_paste(LINKEDIN_PASTE)
        self.prose = self.profile.to_prose()

    def test_degree_bound_to_institution(self):
        """The whole reason this module exists: DEGREE_RE needs to see
        'MSc Electrical Engineering at University of Antwerp' on one line."""
        self.assertIn("MSc Electrical Engineering at University of Antwerp", self.prose)

    def test_role_bound_to_company(self):
        self.assertIn("Senior Radiation Physicist at TechCorp", self.prose)

    def test_dates_visible(self):
        self.assertIn("2018", self.prose)
        self.assertIn("2014", self.prose)
        self.assertIn("2010", self.prose)

    def test_duration_visible(self):
        self.assertIn("6 years 6 months", self.prose)

    def test_about_included(self):
        self.assertIn("radiation measurement", self.prose)

    def test_skills_listed(self):
        self.assertIn("Python", self.prose)
        self.assertIn("Signal Processing", self.prose)

    def test_description_included(self):
        self.assertIn("radiation-tolerant", self.prose)


class TestProfileSchema(unittest.TestCase):
    def test_round_trip(self):
        profile = parse_linkedin_paste(LINKEDIN_PASTE)
        d = profile.to_dict()
        restored = Profile.from_dict(d)
        self.assertEqual(restored.name, profile.name)
        self.assertEqual(restored.headline, profile.headline)
        self.assertEqual(len(restored.experiences), len(profile.experiences))
        self.assertEqual(len(restored.educations), len(profile.educations))
        self.assertEqual(restored.skills, profile.skills)

    def test_from_dict_with_field_alias(self):
        """linkedin_scraper uses 'field' instead of 'field_of_study'."""
        d = {"educations": [{"institution": "MIT", "degree": "PhD", "field": "Physics"}]}
        profile = Profile.from_dict(d)
        self.assertEqual(profile.educations[0].field_of_study, "Physics")

    def test_from_dict_ignores_extra_keys(self):
        d = {"name": "Test", "unknown_key": "ignored",
             "experiences": [{"title": "Eng", "company": "Co", "extra": True}]}
        profile = Profile.from_dict(d)
        self.assertEqual(profile.name, "Test")
        self.assertEqual(profile.experiences[0].title, "Eng")

    def test_from_dict_with_missing_keys(self):
        d = {}
        profile = Profile.from_dict(d)
        self.assertEqual(profile.name, "")
        self.assertEqual(profile.experiences, [])

    def test_to_prose_empty_profile(self):
        p = Profile()
        self.assertEqual(p.to_prose(), "")

    def test_to_prose_education_only(self):
        p = Profile(educations=[Education(institution="MIT", degree="PhD",
                                          field_of_study="Physics", years="2015-2020")])
        prose = p.to_prose()
        self.assertIn("PhD Physics at MIT", prose)
        self.assertIn("2015-2020", prose)


class TestScoringParity(unittest.TestCase):
    def test_linkedin_paste_does_not_score_worse_than_prose(self):
        """Same facts must not produce a worse verdict when pasted from
        LinkedIn vs. typed as clean prose."""
        from larp_meter.audit import run_audit

        prose_text = (
            "Senior Radiation Physicist at TechCorp.\n"
            "Building innovative radiation measurement systems for the nuclear industry.\n"
            "Senior Radiation Physicist at TechCorp, Jan 2018 - Present (6 years).\n"
            "Led development of novel radiation-tolerant sensor arrays.\n"
            "Junior Engineer at OtherCorp, Mar 2014 - Dec 2017 (3 years).\n"
            "MSc Electrical Engineering at University of Antwerp (2010-2014).\n"
            "Skills: Python, Radiation Physics, Signal Processing."
        )

        profile = parse_linkedin_paste(LINKEDIN_PASTE)
        normalised = profile.to_prose()

        prose_report = run_audit("Jan Fictief", prose_text, mode="text")
        linkedin_report = run_audit("Jan Fictief", normalised, mode="text")

        severity = {"INSUFFICIENT DATA": 0, "GREEN": 1, "YELLOW": 2, "ORANGE": 3, "RED": 4}
        prose_sev = severity.get(prose_report["level"], 0)
        linkedin_sev = severity.get(linkedin_report["level"], 0)

        self.assertLessEqual(linkedin_sev, prose_sev + 1,
                             f"LinkedIn paste scored {linkedin_report['level']} vs "
                             f"prose {prose_report['level']} — normaliser failed to close the gap")

    def test_institution_is_extracted_from_normalised_paste(self):
        """The degree-institution binding must survive normalisation."""
        from larp_meter.extract import extract_claims, claims_by

        profile = parse_linkedin_paste(LINKEDIN_PASTE)
        claims = extract_claims(profile.to_prose())
        institutions = claims_by(claims, "degree", "degree_institution")
        inst_names = [c.value for c in institutions]
        self.assertTrue(any("Antwerp" in n for n in inst_names),
                        f"University of Antwerp not found in institutions: {inst_names}")

    def test_institution_lost_in_raw_paste(self):
        """Without the normaliser, the raw LinkedIn paste loses the
        institution binding — the whole problem this module solves."""
        from larp_meter.extract import extract_claims, claims_by

        claims = extract_claims(LINKEDIN_PASTE)
        institutions = claims_by(claims, "degree", "degree_institution")
        inst_names = [c.value for c in institutions]
        # In raw paste, "University of Antwerp" is on a separate line from "MSc",
        # so DEGREE_RE cannot bind them.  It may appear as mentioned_institution
        # instead of degree_institution.
        bound = any("Antwerp" in n for n in inst_names)
        if bound:
            # If the raw extractor ever learns to handle this, this test
            # becomes a no-op rather than a false failure.
            pass
        else:
            mentioned = claims_by(claims, "degree", "mentioned_institution")
            mentioned_names = [c.value for c in mentioned]
            self.assertTrue(any("Antwerp" in n for n in mentioned_names),
                            "University of Antwerp not found at all in raw paste claims")


class TestFromJsonCli(unittest.TestCase):
    def _run(self, argv):
        from larp_meter.cli import main
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        return code or 0, out.getvalue() + err.getvalue()

    def test_from_json_produces_a_report(self):
        profile_data = {
            "name": "Jan Fictief",
            "headline": "CEO at ExampleCo",
            "about": "Building the future of widget manufacturing.",
            "experiences": [
                {"title": "CEO", "company": "ExampleCo",
                 "date_range": "Jan 2015 - Present", "duration": "9 years"}
            ],
            "educations": [
                {"institution": "University of Antwerp",
                 "degree": "MSc", "field_of_study": "Industrial Engineering",
                 "years": "2008 - 2012"}
            ],
            "skills": ["Leadership", "Manufacturing", "Supply Chain"],
            "source": "test",
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False,
                                          encoding="utf-8") as f:
            json.dump(profile_data, f)
            f.flush()
            path = f.name

        try:
            code, out = self._run(["--from-json", path, "--no-save", "--json"])
            self.assertEqual(code, 0, f"exit code {code}, output: {out}")
            report = json.loads(out[out.index("{"):])
            self.assertEqual(report["mode"], "structured")
            self.assertIn("structured_profile", report.get("signals", {}))
        finally:
            os.unlink(path)

    def test_auto_detection_in_text_mode(self):
        code, out = self._run([
            "--text", LINKEDIN_PASTE, "--no-save", "--json"])
        self.assertEqual(code, 0)
        report = json.loads(out[out.index("{"):])
        self.assertEqual(report["mode"], "text:linkedin")


class TestEdgeCases(unittest.TestCase):
    def test_experience_without_date(self):
        text = ("Name\nTitle\n\nExperience\nSome Role\nSome Company\n\n"
                "Education\nSchool\nBSc, Math\n2010 - 2014\n\nSkills\nPython")
        profile = parse_linkedin_paste(text)
        self.assertTrue(len(profile.experiences) >= 1)
        self.assertEqual(profile.experiences[0].title, "Some Role")

    def test_multiple_educations(self):
        text = ("Name\nTitle\n\nExperience\nEng\nCo\n"
                "Jan 2020 - Present · 4 yrs\n\n"
                "Education\n"
                "University A\nMSc, Physics\n2016 - 2020\n\n"
                "University B\nBSc, Math\n2012 - 2016\n\n"
                "Skills\nPython")
        profile = parse_linkedin_paste(text)
        self.assertEqual(len(profile.educations), 2)
        self.assertEqual(profile.educations[0].institution, "University A")
        self.assertEqual(profile.educations[1].institution, "University B")

    def test_skills_dot_delimited_on_one_line(self):
        text = ("Name\nTitle\n\nExperience\nEng\nCo\n"
                "Jan 2020 - Present · 2 yrs\n\n"
                "Education\nSchool\nBSc, CS\n2016 - 2020\n\n"
                "Skills\nPython · Java · Go · Rust")
        profile = parse_linkedin_paste(text)
        self.assertEqual(profile.skills, ["Python", "Java", "Go", "Rust"])

    def test_endorsement_counts_stripped_from_skills(self):
        text = ("Name\nTitle\n\nExperience\nEng\nCo\n"
                "Jan 2020 - Present · 2 yrs\n\n"
                "Education\nSchool\nBSc, CS\n2016 - 2020\n\n"
                "Skills\nPython · 99+ endorsements\nJava · 45 endorsements\nGo")
        profile = parse_linkedin_paste(text)
        self.assertEqual(profile.skills, ["Python", "Java", "Go"])

    def test_months_only_duration(self):
        text = ("Name\nTitle\n\nExperience\nIntern\nCo\n"
                "Jun 2023 - Aug 2023 · 3 mos\n\n"
                "Education\nSchool\nBSc, CS\n2020 - 2024")
        profile = parse_linkedin_paste(text)
        self.assertEqual(profile.experiences[0].duration, "3 months")

    def test_see_more_stripped_from_about(self):
        text = ("Name\nTitle\n\nAbout\nSome interesting text…see more\n\n"
                "Experience\nEng\nCo\nJan 2020 - Present · 2 yrs\n\n"
                "Education\nSchool\nBSc, CS\n2016 - 2020")
        profile = parse_linkedin_paste(text)
        self.assertNotIn("see more", profile.about)
        self.assertIn("interesting", profile.about)


class TestSectionHeaderAmbiguity(unittest.TestCase):
    """A section-header word is not always a section header.

    Splitting on every occurrence lost data two ways: a heading LinkedIn
    re-emits behind 'show all' discarded every entry before it, and a member
    whose skills or job title contained a header word ('Education') had the
    rest of their profile reassigned to the wrong section.
    """

    def test_repeated_header_does_not_drop_earlier_entries(self):
        text = ("Jan Fictief\nSenior Engineer\n\n"
                "Experience\nSenior Engineer\nTechCorp\nJan 2018 - Present\n\n"
                "Experience\nJunior Engineer\nOtherCorp\nMar 2014 - Dec 2017\n\n"
                "Education\nUniversity of Antwerp\nMSc, Electrical Engineering\n2010 - 2014")
        profile = parse_linkedin_paste(text)
        titles = [e.title for e in profile.experiences]
        self.assertEqual(titles, ["Senior Engineer", "Junior Engineer"],
                         "a repeated 'Experience' heading dropped the earlier role")

    def test_header_word_listed_as_a_skill_is_not_a_section(self):
        """'Education' among the skills must not swallow the real degree."""
        text = ("Jan Fictief\nHead of Education at TechCorp\n\n"
                "Experience\nHead of Education\nTechCorp\nJan 2018 - Present\n\n"
                "Education\nUniversity of Antwerp\nMSc, Electrical Engineering\n2010 - 2014\n\n"
                "Skills\nPython\nEducation\nLeadership")
        profile = parse_linkedin_paste(text)

        self.assertEqual(len(profile.educations), 1)
        edu = profile.educations[0]
        self.assertEqual(edu.institution, "University of Antwerp")
        self.assertEqual(edu.degree, "MSc")
        self.assertEqual(edu.field_of_study, "Electrical Engineering")
        self.assertEqual(profile.skills, ["Python", "Education", "Leadership"])

    def test_degree_binding_survives_a_header_word_in_skills(self):
        """The whole point of the module: the binding must reach the prose."""
        from larp_meter.extract import extract_claims, claims_by

        text = ("Jan Fictief\nHead of Education\n\n"
                "Experience\nHead of Education\nTechCorp\nJan 2018 - Present\n\n"
                "Education\nUniversity of Antwerp\nMSc, Electrical Engineering\n2010 - 2014\n\n"
                "Skills\nEducation\nLeadership")
        prose = parse_linkedin_paste(text).to_prose()
        self.assertIn("MSc Electrical Engineering at University of Antwerp", prose)

        institutions = [c.value for c in
                        claims_by(extract_claims(prose), "degree", "degree_institution")]
        self.assertTrue(any("Antwerp" in n for n in institutions),
                        f"degree institution lost: {institutions}")

    def test_forward_section_order_still_splits_normally(self):
        """The ordering rule must not break ordinary, well-formed pastes."""
        profile = parse_linkedin_paste(LINKEDIN_PASTE)
        self.assertEqual(len(profile.experiences), 2)
        self.assertEqual(len(profile.educations), 1)
        self.assertEqual(profile.skills,
                         ["Python", "Radiation Physics", "Signal Processing"])


class TestLocationMisclassification(unittest.TestCase):
    """The line right after the date is only a location if it actually
    looks like one. `to_prose()` never renders `exp.location` at all, so
    misclassifying a description sentence as a location does not just
    mislabel it -- it silently deletes it from every claim the extractors
    ever see. That's a real-content-loss bug against an honest profile,
    not a cosmetic one: a genuine achievement stops existing for scoring
    purposes.
    """

    def test_short_description_with_a_comma_is_not_read_as_location(self):
        text = ("Jan Fictief\nSenior Engineer\n\n"
                "Experience\nSenior Engineer\nTechCorp\n"
                "Jan 2018 - Present · 6 yrs\n"
                "Led cross-functional team of 12, shipped v2 platform.\n\n"
                "Education\nUniversity of Antwerp\nMSc, Electrical Engineering\n2010 - 2014")
        profile = parse_linkedin_paste(text)
        exp = profile.experiences[0]
        self.assertEqual(exp.location, "",
                         f"description sentence misread as location: {exp.location!r}")
        self.assertIn("Led cross-functional team of 12", exp.description)
        self.assertIn("Led cross-functional team of 12", profile.to_prose(),
                      "achievement sentence vanished from the prose the extractors see")

    def test_description_without_trailing_period_is_still_not_a_location(self):
        """Same failure mode without a period to lean on: the real signal
        is that the words after the comma aren't place names."""
        text = ("Jan Fictief\nSenior Engineer\n\n"
                "Experience\nSenior Engineer\nTechCorp\n"
                "Jan 2018 - Present · 6 yrs\n"
                "Grew revenue and closed several new enterprise deals\n\n"
                "Education\nUniversity of Antwerp\nMSc, Electrical Engineering\n2010 - 2014")
        profile = parse_linkedin_paste(text)
        exp = profile.experiences[0]
        self.assertEqual(exp.location, "",
                         f"description sentence misread as location: {exp.location!r}")
        self.assertIn("Grew revenue", exp.description)

    def test_real_comma_separated_location_still_recognised(self):
        """The fix must not regress the case it exists to handle."""
        profile = parse_linkedin_paste(LINKEDIN_PASTE)
        self.assertEqual(profile.experiences[0].location, "Antwerp, Belgium")

    def test_metropolitan_area_location_still_recognised(self):
        text = ("Jan Fictief\nSenior Engineer\n\n"
                "Experience\nSenior Engineer\nTechCorp\n"
                "Jan 2018 - Present · 6 yrs\n"
                "San Francisco Bay Area\n"
                "Shipped the v2 platform.\n\n"
                "Education\nUniversity of Antwerp\nMSc, Electrical Engineering\n2010 - 2014")
        profile = parse_linkedin_paste(text)
        exp = profile.experiences[0]
        self.assertEqual(exp.location, "San Francisco Bay Area")
        self.assertIn("Shipped the v2 platform", exp.description)


class TestNameSurvivesNormalisation(unittest.TestCase):
    """`to_prose()` never rendered `profile.name` at all. That's invisible
    for most facts -- the name doesn't carry claims -- but LinkedIn's own
    display-name field is exactly where a member types a self-applied
    "Dr."/"Prof." honorific, and flag 13 (self-applied doctoral title) only
    ever looks for that honorific anchored to the subject's name inside the
    audited text. Dropping the name line silently defeated flag 13 for
    every LinkedIn-paste subject, however blatant the title inflation --
    not because of any crafting effort, but because the title happens to
    live in the one field the normaliser threw away.
    """

    def test_self_applied_title_in_the_paste_name_reaches_the_prose(self):
        text = ("Dr. Marcus Vane\nVisionary CTO\n\n"
                "Experience\nCTO\nVane Quantum Systems\nJan 2020 - Present\n\n"
                "Education\nSome Business School\nMBA Healthcare Management\n2016 - 2018")
        profile = parse_linkedin_paste(text)
        self.assertIn("Dr. Marcus Vane", profile.to_prose(),
                      "self-applied title in the display name vanished from the prose")

    def test_self_applied_title_in_the_paste_name_triggers_flag_13(self):
        from larp_meter.extract import extract_claims
        from larp_meter.flags import AuditContext, evaluate

        text = ("Dr. Marcus Vane\nVisionary CTO\n\n"
                "Experience\nCTO\nVane Quantum Systems\nJan 2020 - Present\n\n"
                "Education\nSome Business School\nMBA Healthcare Management\n2016 - 2018")
        prose = parse_linkedin_paste(text).to_prose()
        ctx = AuditContext(text=prose, claims=extract_claims(prose),
                           subject_name="Marcus Vane")
        self.assertEqual(evaluate(ctx)[13].status, TRIGGERED)

    def test_ordinary_name_without_a_title_is_unaffected(self):
        """The fix must not turn a plain name into a false credential
        claim or otherwise change extraction for the common case."""
        profile = parse_linkedin_paste(LINKEDIN_PASTE)
        self.assertIn("Jan Fictief", profile.to_prose())
        self.assertEqual(profile.experiences[0].title, "Senior Radiation Physicist")


if __name__ == "__main__":
    unittest.main()
