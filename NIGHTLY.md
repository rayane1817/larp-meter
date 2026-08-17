# Nightly log

Written by each autonomous run for the next one. This is the only memory
between runs — read it before touching BACKLOG.md or picking a task.

---

## 2026-08-15

### Starting point

First nightly run to leave a NIGHTLY.md (none existed). Baseline: 356 tests
green, working tree clean on `master`, no open nightly branch.

### What I did

Closed one concrete slice of the top-priority BACKLOG item ("Verification is
a one-way, claim-anchored funnel" / its duplicate "Zero registry reach on a
realistic prose profile"). I did **not** attempt the full reverse-path
architecture described there (subject → registry → derived Claim →
reconciliation) — that's a big, risky design that needs the OpenAlex
disambiguation groundwork below before any *contradiction* verdict could be
trusted. What I found and fixed is narrower and lower-risk, and it was true
exactly as the backlog measured it:

**`cmd_text`, `cmd_url`, `cmd_from_json`, and the batch-text branch of
`cmd_batch` never called `providers.gather` at all — only `cmd_web` and the
batch-web branch did.** `providers.py` already has a safe, tested,
name-anchored OpenAlex + Wikipedia lookup (gated on `names.name_matches`,
with `ambiguous_identity` reported when several researchers share a name) —
it was just architecturally walled off from every mode except a bare-name
web search. A person who pastes their own bio — the ordinary way this tool
gets used — got **zero** registry contact under `--verify --name` unless
their bio happened to contain a raw DOI or ORCID string. A truthful
researcher describing their work in prose was invisible to verification in
exactly the same way a fabricator was.

Fix: added `cli._subject_registry_signals()`, which runs `providers.gather`
restricted to `(Wikipedia, OpenAlex)` — deliberately **not** Crossref or
DuckDuckGo — and wired it into all four entry points, gated on
`--verify` + a resolvable subject name (never the `"unknown"`/`"pasted-text"`
placeholder). `flags.py`'s flag 6 (verifiable output) and flag 10
(independent validation) already knew how to read `ctx.signals["openalex"]`
and `ctx.signals["wikipedia_about_subject"]` — that logic was written for
web mode and simply unreachable elsewhere, so this required no scoring
changes, only reaching code that already existed and was already tested.
Also surfaced `ambiguous_identity` in the same four modes (previously only
printed in `cmd_web`) and updated `--explain`/README to describe it.

**Why DuckDuckGo and Crossref were left out on purpose:** DuckDuckGo returns
hits for the *name*, not the subject — folding its general web-search
results into a text audit's evidence would credit the subject with material
never confirmed to be theirs, which is precisely the failure mode
`about_subject` gating exists to prevent elsewhere in the pipeline. Crossref
findings feed `corpus` text in web mode; text mode already has real
subject-authored text and mixing in registry-derived prose without a
provenance-tracking mechanism (the still-unbuilt "derived Claim" idea in
BACKLOG.md) would blur who said what. Scoped this down to the two providers
whose *signals* (not corpus text) something already consumes.

**Safety property I checked before writing any test:** both consuming flags
only ever move a report from UNKNOWN to PASSED on new signal — neither can
newly TRIGGER because of this data. So this change can only ever add
corroboration to an honest profile; it cannot manufacture a new accusation.
I did not add any contradiction/negative-finding logic this cycle — that's
explicitly the dangerous part per the OpenAlex research below, and doing it
carelessly is worse than not doing it.

Added `tests/test_cli_registry_wiring.py` — 9 tests, all running the real
`cmd_text`/`cmd_from_json`/`cmd_url`/`cmd_batch` functions (not the provider
or flag logic in isolation) with only the network layer stubbed, following
the "test the real pipeline reaches it" lesson from the ROR dead-code bug.
Specifically checked: (1) flag 6 actually flips to PASSED end-to-end when
OpenAlex has a record and the bio has no identifiers, (2) DuckDuckGo is
never queried from text mode, (3) no name → no registry call, (4)
`ambiguous_identity` reaches the report signals unresolved, (5) omitting
`--verify` makes zero network calls, (6)–(9) the same reachability check for
`--from-json`, `--url`, and batch-text. Full suite: **365 tests, green.**

### BACKLOG.md: confirmed / refuted

- Confirmed live (not just via the recovered evidence in the file): grepped
  and traced `cmd_text`/`cmd_url`/`cmd_from_json`/batch-text — none called
  `providers.gather` before tonight. Matches the backlog's claim exactly.
- Left everything else in BACKLOG.md untouched and unverified. In
  particular I did **not** investigate the "identifier-keyed and one-way"
  duplicate cluster (lines ~153+), the name-matching findings (surname-first
  ordering, non-Latin scripts), the ORCID `/works`/`/employments` findings,
  the company-registry gap, or the DEGREE_RE/ROR capitalisation finding.
  Those are all still exactly what the label says: unverified leads.
- Annotated the two findings I touched in-place with
  `[IN PROGRESS — nightly/2026-08-15]` blocks explaining precisely what's
  now closed vs. still open, rather than marking them `[FIXED]` — the
  underlying architectural gap (no derived Claims, no reconciliation, no
  contradiction path) is still fully open.

### What I learned, worth keeping for future runs

- `report.py`'s `caveats()` and the flags already treat `ctx.signals` as a
  stable, generic contract (`openalex`, `wikipedia_about_subject`,
  `ambiguous_identity`, `search_ok`, `search_failures`,
  `shared_name_evidence`, `profile_anchor`, ...). If you add a new provider
  signal, check `flags.py` and `report.py` for whether something already
  reads that key before assuming you need new consumer code — twice
  tonight the consumer already existed and only the producer needed wiring.
- `git checkout -- <file>` during a mutation test threw away *all* my
  uncommitted edits to that file, not just the deliberate mutation — I had
  redone real work by hand from a system-reminder file dump. For a future
  mutation check, save the original content in memory/a scratch copy (or
  use `git stash` / `git diff > patch` first) rather than relying on
  `git checkout` to snap back a file that also carries un-committed,
  wanted changes.
- I did not get to the mutation-testing pass this cycle (scoring.py,
  names.py, flags.py, verify.py) beyond a couple of spot checks on my own
  new code. That's still open and explicitly called out as a priority in
  the standing instructions.

### OpenAlex reverse-lookup research (for whoever builds the real reverse path)

Not new tonight, but restating what the standing brief already established,
now cross-checked against what `providers.py`'s `OpenAlex` class actually
does, since the next run will likely try to extend it:

- The existing `OpenAlex.search()` already does the *safe* subset: it
  matches on `names.name_matches(subject, [display_name])` before accepting
  a result, and reports `ambiguous_identity` when more than one candidate
  matches. It picks the "best" match by `works_count` when several match —
  this is a **plurality heuristic, not a disambiguation** and is exactly the
  kind of thing that would go wrong on a merged entity (a `Wei Wang`-style
  author record with hundreds of unrelated institutional affiliations could
  win on works_count alone). It's currently only used for a *positive*
  corroboration signal (flag 6 PASS), where a wrong pick just means a
  slightly-too-generous PASS on a flag that can't TRIGGER from this data —
  low harm. It would be actively dangerous to reuse `best` as-is for any
  future contradiction logic without adding the affiliation/`years`-array
  cross-check described in the standing brief first.
- Have not yet re-verified the specific numbers quoted in the standing
  brief (USD rate limiting, 59.8%/7.3%/60.6% OpenAlex stats, the
  `A5100391883` merged-entity example) against a live request this cycle —
  tonight's change makes at most one `/authors?search=` call per audit, well
  within any reasonable per-run budget, so it didn't seem necessary to
  re-confirm before shipping. Worth a fresh live check before anyone builds
  the affiliation/years-array corroboration logic, since API behavior and
  rate limits drift.

### Where to pick up next

1. **Mutation-test scoring.py, names.py, flags.py, verify.py** — this
   cycle's instructions call it out explicitly and I didn't get to it
   beyond spot-checking my own diff. Start with `scoring.py`'s
   `MIN_COVERAGE` boundary (`>=` vs `>`) and `_apply_floors`' tie-breaking
   (`<=` vs `<`) — both are exact-equality-sensitive and I didn't find an
   existing test that pins the boundary itself (only "just under").
2. **The real reverse path** (BACKLOG.md's top finding, still open): turn
   OpenAlex/Crossref/ORCID hits into provenance-carrying derived Claims and
   add a reconciliation step that can produce CONTRADICTED for a
   *quantitative* mismatch ("published extensively" vs 2 works spanning 6
   months). Do the affiliation + `years`-array corroboration work first —
   before this exists, do not let any OpenAlex signal produce a negative or
   TRIGGERED verdict, only PASSED/UNKNOWN as tonight's change does.
3. Everything else in BACKLOG.md is still an unconfirmed lead — the fairness
   audit (non-Western names, married names, non-academic institutions) and
   the LinkedIn-paste review (`linkedin.py`, newest and least-reviewed) are
   both still untouched by any run so far, per the standing instructions'
   priority list.

---

## 2026-08-16 (nightly run)

### What I did

Fixed two CRITICAL fairness bugs in `larp_meter/names.py`, both confirmed live
against the running code before touching anything (BACKLOG.md's own warning —
"every adversarial verification agent ran out of budget" — turned out to be
justified caution, not false alarm: both reproduced exactly as described).

1. **Surname-first naming order.** `name_matches`'s one-token fallback only
   ever checked the LAST token of the subject's name as a possible surname.
   `name_matches('Zhang Wei', ['W. Zhang'])` returned `False` — a real
   Chinese, Korean, Vietnamese or Hungarian researcher whose registry record
   abbreviates their given name gets `MISMATCH` -> flag 11 TRIGGERED -> verdict
   floored at ORANGE, purely because their culture writes the family name
   first. Fixed by accepting a match at EITHER end of the subject's name.

   This is not a free lunch: accepting the first token too means a shared
   GIVEN name ("Jan" in "Jan Vermeulen" vs "Jan Peeters") now also sits at an
   end, and that's a different-person false-positive the suite already had a
   named regression test for (`test_one_shared_token_is_not_a_match` in
   `test_mutation_guards.py`). Fixed that by only accepting the end-match when
   the SAME candidate string's other words are consistent with an
   abbreviation (bare initials, particles, or the subject's own tokens) —
   not a full unrelated word. That test still passes unmodified.

   A single token matching in the MIDDLE of a 3+-part name (Hispanic
   double-surname truncation: "Jose Ramirez Ortega" publishing as "J.
   Ramirez") now returns `None` (UNCHECKABLE) instead of `False` — too weak a
   signal to call either way.

2. **Non-decomposable Latin letters and script mismatches.** `normalize()`
   only strips NFKD combining marks, which does nothing for ø, ł, đ, ð, þ,
   æ, ı, ħ, ŋ — so `name_matches('Bjorn Odegard', ['Bjørn Ødegård'])`
   returned `False`. Added an explicit fold table. Also: a Cyrillic-script
   candidate against a Latin-script subject name (or vice versa) now returns
   `None` instead of a token-search `False` — normalize() doesn't
   transliterate, so "no characters in common" there is a tool limitation,
   not evidence of a mismatch. Also collapsed inner hyphens/apostrophes so
   "Al-Sayed"/"Alsayed" compare equal, without breaking "Smith-Jones"
   double-barrel matching on either half.

   **Caught my own regression before committing:** the hyphen-collapse fix
   only applied to `mine` (via `tokens()`), not to the candidate/blob side of
   the comparison, so `name_matches('Ahmed Al-Sayed', ['Ahmed Alsayed'])` was
   `True` but the reverse, `name_matches('Ahmed Alsayed', ['Ahmed
   Al-Sayed'])`, was `False`. An asymmetric fold is exactly the kind of bug
   this project's whole design exists to prevent — it would produce a false
   MISMATCH depending on which side of the pair happened to type the hyphen.
   Fixed by symmetrizing: both the blob search and the per-candidate word
   split now check the hyphen-collapsed reading too. Regression test added
   (`test_attached_name_match_is_symmetric`) specifically for this.

   **Left unfixed, flagged explicitly in BACKLOG.md:** true transliteration
   spelling variance ("Petrov" vs "Petroff" for the same Cyrillic name under
   different romanization schemes). That needs a phonetic/transliteration
   equivalence table — a much bigger, fuzzier piece of work than a fold
   table, and not something to bolt on as a quick heuristic. Next run should
   scope it properly if picked up: probably a Soundex/metaphone-style
   comparison gated tightly enough not to conflate unrelated names.

Both fixes verified through the REAL dispatch path, not just the `names`
module in isolation — `tests/test_verify.py` gained
`test_family_name_first_author_is_not_falsely_mismatched`, which goes through
`Verifier.verify_doi` with a stubbed Crossref response, exactly the code path
`verify_all` actually calls. This project has a documented history of tests
validating a code path production couldn't reach (the ROR/HANDLERS bug from
several commits ago), so I made a point of not repeating that shape here:
`names.name_matches` has exactly one implementation and both `verify.py`'s
`_attribute` and `providers.py` call it directly — there's no local
reimplementation to drift out of sync with, so the fix reaches production by
construction, not by luck.

**Mutation-tested my own diff** before writing this up: inverted the
script-mismatch guard, inverted the `at_an_end` check, and disabled the
leftover-word compatibility check one at a time, and confirmed the test suite
fails on each (29, 11, and 2 failures respectively). All three mutations
caught; none survived silently.

14 new tests in `tests/test_names.py`, 1 new end-to-end test in
`tests/test_verify.py`. Full suite: 372 tests, all green.

**Turned out incomplete — see the 2026-08-16 review entry directly below.**
`names.name_matches` gained a third return value (`None` = unanswerable) as
the whole point of this fix, but the one place that actually decides a
verdict from it, `verify.py`'s `_attribute`, was never updated to read it —
"there's no local reimplementation to drift out of sync with" was true of
`name_matches` itself, but missed that `_attribute`'s *consumption* of the
result was its own separate place to get wrong, and did.

### BACKLOG.md updates

Marked two CRITICAL findings resolved, with verification notes:
- "Attribution assumes the surname is the last token..." -> `[FIXED]`
- "normalize() folds only combining marks..." -> `[PARTIALLY FIXED]`
  (transliteration variance explicitly still open — see above)

I did NOT touch any other BACKLOG.md entry. Everything else in there is
still exactly as unverified as the file's own header says.

### What I did NOT get to (highest priority for next run)

**The core gap is still open: verification is claim-anchored, not
subject-anchored.** This is the single biggest lever in the codebase (see
BACKLOG.md's first CRITICAL entry, and the task brief's own framing) and I
did not touch it this cycle — the names.py fairness bugs were smaller, more
certain, and directly requested by the "audit for fairness" lens, so I took
the sure thing over starting something I could not finish and verify
end-to-end tonight.

`providers.py` already has most of the honest, hard-won infrastructure this
needs: `OpenAlex.search()` and `Crossref.search()` search by subject name
(not by identifier), already gate on `name_matches` (not truthiness), and
already surface `ambiguous_identity` when multiple researchers share a name.
The problem is entirely architectural: this only runs from `cli.py`'s web/batch
modes (`gather()` at cli.py:97, cli.py:235), its output lands in
`ctx.signals` as opaque dicts, and it never produces a `Claim` or reaches
`verify_all`. A profile with heavy prose claims and zero identifiers still
gets `checkable = []` and INSUFFICIENT DATA, regardless of mode.

**Update from the same-night review: this specific gap (the "only runs from
web/batch modes" half of it) was independently closed by PR #1
(`nightly/2026-08-15`, merged tonight alongside this one) — `cli.py` now
calls the provider chain from every text-based mode too. The rest of this
paragraph — deriving `Claim`s from provider signals and adding a
reconciliation step — is still fully open.**

Next run, if picking this up: read the task brief's OpenAlex section again
first — it documents hard-won, LIVE-measured constraints (USD rate limiting
at ~100 searches per window with no key, 59.8% of author entities are
single-work splits, only 7.3% carry an ORCID, and — critically — an ORCID on
the entity does NOT certify a clean cluster; one measured entity had 2470
works across 863 institutions merged into a single ID). Any subject-anchored
probe has to treat a "no match" as a candidate set for human judgement, never
a standalone negative finding, especially for common East Asian names. Don't
re-derive these constraints from scratch or trust training-data assumptions
about the API — re-verify against a live request if it's been a while.

Concretely, a good next slice: wire OpenAlex/Crossref name-search into
`Verifier` as a second dispatch path (`PROBES: subject_name -> probe()`,
distinct from `HANDLERS: subtype -> handler(claim)`), have it run whenever
`subject_name` is set regardless of mode, and have `verify_all` return
evidence records alongside claims rather than only mutating claim status in
place. Do NOT try to make this produce a `MISMATCH`-strength verdict on day
one — start by making the "0 works found for a researcher claiming 40
papers" case visible in the report at all, even as an UNKNOWN-with-evidence
line. That's the gap the task brief calls out explicitly: today there is no
code path that can print that sentence.

### Other things I noticed but did not verify

- `larp_meter/linkedin.py` (533 lines, newest module, added in commit
  909718b) is explicitly called out in the task brief as least-reviewed and I
  did not get to it this cycle. Worth a red-team pass next time: it's the
  parser for pasted LinkedIn profiles, which is a very different input shape
  (headers, section breaks, no prose) than the free-text bios the rest of the
  test suite exercises.
- I did not re-verify any of the still-open (non-[FIXED]) BACKLOG.md entries
  beyond the two I fixed. In particular the CRITICAL "no reverse path" entry
  (line ~16) and its five near-duplicate variants further down are all still
  exactly as unverified as before — don't assume repetition across the file
  means independent confirmation; they came from the same review run and
  overlap heavily.

---

## 2026-08-16 (same-day human review — not a nightly run)

A separate session (interactive, not the autonomous cron) reviewed both open
PRs from the two entries above before merging either to `master`. Recording
this here because it changes what "confirmed" means for one of tonight's
fixes, and because both PRs are now on `master`, not open branches — the
"where to pick up" pointers above that said "still open" as of their own
commit are otherwise stale the moment you read this.

### What the review found

**PR #1** (subject-anchored OpenAlex/Wikipedia wiring): held up. Re-ran its
365 tests in a clean, isolated worktree (not layered on top of anything
else) and re-derived its core safety property independently by reading
`flags.py` directly — both `f_output` (flag 6) and `f_validation` (flag 10)
return on the new signal before ever reaching a `TRIGGERED` branch, so an
absent record changes nothing and a present one can only help. No changes
needed. Merged as-is.

**PR #2** (names.py fairness fixes): the fixes themselves held up under
independent adversarial tracing — but the PR was incomplete in a way its own
test suite could not catch, because the gap was in a file the PR never
touched. `name_matches` returning `None` for "unanswerable" is the entire
point of this fix, but the only place a verdict actually gets decided from
that return value, `verify.py`'s `_attribute`, still had `elif match: VERIFIED
/ else: MISMATCH` — and `None` is exactly as falsy as `False` in Python, so
it fell straight into `else`. Reproduced live through the real `verify_doi`
dispatch: "Jose Ramirez Ortega", citing his own genuine DOI where Crossref
credits "J. Ramirez" — precisely the Hispanic-surname case this PR's own
`TestMiddleTokenIsUnanswerable` was written to protect — came back
`MISMATCH`, floored at ORANGE by flag 11. Same failure for a Cyrillic
record against a Latin subject name.

This is the third instance in this repository of the same bug shape: **a
component gets fixed and unit-tested correctly in isolation, but the one
place production actually consumes its output doesn't get updated to match,
and nothing in the test suite exercises that seam.** (The other two: the
ROR/HANDLERS dead-code bug, and `verify_github`/`verify_nct` setting
`VERIFIED` on existence alone before an earlier session's fix.) Worth
naming explicitly as a standing review question for every future PR: *does
anything downstream of this change need to learn about the new value you're
now capable of returning?*

Fixed with an explicit `match is None` branch in `_attribute`, two new
regression tests going through the real dispatch (`test_verify.py`:
`test_unanswerable_name_comparison_is_not_a_mismatch`,
`test_non_latin_registry_record_is_not_a_mismatch`), and confirmed by
mutating the fix back out and watching both new tests fail. Pushed to the PR
branch before merging, so the merged history includes the complete, working
fix — not the PR as originally opened.

### State after this review

- Both PRs merged to `master`. **374 tests green on `master` right now** —
  this is the number that matters; the per-PR counts quoted above (365, 372)
  were each measured against a different, now-superseded base.
- No open `nightly/*` branches remain.
- The core gap (subject-anchored verification producing an actual
  `CONTRADICTED`/reconciliation verdict, not just PASSED/UNKNOWN) is still
  fully open, exactly as both entries above describe. Nothing tonight
  attempted it.
- `linkedin.py` still has not had a dedicated red-team pass. Still the
  top item on that front.
- Mutation-testing `scoring.py` (the `MIN_COVERAGE`/`_apply_floors` boundary
  cases flagged in the 2026-08-15 entry) is still undone.

### Where to pick up next

Same three items the 2026-08-15 entry named, in the same order — nothing
about tonight's review changes that priority list, it only closes out the
two PRs that were sitting unmerged when it started:

1. Mutation-test `scoring.py`, `flags.py` (the two files that haven't had a
   dedicated pass yet; `names.py` and `verify.py` got one tonight).
2. The real reverse path: derived `Claim`s + a reconciliation step, gated
   behind the affiliation/`years`-array corroboration work the OpenAlex
   research section above describes. Do not skip straight to a
   contradiction verdict.
3. Red-team `linkedin.py` — still untouched by any run.

Plus the standing review question this session is adding: when you fix a
function to newly return a value it never returned before, grep every
caller, not just the ones your own PR happened to touch.

---

## 2026-08-17 (nightly run)

### Open-PR check (do this first, every night)

`git fetch origin` + a live PR search against `rayane1817/larp-meter` at the
start of this run: **no open `nightly/*` PRs.** The two PRs from
2026-08-15/16 were both merged (per the 2026-08-16 human-review entry
above); nothing has been opened since. Branched fresh from `origin/master`
tip (`79f6cf8`) for tonight's work — clean slate, no merge-order risk.

### Running backlog tally (15 CRITICAL findings)

**8 [FIXED] / 1 [PARTIALLY FIXED] / 6 still open** — unchanged by tonight's
work. Tonight's fixes (below) were both found during tonight's own red-team
pass, not from the original 63-finding review, so they don't move this
tally; they're filed under BACKLOG.md's "Shipped since the original review"
section instead, same convention as the `scoring.py` sweep and flag 13.
Still-open CRITICALs, unchanged: the core reverse-path gap (top finding,
its near-duplicates, and the `--verify` badge-suppression finding), and
"Any identifier appearing anywhere in the text is treated as a personal
authorship claim" (never investigated by any run so far — worth a look
next).

### What I did

Picked two connected pieces of work, both scoped small and both finished
and verified end-to-end tonight — no second speculative feature started:

**1. Red-team pass on `linkedin.py`** — the module the standing brief has
flagged as least-reviewed since three nights ago, and no run had touched it
until tonight. Found and fixed two real bugs, both reproduced live with a
failing test written first, watched fail, then fixed:

- A short post-date description sentence with a comma in it ("Led
  cross-functional team of 12, shipped v2 platform.") was misread as a
  location by `_parse_experiences`, and since `to_prose()` never renders
  `exp.location` at all, the sentence didn't just get mislabelled — it
  silently vanished from everything the extractors and flags ever see.
  Real content loss against an honest profile's actual achievements. Fixed
  with a tighter `_looks_like_location()` heuristic (no digits, no closing
  sentence punctuation, Title-Case comma parts) that still recognises real
  locations like "Antwerp, Belgium" and "San Francisco Bay Area".
- **`Profile.to_prose()` never rendered `profile.name` at all**, which
  meant a self-applied "Dr."/"Prof." title in a LinkedIn display name —
  the cheapest possible way to trigger flag 13, costing a fabricator
  nothing but typing four characters in their own profile's name field —
  was completely invisible to that flag for every LinkedIn-paste subject.
  Found this one not by reading the code but by doing the standing
  brief's own required step: running the CLI end-to-end on a hand-written
  "should be flagged" LinkedIn-paste sample after fix #1, and noticing
  flag 13 stayed silent on a blatant "Dr. Marcus Vane, MBA only" fixture
  that the equivalent plain-prose text (already covered by
  `TestTitleInflationFlag`) correctly triggers. Fixed by rendering
  `self.name + "."` as the first prose line when present. Verified in both
  directions: the fabricated case now reaches flag 13 TRIGGERED through
  the real `extract_claims` → `evaluate` path, and a plain name with no
  title still produces byte-identical claims to before (no new
  false-positive surface).

Both fixes plus 6 new regression tests are in `tests/test_linkedin.py`
(`TestLocationMisclassification`, `TestNameSurvivesNormalisation`). Full
BACKLOG.md write-up with more detail is under "linkedin.py red-team pass"
in the "Shipped since the original review" section.

**2. Mutation-tested `flags.py`** — mandatory every cycle per the standing
brief, and the one file of the four (`scoring.py`, `names.py`, `flags.py`,
`verify.py`) that had never had a dedicated pass. 13 hand-authored
mutations across every bare numeric/boolean comparison in flags 3–13
(flags 1/2 are pure domain-matching with nothing of that shape to mutate).
Each applied to a scratch copy of `larp_meter/flags.py`, full suite run,
reverted before the next one — never left mutated code sitting in the
working tree between mutations.

**12 of 13 survived the first pass.** Only flag 3's `if overlap:` inversion
was caught by the existing suite. All 12 survivors are real, previously
unpinned behaviors — nine are exact-boundary gaps (the same shape as the
`scoring.py` sweep's `MIN_COVERAGE`/`LEVELS` findings: verdict is correct
today, but no test pins the exact cut value itself). Three are more than
cosmetic:

- Flag 11 (the tool's only severity-floor flag) had `if refuted or
  mismatched:` survive as `if refuted:` — no test constructed a
  MISMATCH-only scenario (registry record exists, lists someone else, but
  nothing separately NOT_FOUND); every existing test used NOT_FOUND. Under
  the mutation, a pure attribution mismatch would silently fall through to
  a generic UNKNOWN instead of TRIGGERED, dropping the ORANGE floor for
  exactly the case flag 11 exists to catch.
- Flag 6 had its `c.subtype != "assertion"` filter survive with the filter
  dropped — `assertion` claims (SOFT_EVIDENCE phrases like "peer-reviewed")
  carry no identifier any registry could check. Without the filter they'd
  count as "independently checkable output", which is the exact "vagueness
  beats the tool" evasion this file's top CRITICAL finding describes,
  reproduced one flag deep.
- Flag 8 had `i.status == ex.NOT_FOUND` survive as `== ex.UNCHECKED` — no
  test in `tests/test_flags.py` reached flag 8's TRIGGERED branch through
  `evaluate()` at all (every existing flag-8 test only reaches
  PASSED/UNKNOWN). Same shape as the ROR/HANDLERS dead-code bug this repo
  hit before: the TRIGGERED branch worked when called directly, nothing
  proved `evaluate()` could actually reach it.

All 12 are now pinned in `tests/test_flags.py` (11 new tests — one test
covers both the density and distinct-count boundary for flag 4 at once) and
individually re-confirmed CAUGHT by re-running each mutation after adding
its test. `flags.py` itself needed zero production changes — every
survivor was a genuine untested behavior, not an actual bug, matching the
`scoring.py` sweep's own conclusion. **All four files in the standing
brief's mutation-testing requirement now have at least one dedicated pass.**

### Verification

Ran the full suite after each change (not just at the end): 408 green after
the linkedin.py location fix, 422 green after the name fix and the flags.py
pinning tests (up from 404 at the start of the night). Then ran the CLI
end-to-end on three hand-written LinkedIn-paste samples, per the standing
brief's explicit requirement after touching a pipeline file:

- A verbose but honest paste with a real institution and a DOI I made up on
  the spot — which, by accident, turned out to belong to a real, unrelated
  NumPy paper. Correctly came back ORANGE, flag 11 TRIGGERED, floored by
  the MISMATCH — a useful accidental confirmation that the full
  paste-normalise-extract-verify-score pipeline still reaches ROR and
  Crossref correctly end-to-end after tonight's changes.
- A clean, uneventful paste (Hungarian surname-first name, on purpose, to
  touch the 2026-08-16 names.py fairness fix too) — no flags TRIGGERED,
  INSUFFICIENT DATA on thin content, no false positives.
- The fabricated "Dr. Marcus Vane" sample described above — this is what
  surfaced the name/to_prose bug in the first place, and after the fix
  correctly reaches RED with 6 flags TRIGGERED including flag 13.

### What I learned

- "Run the CLI end-to-end on a should-pass and a should-fail sample" is not
  a formality — it found a real bug tonight (the `to_prose()` name gap)
  that no amount of re-reading the diff for fix #1 would have surfaced,
  because the bug wasn't in the code I'd just changed. It was adjacent,
  latent, and only visible once real fixture text went through the whole
  pipeline.
- The `flags.py` mutation sweep found far more survivors (12/13) than the
  `scoring.py` sweep did (6/12) or the targeted `names.py`/`verify.py`
  passes. Read that as "flags.py's test suite tests outcomes on the
  fixtures that were written, not boundaries or alternate paths through
  the logic" rather than "flags.py is unusually buggy" — none of the 12
  were an actual bug in current behavior, all were untested-but-correct
  behavior. Worth remembering when scoping how much time a mutation pass
  on a given file might need: the flag battery, being 13 independent
  functions each with several branches, has more surface than a single
  scoring function.
- Constructing exact-boundary test fixtures (density == 2.0 at exactly 200
  words with exactly 4 distinct buzzwords, timeline slack == exactly 3
  years) is mechanical but takes real trial-and-error against the actual
  bank/regex data — used a scratch Python REPL to compute word counts and
  hit counts before writing each fixture into the test file, rather than
  guessing and iterating inside the test suite itself. Faster and avoids
  leaving miscounted fixtures behind.

### Where to pick up next

1. **The core gap is still the core gap**: subject-anchored verification
   producing derived Claims + a reconciliation step (CONTRADICTED for a
   *quantitative* mismatch), gated behind the OpenAlex
   affiliation/`years`-array corroboration work described earlier in this
   file. Nothing tonight touched it — same reason as every prior run: it's
   large, needs the disambiguation groundwork first, and a small verified
   change beats a large unverified one.
2. **`linkedin.py` still has more surface than tonight's pass covered.**
   This was a fix-what-you-find pass triggered by the required end-to-end
   check, not an exhaustive line-by-line read. Untouched and worth a
   dedicated look: `_DEGREE_LEVEL_RE`/`_DEGREE_FIELD_RE` are English-only
   (a French "Licence en Droit" or German "Diplom-Ingenieur" degree won't
   bind to its institution the way an MSc does — a fairness gap, not an
   evasion one, since it just loses signal rather than manufacturing an
   accusation); `_parse_educations` assumes the institution is always the
   first line of the group, which matches LinkedIn's current UI but is
   worth a live re-check if it's been a while (LinkedIn's markup changes);
   and `is_linkedin_paste`'s signal-scoring could plausibly misfire on an
   ordinary CV that uses bare "Experience"/"Education" as section headers
   (a very common resume format) — not verified live this cycle, just
   flagged as untested.
3. **"Any identifier appearing anywhere in the text is treated as a
   personal authorship claim"** (CRITICAL, near the end of BACKLOG.md) has
   never been investigated by any run. Worth checking next, alongside the
   remaining open CRITICALs.
4. The BACKLOG.md MAJOR/MODERATE/MINOR tiers (46 findings after dedup) are
   still completely unverified — no run has touched anything below
   CRITICAL yet.
