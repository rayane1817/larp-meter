"""Profile URLs as identity anchors.

A name is not an identifier. Auditing "John Smith" merges every John Smith the
search engine knows about — in one real test that meant two obituaries, a
people-search page and an unrelated researcher's publications scored as a
single individual. A profile URL names exactly one account, which is the only
cheap way to say *which* person is being assessed.

What each platform actually yields:

  linkedin  Best effort. The public preview exposes the account holder's name,
            headline and the opening of their About section through Open Graph
            tags, but LinkedIn answers many requests with HTTP 999 and serves a
            login wall for the rest. When it refuses, the URL still anchors the
            identity even though it yields no text.
  github    A real API. Account age, repository count, followers, bio.
  orcid     A real API. Registered name and biography.

Nothing here logs in, and nothing evades a block: a refusal is reported as a
refusal, never as an absence of substance.
"""

import json
import html as html_lib
import re
import urllib.parse
from dataclasses import dataclass, field

LINKEDIN, GITHUB, ORCID = "linkedin", "github", "orcid"

# Paths that are not one person: directories, search, company and school pages.
_LINKEDIN_NON_PROFILE = ("/pub/dir", "/company/", "/school/", "/search", "/groups/",
                         "/showcase/", "/jobs/", "/posts/", "/feed/")
_GITHUB_RESERVED = {"orgs", "settings", "features", "topics", "collections", "sponsors",
                    "marketplace", "explore", "notifications", "pulls", "issues", "about",
                    "pricing", "enterprise", "team", "login", "join", "search"}
_ORCID_RE = re.compile(r"\b(\d{4}-\d{4}-\d{4}-\d{3}[\dX])\b", re.I)


@dataclass
class ProfileRef:
    platform: str
    handle: str
    url: str

    @property
    def label(self):
        return f"{self.platform}:{self.handle}"


@dataclass
class ProfileData:
    ref: ProfileRef
    name: str = ""
    headline: str = ""
    text: str = ""
    facts: dict = field(default_factory=dict)
    reachable: bool = False
    note: str = ""


class UnsupportedProfileURL(ValueError):
    """The URL is not a single-person profile this tool can anchor to."""


def parse_profile_url(url):
    """Resolve a profile URL to the one account it identifies.

    Raises UnsupportedProfileURL for anything that is not a single person —
    a LinkedIn directory page is precisely the thing that proves a name is
    shared, so accepting it would reintroduce the bug this module exists for.
    """
    raw = (url or "").strip()
    if not raw:
        raise UnsupportedProfileURL("No URL given.")
    if "://" not in raw:
        raw = "https://" + raw

    parts = urllib.parse.urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise UnsupportedProfileURL(f"Only http(s) URLs are supported, got {parts.scheme!r}.")
    host = (parts.hostname or "").casefold()
    host = host[4:] if host.startswith("www.") else host
    path = parts.path.rstrip("/")

    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        lowered = path.casefold()
        if any(bad in lowered for bad in _LINKEDIN_NON_PROFILE):
            raise UnsupportedProfileURL(
                "That is a LinkedIn directory, company or search page, not one person's "
                "profile. A directory page exists because several people share the name — "
                "pick the specific profile you mean.")
        m = re.match(r"^/in/([^/]+)$", path, re.I)
        if not m:
            raise UnsupportedProfileURL("Expected a LinkedIn profile of the form /in/<name>.")
        handle = urllib.parse.unquote(m.group(1))
        # Preserve the country subdomain: it is part of the canonical address.
        return ProfileRef(LINKEDIN, handle, f"https://{parts.netloc}/in/{m.group(1)}")

    if host == "github.com":
        m = re.match(r"^/([^/]+)$", path)
        if not m or m.group(1).casefold() in _GITHUB_RESERVED:
            raise UnsupportedProfileURL("Expected a GitHub user profile of the form /<username>.")
        return ProfileRef(GITHUB, m.group(1), f"https://github.com/{m.group(1)}")

    if host in ("orcid.org", "sandbox.orcid.org"):
        m = _ORCID_RE.search(path)
        if not m:
            raise UnsupportedProfileURL("Expected an ORCID iD of the form 0000-0000-0000-0000.")
        return ProfileRef(ORCID, m.group(1).upper(), f"https://orcid.org/{m.group(1).upper()}")

    raise UnsupportedProfileURL(
        f"No profile reader for {host or url!r}. Supported: linkedin.com/in/<name>, "
        f"github.com/<user>, orcid.org/<id>. For anything else, paste the profile "
        f"text with --text.")


def name_from_handle(handle):
    """Fallback display name from a URL slug, e.g. 'jan-fictief-1a2b' -> 'Jan Fictief'.

    Trailing hash segments that LinkedIn appends for uniqueness are dropped;
    they are not part of anybody's name.
    """
    parts = [p for p in re.split(r"[-_.]+", handle or "") if p]
    while parts and (parts[-1].isdigit() or (len(parts[-1]) <= 12 and re.fullmatch(r"[0-9a-f]+", parts[-1].casefold())
                                             and any(c.isdigit() for c in parts[-1]))):
        parts.pop()
    return " ".join(p.capitalize() for p in parts)


def _meta(body, prop):
    m = re.search(r"<meta[^>]+(?:property|name)=[\"']" + re.escape(prop)
                  + r"[\"'][^>]*content=[\"'](.*?)[\"']", body, re.S | re.I)
    if not m:
        m = re.search(r"<meta[^>]+content=[\"'](.*?)[\"'][^>]*(?:property|name)=[\"']"
                      + re.escape(prop) + r"[\"']", body, re.S | re.I)
    return html_lib.unescape(m.group(1)).strip() if m else ""


def _read_linkedin(ref, fetch):
    data = ProfileData(ref=ref, name=name_from_handle(ref.handle))
    body = fetch(ref.url, browser=True)
    if not body:
        data.note = ("LinkedIn did not serve this profile to an automated request (it answers "
                     "with HTTP 999 or a login wall). The URL still identifies whose profile "
                     "this is; paste the profile text with --text to have something to assess.")
        return data

    first, last = _meta(body, "profile:first_name"), _meta(body, "profile:last_name")
    if first or last:
        data.name = f"{first} {last}".strip()
    title = _meta(body, "og:title")
    description = _meta(body, "og:description")

    # "Name - Headline | LinkedIn"
    if title:
        stripped = re.sub(r"\s*\|\s*LinkedIn\s*$", "", title)
        if " - " in stripped:
            maybe_name, _, headline = stripped.partition(" - ")
            data.headline = headline.strip()
            if not data.name:
                data.name = maybe_name.strip()
        elif not data.name:
            data.name = stripped.strip()

    if not data.name and not description:
        data.note = ("The page loaded but exposed no profile fields — LinkedIn most likely "
                     "served a login wall. Paste the profile text with --text.")
        return data

    data.text = " ".join(x for x in (data.headline, description) if x)
    data.reachable = True
    data.note = ("Read from LinkedIn's public preview: headline and the opening of the About "
                 "section only. That is a fraction of the profile — paste the full text with "
                 "--text for a fuller assessment.")
    return data


def _read_github(ref, fetch):
    data = ProfileData(ref=ref, name=ref.handle)
    body = fetch(f"https://api.github.com/users/{urllib.parse.quote(ref.handle)}")
    if not body:
        data.note = "GitHub API unreachable or rate-limited."
        return data
    try:
        payload = json.loads(body)
    except Exception:
        data.note = "GitHub returned an unparseable record."
        return data
    if not payload.get("login"):
        data.note = f"No GitHub user named {ref.handle!r}."
        return data

    data.name = payload.get("name") or ref.handle
    data.headline = payload.get("bio") or ""
    data.facts = {
        "public_repos": payload.get("public_repos", 0),
        "followers": payload.get("followers", 0),
        "account_created": (payload.get("created_at") or "")[:10],
        "company": payload.get("company") or "",
        "blog": payload.get("blog") or "",
    }
    data.text = " ".join(x for x in (data.headline, payload.get("company") or "") if x)
    data.reachable = True
    data.note = (f"GitHub account created {data.facts['account_created']}, "
                 f"{data.facts['public_repos']} public repositories, "
                 f"{data.facts['followers']} followers.")
    return data


def _read_orcid(ref, fetch):
    data = ProfileData(ref=ref, name="")
    body = fetch(f"https://pub.orcid.org/v3.0/{ref.handle}/person")
    if not body:
        data.note = "ORCID unreachable."
        return data
    try:
        person = json.loads(body)
    except Exception:
        data.note = "ORCID returned an unparseable record."
        return data

    name = person.get("name") or {}
    given = ((name.get("given-names") or {}) or {}).get("value", "")
    family = ((name.get("family-name") or {}) or {}).get("value", "")
    data.name = f"{given} {family}".strip()
    biography = ((person.get("biography") or {}) or {}).get("content", "") or ""
    data.text = biography
    data.reachable = True
    data.note = ("ORCID record found."
                 if data.name else "ORCID record found, but the holder has made their name private.")
    return data


_READERS = {LINKEDIN: _read_linkedin, GITHUB: _read_github, ORCID: _read_orcid}


def read_profile(ref, fetch):
    """Fetch what the platform will give us. Never raises; a refusal is a note."""
    try:
        return _READERS[ref.platform](ref, fetch)
    except Exception as exc:
        return ProfileData(ref=ref, name=name_from_handle(ref.handle),
                           note=f"profile reader error: {type(exc).__name__}")
