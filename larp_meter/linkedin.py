"""LinkedIn paste normaliser and structured Profile schema.

When a user copies a LinkedIn profile and pastes it, the result is a
format-specific mess: repeated headings, UI chrome (Message, Follow, More),
endorsement counts, date-duration combos ("Jan 2018 - Present · 8 yrs 6 mos")
that existing extractors cannot parse.  Worst of all, degrees and institutions
land on separate lines, so DEGREE_RE cannot bind "MSc Electrical Engineering"
to "University of Antwerp" — the institution is lost, and a credential flag
that should pass fires instead.

This module detects LinkedIn paste, strips the noise, and emits a structured
Profile whose to_prose() output is designed so the existing claim extractors
in extract.py produce the same results as hand-written prose with the same
facts.

The Profile schema also serves as the --from-json contract: any source
(linkedin_scraper, LinkedIn data export, manual JSON) can populate it.
"""

import re
from dataclasses import dataclass, field, asdict


# ── Structured profile ────────────────────────────────────────────────

@dataclass
class Experience:
    title: str = ""
    company: str = ""
    date_range: str = ""
    duration: str = ""
    location: str = ""
    description: str = ""


@dataclass
class Education:
    institution: str = ""
    degree: str = ""
    field_of_study: str = ""
    years: str = ""
    description: str = ""


@dataclass
class Profile:
    name: str = ""
    headline: str = ""
    about: str = ""
    experiences: list = field(default_factory=list)
    educations: list = field(default_factory=list)
    skills: list = field(default_factory=list)
    location: str = ""
    source: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        """Build a Profile from a plain dict.  Lenient: extra keys are
        ignored, missing keys get defaults, ``field`` is accepted as an
        alias for ``field_of_study``."""
        exps = [_safe_experience(e) for e in d.get("experiences", []) if isinstance(e, dict)]
        edus = [_safe_education(e) for e in d.get("educations", []) if isinstance(e, dict)]
        return cls(
            name=str(d.get("name", "")),
            headline=str(d.get("headline", "")),
            about=str(d.get("about", "")),
            experiences=[e for e in exps if e],
            educations=[e for e in edus if e],
            skills=[str(s) for s in d.get("skills", [])],
            location=str(d.get("location", "")),
            source=str(d.get("source", "")),
        )

    def to_prose(self):
        """Render as clean text the existing claim extractors handle well.

        The output is designed so that DEGREE_RE matches
        "MSc Electrical Engineering at University of Antwerp", ROLE_RE
        matches "CEO at TechCorp", and YEAR_RE picks up career dates —
        all of which raw LinkedIn paste breaks because degrees,
        institutions and companies land on separate lines.
        """
        parts = []
        if self.name:
            # LinkedIn's display-name field is exactly where a member types a
            # self-applied "Dr."/"Prof." honorific. Leaving it out of the
            # prose meant flag 13's title-inflation check -- which only ever
            # looks for that honorific anchored to the subject's own name in
            # the audited text -- could never see it for a LinkedIn-paste
            # subject, however unsupported the title.
            parts.append(self.name + ".")
        if self.headline:
            parts.append(self.headline + ".")
        if self.about:
            parts.append(self.about)

        for exp in self.experiences:
            line = exp.title or ""
            if exp.company:
                line += f" at {exp.company}" if line else exp.company
            if exp.date_range:
                line += f", {exp.date_range}"
            if exp.duration:
                line += f" ({exp.duration})"
            line += "."
            if exp.description:
                line += f" {exp.description}"
            parts.append(line)

        for edu in self.educations:
            credential = ""
            if edu.degree and edu.field_of_study:
                credential = f"{edu.degree} {edu.field_of_study}"
            elif edu.degree:
                credential = edu.degree
            elif edu.field_of_study:
                credential = edu.field_of_study

            if edu.institution:
                if credential:
                    credential += f" at {edu.institution}"
                else:
                    credential = edu.institution

            if edu.years:
                credential += f" ({edu.years})"
            if credential:
                parts.append(credential + ".")
            if edu.description:
                parts.append(edu.description)

        if self.skills:
            parts.append("Skills: " + ", ".join(self.skills) + ".")

        return "\n".join(parts)


def _safe_experience(d):
    if not isinstance(d, dict):
        return None
    return Experience(
        title=str(d.get("title", "")),
        company=str(d.get("company", "")),
        date_range=str(d.get("date_range", "")),
        duration=str(d.get("duration", "")),
        location=str(d.get("location", "")),
        description=str(d.get("description", "")),
    )


def _safe_education(d):
    if not isinstance(d, dict):
        return None
    return Education(
        institution=str(d.get("institution", "")),
        degree=str(d.get("degree", "")),
        field_of_study=str(d.get("field_of_study", d.get("field", ""))),
        years=str(d.get("years", "")),
        description=str(d.get("description", "")),
    )


# ── LinkedIn paste detection ──────────────────────────────────────────

_SECTION_HEADERS = frozenset({
    "about", "experience", "education", "skills",
    "licenses & certifications", "certifications",
    "volunteer experience", "volunteer",
    "publications", "projects", "languages",
    "interests", "recommendations", "activity",
    "honors & awards", "courses", "organizations",
    "test scores", "patents",
})

# LinkedIn renders profile sections in a fixed order the member cannot
# reorder. That order is what tells a real section header apart from the same
# word appearing as ordinary content — "Education" listed among someone's
# skills, or a heading LinkedIn re-emits behind "show all". Treating every
# occurrence as a header lost data both ways: a repeated "Experience" dropped
# every job before it, and a profile whose skills included "Education" lost its
# actual degree and reported the next skill as the institution instead.
_SECTION_ORDER = {
    "_preamble": 0,
    "about": 1,
    "activity": 2,
    "experience": 3,
    "education": 4,
    "licenses & certifications": 5,
    "certifications": 5,
    "volunteer experience": 6,
    "volunteer": 6,
    "skills": 7,
    "recommendations": 8,
    "publications": 9,
    "patents": 9,
    "courses": 9,
    "projects": 9,
    "honors & awards": 9,
    "test scores": 9,
    "languages": 9,
    "organizations": 9,
    "interests": 10,
}

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
_DATE_DURATION_RE = re.compile(
    _MONTH + r"\s+\d{4}\s*[-–—]\s*"
    r"(?:" + _MONTH + r"\s+\d{4}|Present)"
    r"(?:\s*·\s*\d+\s*(?:yr|mo|year|month)s?"
    r"(?:\s+\d+\s*(?:yr|mo|year|month)s?)?)?",
    re.I,
)

_YEAR_RANGE_RE = re.compile(r"^\d{4}\s*[-–—]\s*(?:\d{4}|Present)$", re.I)

_CHROME_PATTERNS = [
    re.compile(r"^(?:Message|Follow|Connect|More)$", re.I),
    re.compile(r"^\d+\+?\s*connections?$", re.I),
    re.compile(r"^(?:1st|2nd|3rd)$"),
    re.compile(r"^See all\b", re.I),
    re.compile(r"^Show \d+ more\b", re.I),
    re.compile(r"^\d+\+?\s*endorsements?$", re.I),
    re.compile(r"^People also viewed$", re.I),
    re.compile(r"^Show credential", re.I),
    re.compile(r"^Open to\b", re.I),
    re.compile(r"^Report\s*/\s*Block$", re.I),
    re.compile(r"^(?:Like|Comment|Repost|Send|Agree)$", re.I),
    re.compile(r"^(?:Reactions?|Comments?|Reposts?)$", re.I),
    re.compile(r"^Mutual connections?$", re.I),
    re.compile(r"^\d+\s*(?:Like|Comment|Repost)s?$", re.I),
    re.compile(r"^(?:\.{2,}|…)see more$", re.I),
]

_EMPLOYMENT_TYPE_RE = re.compile(
    r"\s*·\s*(?:Full-time|Part-time|Self-employed|Freelance|Contract|"
    r"Internship|Apprenticeship|Seasonal|Temporary)\s*$", re.I)

_DURATION_RE = re.compile(
    r"(?:(\d+)\s*(?:yr|year)s?(?:\s+(\d+)\s*(?:mo|month)s?)?|(\d+)\s*(?:mo|month)s?)",
    re.I,
)

# Words that may appear lowercase inside an otherwise Title-Case place name
# ("United States of America", "Vale do Paraiba"), without disqualifying the
# line as a location.
_LOCATION_CONNECTORS = frozenset({
    "of", "and", "the", "de", "du", "la", "le", "van", "von", "der", "den",
})


def _looks_like_location(line):
    """Is *line* plausibly a LinkedIn location line, not a description?

    The line right after the date/duration is a location only sometimes —
    LinkedIn omits it as often as it includes it. Treating any short,
    comma-containing line as a location swallowed real achievement
    sentences ("Led a team of 12, shipped v2 platform.") into `location`,
    which `to_prose()` never renders — the sentence would silently vanish
    from everything the extractors and flags ever see. A location is a
    short run of Title-Case place-name words; a sentence has digits, a
    closing period, or lowercase verbs the comma test alone can't rule out.
    """
    if not line or len(line) >= 60:
        return False
    if line.endswith((".", "!", "?")):
        return False
    if any(ch.isdigit() for ch in line):
        return False
    lowered = line.lower()
    if any(w in lowered for w in ("remote", "hybrid", "area")):
        return True
    if "," not in line:
        return False
    for part in line.split(","):
        words = part.strip().split()
        if not words:
            return False
        for word in words:
            base = word.strip(".'-")
            if not base:
                continue
            if base.lower() in _LOCATION_CONNECTORS:
                continue
            if not base[0].isupper():
                return False
    return True


def _is_chrome(line):
    stripped = line.strip()
    return bool(stripped) and any(p.match(stripped) for p in _CHROME_PATTERNS)


def _format_duration(match):
    years = int(match.group(1)) if match.group(1) else 0
    months = int(match.group(2)) if match.group(2) else 0
    if not years and match.group(3):
        months = int(match.group(3))
    if years and months:
        return f"{years} years {months} months"
    if years:
        return f"{years} year{'s' if years != 1 else ''}"
    if months:
        return f"{months} month{'s' if months != 1 else ''}"
    return ""


def is_linkedin_paste(text):
    """Return True if *text* looks like a LinkedIn profile copy-paste.

    Conservative: false positives are worse than false negatives because
    the normaliser rewrites the text, while raw paste still works (just
    with weaker extraction).
    """
    if not text or len(text) < 50:
        return False

    stripped_lines = [l.strip().lower() for l in text.splitlines()]

    signals = 0
    has_experience = "experience" in stripped_lines
    has_education = "education" in stripped_lines
    has_skills = "skills" in stripped_lines
    has_about = "about" in stripped_lines

    if has_experience:
        signals += 2
    if has_education:
        signals += 2
    if has_skills:
        signals += 1
    if has_about:
        signals += 1
    if _DATE_DURATION_RE.search(text):
        signals += 2
    if _EMPLOYMENT_TYPE_RE.search(text):
        signals += 1
    if any(_YEAR_RANGE_RE.match(l.strip()) for l in text.splitlines()):
        signals += 1
    if sum(1 for l in text.splitlines() if _is_chrome(l)) >= 2:
        signals += 1

    return signals >= 4 and (has_experience or has_education)


# ── Paste parsing ─────────────────────────────────────────────────────

def _split_by_blank(lines):
    groups, current = [], []
    for line in lines:
        if not line.strip():
            if current:
                groups.append(current)
                current = []
        else:
            current.append(line)
    if current:
        groups.append(current)
    return groups


def _parse_experiences(lines):
    raw_groups = _split_by_blank(lines)

    # Tag each group: does it contain a date-duration line?
    tagged = []
    for group in raw_groups:
        clean = [l for l in group if not _is_chrome(l)]
        if not clean:
            continue
        has_date = any(_DATE_DURATION_RE.search(l.strip()) for l in clean)
        tagged.append((clean, has_date))

    # Merge a no-date group into the preceding dated group — in LinkedIn
    # paste, the description paragraph is blank-line-separated from the
    # date/location block but still belongs to the same entry.
    merged = []
    for clean, has_date in tagged:
        if not has_date and merged:
            prev_clean, prev_has_date = merged[-1]
            prev_clean.extend(clean)
            merged[-1] = (prev_clean, prev_has_date)
        else:
            merged.append((clean, has_date))

    experiences = []
    for clean, has_date in merged:
        exp = Experience()

        if has_date:
            date_idx = None
            for i, line in enumerate(clean):
                if _DATE_DURATION_RE.search(line.strip()):
                    date_idx = i
                    break

            pre = [l.strip() for l in clean[:date_idx] if l.strip()]
            if pre:
                exp.title = pre[0]
                if len(pre) > 1:
                    exp.company = _EMPLOYMENT_TYPE_RE.sub("", pre[1]).strip()

            date_line = clean[date_idx].strip()
            dm = _DATE_DURATION_RE.search(date_line)
            if dm:
                full = dm.group(0)
                if "·" in full:
                    date_part, _, dur_part = full.partition("·")
                    exp.date_range = date_part.strip()
                    dur_m = _DURATION_RE.search(dur_part)
                    if dur_m:
                        exp.duration = _format_duration(dur_m)
                else:
                    exp.date_range = full.strip()

            post = [l.strip() for l in clean[date_idx + 1:] if l.strip()]
            if post:
                first = post[0]
                if _looks_like_location(first):
                    exp.location = first
                    post = post[1:]
                exp.description = " ".join(post)
        else:
            non_empty = [l.strip() for l in clean if l.strip()]
            if non_empty:
                exp.title = non_empty[0]
                if len(non_empty) > 1:
                    exp.company = non_empty[1]

        if exp.title:
            experiences.append(exp)

    return experiences


_DEGREE_LEVEL_RE = re.compile(
    r"^(MSc|M\.Sc\.|BSc|B\.Sc\.|PhD|Ph\.D\.|MBA|MEng|BEng|LLM|LLB|"
    r"Master(?:'s)?(?:\s+of\s+\w+)?|Bachelor(?:'s)?(?:\s+of\s+\w+)?|"
    r"Master of Science|Master of Arts|Master of Business Administration|"
    r"Bachelor of Science|Bachelor of Arts|Bachelor of Engineering|"
    r"Doctor of Philosophy|Doctorate|Doctor)$", re.I)

_DEGREE_FIELD_RE = re.compile(
    r"^(MSc|M\.Sc\.|BSc|B\.Sc\.|PhD|Ph\.D\.|MBA|MEng|BEng|LLM|LLB|"
    r"Master(?:'s)?(?:\s+of\s+\w+)?|Bachelor(?:'s)?(?:\s+of\s+\w+)?|"
    r"Master of Science|Master of Arts|Master of Business Administration|"
    r"Bachelor of Science|Bachelor of Arts|Bachelor of Engineering|"
    r"Doctor of Philosophy|Doctorate|Doctor)"
    r"(?:\s*[,·]\s*|\s+in\s+|\s+of\s+)"
    r"(.+)$", re.I)


def _parse_educations(lines):
    groups = _split_by_blank(lines)
    educations = []

    for group in groups:
        group = [l for l in group if not _is_chrome(l)]
        if not group:
            continue

        edu = Education()
        non_empty = [l.strip() for l in group if l.strip()]
        if not non_empty:
            continue

        edu.institution = non_empty[0]

        for line in non_empty[1:]:
            if _YEAR_RANGE_RE.match(line):
                edu.years = line
                continue

            if not edu.degree:
                df = _DEGREE_FIELD_RE.match(line)
                if df:
                    edu.degree = df.group(1).strip()
                    edu.field_of_study = df.group(2).strip()
                    continue

                if _DEGREE_LEVEL_RE.match(line):
                    edu.degree = line.strip()
                    continue

            if not edu.field_of_study and len(line) < 60 and line[0:1].isupper():
                if line.lower().startswith("activities"):
                    edu.description = (edu.description + " " + line).strip() if edu.description else line
                else:
                    edu.field_of_study = line
            else:
                edu.description = (edu.description + " " + line).strip() if edu.description else line

        if edu.institution:
            educations.append(edu)

    return educations


def _parse_skills(lines):
    skills = []
    for line in lines:
        stripped = line.strip()
        if not stripped or _is_chrome(line):
            continue
        stripped = re.sub(r"\s*·?\s*\d+\+?\s*endorsements?\s*$", "", stripped, flags=re.I)
        if not stripped:
            continue
        if " · " in stripped:
            for s in stripped.split(" · "):
                s = re.sub(r"\s*\d+\+?\s*endorsements?\s*$", "", s.strip(), flags=re.I)
                if s:
                    skills.append(s)
        else:
            skills.append(stripped)
    return skills


def parse_linkedin_paste(text):
    """Parse a LinkedIn profile copy-paste into a structured Profile.

    Deliberately lenient: handles the common paste format, degrades
    gracefully on unusual layouts, and never raises.  The worst case is
    that some fields end up empty and the original text passes through
    to the extractors unstructured.
    """
    lines = text.splitlines()

    sections = {}
    current_section = "_preamble"
    current_rank = _SECTION_ORDER["_preamble"]
    current_lines = []

    def close(section, collected):
        """Append to a section rather than replace it.

        Overwriting meant the second occurrence of a header discarded
        everything gathered under the first one.
        """
        if not collected:
            return
        bucket = sections.setdefault(section, [])
        if bucket and bucket[-1].strip():
            bucket.append("")       # keep entries blank-line separated
        bucket.extend(collected)

    for line in lines:
        stripped = line.strip().lower()
        # An unknown header still opens a section (same rank), so adding to
        # _SECTION_HEADERS later cannot silently turn a heading into content.
        rank = _SECTION_ORDER.get(stripped, current_rank) if stripped in _SECTION_HEADERS else None
        # A header only opens a section when it moves forward through
        # LinkedIn's fixed layout. A backwards jump is the same word being
        # used as content — a job title, a skill — not a new section.
        if rank is not None and rank >= current_rank:
            close(current_section, current_lines)
            current_section, current_rank, current_lines = stripped, rank, []
        else:
            current_lines.append(line)
    close(current_section, current_lines)

    profile = Profile(source="linkedin-paste")

    preamble = [l.strip() for l in sections.get("_preamble", [])
                if l.strip() and not _is_chrome(l)]
    if preamble:
        profile.name = preamble[0]
    if len(preamble) > 1:
        profile.headline = preamble[1]
    for line in preamble[2:]:
        if not re.match(r"^\d+\+?\s*connections?$", line, re.I):
            if not profile.location and len(line) < 60:
                profile.location = line

    about_lines = sections.get("about", [])
    about_text = "\n".join(l for l in about_lines if l.strip() and not _is_chrome(l)).strip()
    profile.about = re.sub(r"\s*(?:\.{2,}|…)see more\s*$", "", about_text, flags=re.I).strip()

    profile.experiences = _parse_experiences(sections.get("experience", []))
    profile.educations = _parse_educations(sections.get("education", []))
    profile.skills = _parse_skills(sections.get("skills", []))

    return profile
