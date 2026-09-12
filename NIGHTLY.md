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

### Post-PR: fixed a pre-existing Python 3.8 CI break, not tonight's own

Once PR #3 was open, CI came back red on `ubuntu-latest, 3.8` and
`windows-latest, 3.8` (both green on 3.10/3.12). Root cause:
`tests/test_scoring.py`'s `test_floor_worse_than_natural_level_does_apply_and_names_itself`
used `{...} | {11: ...}` to merge two dicts — the `|` merge operator on
plain `dict`s is Python 3.9+ only. That line was introduced in `79f6cf8`
(the `scoring.py` mutation-testing sweep, already on `master` before
tonight's branch), not by tonight's changes — confirmed via `git blame`
before touching anything. Since this repo's own CI matrix (`tests.yml`)
treats Python 3.8 as an explicitly supported target (stdlib-only, zero
dependencies), and the fix is a one-line, risk-free, behaviourally
identical substitution (`{**a, **b}`, compatible back to 3.5), fixed it
forward in this PR rather than leaving it red and waiting — see the
drive-to-green PR-ownership rule for a failure that's real but did not
originate in this PR's own diff. Left a one-line note on the PR explaining
why a third, seemingly-unrelated commit is in there.

**Worth remembering for future runs:** the local dev loop everyone has been
using (`python -m unittest discover ...`) runs whatever Python is on the
box — 3.11 in this session, per the `__pycache__/*.cpython-311.pyc` files —
never 3.8. A 3.8-incompatible construct can sit on `master` invisibly until
someone's PR happens to trigger the full CI matrix. If a future run adds
syntax newer than 3.8 (`|` dict-merge, `match` statements, walrus in
comprehensions in some contexts, etc.), local green does not mean CI green.
## 2026-08-18 (nightly run)

### Open PR check (do this before anything else, every night)

**PR #3, `nightly/2026-08-17`, is open and unmerged** — "Nightly 2026-08-17:
linkedin.py red-team fixes + flags.py mutation-testing pass". Draft, not
approved. All 6 CI check-runs (ubuntu/windows x 3.8/3.10/3.12) are
`completed`/`success` — the `get_status` combined-status API reports
`pending`/`total_count: 0` because this repo's checks are GitHub Actions
check-runs, not legacy commit statuses; that field is not meaningful here
and next run should use `get_check_runs`, not `get_status`, to read CI.
Not acting on this PR tonight per the standing instructions — noting it
for the human and branching fresh from `origin/master`'s tip instead.

**State-drift the human should know about:** `master` is not simply "PR #1
+ PR #2 + whatever's on the open PR branches" any more. Between PR #3
being opened and tonight, three commits landed **directly on `master`**,
authored by the repo owner (`rayane1817`, not a nightly session):
`efbd6c2` (flag 13), `79f6cf8` (a `scoring.py` mutation-testing sweep —
the exact item the 2026-08-16 entries above listed as "still open"; it
is not anymore), and `d958ce0` (a **second, independent** `flags.py`
mutation-testing sweep, on top of the one already merged from
2026-08-16). PR #3's own branch separately contains a `flags.py`
mutation-testing commit (`9c2f37e`) done against the *older* base —
so there are now two unmerged flags.py mutation-testing efforts (one on
`master` already, one sitting on PR #3) that will very likely produce
overlapping or literally duplicate test names when PR #3 is eventually
merged. Not mine to resolve — flagging it so whoever merges PR #3 checks
for duplicate `flags.py` pinning tests rather than being surprised by a
merge conflict there. This is exactly the "unmerged nights may conflict
at merge time" risk the standing instructions warn about, now realized.

### Running backlog tally

**8 [FIXED] / 1 [PARTIALLY FIXED] / 6 still open**, of the 15 CRITICAL
findings — unchanged from PR #3's own count. Re-counted directly against
`BACKLOG.md`'s `## CRITICAL (15)` section on `origin/master`'s current tip
(not from the PR #3 body, which was measured against an older base):
FIXED = the institution-dead-code trio (x2 duplicate write-ups),
GitHub/ClinicalTrials existence-vs-attribution (x2 duplicate write-ups),
GitHub-only-registry-with-no-attribution, ClinicalTrials-investigator-
fields, and the surname-first-token fix = 8. PARTIALLY FIXED = the
non-Latin-script/non-decomposable-letters fold (transliteration variance
still open) = 1. Still open = the core "one-way, claim-anchored funnel"
finding and its three near-duplicate write-ups further down the file,
plus "citing no identifiers disables the entire verification half" and
"any identifier anywhere in the text is treated as a personal authorship
claim" = 6. Tonight's work did not change this count — see below.

### What I did

Picked the mandatory mutation-testing pass as tonight's primary item,
targeting `verify.py` — the last of the standing brief's four named files
(`scoring.py`, `names.py`, `flags.py`, `verify.py`) without a *dedicated*
broad sweep. (`scoring.py` and `flags.py` both got real sweeps now, per
the state-drift note above; `names.py` still only has spot-checks from the
surname-order fix, not a full pass — see "where to pick up" below.)

Six hand-authored mutations, each applied to a scratch copy of
`larp_meter/verify.py`, full 417-test suite run after each, file restored
before the next: dropping HTTP 410 from `_get`'s not-found tuple,
dropping the `wanted and` guard in `verify_institution`'s subset match,
narrowing `_is_ambiguous_acronym`'s `<= 5` boundary, dropping the
single-character filter in `_significant_tokens`, and turning `verify_arxiv`'s
`or` into `and` in its error-page detection.

**All six survived the first pass** — every one exposed a real gap where
some `verify.py` behavior had no test pinning it, not an actual live bug
(production code needed zero changes). Full detail and the reasoning for
each is now in `BACKLOG.md` under "Mutation-testing sweep: `verify.py`
(2026-08-18, nightly run)" rather than duplicated here — worth a read for
the two that matter most:

- The `verify_institution` guard is the closest thing to a real bug found
  tonight: without `wanted and ...`, a claim value that decomposes to
  nothing but stopwords is a subset of *any* ROR hit, so it would come
  back VERIFIED regardless of what the registry actually returned —
  manufacturing coverage from an empty query, the exact failure mode
  the standing brief's "never manufacture coverage" line warns against.
- The `verify_arxiv` `or`/`and` mutation is the one with real accusation
  risk if it ever regressed live: under the mutation, an arXiv error page
  that only carries one of the two error tells fell through to
  `_attribute` and came back **MISMATCH** against a stubbed author name —
  a false contradiction on the tool's strongest verdict, purely from an
  error-page detector losing redundancy it was deliberately given.

All six pinned in `tests/test_mutation_guards.py` (`M36`-`M40b`): a new
`TestInstitutionMatchGuards` class, a new `TestArxivErrorSignalsAreIndependent`
class, and one addition to the existing `TestRegistryAnswerVsSilence`.
Each new test individually re-verified: fails against its mutation, passes
against the restored file. **417 -> 423 tests, green throughout.**

Ran the CLI end-to-end (offline, no `--verify` — no production code
changed tonight, so this was a sanity check rather than a required
verification) on a clean sample (YELLOW, 23, flag 6 the only TRIGGERED —
expected, no identifiers to verify offline) and a heavily fabricated one
("Dr. Marcus Vane... 40 years of published, peer-reviewed research...").
The fabricated sample came back **INSUFFICIENT DATA** — flags 4 and 10
TRIGGERED, nothing else decidable. This is not a regression from tonight;
it is a live, first-hand demonstration of the standing brief's own "known
core gap" framing ("vagueness beats the tool") on a sample built to
exercise exactly that. Confirms the gap is still exactly as real and as
unaddressed as the brief describes — recording the concrete numbers here
in case a future run wants a ready-made repro fixture rather than writing
a new one.

### BACKLOG.md: confirmed / refuted

Did not investigate any of the six still-open CRITICAL findings tonight —
the mutation-testing pass was scoped to `verify.py`'s own internal
correctness, not to the architectural reverse-path gap those six describe.
Added one new entry under "Shipped since the original review" documenting
tonight's sweep (see above); did not touch any of the 15 CRITICAL
write-ups themselves. The tally above is a re-count for accuracy, not new
verification work.

### Mutation-testing log (files swept so far, by night)

- `scoring.py`: 2026-08-16 (interactive session) + confirmed present on
  `master` as of tonight (`79f6cf8`). Done.
- `flags.py`: 2026-08-16 (interactive session, merged) **and** two more
  independent sweeps since — one pushed directly to `master` (`d958ce0`,
  outside any nightly run) and one on PR #3's still-open branch
  (`9c2f37e`). Done, arguably over-done — see the state-drift note above.
- `verify.py`: **tonight (2026-08-18)**. Done — 6/6 mutations found real
  gaps, all now pinned.
- `names.py`: only spot-checks from the 2026-08-16 surname-order/
  unanswerable-name fix (3 targeted mutations on that specific diff, not
  a broad sweep). **Still the one file of the four without a dedicated
  pass.**

### What I learned

- `pull_request_read`'s `get_status` method reports the legacy combined
  commit-status API, which this repo's Actions-based CI does not
  populate — it will always read `pending`/`total_count: 0` here
  regardless of real CI state. Use `get_check_runs` instead.
- A human pushing directly to `master` between nightly runs is allowed
  (only the nightly session is bound by the branch/PR-only rule) but it
  means "no open `nightly/*` branches" is not the same claim as "master's
  history since the last night I read is exactly what I'd expect" — worth
  re-diffing `origin/master` against the last entry's stated tip, not just
  checking for open PRs, before assuming you know the starting state.
- Every mutation this cycle survived on a file that already had solid
  targeted regression tests around its known historical bugs
  (surname-order, unanswerable-name, existence-vs-attribution). The
  survivors were all in code paths adjacent to those fixes but never
  themselves deliberately attacked: boundary values, the less-common of
  two OR'd conditions, an HTTP status code sitting next to the one that
  got a real test. Worth remembering as a search heuristic: after a
  targeted bug fix earns its own regression test, the surrounding
  boundaries and sibling conditions in the same function are exactly
  where the next survivor tends to hide.

### Where to pick up next

1. **Mutation-test `names.py`** — the one file of the four still without a
   dedicated broad sweep, only spot-checks tied to a specific fix. Good
   candidates going in, unverified: the fold-table boundary cases in
   `normalize()` (which non-Latin-script codepoints are and are not
   covered), the "leftover-word compatibility check" mentioned in the
   2026-08-16 entry above, and the middle-token-vs-end-token boundary in
   the surname matcher.
2. **The real reverse path** (still the single biggest lever, per every
   prior entry and the standing brief itself) — untouched again tonight.
   Do the affiliation/`years`-array corroboration work before any
   contradiction verdict, exactly as every prior entry has said.
3. **Red-team `linkedin.py`** — PR #3 (still open, unmerged) already did a
   first pass here and found two real bugs (see its description). Once
   PR #3 is merged, a second pass targeting what it didn't cover would be
   the natural next step; until then, don't duplicate PR #3's own
   unmerged work.
4. When PR #3 merges: check `tests/test_flags.py` for duplicate/overlapping
   pinning tests between its `9c2f37e` mutation-testing commit and
   `master`'s `d958ce0` — flagged above, not resolved tonight.
## 2026-08-19 (nightly run)

### Open PRs at the start of this run — for the human's visibility, not acted on

Two `nightly/*` PRs are open and unmerged against `master`, both draft,
both from prior nightly runs, neither touched tonight (per the standing
instruction — branched fresh from `origin/master`'s tip instead):

- **PR #3** (`nightly/2026-08-17`, base since moved — see below):
  `linkedin.py` red-team fixes (two real bugs: a comma in a post-date
  description sentence misread as a location and silently dropped; a
  self-applied "Dr."/"Prof." LinkedIn display name never rendered into
  prose, so flag 13 couldn't see it) + a `flags.py` mutation-testing
  sweep. 422 tests at time of opening. CI status reads `pending`/0 check
  runs via the GitHub API — worth the human confirming whether checks are
  actually configured on this repo before assuming CI ran.
- **PR #4** (`nightly/2026-08-18`): a `verify.py` mutation-testing sweep
  (six mutations, all survived, all real — including one with genuine
  false-MISMATCH risk in `verify_arxiv`'s error-page detector). 423 tests
  at time of opening. Same CI-status caveat as PR #3.
- **Base-branch drift, already flagged by PR #4's own body:** three
  commits landed directly on `master` between nights (not from a nightly
  run) — including a `flags.py` mutation-testing sweep that duplicates
  the one PR #3 already carries on its own branch. Whoever merges PR #3
  should expect a collision there. Tonight's branch is based on current
  `master` (`7699b72`), which already has both of those direct commits
  (`scoring.py` and `flags.py` sweeps) — see below, this matters for the
  backlog tally.

### Backlog tally (15 CRITICAL findings, BACKLOG.md line ~210)

**8 [FIXED] / 1 [PARTIALLY FIXED] / 6 still open** — unchanged from the
last several entries. Tonight's work didn't touch a BACKLOG.md finding
(mutation-testing is a standing requirement, not a backlog item); no
tally movement expected or claimed.

### What I did

Picked up the explicit top-of-list item from PR #4's own closing note:
**`names.py` mutation-testing**, the last of the four files
(`scoring.py`, `flags.py`, `names.py`, `verify.py`) the standing brief
names as required. Small and independent by construction — this only
ever adds tests, touches no production code, and doesn't depend on either
open PR.

Worth flagging first: the repo's own documentation trail on this was
wrong. The `flags.py` sweep write-up (BACKLOG.md, 2026-08-16) claims
"`verify.py` is now the only one of the four named files without a
dedicated mutation pass" — implying `names.py` was already done by then.
It wasn't. What happened 2026-08-16 was the surname-order and diacritics
*fairness fixes*, each landing with targeted tests for the specific bug
found — real, but not a systematic sweep of every comparison in the file.
I found and noted this discrepancy in BACKLOG.md's new section rather
than silently working around it, since the next reader would otherwise
reasonably (and wrongly) conclude `names.py` was covered.

Ran 13 hand-authored mutations across every boundary and guard in
`names.py` (both `len(t) > 1` token filters, the `not mine`/`not usable`
guards, the script-match gate, the mononym/confident-match/single-token
length thresholds, the `parts[0]/parts[-1]` `or`, the `matched not in
words` guard, the `extra`-word filter and its `all(...)` consistency
check, and the hyphen-collapsed `blob_variants` entry) — same
scratch-copy-run-revert harness as the two earlier sweeps.

**5 of 13 survived. 4 are real, all accusation-risk:**

1. `tokens()`'s "no bare initials" filter (`len(t) > 1` → `len(t) > 0`,
   both occurrences): a subject-typed bare initial with no period (e.g.
   "A Zhu") stops being the length-1 mononym set `{"zhu"}` and becomes
   `{"a", "zhu"}`, which a genuine full-name record like "Zhu Wei" no
   longer satisfies under the mononym rule. Live: `name_matches("A Zhu",
   ["Zhu Wei"])` goes `True` → `False`.
2. The `not mine` guard (empty/particle-only subject name): every
   existing test for this guard happens to pair it with a Latin-script
   candidate, where a *different*, later guard (the script-mismatch
   check) independently also returns `None` — so the suite never actually
   exercised whether this specific guard does anything. Deleting it
   outright still passed the full suite. Pairing with a non-Latin
   candidate instead (nothing left to coincidentally catch it) exposes
   it: `name_matches("", ["Михаил Иванов"])` and `name_matches("Dr.",
   [...])` both go `None` → `False` with the guard gone.
3. The `not usable` guard (zero registry candidates), the mirror-image
   masking problem: paired with a non-Latin *subject* name this time (an
   empty blob is "not Latin" too, so the script guard doesn't fire),
   `name_matches("Михаил Иванов", [])` goes `None` → `False`. This one is
   worth naming specifically as a fairness finding, not just a coverage
   gap: a Latin-script subject's own empty-candidate case is *always*
   masked by the script guard firing first, but a non-Latin subject's
   never is — so this exact bug, if it existed, would land exclusively on
   the non-Western names this project's fairness audits exist to protect.
4. (The `all(...)` → `any(...)` mutation on the per-candidate consistency
   check survived too, but turned out to be an **equivalent mutant** —
   `present`'s construction guarantees any `extra` word also in `mine`
   would already have been counted into `present`, contradicting the
   `len(present) == 1` precondition for reaching that branch. Confirmed
   with a 200,000-case random differential fuzzer against both variants
   directly: zero diverging inputs. Not pinned — there is nothing a
   future change could break that a test here would catch.)

All four real survivors pinned in `tests/test_names.py` two new test
classes (`TestBareInitialIsNotASignificantToken`,
`TestEmptyInputsStayUnanswerableAgainstNonLatinData`), each individually
reconfirmed to fail on its mutation and pass on the restored file (not
just checked once at the end — see the transcript's per-mutation
subprocess runs). **417 → 421 tests, green.** `names.py` itself needed
zero production changes — every real survivor was already-correct,
merely untested behavior.

Full mutation-by-mutation detail is in BACKLOG.md under "Mutation-testing
sweep: `names.py` (2026-08-19, nightly run)".

### End-to-end CLI check (required after touching anything in the
### names.py/verify.py/flags.py/extract.py/scoring.py family)

No production code changed tonight, so this was a sanity check rather
than a required regression check — but the required-after-touching-these-
files rule exists precisely so a change doesn't get to skip it by
reasoning "it's only tests," so I ran it anyway, live against Crossref
(network available this session):

- **Clean sample**: a prose bio for the real physicist Markus Aspelmeyer,
  correctly attributed, citing his real DOI (`10.1038/nphys1170`, Crossref
  gives sole author "Markus Aspelmeyer"). Result: the DOI claim comes back
  `VERIFIED`, flags 4/6/10/11 all `PASSED`, OpenAlex/Wikipedia signals
  both corroborate the subject. Overall level lands on **INSUFFICIENT
  DATA** (evidence coverage 32%, just under the 35% `MIN_COVERAGE` floor)
  — expected, not a regression: this is the standing "vagueness/thin-
  profile" gap the task brief already documents, and a short truthful bio
  correctly not being score-manipulated either way is the honest outcome.
- **Fabricated sample**: the same real DOI, same real paper, but
  attributed to "Dr. John Smith, PhD" (not the actual author) plus vague
  "40 years of published, peer-reviewed research" filler. Result:
  `MISMATCH` on the DOI claim (`name_matches` correctly reports "John
  Smith" ≠ "Markus Aspelmeyer" — an actual mismatch, not one of tonight's
  unanswerable-input edge cases), flag 11 `TRIGGERED`, verdict **ORANGE**,
  score 33.

This confirms the full pipeline still routes through `name_matches`
correctly on both the genuine-match and genuine-mismatch paths — tonight's
new tests only add coverage for the *unanswerable* (`None`) paths in
between, which this check doesn't exercise by design (that's what the
unit tests are for).

### Adversarial re-review (step 5 of the standing cycle)

No function's return contract, type, or possible output values changed
tonight — `names.py` itself is byte-identical to the start of the run.
The specific failure this step exists to catch (a caller silently
mishandling a newly-possible return value) doesn't apply when nothing
downstream has anything new to learn about. Skipped with this note rather
than silently, per the instruction to always say when a step doesn't
apply rather than leaving it unaddressed.

### Mutation-testing log (standing requirement, tracked until all four
### files have had a real pass)

- `scoring.py`: done, 2026-08-16 (direct-to-master commit `79f6cf8`, not
  a nightly run). On `master`.
- `flags.py`: done, 2026-08-16 (direct-to-master commit `d958ce0`). On
  `master`. A **second**, independent `flags.py` sweep also exists on the
  still-open `nightly/2026-08-17` PR (#3) — likely duplicate/colliding
  tests for whoever merges it; not resolved tonight since PR #3 wasn't
  touched.
- `names.py`: **done tonight** (this entry). On this branch,
  `nightly/2026-08-19`.
- `verify.py`: done, but only on the still-open `nightly/2026-08-18` PR
  (#4) — not yet on `master`.

**All four files now have at least one real sweep somewhere in the repo's
history**, but `master` itself only has three (`verify.py`'s is stuck on
an unmerged branch). This mandatory requirement will be fully satisfied
on `master` once PR #4 merges — nothing further to do on this front
except merging what already exists.

### What I learned

- The "which files still need a mutation sweep" bookkeeping in this repo
  has been unreliable at least once before (see the flags.py-sweep
  write-up's wrong closing claim above) — worth treating any single
  night's "X still needs a sweep" pointer as a lead to confirm via `git
  log`/`grep`, not a fact, the same way BACKLOG.md's own findings are
  treated. I did that here; future runs should too.
- Equivalent mutants are a real, expected category, not a sign the sweep
  was done wrong — the `all`/`any` survivor here couldn't be distinguished
  by *any* input given how `present` and `extra` are both derived from
  the same `blob`. Forcing a synthetic pinning test for it would have
  been noise (a test with no real regression behind it), not rigor. The
  standing instruction to always pin a survivor should be read as "pin it
  unless you can show — not just suspect — that it's unreachable."
- The "guard masking" pattern (a guard is provably untested because a
  *different*, later guard already returns the same answer for every case
  the test suite tries) seems specific enough to `name_matches`'s stack of
  early-return guards that it's worth a quick grep in other multi-guard
  functions (`verify.py`'s dispatch functions have a few) next time
  someone's doing a mutation pass there — same shape of bug is plausible
  wherever multiple guards can independently reach the same return value.

### What the next run should pick up first

1. **Merge state, not new work, first**: two open, unmerged nightly PRs
   (#3, #4) are sitting with unclear CI (`pending`/0 check runs via the
   API in both cases — confirm whether CI is actually wired up on this
   repo, separately from tonight's task). This isn't something a nightly
   run auto-merges, but it's worth a human's attention before a third
   night's PR stacks on top.
2. **The core gap is still fully open**: subject-anchored verification
   producing an actual `CONTRADICTED`/reconciliation verdict (derived
   `Claims` + reconciliation step) rather than just PASSED/UNKNOWN. Read
   the task brief's OpenAlex section again first (live-measured
   constraints: USD rate limiting, 59.8% single-work author-entity splits,
   only 7.3% carrying an ORCID, merged-entity false positives) — this is
   still the single biggest lever in the codebase and no night has
   attempted the actual derived-Claim/reconciliation architecture yet.
3. Once PRs #3 and #4 both merge, the standing mutation-testing
   requirement is satisfied for all four files — future nights' mandatory
   passes should pick a *different* production file (`providers.py`,
   `linkedin.py`, `extract.py`, `cli.py` are all candidates) rather than
   re-sweeping the same four from scratch.
## 2026-08-23 (nightly run)

### Open PRs at the start of this run — all unmerged, none acted on

`git log`/`master` had not moved since 2026-08-17 (`7699b72`). Three
`nightly/*` PRs were open against it, oldest first:

- **PR #3** (`nightly/2026-08-17`): `linkedin.py` red-team fixes + a
  `flags.py` mutation sweep. Draft, open.
- **PR #4** (`nightly/2026-08-18`): `verify.py` mutation sweep (6
  mutations, all real). Draft, open. Its `verify_institution` finding
  (the `wanted and` guard) is independently re-found and re-pinned
  directly on `master` tonight — see the mutation section below; expect a
  near-duplicate test when this PR eventually merges.
- **PR #5** (`nightly/2026-08-19`): `names.py` mutation sweep (13
  mutations, 4 real). Draft, open.

No nightly run appears to have happened on 2026-08-20/21/22 — no branches,
no NIGHTLY.md entries for those dates. Not investigated further; noting it
here so the gap is visible rather than silently skipped over.

Per standing instructions, none of these three were touched. Branched
tonight's work fresh from `origin/master`'s tip (`7699b72`) rather than
stacking on any of them, and kept tonight's change scoped to `extract.py`
+ its tests plus one `verify.py` test — no overlap with the modules PRs
#3/#4/#5 touch (`linkedin.py`, `verify.py` production code, `names.py`),
so this branch shouldn't conflict with any of them at merge time. The one
soft collision is noted above: PR #4 will likely add a near-duplicate of
tonight's new `verify.py` test when it merges.

### Running backlog tally (15 CRITICAL findings)

**8 [FIXED] / 1 [PARTIALLY FIXED] / 6 still open — unchanged from PR #5's
last recorded tally.** Tonight's DEGREE_RE fix (below) does NOT move this
number: re-checked its section placement in BACKLOG.md before writing this
and it sits in `## MAJOR (25)`, not `## CRITICAL (15)` — I nearly logged it
against the CRITICAL count on the assumption that "a real fix" implies "a
critical fix" without actually re-verifying which section it lives in;
worth flagging as its own small lesson for future nights. The MAJOR/MODERATE/MINOR
tallies aren't tracked run-over-run the way CRITICAL is; not starting that
bookkeeping tonight, just noting the fix landed there instead.

### What I did

**Primary item — fixed a real false-institution-claim bug in `DEGREE_RE`,
confirmed by writing failing tests first.** Picked up BACKLOG.md's
"DEGREE_RE's re.I defeats the capitalisation anchors" CRITICAL entry
(unverified going in, like everything in that file). Reproduced it live
against current `extract.py` before touching anything:
`extract_claims("She earned an MBA from Rotterdam School of Management
and a BSc in Industrial Engineering.")` returned `degree_institution` =
`"Rotterdam School of Management and a"` — a string the subject never
wrote, which under `--verify` gets sent to ROR and printed back as their
own credential (flag 8's evidence line). Root cause confirmed: `DEGREE_RE`
is compiled with `re.I` for the degree/field text, and that flag leaks
into the interpolated `_INSTITUTION_CORE`, so its `[A-Z]`-anchored
"continue across a connector word" group stops meaning "capitalised word"
and starts meaning "any word" — the lowercase "and a" following "of
Management" satisfied it.

Wrote two failing tests in `tests/test_extract.py` first
(`test_degree_institution_is_not_corrupted_by_case_insensitive_overrun`,
`test_degree_institution_does_not_swallow_a_lowercase_connector_word`),
watched both fail against the unmodified code, then fixed it.

**The first fix attempt was wrong, and the full suite is what caught it —
this is the finding worth remembering more than the bug itself.** The
BACKLOG entry's own suggested fix direction was `(?-i:...)` around
`_INSTITUTION_CORE` to restore case-sensitivity. That does stop the
overrun — and it also broke `tests/test_round4.py`'s
`TestDeterminism.test_cosmetic_variation_does_not_move_the_verdict`, which
asserts the tool returns byte-identical claims for an all-caps or
all-lowercase paste of the same profile. Reintroducing `[A-Z]` case
sensitivity into a shared institution pattern meant an all-caps or
all-lowercase "Delft University of Technology" no longer matched at all.
I only caught this because the standing instructions require running the
*full* suite after a change, not just the new tests — `python -m unittest
discover` immediately flagged 2 failures in a file I hadn't touched and
hadn't thought to check by hand. This is the same failure shape as the
2026-08-16 review's "a function's return contract changes and a caller
elsewhere doesn't learn about it" — except one layer further down, in a
shared regex fragment instead of a shared function.

Shipped fix instead: kept `_INSTITUTION_CORE` fully case-insensitive
(so the determinism guarantee holds), and added a negative-lookahead
stopword exclusion (`and|but|or|nor|with|a|an|the|who|which|that`) to the
trailing continuation group, so the over-run words themselves are excluded
by name rather than by case. Both original bug tests pass, the
determinism test's mutation-adjacent boundary (its 6 cosmetic variants,
including uppercase/lowercase) all still pass, and the full suite went
417 → 419 → **420** (one more test came from the `verify.py` mutation
finding below).

### What I confirmed in BACKLOG.md (evidence, not assertion)

- **CRITICAL "DEGREE_RE's re.I..." — CONFIRMED and FIXED.** Live repro
  matched the entry's own measured example exactly (`"...and a"`
  corruption). Marked `[FIXED — nightly/2026-08-23]` in BACKLOG.md with
  the full before/after and the determinism near-miss recorded inline.
- **The entry's second failure mode (truncation: "Technische Universitat
  Munchen" → "Technische Universitat", losing "Munchen") — CONFIRMED but
  left OPEN, deliberately.** Re-measured live: `INSTITUTION_RE`
  (`mentioned_institution`, already case-sensitive, untouched tonight)
  produces the identical truncation on the identical input. It's a
  shared, pre-existing gap in `_INSTITUTION_CORE`'s continuation logic
  (only continues past the institution keyword across a listed connector
  word, never across a bare adjacent capitalised token) — not specific to
  the re.I bug fixed tonight, and lower severity (a truncated real name is
  a weaker false claim than a fabricated one). Good next pick-up if
  continuing this file.

### Mutation-testing log (mandatory this cycle)

Time-boxed spot-check across all four required files rather than a full
sweep of any one, since the primary item above already consumed the
night's main budget. One hand-authored mutation per file, scratch-copy /
full-suite / revert, same discipline as every prior sweep:

| File | Mutation | Result |
|---|---|---|
| `scoring.py` | `_apply_floors` tie-break `<=` → `<` | **Caught** (2026-08-16 sweep's test still active on `master`) |
| `flags.py` | flag 11 `if refuted or mismatched:` → `if refuted:` | **Caught** (2026-08-17 sweep's test still active on `master`) |
| `names.py` | `if len(present) >= 2:` → `>= 3:` | **Caught** (18 failures — incidental coverage from other pinning tests, even though the dedicated 2026-08-19 sweep isn't on `master` yet) |
| `verify.py` | `verify_institution`'s `if wanted and wanted <= have:` → `if wanted <= have:` | **SURVIVED** — real, unpinned on `master` |

The `verify.py` survivor is exactly the bug the still-unmerged PR #4
already found and flagged as its most serious: a claim value that
decomposes to nothing but stopwords ("Of The") gives `wanted` an empty
set, and an empty set is a subset of any ROR hit — so without the guard,
the first institution ROR returns for a query that named *nothing*
comes back `VERIFIED`. Rather than leave `master` unpinned a second time
waiting for PR #4, added
`TestRegistries.test_a_claim_of_nothing_but_stopwords_cannot_be_verified`
directly to `tests/test_verify.py` tonight, confirmed to fail on the
mutation and pass on the restored file. **Expect a near-duplicate test
when PR #4 eventually merges** — flagged in BACKLOG.md too so it isn't a
surprise.

**Standing four-file requirement: closed out.** Between tonight and the
three still-open PRs, all four of `scoring.py`, `names.py`, `flags.py`,
`verify.py` now have at least one real, evidenced mutation pass — two on
`master` (`scoring.py`, `flags.py`), two on unmerged branches
(`names.py` PR #5, `verify.py` PR #4) plus tonight's spot-check and one
new pinned test landing directly on `master` regardless of what happens
to PR #4. Future cycles can go back to deeper, single-file sweeps (repeat
passes, or the files those PRs haven't reached yet) rather than needing to
touch all four every night.

### Verification

- Full suite: 417 → 420 tests, green throughout (checked after the fix,
  after the wrong first attempt was reverted, and after each mutation was
  reverted).
- Ran the CLI end-to-end on two hand-written samples per the standing
  requirement:
  - **Clean**: "Ana Kowalski, mechanical engineer. She earned an MBA from
    Rotterdam School of Management and a BSc in Industrial Engineering
    from TU Delft. Six years designing HVAC systems..." — the exact
    sentence shape that used to corrupt the institution claim. Landed on
    **INSUFFICIENT DATA** (thin, honest, no-verify profile — expected),
    and flag 8's evidence line correctly reads "Degree tied to a named
    institution (Rotterdam School of Management)" — confirmed in the
    saved JSON's raw claim too: `degree_institution` = `"Rotterdam School
    of Management"`, not the corrupted string.
  - **Should-flag**: "Dr. Marcus Vane... PhD in Quantum Information from
    Rotterdam School of Management..." (deliberately using the same
    business-school institution against a claimed quantum-computing
    domain, and the same "and a" sentence shape right after it). Landed
    on **YELLOW 33/100**, flag 1 (Education ≠ Claimed Domain) TRIGGERED —
    correctly identifies the credential/domain mismatch — and flag 8's
    evidence again shows the clean, uncorrupted institution string.

### What the next run should pick up first

1. **The core gap is still fully open** — subject-anchored verification
   (derived `Claim`s from OpenAlex/Crossref + a reconciliation step). Nothing
   in the last several nights has touched this; it remains the single
   biggest lever named in the task brief. Re-read the OpenAlex constraints
   section in the standing brief and re-verify them live before starting —
   they were last measured 2026-08-14.
2. **Three open `nightly/*` PRs (#3, #4, #5) need a human merge decision.**
   They're independent of each other's file scope mostly, but PR #4 will
   collide with tonight's new `verify.py` test (near-duplicate, not a
   logic conflict) — worth a heads-up to whoever merges it.
3. `_INSTITUTION_CORE`'s truncation gap (real institution names cut short
   after the institution-type word when no connector follows — "Technische
   Universitat Munchen" → "Technische Universitat") — confirmed live
   tonight, deliberately left unfixed, affects both `degree_institution`
   and `mentioned_institution` equally. Smaller than tonight's fix but a
   natural continuation of the same area.
4. `linkedin.py`'s dedicated red-team pass (PR #3) is still sitting
   unmerged — worth checking whether a fresh look after this many nights
   turns up anything PR #3 missed, once it's merged or superseded.
## 2026-08-24 (nightly run)

### ⚠ Open PR pileup — for human visibility, not acted on

**Four `nightly/*` PRs are open, draft, and unmerged against `master` right
now**, dating back a week: #3 (`nightly/2026-08-17`, `linkedin.py` red-team +
`flags.py` sweep — **`mergeable_state: dirty`, i.e. now has a real merge
conflict**), #4 (`nightly/2026-08-18`, `verify.py` sweep — clean), #5
(`nightly/2026-08-19`, `names.py` sweep — clean), #6 (`nightly/2026-08-23`,
`DEGREE_RE`/`re.I` institution-name fix — clean). No nightly run happened on
2026-08-20, 08-21 or 08-22 (already flagged by PR #6's own description; still
true). Per the standing instructions, tonight's run did not push to any of
these — each one is small and independently reviewable, but they've now
sat long enough that #3 conflicts with whatever landed after it, and #4/#5's
`verify.py`/`names.py` mutation sweeps are real, already-completed work that
still isn't protecting `master`. **This queue needs a human merge pass** —
there's nothing more the autonomous side should do about it besides keep
flagging it, which is exactly what this section is for.

### Running backlog tally

**CRITICAL: 8 [FIXED] / 1 [PARTIALLY FIXED] / 6 still open** (unchanged
tonight — tonight's fix was MAJOR-severity, not one of the 15 criticals;
mutation-testing gaps aren't BACKLOG.md items). Verified this count directly
against `BACKLOG.md`'s own `## CRITICAL (15)` section on current `master`
before writing it down, rather than trusting the last PR description's
number.

### What I did

**Primary item**: re-verified and independently re-fixed two real bugs in
`linkedin.py` that the 2026-08-17 red-team pass (PR #3) had already found
and fixed — but since PR #3 was never merged, `master` still had both live.
Confirmed both live on `master` before touching anything (grepped for
`_looks_like_location` and `to_prose`'s handling of `self.name` — neither
existed), then wrote failing tests first, watched them fail, then fixed:

1. **`Profile.to_prose()` never rendered `profile.name`.** Flag 13
   (Self-Applied Doctoral Title) scans the rendered prose for a "Dr."/"Prof."
   honorific next to the subject's own name — but the LinkedIn normaliser
   never put the name in that prose at all. A fabricator typing "Dr. Marcus
   Vane" into their own LinkedIn display name field — the cheapest possible
   evasion, no crafted prose needed — was invisible to flag 13 via both
   `--text` auto-detection and `--from-json`. Fixed by rendering the name as
   the first prose line. Verified live via both CLI entry points (see
   BACKLOG.md for the exact before/after flag 13 output).
2. **A short achievement sentence with a comma right after the date line was
   misread as a location**, and since `to_prose()` never renders
   `exp.location` at all, this was silent content loss, not a mislabel: "Led
   cross-functional team of 12, shipped v2 platform." vanished from
   everything the extractors and flags ever see. Fixed by tightening
   `_looks_like_location()`: reject anything with a digit, anything ending
   in sentence punctuation, or any comma-separated part not starting with a
   capital letter.

Both mutation-tested (reverted each fix in isolation — 2 test failures and 1
test failure respectively — then restored). Full detail, including the
exact live CLI output before and after, is in `BACKLOG.md` under
"`linkedin.py`: self-applied title in the name field..." (2026-08-24).

**Mandatory mutation-testing pass**: one spot-check mutation each in
`scoring.py`, `flags.py`, `verify.py`, `names.py` (not a full sweep — the
`linkedin.py` fix was primary tonight), deliberately targeting the specific
guards PRs #4 and #5 already found, to check whether `master` is still
exposed while those PRs sit unmerged. `scoring.py` and `flags.py`: both
caught (already pinned by the 2026-08-16 direct-to-master sweeps).
`verify.py` and `names.py`: **both survived on `master`**, confirming it
really is still exposed to both PR #4's and PR #5's findings. Pinned both
directly on this branch (same "don't leave master unpinned twice" call PR #6
made for the same `verify.py` guard). Full mutation-by-mutation detail in
BACKLOG.md.

### Verification

- Full suite: 417 → 425 tests, green throughout (after each fix, after each
  mutation, and at the end).
- Ran the CLI end-to-end on two hand-written LinkedIn-paste samples per the
  standing requirement:
  - **Clean**: "Elena Voss", a senior backend engineer with a real-shaped
    career and no title claims. Landed on INSUFFICIENT DATA at 27% coverage
    (expected — thin profile, the standing "vagueness beats the tool" gap,
    not a regression) with flag 13 correctly UNDECIDABLE ("no title claimed").
  - **Should-flag**: "Dr. Marcus Vane", MSc-only education, "40 years of
    published, peer-reviewed research" filler. Flag 13 correctly
    **TRIGGERED**: "Self-applies 'Dr. Marcus Vane', but the entire stated
    education (MSc Biology) contains no doctorate." This is the exact case
    tonight's fix exists for, confirmed live through the real pipeline, not
    just the new unit tests.
- Cross-boundary check (the "grep every caller" standing review question):
  `to_prose()` has exactly two callers, `cli.py`'s `_maybe_normalise` (text
  mode) and `cmd_from_json`. Tested both directly — flag 13 triggers
  correctly through `--from-json` too (see BACKLOG.md for the exact repro).
  `_looks_like_location`'s only caller is the one call site changed.

### BACKLOG.md: confirmed / refuted

- Confirmed live: both `linkedin.py` bugs described in PR #3's (unmerged)
  body were still present on `master` at commit `7699b72`, exactly as
  described. Now fixed and documented under "Shipped since the original
  review" — not the same entries as PR #3's, since this is independent
  re-verification, not a cherry-pick.
- Confirmed live: PR #4's `verify_institution` guard finding and PR #5's
  `name_matches` "not usable" guard finding are both still real on `master`
  right now (see mutation-testing section above and in BACKLOG.md). Both
  now pinned on `master` via this branch, independent of whether PR #4/#5
  ever merge.
- Did not re-verify any other BACKLOG.md entry tonight.

### Mutation-testing log (cumulative, for the "each of the four files" tracking)

| File | Dedicated sweep merged to `master`? | Where |
|---|---|---|
| `scoring.py` | Yes | direct commit `79f6cf8`, 2026-08-16 |
| `flags.py` | Yes | direct commit `d958ce0`, 2026-08-16 |
| `verify.py` | **No** — full sweep exists only on unmerged PR #4 | tonight's spot-check found and pinned 1 of its ~6 findings directly on `master` |
| `names.py` | **No** — full sweep exists only on unmerged PR #5 | tonight's spot-check found and pinned 1 of its ~4 findings directly on `master` |

Net effect: every file has now had *some* real, test-confirmed mutation
work land directly on `master` at least once, but `verify.py` and `names.py`
still haven't had the **full** sweep merged — that's sitting finished and
reviewable in PRs #4/#5, waiting on the merge queue above.

### What I learned

- **State drift compounds when PRs don't merge.** Three of tonight's
  "still open" backlog items (the two `linkedin.py` bugs, the `verify.py`
  guard) were already found, fixed, and tested by prior nights — the work
  wasn't missing, it was stuck in review. Re-doing it independently (rather
  than reading the stale branch and cherry-picking) cost real tonight-time
  that could have gone toward the still-fully-open core gap. The queue
  itself is now the single biggest lever on this repo's velocity, more than
  any individual finding.
- Confirming "is this still true on `master`" before touching anything paid
  off exactly the way the standing instructions intend: both `linkedin.py`
  bugs and both mutation-testing guards were BACKLOG-adjacent claims from
  unmerged branches that could easily have been stale by now (master moved
  a lot between 08-17 and today) — they weren't, but checking live instead
  of trusting the write-up is what makes that trustworthy.

### Where to pick up next

1. **Merge the PR queue** (human action, flagged above) — #3 needs conflict
   resolution first, #4/#5/#6 are clean. This is now more valuable than any
   single new finding: it unblocks two full mutation sweeps and a real
   institution-name bug fix that are all sitting finished.
2. **The real reverse path** (BACKLOG.md's top CRITICAL, still fully open):
   subject-anchored `Claims` + reconciliation, gated behind the OpenAlex
   affiliation/`years`-array corroboration work the standing brief
   describes. Still the single biggest lever in the codebase and still
   untouched by any night so far — every run including tonight has picked a
   smaller, more certain item instead. Worth a night with nothing else
   competing for the time slot.
3. Re-verify the OpenAlex/registry numbers in the task brief against a live
   request before anyone starts on (2) — they were last measured 2026-08-14
   and the brief itself says not to trust them indefinitely.
4. `linkedin.py`'s experience/education parsing and section-header handling
   still haven't had a *fresh* red-team pass since 2026-08-17 (PR #3) — only
   two previously-known bugs were re-verified tonight, not a new pass.
## 2026-08-25 (nightly run)

### ⚠ Open PR pileup, now five deep — for human visibility, not acted on

**Five `nightly/*` PRs are open, draft, and unmerged against `master`
right now**, the oldest dating back eight nights:

| PR | Branch | What it carries | State |
|---|---|---|---|
| #3 | `nightly/2026-08-17` | `linkedin.py` red-team fixes + `flags.py` mutation sweep | **`mergeable_state: dirty` — real merge conflict** |
| #4 | `nightly/2026-08-18` | `verify.py` mutation sweep (6 mutations, all real) | clean, CI green |
| #5 | `nightly/2026-08-19` | `names.py` mutation sweep (13 mutations, 4 real) | clean, CI green |
| #6 | `nightly/2026-08-23` | `DEGREE_RE` case-insensitivity fix + 4-file mutation spot-check | clean, CI green |
| #7 | `nightly/2026-08-24` | `linkedin.py` fixes (re-derived independently) + verify.py/names.py mutation pins | clean, CI green |

Read all five diffs in full before starting tonight's work, specifically to
avoid a third instance of what PR #6 and PR #7 both already flagged doing:
**re-deriving work that's already sitting finished on an unmerged branch.**
Worth stating plainly since it's now happened twice: PR #7 independently
re-fixed the exact two `linkedin.py` bugs PR #3 already fixed six nights
earlier (different test names, same root cause), and both PR #6 and PR #7
independently added near-duplicate `verify.py`/`names.py` pinning tests for
guards PR #4/#5's sweeps had already found. None of this is anyone doing
anything wrong — each run correctly checked "is this still true on
`master`" and found the answer was yes, because `master` never received the
unmerged fix — but it means real engineering time has now been spent
*three times* on some of the same handful of bugs, and will keep being
spent every night this queue stays unmerged. **This is no longer a minor
note: it is now the single biggest drag on this project's velocity**,
ahead of any individual BACKLOG.md finding. Tonight's response was to
deliberately pick a primary item with zero file overlap with any of the
five branches (see below) rather than add a sixth risk of duplication, and
to say this as plainly as possible here rather than repeat a softer
version of the same paragraph a fourth time.

### Running backlog tally (15 CRITICAL findings)

**9 [FIXED] / 1 [PARTIALLY FIXED] / 5 still open** — moved by one tonight.
Verified directly against `BACKLOG.md`'s own `## CRITICAL (15)` section on
`origin/master`'s current tip (`7699b72`) before writing this down: FIXED =
the institution-dead-code trio, GitHub/ClinicalTrials existence-vs-
attribution, GitHub-only-registry, ClinicalTrials-investigator-fields, the
surname-first-token fix, and **tonight's fix** (see below) = 9. PARTIALLY
FIXED = the non-Latin-script fold (transliteration variance still open) =
1. Still open = the core "one-way, claim-anchored funnel" finding and its
duplicate write-up further down, "zero registry reach on a realistic
prose profile" (both IN PROGRESS, not FIXED — see 2026-08-15/2026-08-16
entries above), "citing no identifiers disables the entire verification
half", and "`--verify` suppresses the 'nothing was checked' warning" = 5.

### What I did

**Primary item: "Any identifier appearing anywhere in the text is treated
as a personal authorship claim"** — a CRITICAL finding no run had
investigated before tonight (confirmed by grepping every prior NIGHTLY.md
entry and this file's own `[FIXED]`/`[IN PROGRESS]` annotations first), and
with zero file overlap with any of the five open PRs above, which was the
deciding factor in picking it over anything else on the list.

Confirmed live before touching anything, matching the entry's own
measurement exactly: `extract.py` captures a 60-character context window
around every DOI/ORCID/arXiv/patent match into `Claim.context`
(`_context()`, extract.py:171-174) but nothing in the codebase ever reads
that field (`grep -rn "\.context" larp_meter/` returns nothing outside its
own definition and construction) — `verify.py`'s `_attribute`, the single
shared tail for all four identifier types plus the GitHub-user branch,
decides VERIFIED/MISMATCH purely from whether the registry's author list
contains the subject's name, with no way to ask whether the subject's own
sentence was even claiming authorship. Reproduced the entry's own patent-
attorney example through the real dispatch path (stubbed Crossref, not
`run_audit`'s mock network layer): "I prosecuted US 9876543 for a client
in the sensor space. I was not the inventor on this work" came back flag
11 **TRIGGERED**, the tool's only floor-carrying flag, on a sentence that
explicitly disclaims the exact thing the flag accuses it of claiming.

Wrote four failing tests first (`tests/test_verify.py`,
`TestAttribution`), watched three of them fail against the unmodified
code (the fourth, a negative control with no disclaiming language, passed
immediately — confirming it wasn't a fixture bug), then fixed it: added
`_disclaims_authorship()`, a phrase-based guard checked at the top of
`_attribute`, before the existing subject-name/usable-names/match-is-None
branches. When `claim.context` carries an explicit third-party signal
("prior art", "cit-ed/ing/ation", "based/built/building on", "not the
inventor/author/credited/own", "client", "employer", "colleague",
"co-worker", "teammate", "on behalf of", "someone else's", "another's"),
the claim resolves to UNCHECKABLE — the same "existence recorded,
attribution not asserted" treatment `verify_github`'s repo branch and
`verify_nct` already give ownership-ambiguous artifacts, just reached via
context instead of by artifact type.

**Deliberately took the narrower of the two fix directions the BACKLOG
entry offered.** The entry's primary suggestion — require *positive*
first-person/possessive framing before any identifier counts as
attributable at all — would flip the tool's default behavior for the
ordinary case too: a CV that lists "Publications: 10.xxx, 10.yyy" under a
heading, with no "my"/"I" anywhere nearby, is the common shape of a
genuine bio, not a special case. Flipping the default there is a
materially larger, harder-to-fully-review change than fits in one night's
slot, and got explicitly deferred rather than rushed. Tonight's
deny-list-of-disclaiming-phrases approach is asymmetric on purpose: it can
only ever turn a would-be VERIFIED or MISMATCH into UNCHECKABLE, never the
other direction, so an evasive phrasing the guard fails to recognise costs
coverage (same as before tonight), never produces a false accusation. This
fixes the false-positive (honest citation punished) side of the finding;
it does not add new fraud-detection surface, and a fabricator who bare-
pastes a stolen identifier with no citation language at all is unaffected
— noted explicitly in BACKLOG.md so it isn't mistaken for more than it is.

### Verification

- Full suite: 417 → 421 tests, green throughout (after the fix, after each
  mutation below, and at the end).
- Regression-checked the fix cannot become a blanket downgrade: every
  existing hand-constructed `Claim(...)` in the test suite passes no
  `context=` kwarg at all (defaults to `""`), and `bool("")` is falsy, so
  none of them are touched by the new guard —
  `test_doi_without_disclaiming_context_is_still_checked_normally` pins a
  same-shape DOI claim with ordinary, non-disclaiming context and confirms
  it still resolves MISMATCH exactly as before.
- Ran the CLI end-to-end on two hand-written samples per the standing
  requirement, live against real Crossref/Google Patents (network was
  reachable this session):
  - **Clean**: a patent attorney's bio, explicitly stating "I was not the
    inventor on that filing — I drafted and prosecuted the claims on the
    client's behalf." Landed on INSUFFICIENT DATA (thin profile, expected)
    with flag 11 correctly **UNKNOWN** ("none could be attributed to the
    subject") and the claim ledger showing the patent **UNCHECKABLE** with
    the new guard's detail text — not TRIGGERED, which is what it returned
    before tonight's fix.
  - **Should-flag**: "Dr. John Smith... 40 years of published,
    peer-reviewed research", citing a real DOI (Markus Aspelmeyer's actual
    paper) with no disclaiming language anywhere. Flag 11 correctly
    **TRIGGERED**, claim status **MISMATCH** — confirms the fix does not
    blunt genuine fraud detection, only the false-accusation case it
    targets.
- Cross-boundary check (the standing "grep every caller" review question):
  the guard does not introduce a new possible value anywhere — `UNCHECKABLE`
  already existed and is already correctly handled by every downstream
  consumer (`flags.py`'s `f_contradicted`/`f_output`/`f_credentials`,
  `scoring.py`, `report.py`'s `CLAIM_ICON`), because `_attribute` already
  produced it from two other branches (no usable names, unanswerable name
  match) before tonight. This is a new *path* to an existing, already-
  tested outcome, not a new outcome type — a materially smaller blast
  radius than last cycle's `None`-handling bug, and confirmed by grep
  before relying on that claim rather than assuming it.

### Mandatory mutation-testing pass

Time-boxed, one hand-authored mutation each in `scoring.py`, `flags.py`
and `names.py` (verify.py's mutation-testing requirement was already met
by mutating and reverting tonight's own new guard in `_attribute` — see
"Verification" above, three tests failed, confirmed real). Picked lines
not called out in any prior night's sweep write-up, to avoid re-checking
the exact same guard a third time:

| File | Mutation | Result |
|---|---|---|
| `scoring.py` | `category_scores`'s `if r is None or r.status not in (...)`: `or` → `and` | **Caught** — 14 failures/errors |
| `flags.py` | flag 1/2's `if claimed not in dom.CREDENTIAL_GATED:` (both occurrences share this line; mutated the flag-1 instance): `not in` → `in` | **Caught** — 13 failures |
| `names.py` | mononym branch `if len(mine) == 1: return bool(present)` → `return True` | **Caught** — `test_mononym` (`Prince` vs `Madonna`) fails |
| `verify.py` | tonight's own `_disclaims_authorship(claim.context)` guard, deleted | **Caught** — 3 new regression tests fail |

All four caught, all four reverted and the full suite reconfirmed green
after each. No survivors tonight — a legitimate outcome, not a sign the
exercise wasn't done; see prior nights' sweeps for the boundaries these
mutations were deliberately picked to re-check (`category_scores`'
UNKNOWN-exclusion filter and the open-entry-field guard were both real
survivors when first swept on 2026-08-16/2026-08-17, so re-confirming
they're still caught tonight is meaningful, not redundant).

### What I confirmed in BACKLOG.md (evidence, not assertion)

- **CRITICAL "Any identifier appearing anywhere in the text is treated as
  a personal authorship claim" — CONFIRMED and FIXED.** Live repro matched
  the entry's own patent-attorney example exactly. Full before/after and
  the reasoning for the narrower fix direction recorded inline in
  BACKLOG.md.
- Did not re-verify any other BACKLOG.md entry tonight — this was a
  single, focused pick, not a fresh sweep.

### What I learned

- The PR pileup is now actively costing correctness-adjacent effort, not
  just tidiness: reading all five open diffs *before* picking tonight's
  item (rather than after) is what avoided becoming the third instance of
  re-deriving already-fixed work. Future nights should keep doing this
  read-first, and should weight "zero file overlap with every open PR"
  explicitly when choosing what to work on, the same way tonight did.
- `grep -rn "\.context" larp_meter/` returning literally nothing outside
  the field's own definition/construction was the single most useful
  confirmation step tonight — it turned "the BACKLOG entry says this field
  is dead" from an assertion to a directly-checked fact in about five
  seconds, and is worth reaching for early whenever a BACKLOG finding
  claims a field or return value is captured but never consumed.

### Where to pick up next

1. **The PR queue is now the top priority, ahead of any single finding.**
   Five open, unmerged `nightly/*` branches, one already conflicting. Every
   night this stays unmerged is measured, real, duplicated engineering
   effort — not a hypothetical risk any more, per the last three nights'
   independent re-discoveries of the same bugs. Strongly recommend a human
   merge pass (or an explicit decision to close/supersede the ones now
   fully covered by later independent fixes, e.g. PR #3's `linkedin.py`
   half looks superseded by PR #7's independent re-fix) before the next
   nightly run adds a sixth branch to the pile.
2. **The core gap is still fully open** — subject-anchored `Claim`s +
   reconciliation, gated behind the OpenAlex affiliation/`years`-array
   corroboration work the standing brief describes. Untouched again
   tonight; still the single biggest lever in the codebase, and every
   night's entry for the past two weeks has said the same thing. Worth a
   night with nothing else — including the PR-queue problem, once that's
   resolved — competing for the slot.
3. Re-verify the OpenAlex/registry constraints in the task brief against a
   live request before starting on (2) — last measured 2026-08-14, and the
   brief itself says not to trust them indefinitely.
4. Two CRITICAL findings remain genuinely untouched by any run:
   **"Citing no identifiers disables the entire verification half of the
   tool, including its only severity floor"** and **"`--verify` suppresses
   the 'nothing was checked' warning while performing zero checks"** — both
   read in full tonight while surveying the CRITICAL section, neither
   picked because tonight's slot went to the identifier-attribution
   finding instead. Both are well-scoped, both have a live repro already
   written in BACKLOG.md, and both look like reasonable single-night picks
   once the PR queue is under control.
## 2026-08-26 (nightly run)

### ⚠ Open-PR pileup — read this before doing anything else

**Six** `nightly/*` PRs are open and unmerged against `master`, dating back nine
days: #3 (2026-08-17, `linkedin.py` red-team + `flags.py` mutation sweep, base is
stale — predates the direct-to-master flags.py/scoring.py sweeps below), #4
(2026-08-18, `verify.py` mutation sweep), #5 (2026-08-19, `names.py` mutation
sweep), #6 (2026-08-23, `DEGREE_RE`/`re.I` institution-name fix), #7 (2026-08-24,
more `linkedin.py` fixes + mutation pins — a *re-fix* of bugs #3 already fixed,
because #3 never merged), #8 (2026-08-25, prior-art/citation disclaiming on flag
11). Every PR from #6 onward documents this same pileup and explicitly says not to
act on it beyond noting it — repeating that guidance here rather than touching any
of them. Separately: `master` itself moved directly (not via a nightly PR) between
2026-08-16 and 2026-08-17 with the flags.py/scoring.py mutation sweeps and the
flag 11/flag 13 fixes that BACKLOG.md's "Shipped since the original review"
section documents — this NIGHTLY.md file just never got a matching entry for
that work, which is why the log jumps from 08-16 straight to here. Recommend a
merge pass soon: this queue is now a bigger drag on velocity than any individual
finding, and #3/#7 already show what happens when it sits — independent re-fixes
of the same bugs that will collide at merge time.

### Backlog tally

BACKLOG.md CRITICAL: **9 [FIXED] / 1 [PARTIALLY FIXED] / 5 still open** (of 15) —
up from 8/1/6 last recorded here, because tonight's primary item closes one.
(This tally is `master`'s state only; the six open PRs each carry additional
fixes/pins of their own that aren't reflected until they merge — see above.)

### What I did

**Primary item:** fixed BACKLOG.md's CRITICAL "`--verify` suppresses the
'nothing was checked' warning while performing zero checks." Confirmed live
first, exactly as measured: a zero-identifier fabrication (no DOI/ORCID/GitHub/
arXiv/NCT/patent, no named institution) run with `--verify --name "..."` showed
`verified` in the header badge and *dropped* the tool's one "nothing here was
checked against an outside source" disclaimer, with `verifier_stats.api_calls ==
0`. `report['verified']` was set from the CLI flag alone (`audit.py`), never from
whether `verify_all` actually dispatched anything — and `verify_all`'s dispatch
is gated on `HANDLERS`, which a fabricator citing no identifiers trivially clears
by having nothing to check.

Fix: added a second field, `verification_effective` (`audit.py`) — true only when
at least one claim's status left `UNCHECKED` (equivalent to "at least one claim
had an identifier subtype `HANDLERS` recognises," computed as a side effect of
`verify_all` rather than by re-deriving `HANDLERS` membership in `audit.py`).
Deliberately *not* keyed on `verifier.calls > 0`: the verify.py disk cache
(30-day TTL) means a cache-hit run makes zero fresh HTTP calls while still
carrying a completely real, previously-fetched answer — using raw call count
would have manufactured a *new* false "nothing was checked" caveat on every
cache-warm re-run, trading one honesty bug for another. Status-based effectiveness
is cache-agnostic and, deliberately, still reads `True` on a pure network outage
(a dispatched claim that comes back `UNCHECKABLE` did get asked, it just couldn't
be answered) — that's a narrower, correctly-scoped claim than "the identifier
was confirmed," and conflating the two is exactly what `_attribute`'s three-way
split already exists to avoid elsewhere in this codebase.

`report.py` now derives the header badge from a new shared helper,
`_verification_label()` (three states — `unverified` / `verify attempted, 0
checked` / `verified` — used identically by the terminal, Markdown and HTML
renderers so the three can't drift), and gates the "own account" disclaimer on
`verification_effective` instead of the raw flag. `caveats()` gains an explicit
new line for the ineffective case, per the backlog entry's own suggested wording.
Left out on purpose (smaller, separate follow-up, not tonight's scope):
`verifier_stats` still isn't printed inline in the terminal — the new caveat line
covers the actual harm (an over-claiming badge), and surfacing the full stats
block is cosmetic by comparison.

**Cross-boundary check (per the standing review question):** grepped every
reader of `report["verified"]` — all five are in `report.py` (badge ×3, the two
caveat gates) — and the one place `cli.py` hand-builds a report dict without
going through `run_audit()` (the `--interactive` questionnaire mode, which never
calls the verifier at all). Added `"verification_effective": False` there too so
the dict shape stays complete, though `report.py` already reads every field via
`.get()` so this was defensive, not required to avoid a crash.

**Tests:** wrote 8 failing tests first in `tests/test_report.py` (2 errored —
`KeyError`/`AttributeError` — 3 failed on assertions; a couple confirmed the
badge-safe pre-fix cases before the fix, as negative controls), watched them fail
against the unmodified code, then implemented. Covers: the flag-alone case no
longer earns the disclaimer-suppressing badge; the genuinely-effective case still
suppresses it exactly as before (the other direction — guards against
over-correcting); the real end-to-end zero-identifier case through `run_audit`;
a claim that dispatches but hits a total network outage (`urllib.request.urlopen`
mocked to raise) still counts as effective, not a regression to the old
"nothing was checked" framing; and the three renderers all drop the plain
`verified` text under the ineffective case. 417 → 425 tests (see mutation log
below for the other 3).

**End-to-end CLI check**, `LARP_CACHE=<tmp> python3 larp-meter.py --text ... --verify
--name ...`, two hand-written samples:
- **Should-flag-as-ineffective:** the same zero-identifier "Dr. Marcus Vane"
  fabrication from the test suite. Landed GREEN 0/100 (the still-open core gap —
  expected, not a regression) with the badge now correctly reading `verify
  attempted, 0 checked`, and *both* honesty caveats present: "--verify ran but no
  claim carried an identifier any registry could resolve; 0 lookups were
  performed" and "Nothing here was checked against an outside source...". Before
  the fix, the second line was silently absent.
- **Should-verify-normally (regression check):** a profile citing a real DOI
  misattributed to a fake subject name, a real GitHub repo, and a real
  institution, run with live network access. Landed ORANGE 20/100, flag 11
  correctly TRIGGERED on the DOI mismatch, badge correctly reads plain
  `verified` (3/3 claims dispatched, one contradicted) — confirms the effective
  path is completely unchanged.

### BACKLOG.md: confirmed / refuted

- **Confirmed and fixed** (see above): "`--verify` suppresses the 'nothing was
  checked' warning while performing zero checks" — reproduced exactly as
  described, now `[FIXED]` in BACKLOG.md with the fix's specifics and what was
  deliberately left out.
- Did **not** investigate the core architectural gap ("Verification is a
  one-way, claim-anchored funnel" / its duplicates) or any other still-open
  CRITICAL tonight — tonight's item was scoped narrowly on purpose, see "Pick
  ONE primary item" below.

### Mutation-testing log

Mandatory per-cycle spot-check, one mutation in each of the four required files,
re-run against the full suite, reverted before the next:

| File | Mutation | Result |
|---|---|---|
| `scoring.py` | `coverage >= MIN_COVERAGE` → `coverage >` | **Caught** (pinned 2026-08-16) |
| `flags.py` | `if refuted or mismatched:` → `if refuted and mismatched:` | **Caught** (pinned 2026-08-16) |
| `verify.py` | `verify_institution`: `if wanted and wanted <= have:` → `if wanted <= have:` | **Survived** — real, unpinned on `master`. Same bug PR #4 already found; pinned here (`test_a_stopword_only_institution_claim_cannot_verify_against_any_hit`) rather than leave `master` exposed a second time. |
| `names.py` | `name_matches`: deleted `if not usable: return None` | **Survived** — real, unpinned on `master`, and specifically masked: every existing test pairs this path with a Latin-script subject, where the *separate* script-mismatch guard also returns `None` for the same input, so the guard under test could be doing nothing and nothing would notice. Un-masked with a non-Latin subject. Same bug PR #5 already found; pinned here (`TestZeroCandidatesIsUnanswerable`, both the discriminating non-Latin case and the masked Latin case, documented as such) rather than leave `master` exposed a second time. |

Plus the 2 mutations on tonight's own new code (`audit.py`'s
`verification_effective` computation, `report.py`'s disclaimer gate) — both
caught by the tests written for them, confirmed before those tests were kept.

**Result: 425 tests green.** `scoring.py` and `flags.py` remain fully protected
on `master` from the 2026-08-16 sweeps. `verify.py` and `names.py` now each have
one more real gap closed directly on `master` (their full sweeps still sit
unmerged in PRs #4/#5 — this was a one-mutation spot-check, not a substitute for
merging those).

### What I learned, worth keeping for future runs

- **Don't use raw `verifier.calls` as an "was verification effective" signal.**
  The disk cache means a cache-hit run makes zero fresh calls while carrying a
  completely real answer. Claim-status-based ("did anything leave `UNCHECKED`")
  is the cache-agnostic version of the same question and was the right choice
  here — worth remembering for any future work that wants to distinguish
  "attempted" from "answered."
- Crafting a realistic, zero-identifier, GREEN/YELLOW-landing fabrication text by
  hand for a test is fiddlier than it sounds — several attempts landed at
  INSUFFICIENT DATA (coverage just under 35%) before one cleared the threshold.
  Where the exact verdict tier doesn't matter for what's being tested, prefer the
  `TestCaveats` file's established pattern of injecting fields onto an existing
  fixture's report dict over hand-tuning new prose to hit a specific level.
- The open-PR pileup is now the single biggest risk to this repo's own
  bookkeeping being trustworthy: BACKLOG.md's "[FIXED]" tags and NIGHTLY.md's
  tally only reflect `master`, but real fixes for at least 4 more findings
  already exist on unmerged branches. A reader who only skims BACKLOG.md without
  checking `list_pull_requests` would underestimate how much is actually done.

### What the next run should pick up first

1. **The open-PR queue is the top priority for a human, not for an autonomous
   run** — flagging again rather than acting, per standing instructions. #4, #5,
   #6, #8 read as clean/independent; #3 and #7 overlap heavily (same
   `linkedin.py` bugs, fixed twice) and #7 is the more complete of the two.
2. The core architectural gap (subject-keyed probes + a real reconciliation
   step, per the OpenAlex research section near the top of this file) is still
   fully untouched by any run since 2026-08-15's narrow OpenAlex/Wikipedia
   signal-wiring slice. Every night's fabricated end-to-end test sample
   continues to demonstrate it live (tonight's zero-identifier "Dr. Marcus Vane"
   sample landed GREEN 0/100 again) — this remains the single highest-value,
   highest-risk piece of unbuilt work in the repo.
3. `verify.py`'s and `names.py`'s full mutation sweeps still only exist on the
   unmerged PRs #4/#5 — once those merge, `master` inherits full four-file
   coverage; until then, treat tonight's two spot-check pins as a stopgap, not
   a substitute.
## 2026-08-27 (nightly run)

### ⚠ Open-PR queue: seven unmerged `nightly/*` PRs, dating back to 2026-08-17

**Read this first.** `master`'s own copy of this file stops at 2026-08-16 —
everything below the line above is stale the moment you read it, because
every night since 2026-08-17 branched fresh from `master`'s tip (per the
standing instructions) and wrote its own NIGHTLY.md/BACKLOG.md updates onto
a branch that was never merged. `master`'s tip is still commit `7699b72`
(2026-08-17), and every one of PRs #3–#9 below is based on that exact same
commit — nothing has landed since. This is now the single biggest drag on
this project, worse than any individual backlog finding:

| PR | Branch | What it claims | State |
|----|--------|-----------------|-------|
| #3 | nightly/2026-08-17 | `linkedin.py` red-team (name/location bugs) + `flags.py` mutation sweep | open, draft, `dirty` (real merge conflict) |
| #4 | nightly/2026-08-18 | `verify.py` mutation sweep (6 mutations, all real) | open, draft, clean |
| #5 | nightly/2026-08-19 | `names.py` mutation sweep (13 mutations, 4 real) | open, draft, clean |
| #6 | nightly/2026-08-23 | `DEGREE_RE`'s `re.I` institution-name corruption fix | open, draft, clean |
| #7 | nightly/2026-08-24 | Independent re-fix of #3's two `linkedin.py` bugs (never having seen #3 merged) | open, draft, clean |
| #8 | nightly/2026-08-25 | "Citing prior art ≠ claiming authorship" (`_disclaims_authorship`) | open, draft, clean |
| #9 | nightly/2026-08-26 | `--verify` no longer silently erases the "nothing was checked" disclaimer | open, draft, clean |

Several of these are now independently duplicating each other's fixes
(#3/#7 both fix the same two `linkedin.py` bugs; #4/#6/#7/#9 have each
independently re-found and re-pinned the same `verify.py` guard — see
below) because each night correctly branched fresh from `master` rather
than stacking on unmerged work, but nobody has merged any of them in ten
days. **This is not something a nightly run can fix by pushing more
commits** — it needs a human merge pass, ideally oldest-first (or #4/#5/#6
first, since they're clean and #3 already has a real conflict to resolve
by hand). Every PR from #6 onward has already said this in its own
description; recording it here too so it can't be missed by anyone reading
NIGHTLY.md instead of scrolling the PR list.

Per the standing instructions, tonight's branch is cut fresh from
`master`'s tip regardless, and scoped to be small and touch nothing any of
the seven above are likely to conflict on (`flags.py`, plus test files).

### Running backlog tally (15 CRITICALs)

**8 [FIXED] / 1 [PARTIALLY FIXED] / 6 still open — unchanged by tonight.**
(Verified directly against `master`'s current BACKLOG.md, not carried over
by assumption: grepped `^### ` under `## CRITICAL (15)`, 8 carry `[FIXED]`,
1 carries `[PARTIALLY FIXED]`, matching every recent PR description's own
count.) Tonight's work is the core-gap's own named first slice plus a
mutation-testing pin — neither is one of the 15 named CRITICALs, so the
tally itself doesn't move; the two most relevant CRITICALs (the core gap,
and `--verify` no longer erasing its own disclaimer) both have real
progress sitting on unmerged branches (this entry's own core-gap slice, and
PR #9 respectively).

### What I did

**Primary item — the task brief's own highest-priority gap, smallest safe
slice:** made a genuine negative OpenAlex search result visible in the
report for the first time. Before tonight, `ctx.signals.get("openalex")`
could not tell "nobody ever asked" apart from "asked, and found nothing" —
both are falsy — so flag 6's "only unsourced assertions of output" message
for a bio like "Dr. Marcus Vane... has published extensively in peer-
reviewed venues" (BACKLOG's own motivating example) read identically
whether `--verify` ran a real search or not. Now it distinguishes the two
by checking whether `"openalex"` is a *key* in `ctx.signals` (always set
once `providers.OpenAlex.search` completes, even to `None`) rather than
just its value, and appends one hedged sentence — "An OpenAlex author-name
search for this subject found no scholarly record with any published
works — worth checking by hand, since name-based search can under-match
transliterated or diacritic name variants" — when that's genuinely true.
Status stays UNKNOWN always; this cannot push a verdict, only make an
existing UNKNOWN honest about what was actually checked. Full detail,
including the exact mutation-testing self-check that caught a weak
assertion in my own first-draft negative-control test, is in BACKLOG.md's
new "Flag 6: a genuine negative OpenAlex search becomes visible" entry.

Chose this over the two more obvious "smaller, more certain" options
(another `linkedin.py` red-team pass, another isolated mutation sweep)
because every single night since 2026-08-15 has deferred the core gap in
favour of something smaller and certain, and the brief is explicit that
this is the highest-value lever in the codebase. Kept it to the brief's own
recommended *smallest* slice (visibility, not a verdict) specifically so it
would still be small enough to finish, verify end-to-end, and land in one
sitting without the disambiguation groundwork (merged OpenAlex entities,
common-name collisions) the brief says a stronger verdict would need first.

**Secondary — mandatory per-cycle mutation-testing pass**, all four
required files:
- `names.py`: confirmed live that the `not usable` ("zero registry
  candidates") guard in `name_matches` is still unpinned on `master` — it
  was already found on the unmerged `nightly/2026-08-19` branch (PR #5),
  but that never merged, so master itself was exposed. Reverting the guard
  leaves the full suite green and turns `name_matches("Михаил Иванов", [])`
  from `None` (unanswerable) into `False` (reported mismatch) — and, per
  the fixture work below, this lands *exclusively* on non-Latin-scripted
  names, since a Latin-scripted subject's identical case is already caught
  earlier by the script-mismatch guard. Pinned directly on this branch (2
  new tests, one per script) rather than leave it unpinned a second time.
- `scoring.py` (`coverage >= MIN_COVERAGE` boundary) and `flags.py` (flag
  11's `if refuted or mismatched:`): both **caught** — the 2026-08-16/17
  direct-to-master sweeps are still holding, nothing further needed.
- `verify.py` (`verify_institution`'s `if wanted and wanted <= have:`
  guard): **confirmed still live and unpinned on `master`**. This is now
  independently re-found on four separate open PRs (#4, #6, #7, #9).
  Deliberately did **not** write a fifth copy of the same test — recorded
  the confirmation in BACKLOG.md instead. The actual fix here is merging
  any one of those four branches, not writing this test again.

### What I confirmed / refuted in BACKLOG.md

- **Confirmed** (live repro, not by reading the PR description): the
  core-gap CRITICAL's own "0 works found" scenario is real and, before
  tonight, produced byte-identical output whether or not `--verify` had
  actually run a search. Fixed the visibility half only, as described
  above.
- **Confirmed** (live repro): `names.py`'s "zero usable candidates" guard
  is real, still unpinned on `master`, and specifically asymmetric —
  non-Latin-scripted names only. Matches PR #5's independent description
  exactly.
- **Confirmed** (live repro): `verify.py`'s `verify_institution` "empty
  wanted set" guard is real and still unpinned on `master`. Matches PRs
  #4/#6/#7/#9's independent descriptions exactly — this is the fourth
  independent confirmation of the same finding, all from live reproduction
  rather than trusting the earlier write-ups.
- Did **not** re-verify any other BACKLOG.md entry tonight — in particular
  the 6 still-open CRITICALs beyond the core gap were not re-examined;
  don't assume they're still accurate without a fresh look.

### Mutation-testing log (files swept so far, by night)

- `scoring.py`: 2026-08-16 (12 mutations, 6 real, all pinned) — direct to
  `master`. Spot-checked again tonight (1 mutation), still caught.
- `flags.py`: 2026-08-16/17 (33 mutations, 13 real, all pinned) — direct to
  `master`. Spot-checked again tonight (1 mutation), still caught.
- `names.py`: full 13-mutation sweep done on the unmerged `nightly/2026-08-19`
  branch (PR #5) — **not yet on `master`**. Tonight added a targeted 1-guard
  pin directly to `master` (via this branch) for the specific survivor
  confirmed live; the other 3 real survivors PR #5 found are still only on
  that unmerged branch.
- `verify.py`: full 6-mutation sweep done on the unmerged `nightly/2026-08-18`
  branch (PR #4) — **not yet on `master`**. Tonight re-confirmed 1 of those
  6 (the `wanted`/`have` guard) live on `master`, still unpinned there.

**All four files now have had at least one real mutation-testing pass
somewhere** — but two of those passes (`names.py`, `verify.py`) exist only
on unmerged branches, so `master` itself is only fully covered for
`scoring.py` and `flags.py`. This won't change until the queue above gets a
merge pass.

### What I learned

- The single biggest thing blocking progress right now is not a missing
  fix — it's an unmerged-PR queue. Four different survivors of the exact
  same `verify.py` guard have now been independently rediscovered by four
  different nightly runs because none of the branches carrying the fix
  ever merged. Depth-first, small-and-independent nightly branches are the
  right call per the standing instructions, but they only work if
  something eventually merges them; ten nights of unmerged, non-conflicting
  work is nearly as bad as ten nights of no work, plus the wasted
  rediscovery effort.
- `evaluate()`'s per-flag exception guard (found and pinned back on
  2026-08-16/17) has a real, mildly annoying side effect for anyone writing
  a mutation-testing pinning test: a broken guard that would otherwise
  raise `KeyError` instead silently becomes a generic "evaluator error:
  ..." UNKNOWN, which can slip past a loosely-worded assertion
  (`assertNotIn` on a substring) without anyone noticing the test wasn't
  actually discriminating. Worth remembering for future mutation-testing
  work in this file: prefer exact-matching the expected message over
  substring checks when the fallback path could itself produce a
  similar-looking string.

### What the next run should pick up first

1. **This is now explicitly a human-merge-queue problem, not a code
   problem.** If you're an autonomous run reading this with no merge
   access, the single highest-value thing you can do is keep tonight's
   branch small and independent (as this one was) and make the queue's
   existence impossible to miss (as this entry tries to do) — not attempt
   to resolve PR #3's conflict yourself or merge anything, since merging is
   this project's deliberate human-in-the-loop gate.
2. **The core gap, continued**: items (1) and (3) of its fix direction are
   still fully open — OpenAlex/Crossref hits need to become derived
   `Claim`s with provenance (not `signals` dicts), and a reconciliation
   step needs to exist that can produce an actual `CONTRADICTED` status for
   a quantitative mismatch. Read the task brief's OpenAlex constraints
   section again before starting (re-verify live if it's been a while —
   rate limits and response shapes change): the disambiguation groundwork
   (merged entities, common-name collisions, the `years`-array corroboration
   signal) has to come before any verdict stronger than the UNKNOWN-with-
   evidence line this cycle added.
3. `linkedin.py` red-team: PR #3 and PR #7 both independently did a first
   pass and found the same two bugs — once the queue clears, check whether
   a third, fresh pass turns up anything neither of them caught.

---

## 2026-09-12 (nightly run)

### ⚠ Open-PR queue — read this first: TEN unmerged `nightly/*` PRs, sixteen days and counting, zero merges since 2026-08-27

`master`'s tip is still `9f71c98` (the 2026-08-27 merge). Every entry in this file after that point — 2026-08-30 through 2026-09-11, ten nights in a row — exists only on its own unmerged branch:

| PR | Branch | What it claims |
|----|--------|-----------------|
| #11 | `nightly/2026-08-30` | Flags an OpenAlex "best" pick that's likely a merged entity (core-gap disambiguation groundwork) |
| #12 | `nightly/2026-08-31` | An ordinary CV was mistaken for a LinkedIn paste and silently lost content |
| #13 | `nightly/2026-09-01` | Confidential and pre-revenue work is not deception |
| #14 | `nightly/2026-09-02` | A word-wrap can hide a denial from `is_negated` |
| #15 | `nightly/2026-09-03` | A fixed-width context window clipped a disclaiming phrase far from its identifier |
| #16 | `nightly/2026-09-04` | A self-applied doctoral title in lowercase or all-caps was invisible to flag 13, plus a pinned ROR nearest-name tie-break mutation survivor |
| #17 | `nightly/2026-09-08` | A current student's own study dates read as a fabricated future claim |
| #18 | `nightly/2026-09-09` | Mutation-testing sweep + a correction to a stale claim in this file |
| #19 | `nightly/2026-09-10` | The "own account" caveat only credited Wikipedia, never a genuine OpenAlex hit |
| #20 | `nightly/2026-09-11` | A truthful career read as impossible when only its most recent role was dated (timeline fairness fix, part a) |

This is unchanged in kind from every entry since 2026-08-27, and the 2026-09-11 entry already escalated this directly to the human maintainer with a push notification. Tonight's run did **not** send a second one for the same standing fact — nothing about the queue itself is new tonight beyond "+1 PR, +1 day," and repeating an identical alert nightly is exactly the kind of noise that makes a real one easier to miss. If the queue reaches a genuinely new threshold (a merge conflict actually appears, CI starts failing, or it goes untouched for another week+), that would be worth a fresh one — plain accumulation is not.

Tonight's own branch (`nightly/2026-09-12`) is cut fresh from `master`'s tip regardless, per standing instructions, and touches `larp_meter/flags.py`, `larp_meter/verify.py`, `tests/test_flags.py`, `tests/test_verify.py`, `README.md` and `BACKLOG.md`. Of the ten open PRs, only #16 also touches `larp_meter/flags.py` and `tests/test_flags.py` (title-inflation work, different flag) and only #15 also touches `larp_meter/verify.py` (context-window clipping, different function) — checked against each PR's own file list; overlap exists but at the file level only, not the same lines, so this is a merge-conflict question for whoever merges, not a reason to have picked a different area.

### Running backlog tally (15 CRITICALs)

**10 [FIXED] / 1 [PARTIALLY FIXED] / 4 still open — unchanged by tonight**, recounted directly against `master`'s current `BACKLOG.md` (`awk`'d the `## CRITICAL (15)` section and grepped `^### `), matching every recent entry's own count. Tonight's fix is filed under a MAJOR entry (and its MODERATE duplicate), not one of the 15 CRITICALs, so the tally itself doesn't move. The 4 still-open CRITICALs remain the core one-way/claim-anchored funnel finding and its three near-duplicate write-ups from the original five-lens review.

### What I did

**Primary item:** fixed BACKLOG.md's "ROR absence is scored as a triggered credential flag despite the code's own disclaimer" (MAJOR) and its MODERATE duplicate ("ROR-only institution checking produces false positives against real non-research schools") — chosen from the "audit for fairness" lens: it directly punishes an honest person for their institution's ROR-indexing status, which is exactly the kind of fairness gap the task brief calls out, it was still fully unverified going into tonight, and it touches `flags.py`/`verify.py`, files none of the ten open PRs' *lines* actually overlap.

Confirmed live before writing anything, against ROR's real API (not from docs, which understate this): ran `verify_institution` on six real institutions with the exact shape BACKLOG's evidence names — Rotterdam School of Management, London Guildhall University (merged into London Metropolitan in 2002), École Supérieure d'Électricité/Supélec (merged into CentraleSupélec in 2015), Karachi Grammar School, Yeshiva Torah Vodaath, École 42 — **all six returned NOT_FOUND**, and `f_credentials` TRIGGERED flag 8 on every one of them at full weight. Then checked whether the token-overlap ROR itself offers against its nearest candidate could distinguish these from a genuinely fabricated name: it cannot. The six real institutions overlap their nearest ROR hit at 0.25-0.67 (Rotterdam School of Management 0.50, London Guildhall 0.67, Supélec 0.50, Karachi Grammar School 0.67, Yeshiva Torah Vodaath 0.25, École 42 0.33); a fabricated "Institute of Advanced Fictional Studies" overlaps its nearest hit at **0.75** — higher than four of the six real institutions. Also confirmed ROR's search endpoint essentially never returns zero raw results for any institution-shaped query (even "Xzqvwlmp Institute of Zzyzxian Studies" returns 32,195 hits), so the `body`-empty NOT_FOUND branch is nearly dead code in practice; almost every miss, real or fabricated, falls into the same "items exist, none fully match" path this measurement covers. This settles BACKLOG's own two-option fix direction in favour of the first: there is no overlap threshold that catches invention without also accusing real institutions, so a ROR miss must not accuse at all.

Fixed `f_credentials` (`larp_meter/flags.py`): a ROR NOT_FOUND on a `degree_institution` claim now returns UNKNOWN with an advisory note instead of TRIGGERED. This is a genuine narrowing of the flag's power, not a wording change — flag 8 can no longer TRIGGER via this path at all, and I judged that acceptable and correct given the overlap evidence above, consistent with this project's stated governing rule ("when a registry cannot settle a question the answer is UNCHECKABLE, never an accusation" / "prefer missing a fraud to accusing an innocent").

While investigating, also found and fixed the "inverse looseness" BACKLOG's own evidence bullet named as the other half of the same measurement: `_ORG_STOPWORDS` in `larp_meter/verify.py` listed **"universite"** (the accent-stripped form of "université") as a word carrying no identifying information, so a claim like "Universite Paris Sud" reduced to just `{paris, sud}` — trivially a subset of ROR's unrelated "Geosciences Paris Sud" (a research unit, not a university). Every other language's word for university/institute/school already folds to a common stem via `_ORG_STEMS` instead of being discarded (this file's own header comment says so); "universite" — and the already-dead, encoding-mismatched "università" entry beside it (it never matched because the stopword set held the pre-composed accented form while `_significant_tokens` NFKD-strips accents before comparing, so it silently did nothing) — were the sole exceptions. Removed both. Live-reconfirmed the fix: "Universite Paris Sud" no longer verifies against "Geosciences Paris Sud," and a genuine "Universite Paris-Saclay" claim still verifies correctly against ROR's real "Université Paris-Saclay" record.

**Deliberately left open:** the other example in that same evidence bullet, "Le Wagon" → VERIFIED as "Health Wagon," is a different mechanism (a single-significant-token institution name after generic-word stripping trivially satisfies the subset test against anything sharing that one word) and was not fixed tonight, to keep scope to the bug the night's evidence actually demonstrated. Documented as the natural next pick-up in BACKLOG.md, with a concrete candidate fix (`len(wanted) >= 2` for a subset-match VERIFIED) and a note on what was and wasn't checked about it.

Regression tests, written first and confirmed to fail against the pre-fix code:
- `tests/test_verify.py::test_a_non_english_word_for_university_is_not_discarded_as_a_stopword` (fails pre-fix: status VERIFIED; passes post-fix) + a paired positive control `test_a_genuine_non_english_university_name_still_verifies` (already passed both before and after — proves the fix doesn't overcorrect into refusing genuine French-named universities).
- `tests/test_flags.py::test_a_verified_ror_miss_is_a_lead_not_an_accusation` — replaces the old `test_credential_flag_triggers_on_a_verified_ror_miss`, which pinned the now-recognized-as-wrong TRIGGERED behavior on the exact same fixture; updated rather than deleted, with a docstring explaining why the old expectation was the bug. Paired with `test_an_unchecked_institution_is_not_reported_as_a_ror_miss`, confirming the adjacent UNCHECKED path (never verified, or this claim never reached the verifier) still reads as "not itself checked," not as a registry miss — this preserves the original test's mutation-guard intent (NOT_FOUND vs. UNCHECKED must stay distinguishable) even though neither path can TRIGGER anymore.

**Mandatory end-to-end pipeline check:** ran `larp-meter.py --file ... --name ... --verify` directly (not just unit tests, and not stubbed — a real network call against the live ROR API, confirmed via `verifier_stats.api_calls: 1` on a cold cache) on two hand-written samples. An honest supply-chain-leadership bio naming an MBA from Rotterdam School of Management now reads flag 8 UNKNOWN ("has no exact match... not itself evidence of fabrication") instead of TRIGGERED. A hand-written fabricator bio (PhD from "the Institute of Advanced Fictional Studies," buzzword-heavy, fundraising with no traction, logo-wall partnerships) still lands ORANGE overall — flags 6, 7 and 10 correctly TRIGGERED on the *other*, more reliable signals (no checkable output, fundraising without traction, zero independent validation), confirming this fix narrows flag 8 specifically without making the tool blind to an actual fabrication built from multiple weaker tells.

**Cross-boundary check (per the standing review question):** `f_credentials`'s return type and signature are unchanged (still `FlagResult` with the same three statuses); only the status chosen for one specific input shape changed, from TRIGGERED to UNKNOWN. Grepped every consumer: `evaluate()`/`scoring.py` read `.status` generically across all flags, with no special-casing on flag 8's identity or text; flag 11 (the only flag with a floor) is unrelated to flag 8 and reads only `ctx.claims` directly, not flag 8's result; no test or code anywhere pattern-matches on the old "Named institution has no match" string (grepped for it — only this file's own history and BACKLOG.md still quote it, both already updated). Updated README.md's flag-8 table row and the flag-11 paragraph, which both described the old TRIGGERED behavior in prose.

**Mandatory per-cycle mutation-testing pass**, one mutation in each of the four required files, run against the full suite, then reverted:

| File | Mutation | Result |
|---|---|---|
| `scoring.py` | `scored = coverage >= MIN_COVERAGE` → `>` | **Caught** (`test_coverage_exactly_at_min_coverage_is_still_scored` failed) |
| `names.py` | `name_matches`'s `if len(present) >= 2:` → `>= 3` | **Caught** (18 failures + 5 errors) |
| `flags.py` | `f_experience`'s `if claimed not in dom.CREDENTIAL_GATED:` → `in` | **Caught** (`test_experience_flag_catches_domain_gap` failed) |
| `verify.py` | `verify_institution`'s ROR nearest-name tie-break: `if overlap > best_overlap:` → `>=` | **SURVIVED — pinned tonight, see below** |

The `verify.py` survivor is the same one `nightly/2026-09-04` (PR #16) first found and pinned, and `nightly/2026-09-09`/`2026-09-10`/`2026-09-11` each independently re-confirmed live and declined to re-pin, citing the 2026-08-27 entry's precedent ("the actual fix here is merging, not writing this test again"). That precedent has now held for over five independent re-confirmations across three weeks with zero merges, so tonight broke from it: pinned directly on `master` via this branch (`tests/test_verify.py::test_nearest_name_tie_break_is_deterministic_not_last_writer_wins`), on the reasoning that "wait for the merge" has demonstrably stopped being a plan and a five-line test costs nothing to add now regardless of when or whether PR #16 eventually lands. Confirmed the test fails against the mutation (reports "Beta" — the *second*, not first, of two tied candidates) and passes against the restored code (reports "Alpha," the first-seen tied candidate, deterministically). Also mutation-tested tonight's own two new production lines directly (forcing `f_credentials`'s new UNKNOWN branch condition to always/never fire, and forcing `_ORG_STOPWORDS` to still contain "universite") — both caught by the new tests above.

Full suite: 473 → 477 tests (test_flags.py: 1 test replaced, 1 new, net +1; test_verify.py: +3 new), green throughout every step.

### What I confirmed / refuted in BACKLOG.md

- **Confirmed live, fixed**: "ROR absence is scored as a triggered credential flag despite the code's own disclaimer" (MAJOR) — reproduced exactly as described against the real ROR API, with concrete overlap numbers the original entry didn't have (0.25-0.67 for real institutions vs. 0.75 for a fabricated one), which settled the fix-direction choice. Filed in-place as `[FIXED]`.
- **Confirmed live, fixed as a side effect**: "ROR-only institution checking produces false positives against real non-research schools" (MODERATE duplicate, the Le Cordon Bleu example) — same root cause, same fix. Filed as `[FIXED]`, noting the Wikidata P31 cross-check idea in its fix direction remains unbuilt (would let flag 8 positively credit non-research institutions rather than just stop accusing them).
- **Confirmed live, NOT fixed tonight**: the "inverse looseness" evidence bullet's other example, "Le Wagon" → VERIFIED as "Health Wagon" — a distinct single-token-name mechanism, documented as a follow-up with a concrete candidate fix.
- **Re-confirmed live, now pinned rather than re-described**: `verify.py`'s ROR nearest-name tie-break survivor (see mutation-testing table above) — matches PR #16/#18/#19/#20's independent descriptions exactly; this time pinned on `master` instead of re-deferred.
- **Re-confirmed live**: the CRITICAL tally (10/1/4 of 15) is unchanged, counted directly rather than carried forward from a prior entry's claim.
- Did not re-verify anything else in BACKLOG.md tonight, including the 4 still-open CRITICALs or any other MAJOR/MODERATE/MINOR entry.

### Mutation-testing log (files swept so far, by night)

- `scoring.py`: full sweep 2026-08-16 (merged). Spot-checked again tonight (fresh line, `MIN_COVERAGE` boundary) — still caught.
- `names.py`: full sweep 2026-08-19 (merged). Spot-checked again tonight (fresh line, `present`-count threshold) — still caught.
- `flags.py`: full sweeps 2026-08-16/17 (merged). Spot-checked again tonight (fresh line, flag 2's `CREDENTIAL_GATED` membership test) — still caught. Tonight's own new flag-8 branch also mutation-tested directly and caught.
- `verify.py`: full sweep 2026-08-18 (merged) plus several later spot-checks. Tonight: the long-standing ROR nearest-name tie-break survivor (first found 2026-09-04) **pinned on `master` for the first time**, breaking a three-week pattern of re-confirm-and-defer. Tonight's own new `_ORG_STOPWORDS` change also mutation-tested directly and caught.

### What I learned

- ROR's fuzzy search is essentially an OR over words, not an AND: it returns tens of thousands of results for almost any institution-shaped query, real or invented (measured: a purely gibberish query is the only kind that returns zero). That means the "registry returned nothing at all" signal BACKLOG's fix direction implicitly hoped for barely exists in practice — nearly every miss, real or fake, resolves to "items exist, but none fully match," which is why a threshold on token-overlap can't separate the two: I measured the overlap distribution directly (0.25-0.75 across both real and fabricated cases) rather than assuming a threshold would work, and it doesn't. Worth remembering before anyone reaches for "just tune the threshold" on this signal again — the fix has to be architectural (stop trusting the signal to accuse) rather than numerical.
- A stopword list and a stemming table encoding the *same kind* of transformation (both exist to fold institution-type words across languages/spellings) are easy to end up with contradictory entries in, silently, because nothing enforces that a word can only go through one of the two paths — "universite" going through the stopword path defeated the entire point of the stem table existing for it. Worth a structural note for whoever next touches `_ORG_STOPWORDS`/`_ORG_STEMS`: an assertion that no stem-table prefix also appears literally in the stopword set would have caught this at import time instead of needing a live API call to surface it.
- Breaking a "don't duplicate, the fix is merging" precedent that five separate nights had each independently upheld felt like the right call specifically because it had already run its course (three weeks, zero merges, a five-line cost) — but it's worth flagging explicitly for whoever reads this next, in case there's a reason (visibility into an in-progress human review, say) that this run couldn't see. If the human maintainer *is* actively working through the queue and this test ends up duplicated in a merged PR #16, that's a trivial conflict to resolve, not a real cost.

### What the next run should pick up first

1. **The open-PR queue — ten deep, sixteen days, zero merges.** Still not a nightly run's call to fix by pushing code; already escalated via notification on 2026-09-11 and not re-escalated tonight per the reasoning above. If it reaches a new threshold (a real conflict, a CI failure, another week-plus of silence) that would justify a fresh one.
2. **Le Wagon-shaped single-token institution false positives** (this entry's "deliberately left open" item above) — concrete candidate fix already sketched in BACKLOG.md's now-`[FIXED]` entry: require `len(wanted) >= 2` for a subset-match VERIFIED, checked against the existing test suite's institutions (all produce 2-3 tokens) but not against real short-named institutions generally.
3. **The core gap, continued** — unchanged from every entry since 2026-08-15. Items (1) and (3) of its fix direction (derived `Claim`s with provenance from OpenAlex/Crossref, and a reconciliation step) are still fully open. Re-verify the OpenAlex rate-limit/response-shape numbers live before extending that work if it's been a while — they change.
4. A structural guard for `_ORG_STOPWORDS`/`_ORG_STEMS` (an import-time assertion that no stem prefix also appears as a literal stopword) would have caught tonight's "universite" bug without needing a live API call — worth adding if someone is back in this file.
