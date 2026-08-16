"""Personal-name comparison.

Deciding whether a record belongs to the subject is the single most damaging
judgement this tool makes — a false MISMATCH reads as "they lied about their
publications". The rules here are deliberately permissive: they must tolerate
initials, diacritics, transliteration and particles, and only report a mismatch
when no meaningful part of the name is present at all.
"""

import re
import unicodedata

# Name particles and honorifics carry no identifying information.
PARTICLES = {
    "de", "del", "della", "der", "den", "van", "von", "vander", "vande", "da",
    "di", "du", "la", "le", "el", "al", "bin", "ibn", "ter", "ten", "op", "st",
    "dr", "prof", "mr", "ms", "mrs", "phd", "msc", "bsc", "md", "jr", "sr", "ii", "iii",
}

# Letters Unicode does NOT decompose under NFKD, so the combining-mark strip in
# normalize() leaves them untouched. A Nordic, Polish, Icelandic, Turkish or
# Maltese name then fails to fold to the ASCII form a registry, publisher or
# hand-typed --name often carries, and the reverse: an ORCID/Crossref record
# holding the accented original shares zero tokens with an ASCII subject name.
# Keys are already casefolded, since this runs after .casefold() below.
_EXTRA_FOLDS = (
    ("ø", "o"), ("ł", "l"), ("đ", "d"), ("ð", "d"), ("þ", "th"),
    ("æ", "ae"), ("ı", "i"), ("ħ", "h"), ("ŋ", "n"),
)

# A hyphen or apostrophe INSIDE a word is attachment, not separation, in many
# traditions ("Al-Sayed"/"Alsayed", "O'Brien"/"OBrien") -- collapsing it lets
# both spellings of the same name compare equal.
_INNER_HYPHEN_RE = re.compile(r"(?<=\w)[-'](?=\w)")


def normalize(text):
    """Casefold and strip diacritics so 'Müller' and 'Muller' compare equal."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    folded = stripped.casefold()
    for src, dst in _EXTRA_FOLDS:
        folded = folded.replace(src, dst)
    return folded


def tokens(name):
    """Significant name tokens: no particles, no honorifics, no bare initials.

    Returns the union of two readings of any hyphenated/apostrophed word: the
    hyphen-as-separator reading (a double-barrel or married surname like
    "Smith-Jones" is two names, each independently citable) and the
    hyphen-as-attachment reading (a name like "Al-Sayed" is one name that
    sources render inconsistently as "Al-Sayed" or "Alsayed"). Since this only
    ever ADDS tokens to the set, it can make a match more forgiving but can
    never manufacture a false mismatch.
    """
    normalized = normalize(name)
    split = {t for t in re.split(r"[^\w]+", normalized) if len(t) > 1 and t not in PARTICLES}
    joined = {t for t in re.split(r"[^\w]+", _INNER_HYPHEN_RE.sub("", normalized))
              if len(t) > 1 and t not in PARTICLES}
    return split | joined


def initials(name):
    return {t[0] for t in re.split(r"[^\w]+", normalize(name)) if t}


def name_matches(subject, candidates):
    """Does `subject` appear among `candidates`?

    Returns True / False, or None when the question is not answerable — either
    no subject name was supplied, or the registry gave no names to compare
    against. The caller must never treat None as a mismatch: "we could not
    check" and "this is someone else's work" are different claims, and only
    one of them is an accusation.
    """
    mine = tokens(subject)
    if not mine:
        return None

    usable = [c for c in candidates or [] if c and c.strip()]
    if not usable:
        return None

    blob = normalize(" ".join(usable))

    # normalize() folds diacritics and the handful of non-decomposable Latin
    # letters, but it does not transliterate. A record deposited in Cyrillic,
    # CJK, Arabic, Hebrew or Devanagari script shares zero characters with a
    # Latin-script subject name no matter whose work it actually is -- that is
    # a gap in what this tool can read, not evidence the record belongs to
    # someone else.
    mine_is_latin = any(re.search(r"[a-z]", t) for t in mine)
    blob_is_latin = bool(re.search(r"[a-z]", blob))
    if mine_is_latin != blob_is_latin:
        return None

    # The hyphen-collapsed reading has to apply to the candidate side too, not
    # just to `mine` via tokens(): otherwise "Al-Sayed" (subject) still finds
    # "Alsayed" (candidate) -- present is searched FOR mine's tokens, and
    # "alsayed" is one of them -- but the reverse pairing does not, because
    # the un-collapsed candidate blob never contains "alsayed" as a literal
    # word. A fold that only works in one direction is exactly the kind of
    # asymmetry that turns an honest match into a false MISMATCH.
    blob_variants = (blob, _INNER_HYPHEN_RE.sub("", blob))
    present = {t for t in mine
               if any(re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", v) for v in blob_variants)}

    # A single-token name (mononym) matches on that token alone.
    if len(mine) == 1:
        return bool(present)

    # Two or more matching tokens is a confident match.
    if len(present) >= 2:
        return True

    # One token is enough when it is the surname and the given name is likely
    # abbreviated, e.g. "A. Lovelace" for "Ada Lovelace" -- but which end of
    # the name the surname sits on is a matter of convention, not universal
    # fact. It is last in Western order but first in Chinese, Korean,
    # Vietnamese and Hungarian order ("Zhang Wei" abbreviated as "W. Zhang"),
    # so both ends are accepted.
    if len(present) == 1:
        matched = next(iter(present))
        parts = [t for t in re.split(r"[^\w]+", normalize(subject))
                 if len(t) > 1 and t not in PARTICLES]
        at_an_end = bool(parts) and (parts[0] == matched or parts[-1] == matched)
        if not at_an_end:
            # A single token matching somewhere in the MIDDLE of a longer
            # name -- a middle name, or the second half of a Hispanic/
            # Lusophone double surname a person publishes under only the
            # first half of -- is too weak a signal to call either way.
            # Reporting it as a mismatch would accuse a stranger of
            # borrowing this person's name over one shared word.
            return None

        # The shared token sits at an end, but a shared given name ("Jan" in
        # both "Jan Vermeulen" and "Jan Peeters") sits at an end too, and
        # those are different people. Only accept the match when the SAME
        # candidate string's other words are consistent with an abbreviation
        # of the rest of the subject's name -- bare initials, particles, or
        # the subject's own tokens -- rather than a full, unrelated word.
        for cand in usable:
            cand_norm = normalize(cand)
            words = set()
            for v in (cand_norm, _INNER_HYPHEN_RE.sub("", cand_norm)):
                words |= {w for w in re.split(r"[^\w]+", v) if w}
            if matched not in words:
                continue
            extra = [w for w in words if w != matched and len(w) > 1 and w not in PARTICLES]
            if not extra or all(w in mine for w in extra):
                return True
        return False
    return False
