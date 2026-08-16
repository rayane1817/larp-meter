"""Fairness tests for names.name_matches.

Found by an adversarial fairness audit: name_matches only ever checked the
LAST significant token as a surname, and only ever folded diacritics that
Unicode NFKD decomposes. Both are silent Western-naming assumptions. A false
MISMATCH from either one floors the verdict at ORANGE for an honest person on
the sole basis of how their name is conventionally ordered or spelled -- see
verify.py's _attribute, which is the strongest and most damaging verdict this
tool can produce.
"""

import unittest

from larp_meter import names


class TestSurnameFirstOrder(unittest.TestCase):
    """Chinese, Korean, Vietnamese and Hungarian order puts the family name
    first. The old code only ever checked parts[-1], so an abbreviated
    given name ("W. Zhang" for "Zhang Wei") was reported as someone else's
    work purely because of naming-order convention, not any actual mismatch.
    """

    def test_chinese_family_name_first_still_matches_its_own_abbreviation(self):
        self.assertTrue(names.name_matches("Zhang Wei", ["W. Zhang"]))
        self.assertTrue(names.name_matches("Wang Xiaoming", ["X. Wang"]))

    def test_korean_family_name_first_still_matches_its_own_abbreviation(self):
        self.assertTrue(names.name_matches("Kim Ji-woo", ["J. Kim"]))

    def test_vietnamese_family_name_first_survives_a_particle_given_name(self):
        """'Van' inside 'Nguyen Van An' is a given-name particle, not the Dutch
        preposition, but it must not stop 'Nguyen' from matching."""
        self.assertTrue(names.name_matches("Nguyen Van An", ["V. A. Nguyen"]))

    def test_western_surname_last_still_matches_as_before(self):
        """The fix must not regress the ordinary, previously-passing case."""
        self.assertTrue(names.name_matches("Ada Lovelace", ["A. Lovelace"]))


class TestSharedGivenNameIsNotAMatch(unittest.TestCase):
    """Accepting either end of the name must not make every 'Jan' the same
    person -- that would recreate the exact false-attribution failure the
    surname-only rule already guarded against, just on the other end."""

    def test_shared_given_name_with_an_unrelated_full_surname_is_not_a_match(self):
        self.assertFalse(names.name_matches("Jan Vermeulen", ["Jan Peeters"]))
        self.assertFalse(names.name_matches("Maria Garcia", ["Maria Rodriguez"]))

    def test_shared_given_name_plus_a_real_abbreviation_of_the_rest_matches(self):
        """'Zhang Wei' cited alongside a co-author 'M. Chen' must not have the
        co-author's full name treated as evidence of a mismatch."""
        self.assertTrue(names.name_matches("Zhang Wei", ["W. Zhang", "M. Chen"]))


class TestMiddleTokenIsUnanswerable(unittest.TestCase):
    """A Hispanic/Lusophone name is often published under only its first
    surname ('Jose Ramirez' for 'Jose Ramirez Ortega'). A registry entry using
    just an initial for that surname shares one token with the subject, but
    that token sits in the MIDDLE of the subject's name -- neither a
    confident match nor a confident mismatch."""

    def test_single_middle_token_match_is_unanswerable_not_a_mismatch(self):
        self.assertIsNone(names.name_matches("Jose Ramirez Ortega", ["J. Ramirez"]))


class TestNonDecomposableLatinLetters(unittest.TestCase):
    """Unicode NFKD has no decomposition for these letters, so the old fold
    (decompose + drop combining marks) left them untouched: ø, ł, đ, ð, þ, æ,
    ı, ħ, ŋ. A Nordic, Polish, Icelandic or Maltese name typed in ASCII then
    failed to match its own accented registry record, and vice versa."""

    def test_norwegian_o_slash_folds_to_o(self):
        self.assertTrue(names.name_matches("Bjorn Odegard", ["Bjørn Ødegård"]))

    def test_icelandic_thorn_folds_to_th(self):
        self.assertTrue(names.name_matches("Halldor Thorsson", ["Halldór Þorsson"]))

    def test_still_rejects_a_genuinely_different_name_after_folding(self):
        self.assertFalse(names.name_matches("Bjorn Odegard", ["Erik Solberg"]))


class TestHyphenatedAndAttachedNames(unittest.TestCase):
    """A hyphen inside a name is ambiguous: 'Smith-Jones' is a double-barrel
    surname citable as either half, but 'Al-Sayed' is one attached name
    rendered inconsistently with or without the hyphen. Both readings must be
    available, and neither should come at the cost of the other."""

    def test_attached_name_matches_its_unhyphenated_spelling(self):
        self.assertTrue(names.name_matches("Ahmed Al-Sayed", ["Ahmed Alsayed"]))

    def test_attached_name_match_is_symmetric(self):
        """The reverse direction is the one the fix first got wrong: the
        collapsed reading has to apply to the CANDIDATE side too, or only
        one of the two spelling directions ever matches."""
        self.assertTrue(names.name_matches("Ahmed Alsayed", ["Ahmed Al-Sayed"]))

    def test_double_barrel_surname_still_matches_on_its_final_half(self):
        """The hyphen split must survive the union with the joined reading:
        'Jones' alone (the last token) is still a confident match."""
        self.assertTrue(names.name_matches("Ada Smith-Jones", ["A. Jones"]))


class TestScriptMismatchIsUnanswerable(unittest.TestCase):
    """normalize() folds diacritics; it does not transliterate. A record
    deposited in a non-Latin script shares zero characters with a Latin-script
    subject name regardless of whose work it is -- a limit of what this tool
    can read, not evidence the record belongs to someone else."""

    def test_cyrillic_record_against_a_latin_subject_name_is_unanswerable(self):
        self.assertIsNone(names.name_matches("Mikhail Ivanov", ["Михаил Иванов"]))

    def test_both_sides_in_the_same_non_latin_script_still_compare(self):
        self.assertTrue(names.name_matches("Михаил Иванов", ["Михаил Иванов"]))
