# LARP Meter v3 — Claim-vs-Evidence Auditor

**Audit professional self-presentation against verifiable substance, and check the checkable claims against public registries.**

A due-diligence *triage* instrument. It surfaces leads worth investigating by hand. It does not render verdicts about people, and it is built to say **"I don't know"** rather than guess.

```bash
python larp-meter.py --url https://linkedin.com/in/jane-doe --text "<paste the profile>"
python larp-meter.py --url https://github.com/janedoe --verify
python larp-meter.py --text "President @ DeepTech. MoU signed. Seeking 8-12M. MSc Public Health."
```

---

## What makes v3 different

v1 counted keywords. v2 fixed the counting. v3 stops trusting the text at all where a public registry can answer instead.

### 1. Claims are verified, not just pattern-matched

Identifiers found in a profile are checked against the registry that owns them:

| Claim | Registry | Answers |
|---|---|---|
| DOI | Crossref | Does the paper exist? Is the subject an author? |
| ORCID | orcid.org | Does the record exist, and whose is it? |
| arXiv ID | arXiv API | Real preprint? Listed authors? |
| GitHub repo | GitHub API | Exists? Stars, last push, **empty repo?** |
| NCT number | ClinicalTrials.gov | Registered trial? Current status? |
| Patent number | Google Patents | Real grant? Listed inventors? |
| Institution | ROR | Is this a real organization? |

**Existence is not attribution.** With `--name`, an artifact that exists but does not list the subject returns `MISMATCH` — a far stronger signal than a missing one, and the single most useful thing this tool produces:

```
Claim ledger  (registry lookups)
  ✗ doi     10.1038/nature14539    MISMATCH
    Paper "Deep learning" exists but does NOT list the subject (Yann LeCun, Yoshua Bengio, …)
  ✗ github  acme/nonexistent-repo  NOT_FOUND
    GitHub repository 'acme/nonexistent-repo' does not exist.
```

### 2. It works on every profession, not just tech

Flags 1 and 2 used to be hardcoded to one archetype: a non-technical person claiming deep tech. A finance, medical or legal fabricator sailed through, and honest non-technical professionals were unscoreable.

v3 uses a **domain taxonomy** (technology, science, medicine, finance, law, policy, business, marketing, design, education). Each domain carries claim markers, credential markers and role markers, plus a **directional** transfer map so a physicist leading an AI venture is not treated as a fraud.

Transfer is deliberately one-way. A doctor moving into health policy is ordinary; a public-policy graduate claiming to deliver clinical treatment is not. An earlier symmetric version let exactly that through — naming a policy degree instead of an MBA was enough for a fabricated Chief Medical Officer profile to pass.

Two fairness rules are built in:

- **Credentials only count inside an education context.** Otherwise the sentence "we run a quantitative **finance** fund" reads as a finance qualification and clears the very flag it should trip.
- **Only credential-gated domains can trigger a mismatch** (technology, science, medicine, finance, law). Marketing, design, business and policy are open-entry, so a "missing degree" there is not evidence of anything — flagging it would just punish self-taught people and career changers.

### 3. Absence of evidence is never an accusation

The failure mode that matters in a due-diligence tool is not missing a fraud — it is libelling an honest person. v3 was put through an adversarial review specifically hunting for that, and the fixes are load-bearing:

- **Existence is not attribution, and silence is neither.** A registry that returns no usable names — a book with no author array, an ORCID record set to private, arXiv's 200-OK error feed, scraped patent markup that drifted — returns `UNCHECKABLE`. Only a registry that *does* list names and does not list the subject returns `MISMATCH`.
- **Attribution requires `--name`.** Without it the tool reports that an artifact exists and says so, rather than comparing against a placeholder.
- **A blocked network is not an empty world.** Search failures are never cached as emptiness, and flag 10 returns `UNKNOWN` when the search layer could not reach its sources.
- **Failure to parse is not concealment.** An institution name the extractor cannot read (common outside English) makes the credential flag `UNKNOWN`, not triggered.
- **Registry absence is a lead, not a verdict.** ROR indexes research organizations, so the report says "confirm directly" rather than asserting an institution is fake.
- **Namesakes are not merged.** Web results that are not clearly about the subject are excluded from scoring and reported as set aside, and the tool warns when several people share the name.
- **Reporting on a field is not claiming to work in it.** A technology journalist or a recruiter placing engineers is not treated as claiming technical expertise.

### 4. Absence of evidence is never innocence

Every flag returns `TRIGGERED`, `PASSED`, or **`UNKNOWN`**. Unknown flags are excluded from the score entirely and lower *evidence coverage* instead. Below 35% coverage the tool refuses to grade and returns `INSUFFICIENT DATA`.

```
LARP score = 100 × (weight of TRIGGERED flags) / (weight of DECIDED flags)
coverage   = (weight of decided flags) / (total weight, 17.0)
```

| Verdict | Condition |
|---|---|
| ⚪ INSUFFICIENT DATA | coverage < 35% — refuses to score |
| 🟢 GREEN | score < 20 |
| 🟡 YELLOW | 20–39 |
| 🟠 ORANGE | 40–64 |
| 🔴 RED | ≥ 65 |

Results are also broken down **by dimension** — credentials, track record, relationships, rhetoric, validation — because one number hides where the problem actually is.

### 5. Web mode no longer depends on scraping

Search engines now answer automated requests with anti-bot pages. Instead of one scraper, v3 runs a **provider chain** of authoritative key-free APIs, and treats HTML search as an optional bonus:

- **Wikipedia** — independent encyclopedic coverage (real third-party validation, not a self-published bio)
- **OpenAlex** — publication and citation record, with author-name matching so a prolific stranger isn't credited to your subject
- **Crossref** — publications by author
- **DuckDuckGo** — best-effort, frequently blocked, never required

A provider that fails contributes nothing and is reported as unavailable. **A network failure is never treated as evidence against the subject.**

---

## The 12 flags

| # | Flag | W | Dimension | Detects |
|---|---|---|---|---|
| 1 | Education ≠ Claimed Domain | 1.5 | credentials | Credentials in an unrelated field to the one claimed |
| 2 | Experience ≠ Declared Title | 1.5 | credentials | Senior title with no role history in that domain |
| 3 | Self-Referential Partners | 2.0 | relationships | Own organizations presented as independent "partners" |
| 4 | Buzzword Density | 1.0 | rhetoric | Hype per 100 words, with a distinct-term threshold |
| 5 | Vague Partnerships Only | 1.0 | relationships | MoUs and NDAs instead of contracts, grants, revenue |
| 6 | No Verifiable Output | 1.5 | track record | "Building" with no checkable artifact anywhere |
| 7 | Fundraising Without Traction | 1.5 | track record | Raising money with zero customers or revenue |
| 8 | Unverifiable Credentials | 1.0 | credentials | Degree with no institution, or one absent from ROR |
| 9 | Logo Wall Syndrome | 1.0 | relationships | Many partner names, no substantive joint work |
| 10 | No Independent Validation | 1.0 | validation | Only self-controlled platforms; pure echo chamber |
| 11 | **Contradicted Verifiable Claim** | 2.5 | track record | A registry actively refutes a specific claim — **floors the verdict at ORANGE** |
| 12 | **Timeline Implausibility** | 1.5 | credentials | Claimed durations that don't fit the stated dates |

Flag 11 carries the heaviest weight, and a *floor*: when a registry contradicts a claim the verdict cannot come out better than ORANGE, however well the rest of the profile reads. Without that, a fabricated bio absorbed one contradiction under a pile of unverified assertions and still scored GREEN. It is the only flag backed by an external authority rather than by reading tea leaves. Institution misses are deliberately *excluded* from it and handled by flag 8 at lower weight, since ROR indexes research organizations and a small or non-research school can be legitimately absent.

---

## Install & usage

Python 3.8+, **zero dependencies**, stdlib only. Runs on Windows and POSIX.

```bash
git clone https://github.com/rayane1817/larp-meter.git
cd larp-meter
python larp-meter.py --selftest     # 303 tests
python larp-meter.py --explain      # full methodology
```

```bash
# Text (most reliable)
python larp-meter.py --text "<paste a bio>"
python larp-meter.py --file bio.txt

# Web footprint via the provider chain, with registry verification
python larp-meter.py "Jane Doe" --verify --name "Jane Doe"

# Read the top result pages too; --refresh bypasses the cache
python larp-meter.py "Jane Doe" --deep --refresh

# Machine-readable / reports
python larp-meter.py --text "..." --json --no-save
python larp-meter.py --file bio.txt --html report.html --md report.md

# Many subjects at once (.jsonl of {name,text} or name<TAB>text lines)
python larp-meter.py --batch subjects.jsonl --csv summary.csv

# Guided 12-question assessment, and past audits
python larp-meter.py --interactive
python larp-meter.py --list
```

### Customising the keyword banks

Drop a `keywords.json` next to the tool (or point `$LARP_KEYWORDS` at one). A key replaces a bank; prefix it with `+` to extend one:

```json
{
  "buzzwords": ["synergy", "paradigm shift", "web3-native"],
  "+tech_claims": ["fusion", "neuromorphic"]
}
```

### Environment

| Variable | Purpose |
|---|---|
| `OBSIDIAN_VAULT_PATH` | Write a Markdown note to `<vault>/research/` |
| `LARP_OUTPUT` / `LARP_CACHE` | Relocate reports and cache |
| `LARP_KEYWORDS` | Path to a keyword-bank override |
| `GITHUB_TOKEN` | Raises the GitHub API rate limit during `--verify` |

---

## Output

| Artifact | Location |
|---|---|
| JSON report | `output/YYYYMMDD_HHMMSS_<slug>.json` |
| HTML report | `--html <path>` — self-contained, light/dark aware |
| Markdown | `--md <path>`, plus the Obsidian vault if configured |
| Batch CSV | `--csv <path>` |
| Caches | `cache/` (search, 7 days) and `cache/verify/` (registries, 30 days) |

---

## Audit a profile, not a name

**A name is not an identifier.** Auditing a bare name searches for it, and a search cannot tell two people apart. Run on one real name, the tool pulled together two obituaries, a people-search page, a LinkedIn disambiguation directory, a social account and an unrelated researcher's publications — and scored all of it as a single individual.

`--url` anchors the report to one account:

```bash
python larp-meter.py --url https://be.linkedin.com/in/jane-doe --text "<paste the profile>"
python larp-meter.py --url https://github.com/janedoe --verify
python larp-meter.py --url https://orcid.org/0000-0002-1825-0097
```

| Platform | What it yields |
|---|---|
| `linkedin.com/in/<name>` | Best effort. The public preview exposes the account holder's name, headline and the opening of the About section, but LinkedIn answers many requests with HTTP 999 or a login wall. When it refuses, the URL still fixes *whose* profile this is — paste the text with `--text`. |
| `github.com/<user>` | A real API: account age, repositories, followers, bio. |
| `orcid.org/<id>` | A real API: registered name and biography. |

Directory, company, school and search URLs are **refused**, with an explanation. A LinkedIn `/pub/dir/` page is the very thing that proves a name is shared, so accepting it would reintroduce the bug this mode exists to fix.

The anchor is honest about its limits: it identifies the profile, but any corroborating sources (Wikipedia, OpenAlex, Crossref) are still located **by name**, so those may belong to someone else. The report says so.

## Who this tool cannot assess

Measured, not guessed. A matched-pair audit of the scoring produced these:

- **A well-written fabrication passes text mode.** An entirely invented profile — fake company, fake patent number, nonexistent repository, invented press mention — scored **GREEN 0/100 at 68% coverage**. Nothing in text mode establishes that a claim is *true*, only that the profile is specific and internally consistent. `--verify` is what closes this: it caught the same profile's nonexistent repository and a patent number belonging to somebody else's soybean cultivar. **Treat an unverified GREEN as "no internal contradictions found", never as corroboration** — the report now says so itself.
- **Trades and non-academic professions are out of scope.** A master plumber with fifteen years and 400 installations yields **0% evidence coverage**: every registry this tool consults is academic or corporate. It correctly returns INSUFFICIENT DATA rather than judging, but it has nothing useful to say about most of the working population.
- **A bare name search cannot identify anyone.** Use `--url` to anchor the report to one account; without it, web mode may merge namesakes and says so.
- **Private people look identical to absent ones.** Someone who keeps no public profile and someone with nothing to show produce the same thin footprint. Coverage drops and the tool declines to score — which is the honest outcome, but it means the instrument is least useful exactly where discretion is most normal.
- **Registry absence skews academic.** ROR and OpenAlex index research organizations, so practitioners outside research have thinner footprints through no fault of their own. That is why absence lowers coverage instead of raising the score.

Phrasing parity is enforced by tests: the same facts in plainer or non-native English must reach the same verdict, and institution names in German, Spanish or Swedish must score the same as their English equivalents.

## Limitations — read before acting on a report

- **Heuristics, not comprehension.** Sarcasm, negation, quoting someone else, and non-English text will all fool it.
- **It reads what it is given.** A profile that omits a real degree gets scored on the omission.
- **ROR and OpenAlex skew academic.** Practitioners outside research have thinner registry footprints through no fault of their own; that is why absence lowers coverage instead of raising the score.
- **A RED verdict is a prompt to investigate, not a finding of dishonesty.** The failure mode that matters here is accusing an honest person, which is why unknowns stay unknown and network failures are never evidence.

Use it for due diligence on public professional claims. Don't publish its output as an accusation.

## License

MIT.
