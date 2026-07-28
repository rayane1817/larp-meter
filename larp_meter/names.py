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


def normalize(text):
    """Casefold and strip diacritics so 'Müller' and 'Muller' compare equal."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


def tokens(name):
    """Significant name tokens: no particles, no honorifics, no bare initials."""
    return {t for t in re.split(r"[^\w]+", normalize(name))
            if len(t) > 1 and t not in PARTICLES}


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
    present = {t for t in mine if re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", blob)}

    # A single-token name (mononym) matches on that token alone.
    if len(mine) == 1:
        return bool(present)

    # Two or more matching tokens is a confident match.
    if len(present) >= 2:
        return True

    # One token is enough when it is the surname (conventionally last) and the
    # given name is likely abbreviated, e.g. "A. Lovelace" for "Ada Lovelace".
    if len(present) == 1:
        parts = [t for t in re.split(r"[^\w]+", normalize(subject))
                 if len(t) > 1 and t not in PARTICLES]
        if parts and parts[-1] in present:
            return True
    return False
