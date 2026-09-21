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

## 2026-08-30 (nightly run)
## 2026-08-31 (nightly run)

### Open-PR check (do this first, every night)

`git fetch origin` + a live PR search against `rayane1817/larp-meter`:
**no open `nightly/*` PRs.** `master`'s tip is `9f71c98` ("Merge
nightly/2026-08-27: surface a genuine negative OpenAlex search on flag 6")
— exactly the seven-PR merge queue the 2026-08-26/27 entries flagged
(#3–#9) is now fully merged, in commit order, onto `master`. Good news for
the human-in-the-loop bottleneck those two entries called the single
biggest drag on the project; nothing further needed from a nightly run on
that front.

**Gap in this log:** there are no 2026-08-28 or 2026-08-29 entries here,
and no commits on `master` between the 2026-08-27 merge and tonight —
whatever happened those two nights (if anything), it isn't reflected in
git history or this file. Not something to chase down or explain away;
just flagging the gap so nobody reading this assumes continuity that
isn't there. Branched fresh from `origin/master`'s tip (`9f71c98`) for
tonight's work, per the standing instructions, regardless.

### Running backlog tally (15 CRITICAL findings)

**10 [FIXED] / 1 [PARTIALLY FIXED] / 4 still open** — re-counted directly
against `BACKLOG.md`'s `## CRITICAL (15)` section on `origin/master`'s
current tip (not carried over by assumption): grepped every `### ` header
under that section, 10 carry `[FIXED]`, 1 carries `[PARTIALLY FIXED]`. This
is genuinely better than the 8/1/6 last recorded in this file (2026-08-19)
— the merge queue clearing brought real, previously-unmerged fixes onto
`master`, including "Any identifier appearing anywhere in the text is
treated as a personal authorship claim," which no run had investigated as
of 2026-08-19 and is now `[FIXED]`. The 4 still open are the core
architectural gap (top CRITICAL) and its three near-duplicate write-ups
further down the file — all one and the same finding. Tonight's own work
(below) doesn't close any of the 4; it's filed under BACKLOG.md's "Shipped
since the original review" section instead, matching the convention every
recent entry has used for mutation-testing sweeps and incremental core-gap
slices that aren't themselves one of the 15 original findings.

### What I did

**Primary item:** the first actual piece of the core gap's own named
disambiguation-groundwork prerequisite ("do the affiliation/`years`-array
corroboration work first"), which every entry since 2026-08-15 has pointed
at as blocking and none had started. `providers.OpenAlex.search` picks
`best` among several name-matched candidates purely by `works_count`
plurality — the task brief's own research calls this actively dangerous,
since a merged entity (several real researchers sharing a name, collapsed
into one OpenAlex author ID by the name-matching pipeline OpenAlex itself
runs) typically has a *higher* works_count than any single real person, so
plurality prefers the merged record over a genuine one.

Re-verified the brief's headline example live against the real API before
writing any code, per the standing instruction not to trust the brief's own
numbers indefinitely: `GET /authors/A5100391883` ("Wei Wang") today lists
**873** affiliations (up from 863 when the brief was last measured) across
education, healthcare, government and company institutions in at least
China and the US — confirms the merged-entity problem is exactly as real
as described, with fresh numbers. Also found something not in the brief:
`GET /authors?search=...` — the endpoint `providers.py` actually calls —
is hitting OpenAlex's own USD rate limiter with **`$0` remaining for the
rest of today** in this environment (`dailyRemainingUsd: 0`, `retryAfter`
~21.8h), and even a bare `/authors?per_page=1` with no search term now
costs money. The free singleton `/authors/{id}` and `/autocomplete/authors`
endpoints are unaffected (`cost_usd: 0.0` on autocomplete, confirmed live)
and were the only OpenAlex calls this session could actually make today.
This didn't block tonight's change — implemented and tested entirely
against stubbed fetch responses, this project's own established
convention, with no live-search dependency — but it's a concrete, current
data point for whoever extends this next: prefer the free
singleton/autocomplete endpoints over the costed `/authors?search=` list
endpoint wherever the design allows it, and don't assume `/authors?search=`
is reliably reachable for a live end-to-end check on any given night.

Added `providers._affiliation_institution_count()`: counts distinct
institutions from the full `affiliations` array (`{institution, years}`
pairs, richer than the handful summarised in `last_known_institutions`),
falling back to `last_known_institutions` if `affiliations` is absent
(defensive — not independently confirmed present on the *list* endpoint's
response today, only on the singleton, because of the rate limit above).
`best` now carries `institution_count` and a `merge_risk` boolean
(`institution_count >= 15` — comfortably above a well-travelled genuine
career, comfortably below the 873 a merged entity actually shows).

**Deliberately does not change which candidate `best` picks, and cannot
produce a new TRIGGERED anywhere.** Flag 6 (`f_output`) still returns
PASSED on any real record exactly as before — existence of a record is
still real, if weak, corroboration, merged entity or not. The only change:
a `merge_risk` record's PASSED evidence text now names the institution
count and warns it may blend several careers, so a human reading the
report knows not to lean on "OpenAlex found a huge record" as strong
personal corroboration. This is the narrowest usable slice of the
disambiguation groundwork — real infrastructure now exists in
`ctx.signals["openalex"]` for a future reconciliation step — without itself
attempting reconciliation, a new verdict, or changing which candidate gets
picked as `best` under merge_risk (that's a separate, larger design
question, left for whoever picks this up next).

**Verification, TDD throughout:** wrote all tests first, watched every one
fail against the unmodified code (`KeyError`s for the missing signal keys,
plain assertion failures for the missing evidence text), then implemented.
5 new tests in `tests/test_providers.py` — including an exact `>=` boundary
pin at 14 vs. 15 institutions, since this repo's flags.py mutation sweeps
have repeatedly shown a threshold with nothing sitting exactly on the cut
survives a `>=`/`>` inversion silently. 2 in `tests/test_flags.py` — the
caution appears on a merge-risk signal, stays absent on an ordinary one,
including a fixture using the pre-tonight signal shape (no
`institution_count`/`merge_risk` keys at all) to pin that every existing
caller keeps working unchanged. 1 true end-to-end test in
`tests/test_cli_registry_wiring.py`, using the real raw JSON shape (an
`affiliations` array, not a hand-summarised dict) through the actual
`cmd_text` pipeline — per this repo's standing lesson (the ROR/HANDLERS
dead-code bug and, one layer up, the `_attribute`/`None` bug from
2026-08-16), a flags.py-only test proves nothing about whether the real
`OpenAlex.search` → `ctx.signals` → flag pipeline actually produces this
shape. 473 → 480 tests, green throughout, run after every step not just at
the end.

Mutation-tested the new code directly, each mutation applied, suite run,
then reverted before the next: inverted `>=` to `>` in the merge_risk
threshold (caught only by the new boundary test — every other test sat
comfortably off the cut); deleted the `merge_risk` gate in `flags.py`'s
caution text (caught by both the flags.py unit test and the end-to-end
test); dropped the `affiliations`-array branch in
`_affiliation_institution_count`, forcing the `last_known_institutions`
fallback unconditionally (caught by two tests, including the boundary
test, since `last_known_institutions` never carries enough entries to
cross 15). All three caught, all reverted, suite confirmed green again
after each revert.

**Required end-to-end CLI check** (mandatory after touching
`providers.py`/`flags.py`): ran the real `larp_meter.cli.main()` — not just
test-harness function calls — with a stubbed fetcher, on two hand-written
samples. A clean, honest researcher with a genuinely small
single-institution OpenAlex record: flag 6 PASSED, plain evidence text, no
caution — byte-identical to pre-tonight behavior. A "Wei Wang"-shaped
merged record (30 synthetic institutions): flag 6 PASSED, now with the
institution-count caution appended to the evidence text, exactly as
designed. Both samples landed INSUFFICIENT DATA overall (thin bios, as
expected for a short hand-written fixture) — confirms the change doesn't
manufacture coverage or move a verdict in either direction, only qualifies
an existing PASSED's evidence text.

**Mandatory per-cycle mutation-testing spot-check**, one mutation in each
of the four standing files, full suite run after each, reverted before the
next — all four **caught**, confirming `master` is still fully protected on
all four fronts after the merge queue landed:

| File | Mutation | Result |
|---|---|---|
| `scoring.py` | `coverage >= MIN_COVERAGE` → `coverage >` | **Caught** |
| `flags.py` | `if refuted or mismatched:` → `if refuted and mismatched:` | **Caught** |
| `verify.py` | `verify_institution`: `if wanted and wanted <= have:` → `if wanted <= have:` | **Caught** — previously only pinned on the (then-unmerged) PR #4/#9 branches; confirmed the merge brought the pinning test onto `master` too. |
| `names.py` | `name_matches`: deleted `if not usable: return None` | **Caught** — same note as `verify.py`: previously only pinned on unmerged branches, now confirmed live on `master`. |

### BACKLOG.md: confirmed / refuted

- **Confirmed live, with fresh numbers** (not from the brief's own older
  measurement): the "Wei Wang" merged-entity example (`A5100391883`) is
  still real today, now at 873 affiliations (was 863). Recorded in
  BACKLOG.md's new entry under "Shipped since the original review."
- **New finding, not previously documented anywhere in this repo**:
  OpenAlex's `/authors?search=` list endpoint is USD-rate-limited to $0
  remaining for the rest of today in this environment, while the free
  singleton `/authors/{id}` and `/autocomplete/authors` endpoints are
  unaffected. Recorded for whoever extends this work next — see "What the
  next run should pick up first" below.
- Re-counted the CRITICAL tally against `master`'s current BACKLOG.md
  (10/1/4, up from the 8/1/6 last recorded here) — a re-count reflecting
  the merge queue clearing, not new verification work on any individual
  finding. Did not re-open or re-verify any of the 10 `[FIXED]` or 4
  still-open findings beyond the top one (the core gap, addressed above).

### What I learned

- The seven-PR merge queue that dominated the last four entries in this
  file is resolved. Whatever most recently merged it did so in commit
  order (`972165c` through `9f71c98`, matching PR #3 through #9's dates
  exactly) without leaving any visible conflict debris in the log — worth
  noting as a healthy outcome given PR #3 was flagged `dirty` (a real merge
  conflict) as of 2026-08-27.
- OpenAlex's rate-limit posture for anonymous/no-key traffic keeps getting
  stricter over the roughly two weeks this project has been checking it
  live (per-search USD billing was already true in the brief; today even a
  bare unfiltered list call costs money, and this environment's daily
  budget was already exhausted before this session's own first call). Any
  future work extending the reverse-path/OpenAlex integration should
  design for "list search may be completely unavailable on any given
  night" as the normal case, not the exception — the free singleton and
  autocomplete endpoints are the more dependable foundation.
- Re-confirmed the project's own established pattern still holds:
  affiliation-array shape (`{institution, years}` per entry) is exactly as
  the brief described it, live, on the singleton endpoint. Did not get to
  independently confirm the *list* endpoint returns the identical shape
  (blocked by today's $0 budget) — the code defensively assumes it does
  and falls back if not, but this is worth a live check on a night when
  the search budget resets, rather than treating tonight's assumption as
  settled fact indefinitely.

### What the next run should pick up first

1. **The core gap, continued**: `best` is still chosen by works_count
   alone even when `merge_risk` is true. A genuine next slice: either stop
   trusting `best` for anything beyond "a record exists" under
   `merge_risk`, or use the per-affiliation `years` array (present in the
   data, not yet consumed by anything) to cross-check temporal overlap
   against the subject's own claimed career dates/institutions — the
   actual reconciliation step every entry since 2026-08-15 has deferred.
   Do this only after confirming (see above) that `/authors?search=`
   really does return the full `affiliations` array, not just
   `last_known_institutions` — worth a live check once today's $0 budget
   resets.
2. **`linkedin.py` red-team**: still the least-reviewed module by every
   prior entry's own account; PR #3/#7's fixes are now on `master`, so a
   fresh pass targeting what neither of them covered (see the 2026-08-17
   entry's own list: non-English degree parsing, `_parse_educations`'
   first-line-is-the-institution assumption, `is_linkedin_paste`'s
   signal-scoring on an ordinary CV) is now genuinely new ground, not a
   third re-fix of the same two bugs.
3. Figure out why 2026-08-28/2026-08-29 left no trace in this file or in
   `master`'s history — not urgent, but worth a human's attention if it
   indicates the nightly schedule itself missed two firings rather than
   firing and finding nothing worth doing.
**one open `nightly/*` PR, #11 (`nightly/2026-08-30`)**, draft, based cleanly
on `master`'s current tip (`9f71c98`) — not stale, just unmerged. No CI
configured on this repo (`pull_request_read get_status` returns zero
statuses) and no reviews yet. It adds `providers._affiliation_institution_count()`
and a `merge_risk` flag on OpenAlex's `best` candidate (institution_count
>= 15) — a real, tested, narrow slice of the core-gap's disambiguation
groundwork. Nothing to act on from a nightly run here per the standing
instructions (merging is the human's gate); noting it so it isn't missed.
Branched tonight's work fresh from `master`'s tip regardless, and kept it to
`linkedin.py` + its tests specifically so it cannot conflict with #11's
`flags.py`/`providers.py` diff at merge time.

### Running backlog tally (15 CRITICAL findings)

**10 [FIXED] / 1 [PARTIALLY FIXED] / 4 still open — unchanged by tonight**
(re-counted directly against `BACKLOG.md`'s `## CRITICAL (15)` section on
`master`'s tip: grepped every `### ` header, 10 carry `[FIXED]`, 1 carries
`[PARTIALLY FIXED]`, matching the 2026-08-30 entry's own count exactly — no
merges landed since then to move it). The 4 still open are the core
architectural gap and its three near-duplicate write-ups. Tonight's fix is
filed under BACKLOG.md's "Shipped since the original review" section, not
against any of the 15, since it isn't one of the original findings.

### What I did

**Primary item:** confirmed and fixed a bug flagged as untested speculation
since the 2026-08-17 `linkedin.py` red-team pass — `is_linkedin_paste`
misfiring on an ordinary CV that uses bare "Experience"/"Education" as
section headers. Reproduced live first: a hand-written two-job CV fixture
with plain `"2019 - Present"` date ranges (no LinkedIn-specific formatting
at all) scored `signals=5` (headers alone give 4, a bare year-range line
gives a 5th) against the `signals >= 4` gate, with no requirement that
anything in the text is actually LinkedIn-specific. `cli._maybe_normalise`
then replaced the entire audited text with
`parse_linkedin_paste(text).to_prose()`, whose experience parser only
recognises a group as "dated" via LinkedIn's own month-based
`"Jan 2020 - Present · 2 yrs"` pattern — a plain `"2019 - Present"` line
doesn't match, so every group gets folded into one entry and only the first
two lines (title, company) survive. Concretely: the fixture's entire second
job and both achievement sentences vanished, 75 words of CV becoming 31
words of prose, *before `extract_claims` ever ran*. Not a mislabelling —
silent content loss against an honest person's real, true claims.

Fixed by requiring at least one genuinely LinkedIn-specific marker (the
month-based date/duration regex, the `"· Full-time"`-style employment-type
regex, or ≥2 lines of UI chrome) alongside the existing header/signal gates.
This only narrows detection — consistent with the module's own docstring,
which already states false positives are worse than false negatives here
because raw paste still works, just with weaker extraction. Both existing
LinkedIn fixtures (`LINKEDIN_PASTE`, `MINIMAL_PASTE`) still detect correctly
since both already carry a real month-based date match.

**TDD, tests written first and watched fail against unmodified code:**
`test_ordinary_cv_with_bare_headers_is_not_mistaken_for_linkedin_paste`
(unit) and `TestOrdinaryCvContentSurvives` (real `larp_meter.cli.main()`
end-to-end, checking `report["mode"]` and `report["word_count"]`) — the
latter specifically because, per this repo's standing lesson (the
ROR/HANDLERS dead-code bug, and the `_attribute`/`None` bug one layer up), a
unit test on `is_linkedin_paste` alone proves nothing about whether the
dropped content is still missing once the real `--text` pipeline runs.
473 → 475 tests, green throughout.

**Required end-to-end CLI check**, two additional hand-written samples
beyond the test suite (mandatory after touching `linkedin.py`): a clean
LinkedIn paste with genuine markers (Message/Follow chrome, a connections
count, a real `"Jan 2021 - Present · 5 yrs 8 mos"` line) — still detected
and normalised, `mode: text:linkedin`, as before. A fabricator's plain-text
CV with a self-applied "Dr." title and no matching credential in the stated
education — no longer normalised (`mode: text`), and flag 13 correctly
TRIGGERED once `--name` is supplied (UNKNOWN with no `--name`, which is
flag 13's own documented, unrelated contract — not a regression from
tonight's change; verified by rerunning with `--name` set).

**Mandatory per-cycle mutation-testing spot-check**, one mutation in each of
the four standing files, full suite run after each, reverted before the
next — all four **caught**, confirming `master` is still fully protected on
all four fronts (no full sweep needed tonight; all four already have a
dedicated pass recorded in earlier entries):

| File | Mutation | Result |
|---|---|---|
| `scoring.py` | `coverage >= MIN_COVERAGE` → `coverage >` | **Caught** (1 failure) |
| `flags.py` | `if refuted or mismatched:` → `if refuted and mismatched:` | **Caught** (4 failures) |
| `verify.py` | `verify_institution`: `if wanted and wanted <= have:` → `if wanted <= have:` | **Caught** (3 failures) |
| `names.py` | `name_matches`: deleted `if not usable: return None` | **Caught** (4 failures) |

### Mutation-testing log (files swept so far, by night)

- `scoring.py`: full sweep 2026-08-16 (12 mutations, 6 real, all pinned).
  Spot-checked again tonight (1 mutation), still caught.
- `flags.py`: full sweep 2026-08-16/17 (33 mutations, 13 real, all pinned).
  Spot-checked again tonight (1 mutation), still caught.
- `names.py`: full sweep 2026-08-19 (PR #5, now merged onto `master`).
  Spot-checked again tonight (1 mutation), still caught.
- `verify.py`: full sweep 2026-08-18 (PR #4, now merged onto `master`).
  Spot-checked again tonight (1 mutation), still caught.

**All four files now have a full sweep on `master` itself** (the 2026-08-27
entry's caveat — that the `names.py`/`verify.py` sweeps only existed on
unmerged branches — no longer applies now that the merge queue has cleared).

### BACKLOG.md: confirmed / refuted

- **Confirmed live** (not from the 2026-08-17 entry's own speculation alone):
  `is_linkedin_paste` genuinely misfires on an ordinary CV using bare
  "Experience"/"Education" headers, and the resulting normalisation
  genuinely drops real content (75 → 31 words on the hand-written fixture).
  Fixed and pinned as described above; recorded as a new "Shipped" entry in
  BACKLOG.md.
- Did not re-verify any other BACKLOG.md entry tonight, including the two
  other items on the 2026-08-17 list (`_DEGREE_LEVEL_RE`'s English-only
  vocabulary, `_parse_educations`'s institution-is-line-one assumption) or
  any of the 4 still-open CRITICALs. Don't assume those are still accurate
  without a fresh look.

### What I learned

- The "worth a dedicated look, not verified live" caveats earlier entries
  leave behind are worth taking literally — this was flagged as plausible
  speculation two weeks ago (2026-08-17) and sat untouched until tonight's
  live repro confirmed it was not just plausible but immediately
  reproducible on the first hand-written fixture tried.
- `_YEAR_RANGE_RE` (a bare `"YYYY - YYYY"`/`"YYYY - Present"` line) is not
  actually a LinkedIn-specific signal — it's just as common in an ordinary
  resume's date formatting. Worth remembering if `is_linkedin_paste` is
  touched again: the only genuinely distinguishing markers found in this
  file are the month-based date/duration combo, the employment-type suffix,
  and UI chrome. Section headers and bare year ranges are necessary but not
  sufficient.

### What the next run should pick up first

1. **The core gap, continued** (unchanged from the last several entries):
   PR #11's `merge_risk` flag exists but `best` is still chosen by
   `works_count` alone even when `merge_risk` is true. Use the per-affiliation
   `years` array to cross-check temporal overlap against the subject's own
   claimed career — the actual reconciliation step every entry since
   2026-08-15 has deferred. Re-verify OpenAlex's live rate-limit posture
   first (PR #11 found `/authors?search=` fully $0-rate-limited on
   2026-08-30; check whether that's still true before assuming a live
   end-to-end check against the real API is possible on any given night).
2. **`linkedin.py`, remaining untouched leads from the 2026-08-17 list**:
   `_DEGREE_LEVEL_RE`/`_DEGREE_FIELD_RE`'s English-only vocabulary (a French
   "Licence en Droit" or German "Diplom-Ingenieur" won't bind to its
   institution — a fairness gap, not an evasion one) and
   `_parse_educations`'s assumption that the institution is always the
   first line of the group (worth a live re-check against LinkedIn's current
   markup before changing anything, since it may have shifted).
3. PR #11 is still open and unmerged as of tonight — worth a human merge
   pass before it joins the kind of queue the 2026-08-26/27 entries had to
   flag as the project's biggest bottleneck.
---

## 2026-09-01 (nightly run)

### ⚠ Two open, unmerged `nightly/*` PRs — read before doing anything else

Neither is stale or conflicting; both are green and clean, and don't touch
overlapping files, so a human merge pass can take either or both in any
order:

| PR | Branch | What it does | State |
|----|--------|--------------|-------|
| #11 | `nightly/2026-08-30` | First slice of the core gap's own named prerequisite: flags an OpenAlex `best` pick that's likely a merged entity (`institution_count`/`merge_risk` on flag 6's evidence, never changes which candidate is picked or produces a new TRIGGERED). Touches `providers.py`, `flags.py`. | open, draft, `mergeable_state: clean`, CI green (6/6 checks) |
| #12 | `nightly/2026-08-31` | Fixes `is_linkedin_paste` misfiring on an ordinary CV that uses bare "Experience"/"Education" headers, which was silently dropping content (a real second job and both achievement sentences) before extraction ever ran. Touches `linkedin.py` and its tests only. | open, draft, `mergeable_state: clean`, CI green (6/6 checks) |

Both are based cleanly on `master`'s current tip (`9f71c98`) and PR #12's own
description already confirms it doesn't overlap PR #11's files. Per the
standing instructions this is not something a nightly run acts on — flagging
for a human merge pass, same as prior pileup nights, but this one is small
(two PRs, non-conflicting, both green) rather than the five-to-seven-deep
queues earlier nights had to describe.

### Running backlog tally (CRITICAL findings)

**10 [FIXED] / 1 [PARTIALLY FIXED] / 5 still open (of 16)** — the 16th is new
tonight (see below); of the 15 counted on 2026-08-27 the split was already
10/1/4 unchanged since, so tonight's work moves the MAJOR section (see below)
and adds one new CRITICAL, not the CRITICAL tally's fixed/open ratio.
(Counted directly against `master`'s `BACKLOG.md` just now: `grep -c` under
`## CRITICAL` for `[FIXED]`/`[PARTIALLY FIXED]`/neither, 16 headers total.)

### What I did

**Primary item:** fairness-lens fix for the MAJOR finding "Confidential work
and pre-revenue fundraising are scored as deception." Confirmed live first:
a hand-written satellite-power-electronics engineer bio (`MSc TU Delft, 12
years since 2013, building next-gen hardware, "most of this work is covered
by customer NDAs and cannot be published", raising a pre-seed round for a
pre-product line`) TRIGGERED flag 6 ("cites no checkable artifact") and flag
7 ("no customer, revenue or usage figure of any kind") before any change —
exactly as BACKLOG.md described, on text with zero registry contradictions
anywhere.

Wrote 3 failing tests first (`tests/test_flags.py`), watched them fail
against unmodified code, then fixed: added two new keyword banks in
`matching.py` — `confidentiality_reasons` (nda, non-disclosure, confidential,
proprietary, classified, export controlled, itar, trade secret, stealth
mode, ...) and `pre_revenue_stage` (pre-revenue, pre-seed, pre-product, not
yet generating revenue, early stage startup, ...). `f_output` (flag 6) now
checks for a confidentiality reason before returning TRIGGERED on a bare
building claim with no artifact, and returns UNKNOWN with the reason quoted
back instead. `f_fundraising` (flag 7) does the same with the pre-revenue
bank before its final TRIGGERED branch. Both checks sit *after* the existing
PASSED branches (a real artifact or real traction still wins outright) and
*before* the TRIGGERED fallback, so this can only ever soften a would-be
TRIGGERED into UNKNOWN — it can never turn anything into a new TRIGGERED,
and it can never manufacture a PASSED where none existed. A bare building/
funding-ask claim with **no** stated reason still TRIGGERS exactly as
before — confirmed via the pre-existing `test_no_verifiable_output` and
`test_fundraising_without_traction` tests, unmodified, both still passing.

**Cross-boundary check (per the standing review question):** grepped every
reader of flag 6/7's `FlagResult` — `scoring.py` and `report.py` both key
purely on `r.status in (TRIGGERED, PASSED, UNKNOWN)`, generically, with zero
per-flag text parsing (confirmed by grep: neither file mentions `f_output`,
`f_fundraising`, or a flag-6/7-specific string anywhere). Both flags already
return UNKNOWN in other branches (e.g. "not visibly fundraising"), so no
downstream code path is newly reachable — this doesn't add a case anything
needs to learn about, only a new way to reach an already-handled one.

**End-to-end CLI check**, two hand-written samples, `python3 larp-meter.py
--file ... --name ...`:
- **Should-soften:** the NDA-engineer/pre-seed sample above. Before: flags 6
  and 7 both TRIGGERED. After: flag 6 reads "Claims to be building something
  with no checkable artifact, but the text states a reason it wouldn't have
  one ('cannot be published') — ..."; flag 7 reads "...but the text states
  this is a pre-seed raise — no customer or revenue figure is expected at
  this stage." Both UNKNOWN, both counted out of coverage rather than
  against the subject.
- **Should-still-trigger (regression check):** the standing "Dr. Marcus Vane"
  fabricator sample (building claims + funding ask, no NDA/pre-revenue
  language, no identifiers). Flag 6 stayed TRIGGERED ("Claims to be building
  something, yet cites no checkable artifact...") exactly as before — the
  escape hatch didn't fire because nothing in the text earned it.

Full suite: 473 → 476 tests, green throughout.

### A second, bigger bug found while writing the end-to-end check — NOT fixed tonight

While hand-writing the fabricator sample I split "no customers or revenue
disclosed yet" across a line wrap (an ordinary word-wrap, not a paragraph
break) and flag 7 read it as **PASSED** ("Fundraising with stated traction
(revenue)") instead of the TRIGGERED/UNKNOWN it should have been — the
negation ("no customers or [wrap] revenue") had silently stopped applying.
Traced it to `is_negated`/`_CLAUSE_END_CHARS` in `matching.py`: a bare `\n`
is treated as an unconditional clause boundary, so a negator immediately
before a word-wrap becomes invisible to the word immediately after it. Built
a clean minimal repro confirming this is general, not specific to my two new
banks or to "revenue":

```
find_terms("We are not raising a Series A at this time.", ..., skip_negated=True)   -> []
find_terms("We are not\nraising a Series A at this time.", ..., skip_negated=True)  -> ['raising']
```

This is a real, currently-live false-accusation risk on completely ordinary
input (any plain-text paste, PDF-extracted CV, or hard-wrapped email that
happens to deny a funding_ask/traction/building_claims/vague_partnership
term across a line break) — worse than tonight's primary finding, because it
can actively fabricate a TRIGGERED accusation rather than merely fail to
soften one. Did **not** attempt a fix tonight: it touches `is_negated`, the
shared guard every `skip_negated=True` call in the whole flag battery relies
on, `matching.py` has never had a mutation-testing sweep (only
`scoring.py`/`names.py`/`flags.py`/`verify.py` are covered — see the log
below), and a naive fix (just drop `\n` from `_CLAUSE_END_CHARS`) risks the
opposite failure — negation bleeding across an intentional bullet/field
break ("No revenue.\nRaising a seed round." would wrongly suppress the
second line's real ask). That needs its own dedicated night with a proper
`matching.py` mutation sweep and tests pinning both directions. Recorded as
a new CRITICAL finding in BACKLOG.md ("Word-wrapped negation loses its scope
at every bare newline") with the repro above and a scoped fix direction —
this is the single highest-priority item for whoever picks up next.

### BACKLOG.md: confirmed / refuted

- **Confirmed and partially fixed**: "Confidential work and pre-revenue
  fundraising are scored as deception" — reproduced live exactly as
  described, fixed the escape-hatch half, left the "cap combined
  contribution" half and a dedicated evasion red-team of the two new banks
  explicitly open. Marked `[PARTIALLY FIXED]` with full detail in place.
- **Confirmed live, new finding, not previously in BACKLOG.md**:
  word-wrapped negation losing scope at a bare newline (see above). Added as
  a new CRITICAL with live repro, not a re-derivation of anything already in
  the file.
- Did **not** re-verify any other still-open BACKLOG.md entry tonight,
  including the two open core-gap duplicates and "Citing no identifiers
  disables the entire verification half of the tool, including its only
  severity floor" — read that last one in full while choosing tonight's
  item and deliberately did not attempt it: its own suggested fixes (turn a
  no-identifier profile's UNKNOWN into TRIGGERED, or attach the ORANGE floor
  to a flag that can fire without registry input) both risk exactly the
  false-accusation failure mode this project's governing value exists to
  prevent — every honest person with no public identifiers (career break,
  confidential work, non-academic field, thin online presence) would eat the
  same penalty as a fabricator. That's a real design problem, not a
  same-night fix; flagging it explicitly rather than picking it and
  producing something rushed.
## 2026-09-02 (nightly run)

### Three open, unmerged `nightly/*` PRs — read before doing anything else

Much smaller queue than the 5-7-deep pileups earlier nights had to describe,
and none of the three touch a file this branch touches:

| PR | Branch | What it does | Files touched |
|----|--------|---------------|----------------|
| #11 | `nightly/2026-08-30` | Flags an OpenAlex `best` pick that's likely a merged entity (core-gap groundwork) | `providers.py`, `flags.py` |
| #12 | `nightly/2026-08-31` | Fixes `is_linkedin_paste` misfiring on an ordinary CV with bare "Experience"/"Education" headers | `linkedin.py` |
| #13 | `nightly/2026-09-01` | Confidentiality/pre-revenue escape hatch for flags 6/7 (fairness fix) + surfaced tonight's finding below | `flags.py`, `matching.py` |

All three are based cleanly on `master`'s current tip (`9f71c98`) per `list_pull_requests`. #11 and #13 both touch `flags.py`, so whichever merges second will need a trivial rebase — noting it here rather than acting on it; merging is the human's gate, not a nightly run's. Tonight's branch is cut fresh from `master`'s tip regardless, per the standing instructions, and only touches `matching.py` and test files — nothing any of the three above are likely to conflict on. Not a merge-queue emergency this time; just flagging for visibility as every night is asked to.

### Running backlog tally (CRITICAL findings)

**11 [FIXED] / 1 [PARTIALLY FIXED] / 4 still open (of 16)** — verified directly
against `master`'s `BACKLOG.md` just now (`grep -c` under `## CRITICAL` for
`[FIXED]`/`[PARTIALLY FIXED]`/neither). The 16th CRITICAL is the one this
branch adds and fixes tonight (see below) — it existed only on the unmerged
PR #13's copy of BACKLOG.md before this, so `master` itself was still showing
15/10/1/4 until this branch. The 4 still open: the core gap itself (line
~761), its near-duplicate "identifier-keyed and one-way" (line ~922), "Zero
registry reach on a realistic prose profile" (line ~878, a specific instance
of the same core gap), and "Citing no identifiers disables the entire
verification half of the tool" (line ~832) — all four unchanged tonight, not
re-verified this cycle beyond the read already logged on 2026-09-01.

### What I did

**Primary item:** fixed the CRITICAL finding the unmerged PR #13 surfaced but
explicitly left open — "Word-wrapped negation loses its scope at every bare
newline." Confirmed live first, exactly as PR #13's NIGHTLY.md entry
described and BACKLOG.md now records in full: `is_negated`'s clause-boundary
scan treats every `\n` as a hard stop (`_CLAUSE_END_CHARS` included it
alongside `.;:!?•|`), so an ordinary word-wrap silently drops a negator from
its own clause. `find_terms("We are not\nraising a Series A at this time.",
["raising"], skip_negated=True)` returned `['raising']` — the identical text
without the wrap correctly returned `[]`. This is a live false-accusation
bug: any plain-text paste, PDF extraction, or hard-wrapped email that denies
a `funding_ask`/`traction`/`building_claims`/`vague_partnership` term across
a line break had the denial silently ignored, and `f_fundraising` (the
highest-weighted flag after the contradiction check) could read an explicit
"we are not raising" as an active, traction-free fundraise.

Wrote 7 unit tests (`tests/test_negation.py::TestNewlineClauseBoundary`) and
one end-to-end flag test first, watched all 8 fail against unmodified code,
then fixed `larp_meter/matching.py`: removed `\n` from `_CLAUSE_END_CHARS`
outright and added `_hard_newline_before()`, which walks backward through
consecutive newlines (bounded by the file's existing `_MAX_LOOKBACK_CHARS`
window, so this cannot reintroduce the quadratic cost the file's own history
warns about) and only treats one as a clause boundary when it is a genuine
blank-line paragraph break, or is immediately followed by a bullet/numbered
list marker (`•`, `▪`, `‣`, `*`, `-`, an en/em dash, or `1.`/`1)`-style
numbering). An ordinary mid-sentence word-wrap matches neither condition and
is now treated as whitespace, so a negator reaches across it exactly as it
would on one physical line.

**Caught a weak test while mutation-testing my own diff, before it shipped:**
my first draft of the paragraph-break regression test used a sentence that
already ended in a period before the blank line ("...this quarter.\n\nWe are
raising..."), so disabling the new blank-line check entirely left the test
still passing — the pre-existing period boundary was doing the work, not the
code under test. Same failure shape for the bullet/numbered-list tests: my
first draft used a literal `•` character (already one of the *original*
`_CLAUSE_END_CHARS`, independent of anything new) and a period-terminated
numbered marker ("1. No revenue"), so both accidentally passed via unrelated
pre-existing logic even with the new bullet-detection code disabled.
Rewrote all three to use markers/punctuation that isn't already a clause-end
char on its own (`-` bullets, `1)` numbering, and put the negator within the
6-token lookback window so the existing lookback cap can't accidentally save
a non-discriminating test either) — re-ran each mutation and confirmed a real
failure this time. This is the exact "a test that cannot fail is worse than
no test" lesson `test_mutation_guards.py`'s own docstring already names;
worth restating because it happened on a test I wrote *for* a mutation check
and only caught by actually running the mutation, not by reading the test.

Also pinned the opposite direction explicitly (not just the reported bug):
`test_word_wrapped_negation_still_applies` / `test_word_wrap_mid_phrase_still_applies`
cover the fix itself; `test_paragraph_break_still_stops_negation`,
`test_hyphen_bullet_list_item_stops_negation` and
`test_numbered_list_item_stops_negation` cover the failure mode PR #13's own
finding explicitly worried a naive fix would reintroduce — a real list-item
break must still stop negation, or "No revenue" in one bullet would wrongly
suppress "Raising a seed round" in the next.

**End-to-end CLI check**, two hand-written samples via
`LARP_CACHE=<tmp> python3 larp-meter.py --file ... --name ...`:
- **Should-soften (honest, word-wrapped denial):** a Norwegian robotics
  founder bio denying an active raise across a line break ("We are not\n
  seeking investment and are not raising at this time. We have 12 paying
  customers..."). Flag 7 correctly reports UNDECIDABLE — "Not visibly
  fundraising; the flag does not apply" — where before the fix the wrapped
  "raising" would have been read as asserted and (with no traction language
  recognized either, since the denial masks it) risked a false TRIGGERED.
- **Should-still-trigger (regression check, genuine wrapped assertion):** the
  standing "Dr. Marcus Vane" fabricator sample, with the funding claim itself
  wrapped across an unrelated line break ("We are actively\nraising a Series
  A round. 40 enterprise customers and 12M in ARR."). Flag 7 correctly still
  reports PASSED — "Fundraising with stated traction (customers, arr)" —
  confirming the fix does not over-correct and suppress a genuine assertion
  just because it happens to wrap.

Also added `tests/test_round4.py::test_a_newline_heavy_document_stays_tractable`,
mirroring that file's existing hype-heavy-document perf regression test,
since the new backward walk through newlines touches exactly the kind of
unpunctuated pathological input that test class exists to guard against
(1500 repeats of an unpunctuated newline-terminated line stayed well under
the file's existing 10-second budget).

**Cross-boundary check (per the standing review question):** `is_negated`'s
signature and return contract are completely unchanged (still a plain bool;
only the internal boundary computation changed), so this is not the
"function's return contract grew a new case, caller didn't handle it" shape
the standing instructions warn about. Grepped both call sites: `matching.py`'s
own `_matches()` and `extract.py:251`'s `negated=zero or is_negated(...)` —
neither needed any change, and both are exercised by the full suite, not
just `matching.py`'s own tests.

Full suite: 473 → 481 tests, green throughout.

### BACKLOG.md: confirmed / refuted

- **Confirmed and fixed**: "Word-wrapped negation loses its scope at every
  bare newline" — reproduced live exactly as PR #13 described it, added as
  CRITICAL #16 (it wasn't on `master` yet, only on the unmerged branch) and
  marked `[FIXED]` immediately with full detail, since this branch closes it
  in the same night it's recorded.
- Did **not** re-verify any of the four still-open CRITICALs tonight (the
  core gap and its two duplicates, plus the no-identifiers-disables-
  verification finding) — all four were already read in full as recently as
  2026-09-01's entry and deliberately not re-derived here.
## 2026-09-13 (nightly run)

### ⚠ Open-PR queue: 11 unmerged `nightly/*` PRs, dating back to 2026-08-30 — read this first

`master`'s own copy of this file still stops at 2026-08-27, exactly as that
entry warned it would: every night since 2026-08-30 branched fresh from
`master`'s tip (per the standing instructions) and wrote its own
NIGHTLY.md/BACKLOG.md updates onto a branch nobody has merged. `master`'s tip
is still commit `9f71c98` (2026-08-27's merge). The queue has grown, not
shrunk, since the 2026-08-27 entry called seven unmerged PRs "the single
biggest risk to this repo's own bookkeeping" — it is now eleven:

| PR | Branch | What it claims | Draft/CI |
|----|--------|-----------------|----------|
| #11 | nightly/2026-08-30 | Flag an OpenAlex "best" pick that's likely a merged entity | open, draft |
| #12 | nightly/2026-08-31 | An ordinary CV mistaken for a LinkedIn paste silently lost content | open, draft |
| #13 | nightly/2026-09-01 | Confidential and pre-revenue work is not deception | open, draft |
| #14 | nightly/2026-09-02 | A word-wrap can hide a denial from `is_negated` | open, draft |
| #15 | nightly/2026-09-03 | A fixed-width context window clipped a disclaiming phrase far from its identifier | open, draft |
| #16 | nightly/2026-09-04 | A self-applied doctoral title in lowercase/all-caps was invisible to flag 13 | open, draft |
| #17 | nightly/2026-09-08 | A current student's own study dates read as a fabricated future claim | open, draft |
| #18 | nightly/2026-09-09 | Pin flags.py's buzzword carve-out lower boundary | open, draft |
| #19 | nightly/2026-09-10 | The "own account" caveat only credited Wikipedia, never a genuine OpenAlex hit | open, draft |
| #20 | nightly/2026-09-11 | A truthful career read as impossible when only its most recent role was dated | open, draft |
| #21 | nightly/2026-09-12 | An honest institution ROR doesn't index read as a fabricated credential | open, draft |

Checked each branch's diff against `master` (`git diff --stat`) rather than
trusting titles alone: none of the eleven touch `verify.py`'s DOI handler or
`flags.py`'s flag 11 in a way that would conflict with tonight's change (only
#15/#21 touch `verify.py`, and both are scoped to institution/context-window
logic, not `verify_doi`). Per standing instructions this is **not something a
nightly run can fix by pushing more commits** — it needs a human merge pass.
Recording it here again, prominently, because a reader who only skims
BACKLOG.md's `[FIXED]` tags (which reflect `master` only) would have no way
to know eleven more nights of real, tested work are sitting unlanded.

### Running backlog tally (15 CRITICALs)

**10 [FIXED] / 1 [PARTIALLY FIXED] / 4 still open — unchanged by tonight**,
verified directly against `master`'s current `BACKLOG.md` (grepped `^### `
under `## CRITICAL (15)`: 10 carry `[FIXED]`, 1 carries `[PARTIALLY FIXED]`,
4 carry neither). Tonight's fix landed on a **MAJOR** finding, not one of the
15 CRITICALs, so this tally itself doesn't move. The 4 still-open CRITICALs
are the core architectural gap and its three near-duplicate framings
("Citing no identifiers disables the entire verification half...", "Zero
registry reach on a realistic prose profile...", "Verification is
identifier-keyed and one-way...") — all still fully open, no PR in the queue
above touches them.

### What I did

**Primary item:** fixed the MAJOR finding "Nothing checks whether a cited
paper was retracted... and Crossref already returns the fields" — `verify_doi`
fetched the full Crossref record but read only `title`/`author`, so a
subject citing a formally retracted paper as their published work was
reported VERIFIED, exactly like a paper still standing. Chose this over the
core gap (still the standing brief's top priority, but the 08-27 entry and
every entry since has independently judged a same-night attempt at the full
reverse-path architecture too large and risky to land safely without the
disambiguation groundwork first — nothing in the eleven queued PRs attempts
it either, so this remains correctly deferred rather than newly neglected)
and over another isolated backlog-item red-team pass, because this one is
small, uses an identifier the subject already volunteered (no new
disambiguation risk), and is explicitly called out in BACKLOG.md as one of
the two highest-signal, most-checkable forms of publication LARP the tool
was blind to.

Live-checked the finding's own motivating DOI (`10.1038/s41586-023-06774-2`)
against `api.crossref.org` before writing any code: it is actually the
*retraction notice* for a different paper, not the original — and checking
the *original* paper's own DOI (`10.1038/s41586-023-05742-0`) turned up a
real wrinkle the backlog's "Fix direction" didn't anticipate: that record's
own `update-to` list carries only `"expression_of_concern"` and
`"correction"`, never `"retraction"` — Crossref/Retraction Watch attaches
the retraction relation to the separate notice DOI instead. Relying on
`update-to` alone, as the backlog entry suggested, would have silently
missed this exact live retraction. Cross-checked a second real case (The
Lancet's Surgisphere COVID paper, `10.1016/S0140-6736(20)31180-6`) where
`update-to` DOES carry `"retraction"` directly on the record itself,
confirming the relation's placement is genuinely inconsistent across
publishers rather than a one-off. Fixed by trusting either signal: an
`update-to` entry of type `"retraction"`, OR the record's own title
prefix-matching a publisher-applied retraction marker
(`"retracted"`/`"retraction"`/`"withdrawn"`, anchored at the start so a
paper merely discussing retraction as a topic isn't caught by a substring
match).

Added a new `Claim.retracted` field (default `False`) rather than repurposing
`claim.status` — retraction is a fact about the artifact's continued
validity, independent of whether the subject wrote it, and conflating the
two would have made a disclaimed citation of someone else's retracted paper
look identical to the subject's own retracted work. Wired into flag 11
(`f_contradicted`), not a new flag: a **confirmed** (subject-attributed,
`--name` given) DOI claim that is also retracted now TRIGGERS with its own
neutral message ("no longer standing evidence... whatever the reason for the
retraction") and still carries the ORANGE floor. Guarded both false-
accusation shapes this exact flag has been bitten by before: without
`--name`, a retracted-but-unattributed claim stays in the pre-existing
"existence alone is not confirmation" UNKNOWN branch; a citation the
subject's own text disclaims as prior art (`_disclaims_authorship`, the
2026-08-25 fix) stays UNCHECKABLE regardless of retraction status. Full
detail, including exactly which lines changed and why, is in BACKLOG.md's
updated entry.

**Left deliberately out of scope:** the preprint/`posted-content`-contradicts-
`peer-review-claim` half of the same backlog entry needs correlating a
`doi`/`arxiv` claim against a separate `artifact/assertion` claim elsewhere
in the text — a claim-linking capability that doesn't exist yet — and the
OpenAlex-works-by-DOI/DOAJ extensions the entry describes as the next step
up in value. Both are recorded as still-open in BACKLOG.md for the next run.

### Tests

Wrote 8 new tests first, watched each fail against the unmodified code, then
implemented:
- `tests/test_verify.py::TestRetraction` (6 tests): both detection signals
  independently (`update-to` type, and the title-prefix fallback the live
  Nature case needed), a negative control (an ordinary standing paper), a
  false-positive guard (a paper merely *about* retraction as a topic must not
  match), the disclaimed-citation case (retracted but not the subject's own
  claim to defend), and one full `run_audit` pipeline test using a real,
  live-shaped Crossref response (not `verify_doi`/flag 11 in isolation).
- `tests/test_flags.py::TestContradictionFlag` (+3 tests): confirmed+retracted
  TRIGGERS with the new message, confirmed+standing still PASSES (regression
  guard against a blanket downgrade), and retracted-without-a-name still does
  not read as confirmation.

**482 tests green** (474 → 482).

**End-to-end CLI check**, live network, two hand-written samples:
- **Should-flag:** "Nathan Dasenbrock-Gammon. My peer-reviewed breakthrough on
  near-ambient superconductivity, published as 10.1038/s41586-023-05742-0..."
  (a real author's name paired with his own real, retracted DOI). Flag 11
  TRIGGERED: "1 confirmed paper(s) have since been retracted by their
  publisher — no longer standing evidence of the claimed track record,
  whatever the reason for the retraction." Also re-ran BACKLOG.md's own
  motivating sample verbatim ("Dr. Marcus Vane... 10.1038/s41586-023-06774-2
  established the field") — correctly TRIGGERED via the pre-existing MISMATCH
  path (Marcus Vane isn't a real author of that record either), with the new
  retraction sentence now visible in the evidence detail where before nothing
  distinguished a retracted paper from a standing one.
- **Should-pass-cleanly:** "Charles R. Harris. Research engineer... Co-author
  of the NumPy array programming paper, 10.1038/s41586-020-2649-2..." — a
  real author citing his own real, standing paper. Flag 11 correctly PASSED
  ("All 1 checked identifier(s) confirmed by their registries"), no
  retraction wording anywhere, landing INSUFFICIENT DATA only on the
  pre-existing thinness gate (unrelated to tonight's change) — confirms the
  ordinary honest path is completely unaffected.

### Cross-boundary check (per the standing review question)

Grepped every reader of `.retracted` and every place that special-cases flag
11's id: the only writer is `verify.py`'s new `_is_retracted`/`verify_doi`
code, the only reader is the one new line in `flags.py`'s `f_contradicted`.
`Claim.to_dict()` (`asdict`) picks up the new field automatically for the
JSON report; grepped for any test asserting an exact claim dict shape or key
set — none exist, so the new field cannot silently break a JSON consumer.
`report.py` renders `claim["detail"]` and flag `description`/`evidence`
generically; no renderer needed updating. Confirmed the new `retracted =
[c for c in confirmed if c.retracted]` branch sits strictly *after* the
existing `if not ctx.subject_name: return UNKNOWN` guard in the `confirmed`
branch — i.e., it can only ever fire on a claim the flag has already
established is both subject-attributed AND has a real `--name` behind it,
so it inherits both existing false-accusation guards for free rather than
needing its own copies.

### Mutation-testing log

Mandatory per-cycle spot-check, one mutation in each of the four required
files, run against the full suite, then reverted:

| File | Mutation | Result |
|---|---|---|
| `scoring.py` | `scored = coverage >= MIN_COVERAGE` → `coverage >` | **Caught** (`test_coverage_exactly_at_min_coverage_is_still_scored`, pinned since 2026-08-16) |
| `flags.py` | tonight's own `if reason:` (confidentiality escape) → `if not reason:` | **Caught** (5 failures, including the two new tests written for this fix) |
| `verify.py` | `verify_institution`'s `if overlap > best_overlap:` → `>=` | **Caught** (existing ROR best-match tests) |
| `names.py` | `name_matches`'s `if len(present) >= 2:` → `> 2` | **Caught** (18 failures + 5 errors, existing attribution tests) |

All four still fully protected on `master`. **`matching.py` itself has never
had a mutation-testing pass** — worth naming explicitly now that tonight
found a live, unpinned bug in it (`is_negated`'s newline handling, above);
recommend it join the mandatory four for the file that hosts the fix, once
that fix exists.

### What I learned

- **Made, and caught, the exact mistake the 2026-08-15 entry warned about**:
  ran `git checkout -- larp_meter/flags.py` to revert a deliberate mutation
  while my real, uncommitted fix was still sitting in that same file. It
  reverted both — silently discarded the confidentiality-escape-hatch code,
  not just the one-line mutation — and I didn't notice until the *next*
  mutation's test run failed with the wrong symptom (a `flags.py` test
  failing during what was supposed to be a `verify.py`-only mutation check).
  Recovered by re-applying the two edits from what was still in this
  session's own context, then re-ran the full suite to confirm nothing else
  had been silently lost. For the rest of tonight's mutation passes,
  switched to `cp file file.orig` / `cp file.orig file` instead of `git
  checkout --`, which doesn't care whether the file also carries
  uncommitted real changes. **This is worth turning into a standing habit
  note, not just a one-off recovery story**: `git checkout -- <file>` is
  only safe as a mutation-revert when that file has no other uncommitted
  work in it at that moment — true for a from-scratch mutation sweep on an
  untouched file, false for exactly the common case of mutation-testing your
  *own* fresh, uncommitted change in the same file. `cp`/`git stash` costs
  nothing extra and removes the failure mode entirely.
- The line-wrap negation bug is a good example of the brief's own advice
  actually paying off: it was found purely by doing the mandated end-to-end
  CLI check with a hand-written sample, not by unit-testing anything in
  isolation. A `find_terms(...)` call in a unit test would never have used a
  word-wrapped multi-line string; a hand-authored "realistic" bio (typed as
  prose, wrapped for readability the way NIGHTLY.md itself is wrapped) hit
  it immediately.

### What the next run should pick up first

1. **`matching.py`'s `is_negated` newline handling** — the new CRITICAL
   finding above. Live-reproduced, scoped fix direction already written
   into BACKLOG.md. Needs: a real design for "which newlines are clause
   boundaries" that doesn't just trade one direction of error for the
   other (test both: a wrapped negation preserved, AND a genuine
   bullet-separated list still not bleeding negation across items), a full
   mutation-testing sweep of `matching.py` (never yet done — first time it
   would join the standing four-file rotation), and an end-to-end CLI check
   on a realistically word-wrapped sample specifically, since that's the
   input shape that hid this for however long it's existed.
2. The two small, non-conflicting open PRs (#11, #12) — still just a
   human-merge-queue item, not something for an autonomous run to act on,
   but worth surfacing every night until they land so they don't quietly
   become a third and fourth entry in a new pileup.
3. **"Citing no identifiers disables the entire verification half of the
   tool, including its only severity floor"** — read in full tonight,
   deliberately not picked (see above). Still the most consequential open
   CRITICAL after the core gap itself, and still needs a genuinely careful
   design — not "flip UNKNOWN to TRIGGERED" — to close without punishing
   every honest person with a thin public footprint.
4. The core gap (subject-anchored `Claim`s + reconciliation) is still fully
   open beyond PR #11's unmerged merge-risk groundwork. Unchanged tonight;
   still the single biggest lever in the codebase per every entry since
   2026-08-15.
5. `matching.py` should be added to the mandatory four-file mutation-testing
   rotation (`scoring.py`, `names.py`, `flags.py`, `verify.py`) once its own
   dedicated sweep happens — it has never had one, and tonight found a real,
   live, unpinned bug in it on the very first close look.
files, run against the full suite, then reverted (used `cp file /tmp/...` /
`cp /tmp/.../file file` throughout, not `git checkout --`, per the standing
lesson from 2026-09-01 about that command discarding uncommitted work
sharing the same file):

| File | Mutation | Result |
|---|---|---|
| `scoring.py` | `_apply_floors`'s `if ... <= _SEVERITY_ORDER.index(level):` → `<` | **Caught** (`test_exact_tie_keeps_the_ordinary_summary_not_the_floor_message`) |
| `verify.py` | `verify_institution`'s `if wanted and wanted <= have:` → `if wanted <= have:` | **Caught** (3 failures, incl. `test_a_stopword_only_institution_claim_cannot_verify_against_any_hit`) |
| `names.py` | `name_matches`'s `if len(present) >= 2:` → `> 2` | **Caught** (18 failures + 5 errors) |
| `flags.py` | `f_contradicted`'s `if refuted or mismatched:` → `if refuted and mismatched:` | **Caught** (4 failures, incl. a test literally named for this mutation) |

Plus the four mutations on tonight's own new `matching.py` code (disabling
the blank-line check, disabling the bullet-marker check, reverting to the
old always-hard-newline behavior, and the boundary tie-break `>=`→`>`) — see
"What I did" above for the first three (all caught after fixing the
non-discriminating draft tests); the tie-break mutation is unobservable by
construction (when `nl_boundary == boundary` the assignment is a no-op
either way), so it's not a real gap, just noted for completeness.

**Result: 481 tests green.** All four required files remain protected on
`master` by at least one live, passing mutation check tonight — this was a
spot-check rotation, not a full sweep of any file; `matching.py` itself
(new to any mutation-testing attention this cycle) got the closest thing to
a full sweep it's had, scoped to the code this branch actually added.

### What I learned

- **A test written specifically to catch a mutation can itself pass "by
  accident" if it isn't checked against the mutation it's meant to catch.**
  Three of my own first-draft tests tonight (paragraph-break, bullet-list,
  numbered-list) all happened to route through *unrelated* pre-existing
  boundary logic (a stray trailing period, a `•` character already in the
  original `_CLAUSE_END_CHARS`, a period inside a numbered marker) rather
  than the new code they were meant to exercise, and every one of them still
  passed with that new code deliberately disabled. The only way this
  surfaced was running the mutation and watching the test *not* fail — never
  trust a regression test's intent from reading it; run the mutation it's
  supposed to catch, every time, even (especially) for tests written in the
  same sitting as the fix.
- The three-PR queue is currently in good shape (small, clean, non-
  conflicting) compared to the 5-7-deep pileups earlier nights had to
  describe at length — worth naming as a positive data point, not just
  flagging problems. `flags.py` being touched by two of the three (#11,
  #13) is a minor, expected rebase cost, not a real conflict risk (verified
  no line-range overlap by reading both diffs).

### What the next run should pick up first

1. **The core gap** (subject-anchored `Claim`s + reconciliation) is still
   fully open, per every entry since 2026-08-15. Still the single biggest
   lever in the codebase; PR #11's unmerged merge-risk groundwork is the
   only progress toward it sitting anywhere, merged or not.
2. **"Citing no identifiers disables the entire verification half of the
   tool, including its only severity floor"** — still the most consequential
   open CRITICAL after the core gap, per 2026-09-01's entry; still needs a
   genuinely careful design, not a blunt UNKNOWN→TRIGGERED flip, to avoid
   punishing every honest person with a thin public footprint.
3. The three small, non-conflicting open PRs (#11, #12, #13) — keep
   surfacing them every night until a human merge pass lands them, per
   standing instructions; not something an autonomous run should act on
   directly.
4. `matching.py` has now had its first real, if narrowly-scoped, mutation
   check (limited to the newline-boundary code this branch added). The rest
   of the file — `term_re`, `find_non_overlapping`'s span-sorting, the
   `LOCAL_NEGATORS`/`CLAUSE_NEGATORS` lookback-token counts themselves — has
   never had a dedicated sweep. Worth a full pass next time `matching.py`
   is the night's focus, not just a spot-check riding along with an
   unrelated fix.
## 2026-09-03 (nightly run)

### ⚠ Open-PR check — four unmerged `nightly/*` PRs, all based on the same master tip

`master`'s NIGHTLY.md still stops at 2026-08-27 above — the human merge pass
that entry's own successors kept asking for did happen at some point after
that (the PR-queue table above is stale: `git log` shows every one of
2026-08-17 through 2026-08-27's PRs merged, `9f71c98` being the last), but
nothing has merged since. Four nights sit open and unmerged right now, all
draft, all green, all based on the identical `master` commit `9f71c98`:

| PR | Branch | What it claims | CI |
|----|--------|-----------------|----|
| #11 | nightly/2026-08-30 | OpenAlex merge-risk detection (flags a "best" pick that's likely a merged entity) — `providers.py`/`flags.py` | green |
| #12 | nightly/2026-08-31 | An ordinary CV mistaken for a LinkedIn paste silently lost content — `linkedin.py` | green |
| #13 | nightly/2026-09-01 | Confidential/pre-revenue work no longer scored as deception — `flags.py` (flags 6/7) | green |
| #14 | nightly/2026-09-02 | A word-wrap can hide a negation from `is_negated` — `matching.py` | green |

All four are clean, small, and touch disjoint files from each other and from
tonight's branch (`extract.py`, `verify.py`, and their tests — untouched by
any of #11–#14). Per the standing instructions this is for the human's
visibility, not something to act on: not merging, not rebasing onto, not
duplicating any of their fixes. Branched fresh from `master`'s tip (`9f71c98`)
for tonight's work.

### Running backlog tally (15 CRITICAL findings, BACKLOG.md `## CRITICAL (15)`)

**10 [FIXED] / 1 [PARTIALLY FIXED] / 4 still open** — re-counted directly
against `master`'s current `BACKLOG.md` (`grep -c '\[FIXED\]'` /
`'\[PARTIALLY FIXED\]'` under the CRITICAL section), not carried over from
memory. Up from the last recorded tally of 9/1/5 (2026-08-26) — one more
CRITICAL closed by whatever landed on `master` between 2026-08-27 and now
(most likely PR #9's `--verify` disclaimer fix, already `[FIXED]` in
`BACKLOG.md` with that exact write-up). Tonight's own fix is not one of the
15 named CRITICALs (it's a `verify.py`/`extract.py` finding discovered live
tonight, not from the original 63-finding review), so it doesn't move this
number — filed under "Shipped since the original review" instead, same
convention as every other night's from-scratch discovery. The 4 still open
are the core one-way/claim-anchored funnel finding and its three
near-duplicate write-ups (lines ~3, ~74, ~120, ~164) — none investigated
tonight.

### What I did

**Primary item:** found and fixed a real false-accusation gap in
`_disclaims_authorship` (`verify.py`, shipped 2026-08-25) that no run had
looked at since it landed — picked over the four open PRs' territory
specifically because it shares zero files with any of them (`extract.py`,
`verify.py`; #11/#13 touch `flags.py`, #12 touches `linkedin.py`, #14
touches `matching.py`).

`_disclaims_authorship` only ever sees `claim.context`, and that field was a
fixed 60-character window (`extract.py`'s `_context()`, unmodified since
before this project decomposed bios into typed claims) — never reconsidered
for whether it was wide enough to contain the disclaiming phrase it exists
to feed. Confirmed live: an outside patent attorney's or research
consultant's own sentence, written as one continuous clause ("I have spent
my career as outside patent counsel prosecuting numerous filings on behalf
of corporate clients, including for instance US9876543 which I filed for a
sensor startup"), lost "on behalf of" — the only disclaiming phrase in the
sentence — because it started more than 30 characters before the identifier
it qualifies. Before tonight this came back `MISMATCH`, floored at ORANGE by
flag 11, on a sentence that explicitly disclaims the exact thing being
accused.

Fixed `_context()` to scan outward to the nearest sentence boundary instead
of a fixed width (capped at 300 characters each direction, so a document
with no punctuation at all can't make the scan unbounded — same reasoning
`matching.py`'s `is_negated` already uses for its own lookback cap).
`claim.context` has exactly one reader in the whole codebase
(`_disclaims_authorship` — confirmed by grep before relying on it), so this
could be widened freely with no risk to any other consumer.

**The required end-to-end check surfaced two more real bugs that a
diff-reading pass would not have caught**, both fixed in this same PR rather
than shipped with a known gap:

1. A bare `\n` in the sentence-boundary set reintroduced the exact bug one
   line-length away: a plain-text file written with an ordinary ~80-column
   word wrap put the disclaiming phrase on one physical line and the
   identifier on the next, and the live CLI run against a real file (not a
   Python string literal, which never wraps) came back `MISMATCH` again.
   Fixed by dropping `\n` from the boundary set — unlike `matching.py`'s
   negation scope, nothing here needs to stop at a genuine paragraph break,
   since over-widening in the rare case this misses can only ever add a
   disclaiming phrase, never manufacture an accusation.
2. Widening the window made an existing, previously-dormant false-negative
   in `_NON_ATTRIBUTION_CONTEXT_RE` reachable at realistic distance: its
   citation alternative, `cit(?:e|es|ed|ing|ation)`, matches the passive "is
   cited BY" (other people citing the subject's own paper — corroboration)
   as readily as the active "citing prior art" (the subject disclaiming
   someone else's work) it was written for. Live-confirmed with a
   fabricated "Dr. John Smith... his landmark paper, `<doi>`, is considered
   foundational... and is cited by thousands of researchers worldwide" (the
   DOI is a real, unrelated author's paper) — the word "cited" 83 characters
   after the identifier let a genuine fabrication escape from `MISMATCH` to
   `UNCHECKABLE`. Fixed with a negative lookahead,
   `cit(?:e|es|ed|ing|ation)(?!\s+by\b)`.

Both follow-on bugs were found only because the standing "run the CLI
end-to-end on two hand-written samples" requirement was followed literally —
a real file on disk, live network — rather than trusted to the offline unit
tests alone, which were green at each intermediate (wrong) state.

### Verification

- 8 new tests, each written first and watched fail against the code at that
  point, then fixed: 4 in `tests/test_extract.py` (distant disclaimer
  captured; does not cross a preceding sentence boundary; does not cross a
  following sentence boundary — this one is what caught the "farthest
  boundary" mutation below; survives an ordinary word-wrap), 3 in
  `tests/test_verify.py` (the "cited by" false-negative, its "citing ... as
  prior art" negative control, and a full `run_audit` end-to-end test with
  the realistic distant-disclaimer sentence), 1 in `tests/test_round4.py` (a
  20,000-identifier unpunctuated-document perf guard).
- Mutation-tested every new line of production logic, each confirmed with a
  freshly cleared `__pycache__` (see "what I learned" below for why that
  matters): inverting the backward-scan boundary comparison (caught by the
  "preceding boundary" test), inverting the forward-scan comparison (caught
  by the "following boundary" test — this one **survived on the first
  attempt**, because my first version of that test only checked a text with
  nothing beyond the sentence-ending period, so the mutated "always use the
  outer cap" behavior produced an identical result by coincidence; added
  trailing content after the boundary to discriminate, then it caught),
  removing the `\n`-exclusion fix, and removing the `cit(?:...)(?!\s+by\b)`
  lookahead — all four caught after their respective tests were in place.
- Ran the real CLI end-to-end, live against Crossref (network reachable this
  session; Google Patents returned 503 from this sandbox all night, so used
  a DOI-based fixture instead of the historical patent one), on two
  hand-written samples, comparing the exact same claim against a genuinely
  reverted pre-fix `_context()` and the real fix, not just before/after in
  memory:
  - **Should-not-be-accused:** a hard-wrapped plain-text file, an outside
    research-consultant bio disclaiming authorship of a real, unrelated DOI
    ("...on behalf of corporate clients, including for instance a well known
    paper, 10.1038/nphys1170, which I summarized for a startup..."). Pre-fix:
    `MISMATCH`. Post-fix: `UNCHECKABLE`, "the surrounding text frames it as
    someone else's work."
  - **Should-still-be-flagged (regression check):** "Dr. John Smith... his
    landmark paper, 10.1038/nphys1170, is considered foundational... and is
    cited by thousands of researchers worldwide" — the same real DOI,
    misattributed, with no disclaiming language of the kind this fix targets.
    Both before and after: `MISMATCH`, flag 11 `TRIGGERED`. Confirms the fix
    only closes the false-accusation gap and does not blunt genuine fraud
    detection.
- Mandatory per-cycle mutation-testing spot-check, one mutation in each of
  the four required files, all done with a cleared `__pycache__` (see
  below), all four **caught** by the existing suite — no survivors, no new
  pins needed:

  | File | Mutation | Result |
  |---|---|---|
  | `scoring.py` | `next((lv, s) for cut, lv, s in LEVELS if larp < cut)`: `<` → `<=` | **Caught** — `test_larp_of_exactly_65_is_red_not_orange` and 2 others fail |
  | `names.py` | `name_matches`'s script-mismatch guard: `if mine_is_latin != blob_is_latin:` → `==` | **Caught** — 41 failures/errors |
  | `flags.py` | flag 11's no-name-with-confirmed guard: `if not ctx.subject_name:` → `if ctx.subject_name:` | **Caught** — `test_a_real_authored_paper_still_confirms` and 2 others fail |
  | `verify.py` | `verify_github`'s comparable-name gate: `len(published.split()) >= 2` → `>= 1` | **Caught** — `test_a_bare_handle_never_founds_a_mismatch` fails |

- Full suite: 473 → 481 tests, green at every intermediate step (after the
  primary fix, after each of the two follow-on fixes, and at the end).

### BACKLOG.md: confirmed / refuted

- **New finding, confirmed live and fixed** (not from the original 63): the
  `claim.context` window feeding `_disclaims_authorship` was too narrow to
  reliably contain the disclaiming phrase it exists to detect, in exactly
  the shape a real, honest sentence produces. Full write-up under "Shipped
  since the original review" — `claim.context`'s fixed 60-character window
  clipped a disclaiming phrase far from its identifier.
- Did not investigate any of the four still-open CRITICALs (the core
  reverse-path gap and its duplicates) tonight — this was a narrowly scoped
  fix to an existing guard, not an attempt at the architecture change those
  findings describe.
---

## 2026-09-10 (nightly run)

### ⚠ Open-PR queue — read this first: eight unmerged `nightly/*` PRs, eleven days and counting, zero merges since 2026-08-27

**This is now the single most important fact in this file.** `master`'s tip
is still the 2026-08-27 merge (`9f71c98`) — nothing has landed since. Every
PR below is based cleanly on that exact commit, `mergeable_state: clean`,
draft, no CI configured on this repo, zero review comments on any of them:
---

## 2026-09-11 (nightly run)

### ⚠ Open-PR queue — read this first: NINE unmerged `nightly/*` PRs, fifteen days and counting, zero merges since 2026-08-27

**This is still, by far, the single most important fact in this file, and it has gotten worse every night it's been reported.** `master`'s tip is unchanged since the 2026-08-27 merge (`9f71c98`) — every entry this file records after that point (2026-08-30 through 2026-09-10, nine nights in a row) exists only on its own unmerged branch, never on `master`. All nine PRs below are `mergeable_state: clean`, draft, no CI configured on this repo, and have received zero review comments:
---

## 2026-09-12 (nightly run)

### ⚠ Open-PR queue — read this first: TEN unmerged `nightly/*` PRs, sixteen days and counting, zero merges since 2026-08-27

`master`'s tip is still `9f71c98` (the 2026-08-27 merge). Every entry in this file after that point — 2026-08-30 through 2026-09-11, ten nights in a row — exists only on its own unmerged branch:

| PR | Branch | What it claims |
|----|--------|-----------------|
| #11 | `nightly/2026-08-30` | Flags an OpenAlex "best" pick that's likely a merged entity (core-gap disambiguation groundwork) |
| #12 | `nightly/2026-08-31` | An ordinary CV was mistaken for a LinkedIn paste and silently lost content |
| #13 | `nightly/2026-09-01` | Confidential and pre-revenue work is not deception (partial fix; also found, did not fix, the newline-negation bug #14 later closed) |
| #14 | `nightly/2026-09-02` | A word-wrap can hide a denial from `is_negated` |
| #15 | `nightly/2026-09-03` | A fixed-width context window clipped a disclaiming phrase far from its identifier |
| #16 | `nightly/2026-09-04` | A self-applied doctoral title in lowercase or all-caps was invisible to flag 13 (plus 3 pinned mutation survivors: `scoring.py` category-exclusion, flag 13's tail-window cap, `verify.py`'s ROR tie-break) |
| #17 | `nightly/2026-09-08` | A current student's own study dates read as a fabricated future claim (part (b) of the timeline-fairness finding; part (a) still open) |
| #18 | `nightly/2026-09-09` | Mutation-testing sweep + a correction to a two-week-old stale "still unpinned" claim in this very file |

Every one of #11–#18 is small, independently authored, and (per each PR's own
description, re-checked against the file lists above) touches disjoint or
near-disjoint files — this was never a conflict problem. It is purely a
"nobody has pressed merge in eleven days" problem, restated by five separate
nightly entries in a row (08-27, 09-01, 09-02, 09-03, 09-04, 09-08, 09-09,
now this one) with escalating counts (5 → 6 → 7 → 8 deep) and zero response.
Tonight's own branch is cut fresh from `master`'s tip regardless, per the
standing instructions, and touches only `larp_meter/report.py` and two test
files — none of which any of #11–#18 touch, so it should not conflict with
any of them at merge time.
## 2026-09-16 (nightly run)

### ⚠ Open-PR queue: FOURTEEN unmerged `nightly/*` PRs, dating back to 2026-08-30 — read this first

**`master`'s tip is still `9f71c98` ("Merge nightly/2026-08-27").** Twenty
consecutive nights have now produced independently-reviewable work with
zero merges landing. The queue grew again since 2026-09-15's own count of
thirteen (see that entry for the table through PR #23) — PR #24
(`nightly/2026-09-15`, "mutation-testing names.py and scoring.py finds two
real, unpinned gaps") is now also open and unmerged, bringing the total to
**fourteen**, PRs #11 through #24 inclusive, spanning 2026-08-30 through
2026-09-15. Checked live via the GitHub API rather than trusting each PR's own
description: all fourteen are still open and draft. (First check used the
wrong API — `get_status`, the legacy commit-status endpoint — which
reported zero statuses and briefly looked like CI wasn't running at all;
`get_check_runs`, the one that actually reflects `tests.yml`'s GitHub
Actions runs, shows all 6 matrix jobs green on both the oldest, PR #11,
and the newest, PR #24, checked directly rather than assumed. Recording
the correction so a future run doesn't repeat it: `get_status` is the
wrong tool for a repo whose CI is Actions-only.) None has a review. This
is not a merge-conflict or CI-failure problem — every PR reports `clean`
mergeable state and green CI; it is nobody having merged anything in
three weeks. Per standing instructions this is flagged, not acted on:
tonight's branch is cut fresh from `master`'s current tip regardless, and
deliberately scoped (test-only changes to a file — `verify.py` — that
**no** open PR appears to touch, based on each PR's own title) to minimize
collision risk at merge time. **A human merge pass is now three weeks
overdue and is the single highest-leverage action available on this
project** — every night that passes without one means real, independently
verified fixes for distinct findings keep sitting unreleased, and (per
2026-09-15's own finding) some of them are now being independently
re-discovered by later nights that can't see work sitting on other
people's unmerged branches.

### Running backlog tally (15 CRITICALs)

**10 [FIXED] / 1 [PARTIALLY FIXED] / 4 still open — unchanged by tonight.**
Re-counted directly against `master`'s current `BACKLOG.md` (`grep "^### "`
under `## CRITICAL (15)`), not carried forward from the 2026-09-09 entry's
own correction — matches it exactly, and nothing in the CRITICAL section
changed tonight (tonight's fix is filed under "Shipped since the original
review," like most nightly work, not against one of the 15 named findings).
The 4 still open are the core one-way/claim-anchored funnel finding and its
three near-duplicate write-ups from the original 5-lens review.

### What I did

**Primary item:** found and fixed a real, live bug in `report.py`'s
`caveats()` — a file with no full mutation-testing pass on record and
untouched by any of the eight then-open PRs, chosen specifically so tonight's
branch could not conflict with or duplicate any of them. `caveats()`'s single
most consequential disclaimer ("Nothing here was checked against an outside
source... treat a clean result as 'no internal contradictions found', not as
corroboration") only ever checked `signals["wikipedia_about_subject"]` before
deciding whether real outside-source corroboration existed — it never
checked `signals["openalex"]`, even though flag 6 (`f_output`) reads that
exact signal to PASS with "Independent scholarly record found: N works with M
citations (OpenAlex)." Both signals come from the same 2026-08-15
`_subject_registry_signals` gather; the caveat logic simply never learned
about the second one.

Confirmed live before writing anything: `caveats({"level": "GREEN",
"verification_effective": False, "signals": {"openalex": {"works": 12,
"citations": 340}}})` still returned the "own account" disclaimer — a
subject with zero identifiers in their bio but a real, name-matched OpenAlex
author record (exactly the case the 2026-08-15 work exists to give credit
for) got told nothing had been externally checked, directly contradicting
flag 6's own PASSED evidence one section down in the same report. This
doesn't move a score or manufacture an accusation, but it actively misleads a
reader about how much of a clean verdict rests on self-report versus a real
outside source — precisely the distinction this caveat exists to draw, and
precisely the kind of thing an honest, well-documented researcher with no
DOIs in their bio would be shortchanged by.

Wrote 2 tests in `tests/test_report.py` first (the fix itself, mirroring the
existing `wikipedia_about_subject` test exactly; and a negative-control
guarding the fix from overcorrecting — a completed-but-empty OpenAlex search,
`signals["openalex"]` is `None`, the genuine "asked and found nothing" case
the 2026-08-27 entry made visible, must still get the full caveat), watched
the first fail against the repro above, then fixed `caveats()` to also treat
`scholar and scholar.get("works")` (mirroring flag 6's own truthiness check
verbatim) as corroboration alongside `wikipedia_about_subject`.

**End-to-end pipeline check, mandatory per this repo's own recurring lesson**
(a component correct in isolation while the real pipeline never reaches it —
the ROR/HANDLERS bug, the `_attribute`/`None` bug): added
`tests/test_cli_registry_wiring.py::test_a_real_openalex_hit_silences_the_own_account_caveat`,
running the real `cmd_text` → `run_audit` → `caveats` chain with the network
stubbed, confirming `_subject_registry_signals`'s OpenAlex signal reaches
`caveats()` in the exact shape it actually produces (`{"works": N,
"citations": M, "institutions": [...], "orcid": ..., "display_name": ...}`),
not just a hand-built dict shaped the way I assumed in the report.py-only
test. This one bio needed care to construct: it has to reach GREEN/YELLOW
(enough decided flags) while carrying zero identifier-claims of any subtype
in `verify.HANDLERS` (so `verification_effective` stays False and the caveat
condition is actually reachable) — a degree/institution claim alone would
have made `verification_effective` True via ROR dispatch and hidden the gap
entirely. Confirmed this test fails identically to the isolated repro when
run against the code with the fix reverted (checked by temporarily restoring
the pre-fix condition and re-running both new tests, then restoring the fix
and re-running the full suite to confirm nothing was left mutated).

Mutation-tested the new code directly: dropping the new `and not (scholar
and scholar.get("works"))` clause entirely, and renaming the `"works"` key to
a wrong one — both caught by the new tests. Full suite: 473 → 476 tests,
green throughout.

Also ran the CLI directly on two hand-written samples (`--file`, no
`--verify`, since a live registry call isn't reproducible in this sandbox and
the network-stubbed unittest above is the rigorous version of this same
check): a clean engineer bio with real, concrete deal terms landed GREEN
17/100 with a genuine Timeline flag TRIGGERED on a real dating gap (correct —
not this fix's concern) and the "own account" caveat present (correct, since
no `--verify`/OpenAlex signal was in play at all here); a hype-heavy
fabricator bio landed GREEN 0/100 pre-`--verify`, also as expected for that
sample. Neither hand run exercises the specific OpenAlex-signal path (that
needs a stubbed registry response, which only the unittest above can give
deterministically) — the stubbed end-to-end test is the actual proof this
change works through the real pipeline, not these two.

**Cross-boundary check (per the standing review question):** `caveats()`'s
signature and return type (a list of strings) are unchanged — only an
internal boolean condition changed — so every caller (`render_terminal`,
`render_markdown`, `render_html`) needed no changes and is exercised by the
existing renderer tests, which all stayed green.

**Mandatory per-cycle mutation-testing spot-check**, one mutation in each of
the four required files, run against the full suite, then reverted:

| File | Mutation | Result |
|---|---|---|
| `scoring.py` | `LEVELS` cut boundary: `larp < cut` → `larp <= cut` | **Caught** (3 failures) |
| `names.py` | `name_matches`'s `if len(present) >= 2:` → `>= 3` | **Caught** (18 failures + 6 errors) |
| `verify.py` | `verify_institution`'s `if wanted and wanted <= have:` → `if wanted <= have:` | **Caught** (3 failures) |
| `verify.py` | ROR nearest-name tie-break: `if overlap > best_overlap:` → `>=` | **SURVIVED** — see below |
| `flags.py` | `f_contradicted`'s `if refuted or mismatched:` → `and` | **Caught** (4 failures) |

**The `verify.py` tie-break survivor is not new** — it's the identical
mutation `nightly/2026-09-04` (PR #16) already found and pinned with
`test_nearest_name_tie_break_is_deterministic_not_last_writer_wins`, but that
fix exists only on PR #16's unmerged branch, so `master` itself is still
exposed to it. Per the 2026-08-27 entry's own precedent for this exact
situation ("the actual fix here is merging... not writing this test again"),
did **not** write a second copy of the same pin — recorded in BACKLOG.md
instead. Every other mutation tried tonight remains caught; no new
production gap found in the four standing files.

### What I confirmed / refuted in BACKLOG.md

- **New finding, confirmed live and fixed**: the "own account" caveat's
  Wikipedia-only corroboration check, blind to a genuine OpenAlex hit. Full
  write-up filed under "Shipped since the original review."
- **Re-confirmed live, not duplicated**: `verify.py`'s ROR tie-break
  (`>` → `>=`) is still a real, live, unpinned survivor on `master` — matches
  PR #16's description exactly, four days old, still unmerged.
- **Re-confirmed live**: the backlog tally (10/1/4 of 15 CRITICALs) is
  unchanged and matches the 2026-09-09 entry's own corrected count exactly —
  counted directly, not carried forward.
- Did **not** re-verify any other BACKLOG.md entry tonight, including the 4
  still-open CRITICALs, PR #17's still-open timeline part (a), or the
  `re.I`-audit lead from 2026-09-04's entry. None of those were touched or
  re-derived.

### Mutation-testing log (files swept so far, by night)

- `scoring.py`: full sweep 2026-08-16. Spot-checked again tonight (fresh
  line, the `LEVELS` cut boundary in the `next()` generator) — still caught.
- `flags.py`: full sweeps 2026-08-16/17. Spot-checked again tonight (fresh
  line, flag 11's no-name-with-confirmed guard) — still caught.
- `names.py`: full sweep 2026-08-19 (on `master` since — confirmed the
  `TestBareInitialIsNotASignificantToken`/`TestZeroCandidatesIsUnanswerable`
  classes from that sweep are present in `tests/test_names.py` today).
  Spot-checked again tonight (fresh line, the script-mismatch guard) —
  still caught.
- `verify.py`: full sweep 2026-08-18. Spot-checked again tonight (fresh
  line, `verify_github`'s comparable-name gate) — still caught. Also fully
  mutation-tested tonight's own three new pieces of logic in `extract.py`/
  `verify.py` (see "Verification" above) — all caught.
- `extract.py` and `matching.py` are not among the four standing files this
  requirement names, but tonight's fix lives mostly in `extract.py`, and
  every line of it got mutation-tested directly as part of writing the fix
  (see above), not merely spot-checked.

### What I learned

- **A mutate-then-restore cycle inside the same wall-clock second can leave
  a stale `.pyc` that silently serves the previous mutation's bytecode.**
  Spent a while debugging what looked like an impossible result — calling
  `_context()` through the imported module gave a completely different
  answer than executing the exact same source (via `inspect.getsource` +
  `exec`) in a fresh namespace — before finding `__pycache__/extract.cpython-311.pyc`
  dated to an earlier mutation in the same second. CPython's default
  `.pyc` invalidation is mtime-based at one-second resolution; a rapid
  mutate/run/restore loop like this project's own mutation-testing
  discipline explicitly calls for can trip it. Fix: `find . -name
  __pycache__ -exec rm -rf {} +` (or `PYTHONDONTWRITEBYTECODE=1`) before
  *every* mutation-testing run, not just once at the start of the session —
  every command in tonight's mutation log after discovering this did both.
  Worth adding to whatever future run's mutation-testing muscle memory:
  a mutation that "wasn't caught" is worth a second look with a cleared
  cache before writing it up as a real survivor.
- **The standing "run the CLI end-to-end on a real file" requirement earns
  its keep by being taken completely literally.** Both follow-on bugs
  tonight (the word-wrap boundary, the passive-voice citation regex) were
  invisible to the offline unit tests — those use Python string literals,
  which never word-wrap, and a distance too short to trip the passive-voice
  collision. Only a real `.txt` file, hand-wrapped the way a person's editor
  actually wraps text, and a live registry hit landing far enough away,
  surfaced them. This is the same lesson as the 2026-08-17 entry's
  `to_prose()` name gap and the 08-31 LinkedIn-paste content-loss bug: the
  bug is not always in the code you just changed, and a synthetic fixture
  engineered to be minimal can accidentally engineer the bug away too.
- Widening a data field that looked entirely unused outside one guard
  (`claim.context`) was safe here because a grep actually confirmed zero
  other readers before relying on that — worth continuing to check
  explicitly rather than assuming from a field's narrow original purpose.

### What the next run should pick up first

1. **The open-PR queue (#11–#14) is a human-merge-queue matter, not a code
   problem** — flagged for visibility above, not acted on, per standing
   instructions. All four are clean, small, and mutually non-conflicting by
   file; #13 and tonight's branch both touch `flags.py`/`verify.py`
   respectively but not the same lines.
2. **The core reverse-path gap is still the core reverse-path gap** — four
   CRITICAL write-ups, zero investigated tonight. Every prior entry's advice
   still stands: do the OpenAlex affiliation/`years`-array corroboration
   work (PR #11 already started this) before attempting any verdict
   stronger than UNKNOWN-with-evidence.
3. Now that `_NON_ATTRIBUTION_CONTEXT_RE` has one negative-voice exclusion
   (`cit(?:...)(?!\s+by\b)`), worth a closer read of its other alternatives
   for the same passive/active ambiguity before assuming they're clean —
   not checked tonight beyond the one collision the end-to-end test actually
   surfaced. `client`/`employer`/`colleague`/`co-worker`/`teammate` in
   particular are bare nouns with no voice distinction at all and could
   plausibly have their own false-negative shape once a sentence widens
   enough to reach one that describes someone else's role, not the
   subject's own disclaiming statement — untested speculation, not a
   confirmed finding.
## 2026-09-04 (nightly run)

**Open-PR queue, unchanged since last night's entry and growing: still not
merged.** Five `nightly/*` PRs are open against `master`, all draft, clean,
green, and — per each PR's own description — touching disjoint files from
one another: #11 (`2026-08-30`, OpenAlex merge-risk detection —
`providers.py`/`flags.py`), #12 (`2026-08-31`, LinkedIn-paste misdetection —
`linkedin.py`), #13 (`2026-09-01`, confidential/pre-revenue work —
`matching.py`/`flags.py`), #14 (`2026-09-02`, word-wrap breaking negation —
`matching.py`), #15 (`2026-09-03`, a fixed-width context window clipping a
disclaimer — `extract.py`/`verify.py`). None of this was actioned tonight —
merging is the project's deliberate human-in-the-loop gate — but it is worth
repeating from last night's entry: this is now explicitly a human-merge-queue
problem, not a code problem, and the queue has not gotten shorter.

**8 [FIXED] / 1 [PARTIALLY FIXED] / 6 still open of the 15 CRITICALs —
unchanged by tonight** (re-verified directly against `master`'s current
`BACKLOG.md`: `grep "^### " under "## CRITICAL (15)"`, same counts as every
recent PR description). Tonight's fix is a MAJOR-adjacent finding under the
already-[FIXED]-adjacent flag 13 write-up, not one of the 15 named
CRITICALs, so the tally itself doesn't move. The core gap (this run's
highest-priority item per the standing brief) was not touched tonight — see
"What the next run should pick up first" below for why, and what a
follow-up night should actually do about it.

### What I did

**Primary item:** flag 13 (self-applied doctoral title) matched only the
exact title-case spelling of "Dr."/"Prof."/"Professor" — `_DOCTORAL_HONORIFIC_RE`
had no `re.I`. Found via the red-team-for-evasion lens: not a clever attack,
just the default output of an all-lowercase LinkedIn-paste style or an
all-caps resume header, both common on their own. Confirmed live before
touching anything: the flag's own motivating fixture ("Dr. Anke
Verstraeten..." with an education list stopping at Master's), re-cased to
"dr. Anke Verstraeten...", read UNKNOWN ("no title claimed") instead of
TRIGGERED, through `run_audit` end to end. Wrote the failing test first
(watched it fail: `'UNKNOWN' != 'TRIGGERED'`), added `re.I`, watched it
pass. Grepped every consumer of the regex — `f_title_inflation` is the only
one — so no cross-boundary risk. The name-adjacency check immediately below
the regex (title must sit next to the subject's own name, same line, capped
window) is what actually prevents a false accusation here, and it is
untouched by letter case, so this closes a false-negative gap without
loosening anything that guards against a false positive.

**Mandatory mutation-testing pass, all four required files.** Time-boxed,
new lines each (not re-testing guards prior nights already pinned):

- `scoring.py`: `category_scores`'s own `r.status not in (TRIGGERED, PASSED)`
  → `not in (TRIGGERED,)` **survived**. The one existing test for this
  filter (`TestCategoryScoresExcludeUndecided`) pairs a TRIGGERED flag with
  an otherwise-UNKNOWN category — PASSED and UNKNOWN get excluded
  identically either way when nothing in that category TRIGGERED, so it
  can't discriminate this mutation. A category where every decided flag
  PASSED and none TRIGGERED is the case that does: the mutated filter drops
  the whole category out of `buckets`, so it's simply missing from
  `categories` in the report — not "unscored", just silently absent, as if
  never evaluated. Pinned with a PASSED-only "rhetoric" category fixture
  (`tests/test_scoring.py::TestCategoryScoresIncludePassed`).
- `flags.py`: widened flag 13's own same-line tail slice from `[:60]` to
  `[:600]` — **survived**. Every existing fixture keeps the subject's name
  within a few words of the honorific, so the cap that stops a distant,
  unrelated mention of the subject from being misread as a self-applied
  title (the function's own comment explains why it exists) was never
  actually exercised by any test. Pinned with a fixture where "Dr. Schilt"
  (someone else's title) and the subject's own name share one physical line
  ~130 characters apart, describing a colleague's work with no doctorate —
  must stay UNKNOWN; the widened window instead reads it as self-applied
  (came back PASSED on the mutation, driven by the word "doctorate"
  appearing in the subject's own disclaiming sentence and being read as
  degree evidence — a separate, smaller oddity worth another look some
  night, not chased further tonight since the pinning test only needs the
  UNKNOWN/not-UNKNOWN discrimination).
- `verify.py`: `verify_institution`'s ROR "nearest listed name" tie-break,
  `if overlap > best_overlap:` → `if overlap >= best_overlap:` — **survived**.
  Two hits that both fail `wanted <= have` but score identical overlap
  fractions should report the first one ROR listed, deterministically;
  `>=` lets a later equally-relevant hit silently overwrite it in the
  evidence text shown to the reader. Pinned with two synthetic ROR items
  engineered to the same overlap fraction (0.2 each) by construction.
  Cosmetic in impact (status stays NOT_FOUND either way; only which
  "nearest" name gets quoted changes) but still a real, previously-untested
  behavior, so it gets a test rather than a shrug.
- `names.py`: two mutations tried (`len(present) >= 2` → `>= 3`, and the
  Latin/non-Latin XOR script-mismatch guard flipped to AND) — both **caught
  immediately and heavily** (18-35 failures each). No survivor tonight; this
  file remains the most thoroughly pinned of the four.

All three survivors are closed with a regression test alone — none needed a
production fix, since in each case the guard itself was already correct,
just unpinned. Same fail-first discipline as the primary fix: mutate, watch
the new test fail, restore, watch it pass.

### What I confirmed / refuted in BACKLOG.md

- **Confirmed** (live repro): flag 13's case-sensitivity gap is real and
  exactly as described above — not previously in BACKLOG.md as its own
  finding (the flag 13 write-up predates this specific gap); added a
  `[FIXED — nightly/2026-09-04]` note under the existing "Flag 13" entry.
- **Did not** re-verify any of the 6 still-open CRITICALs, or re-derive the
  core-gap's own status, beyond the tally check above — no new evidence
  gathered on either tonight.

### Mutation-testing log (files swept so far, by night)

- `scoring.py`: 2026-08-16 (12 mutations, 6 real) direct to `master`;
  2026-08-26 spot-check (1 mutation, caught); **tonight** (1 new mutation,
  a genuine survivor, pinned) — `master` now has two independent real
  pins in this file.
- `flags.py`: 2026-08-16/17 (33 mutations, 13 real) direct to `master`;
  several nightly spot-checks since, all caught; **tonight** (1 new
  mutation in flag 13's own tail-window logic, a genuine survivor, pinned).
- `names.py`: full 13-mutation sweep on unmerged `nightly/2026-08-19` (PR
  #5, still not on `master`); a 1-guard pin landed directly on `master` via
  2026-08-27's run; **tonight**, 2 more mutations tried directly against
  `master`, both caught — `master`'s own coverage of this file, independent
  of the still-unmerged PR #5, keeps growing.
- `verify.py`: full 6-mutation sweep on unmerged `nightly/2026-08-18` (PR
  #4, still not on `master`); the `wanted <= have` guard's own pin landed
  directly on `master` (`tests/test_verify.py::test_a_stopword_only_institution_claim_cannot_verify_against_any_hit`,
  confirmed present tonight); **tonight** adds a second, different survivor
  in the same function (the tie-break determinism above), also pinned
  directly on `master`.

**All four files have now had at least one real mutation-testing pass
directly on `master` itself** (not only on an unmerged branch) — this is a
meaningfully better state than several recent entries described, where
`names.py`/`verify.py` coverage existed only on branches that never merged.
`master`'s own protection has been growing night over night regardless of
the queue; the queue mainly costs re-discovery effort on `providers.py` /
`linkedin.py` / `matching.py` / `extract.py`, whose sweeps are still stuck
on unmerged branches.

### What I learned

- A regex missing `re.I` is exactly the shape of bug this project's
  red-team lens is built to catch: no adversarial cleverness needed, no
  crafted input — just an ordinary stylistic choice (writing in lowercase,
  or in caps) that happens to fall outside a pattern's assumed case. Worth
  grepping `flags.py`, `matching.py` and `extract.py` for other
  `re.compile(...)` calls that lack `re.I` where nothing in a nearby comment
  explains why case-sensitivity is deliberate (as it is, correctly, for
  `DEGREE_RE` per the 2026-08-23 fix) — did not have time to do that sweep
  tonight; flagging as the cheapest next lead.
- Mutating a same-line character cap (60 → 600) is a different kind of
  mutation than the boundary/comparison mutations this project usually
  tries (`>` vs `>=`, dropping a guard clause) — it's a magnitude change to
  a constant with no single "obviously correct" alternative to test against.
  Worth remembering as its own mutation category for future sweeps: any
  hard-coded window, cap, or threshold constant is itself mutable, not just
  the comparisons around it.

### What the next run should pick up first

1. **The `re.I` grep this entry ran out of time for.** Check every
   `re.compile` in `flags.py`, `matching.py`, `extract.py` for a
   case-sensitivity choice that isn't explained by a nearby comment the way
   `DEGREE_RE`'s is — each unexplained one is a candidate for tonight's
   exact bug shape.
2. **The core gap, still.** Unchanged from every recent entry: items (1)
   and (3) of its fix direction (OpenAlex/Crossref hits becoming derived
   `Claim`s with provenance; a reconciliation step producing CONTRADICTED
   for a quantitative mismatch) are still fully open, and still blocked on
   the disambiguation groundwork PR #11 started. Re-verify OpenAlex's rate
   limits and response shapes live before extending it — the brief's own
   numbers are dated 2026-08-14 and this project has already learned once
   that they drift.
3. **The merge queue.** Still five deep, still not this project's call to
   resolve — but if a run ever gets explicit merge access or instruction to
   consolidate, `providers.py`/`flags.py` (#11) and `matching.py`/`flags.py`
   (#13, #14) are the two places multiple open PRs touch the same file and
   will need real conflict resolution, not just a fast-forward.
---

## 2026-09-08 (nightly run)

### Open-PR check (read this first)

**The merge queue is now six deep and has not moved since the last entry in
this file (2026-08-27).** Six `nightly/*` branches are open against
`master`, all draft, all clean and green individually, none merged:

| PR | branch | date | touches |
|----|--------|------|---------|
| #11 | `nightly/2026-08-30` | 08-30 | `providers.py`, `flags.py` (OpenAlex merge-risk) |
| #12 | `nightly/2026-08-31` | 08-31 | `linkedin.py` (CV misdetected as a paste) |
| #13 | `nightly/2026-09-01` | 09-01 | `flags.py` (confidentiality/pre-revenue escape hatch) |
| #14 | `nightly/2026-09-02` | 09-02 | `matching.py` (word-wrap breaks negation) |
| #15 | `nightly/2026-09-03` | 09-03 | `extract.py`, `verify.py` (disclaimer context window) |
| #16 | `nightly/2026-09-04` | 09-04 | `flags.py` (lowercase/all-caps doctoral title) |

Each PR's own body already documents the others open at the time it was
written, so this isn't new information — but the 08-27 entry's own warning
("ten nights of unmerged, non-conflicting work is nearly as bad as ten
nights of no work") has now gone unheeded for **eleven more nights** with
zero merges, and there are no branches at all for 09-05, 09-06 or 09-07 —
either the schedule didn't fire those nights or those runs' output never
made it to a pushed branch; either way it's a second, separate gap worth
someone's attention alongside the merge queue itself. I did not attempt to
resolve or merge any of #11–#16 — merging is this project's deliberate
human-in-the-loop gate, not something an autonomous run should route
around. This entry's own branch (`nightly/2026-09-08`) is forked fresh from
`master`'s current tip (still `9f71c98`, the 08-27 merge) and touches only
`extract.py`, `BACKLOG.md` and two test files, disjoint from all six
branches above, so it should not conflict with any of them at merge time.

### Backlog tally (CRITICAL, 15 total)

**10 [FIXED] / 1 [PARTIALLY FIXED] / 4 still open.** Verified directly
against `master`'s current `BACKLOG.md` by grepping `^### ` under
`## CRITICAL (15)`, not carried over by assumption. Of the 4 still open, 3
are duplicate write-ups of the same core gap (the tool cannot check a claim
that carries no identifier) and the 4th is the non-Latin-script `normalize()`
gap already marked partial. This tally does not move tonight — the item I
fixed is a MAJOR-severity finding (timeline fairness), not one of the 15
CRITICALs — but is worth restating since none of #11–#16 touch a CRITICAL
either; the actual fixes sitting in the queue are mostly MAJOR/MODERATE
fairness and correctness bugs, not core-gap progress.

### What I did

Chose the mandatory mutation-testing pass first, since it doubles as a
check on whether the merge queue's absence has left `master` newly exposed.
One mutation each in `scoring.py` (`coverage >= MIN_COVERAGE` boundary,
`_apply_floors`' `<=` tie-break), `names.py` (the "zero usable candidates"
guard flagged as unpinned-on-`master` in the 08-27 entry), and `verify.py`
(the `wanted <= have` ROR subset test, independently re-found unpinned on
`master` by four separate nightly runs per that same entry) — **all three
are now caught** (38+5, 4, and the scoring ones all failing loudly), a
genuine improvement over 08-27's snapshot: whatever merged between then and
now (`master` is still at the same `9f71c98` tip, so this must have
happened via direct fixes on `master` before 08-27's last merge, or I'm
misreading which commit introduced the pin — either way, confirmed live,
not assumed). `flags.py`'s flag 10 word-count boundary (`>= 40`) also
caught. No survivor found in this spot-check; see the mutation-testing log
below for exact mutations tried.

With the mandatory sweep clean, went looking for a fresh, small, correctly-
scoped finding not already claimed by one of the six queued PRs (to avoid
adding a seventh entry to an already-stuck queue with work that just
duplicates what's sitting unmerged). Found one: BACKLOG.md's MAJOR-severity
"Timeline flag accuses ordinary CVs" entry, untouched by any open PR,
confirmed live on `master` exactly as written:

```
$ larp-meter --file student.txt --name "Jane Student"    # "MSc ..., 2025 - 2027"
⚪ INSUFFICIENT DATA · evidence coverage 19%
[12] TRIGGERED: Timeline does not add up: date(s) stated as past but in the future: 2027.

$ larp-meter --file veteran.txt --name "Maria Alvarez"   # "twelve years... since 2021 has led..."
⚪ INSUFFICIENT DATA · evidence coverage 14%
[12] TRIGGERED: claims 12 years of experience, but the earliest date anywhere
     in the profile is 2021 — at most ~5 years are accounted for.
```

Fixed part (b) only (the future-date/range half): `extract.py`'s
`FORWARD_MARKERS` now recognises `class of`, and a new `_is_forward_year()`
helper also exempts the back half of an ascending `YYYY - YYYY` range from
the "date stated as past but in the future" check — a course of study, a
grant term or a multi-year contract states an expected boundary, not a
claimed-past event. The range check requires the first year to be no later
than the second (`<=`, not `<`, since a same-year "range" like a one-year
program written `2027 - 2027` is the same boundary case, not a new one) and
is scoped to a 10-character lookback so it can't reach across an unrelated
earlier year. Re-ran the student repro above post-fix: `[12] Not enough
dated detail to test the timeline` — no longer flagged, no longer part of
the "Only N of 13 flags decided" total in a way that manufactures coverage
(it moves from a wrongly-decided TRIGGERED to a correctly-undecided
UNKNOWN, which is the honest direction per the project's own coverage
rule).

**Did not fix part (a)** (the recent-roles-only false accusation — the
veteran repro above). Drafted BACKLOG's own suggested fix (gate the
duration check on a dated education anchor) and it broke an existing,
apparently-deliberate test — `test_flags.py`'s
`test_career_slack_is_exactly_three_years`, whose second half
(`"21 years of experience in robotics. Founded the lab in 2009."` →
TRIGGERED) has no education claim at all, only a "founded" date, and would
flip to UNKNOWN under that gate right alongside the genuine false-accusation
case. A minimum-dated-years-count gate has the identical problem. The real
distinguishing feature — "founded the lab" plausibly marks the origin of
the described career, "has led the team since" only dates a role change
within one already established — is a semantic distinction current
extraction has no way to make, and guessing at it under a time-box risks
trading one false-accusation mode for another (or opening a new evasion:
a fabricator prepending any "founded X in <recent year>" clause to earn the
same leniency). Left fully documented in BACKLOG.md for whoever takes this
on with more time.

### What I confirmed / refuted in BACKLOG.md

- **Confirmed** (live repro, both halves, exactly as written): "Timeline
  flag accuses ordinary CVs" is real on `master`. Fixed (b), left (a) open
  with the new design nuance recorded above and in BACKLOG.md itself.
- **Confirmed** (live repro): the `names.py` "zero usable candidates" guard
  and `verify.py`'s ROR `wanted <= have` subset test, both called out as
  unpinned-on-`master` in the 08-27 entry, are now caught by the existing
  suite — recorded above so nobody re-derives this a fifth time.
- Did not re-verify any other BACKLOG.md entry tonight, including the
  6-PR-deep queue's own findings (#11–#16) — those stand on their own
  branches' descriptions, unexamined by this run beyond confirming they're
  still open and still disjoint from tonight's change.

### Mutation-testing log

- `scoring.py`: `coverage >= MIN_COVERAGE` → `>` — caught
  (`test_coverage_exactly_at_min_coverage_is_still_scored`).
  `_apply_floors`' `<=` → `<` tie-break — caught
  (`test_exact_tie_keeps_the_ordinary_summary_not_the_floor_message`).
  Spot-check only, consistent with prior nights' full sweeps holding.
- `names.py`: `name_matches`'s `if not usable: return None` inverted to
  `if usable: return None` — caught heavily (38 failures + 5 errors). This
  guard was called out as live-and-unpinned on `master` in the 08-27 entry;
  it is solidly pinned now.
- `verify.py`: `verify_institution`'s `if wanted and wanted <= have:` →
  `< have` — caught (`test_word_order_and_stopwords_do_not_break_the_match`).
  Same status: called out as unpinned in the 08-27 entry, solidly pinned
  now.
- `flags.py`: flag 10's `ctx.word_count >= 40` → `> 40` — caught. Flag 11's
  `if refuted or mismatched:` not re-tried tonight (already pinned per the
  2026-08-16/17 sweep log).
- `extract.py` (not one of the four mandatory files, but the module this
  cycle's own fix touched): mutation-tested all three new lines directly —
  the `<=`/`<` range-boundary comparison **survived** on the first attempt
  (every existing ascending-range fixture has two *different* years, so
  nothing exercised the equal-boundary case) and is now pinned with
  `test_equal_year_range_boundary_still_exempts_the_second_year`, which
  calls the new `_is_forward_year()` helper directly rather than going
  through `extract_claims()` — an equal-value range collides with the
  claim-dedup key otherwise, since a real ascending range's own start year
  passing through unaffected made a duplicate-value assertion untrustworthy.
  Removing the new `class of` marker and disabling the range check outright
  were both also caught.
- **Mutation-testing hygiene note, recorded so nobody repeats this:**
  reached for `git checkout -- larp_meter/extract.py` to snap back a
  deliberate mutation partway through this exact pass and it discarded my
  *entire* uncommitted fix, not just the mutation — the identical trap the
  2026-08-15 entry already documented under "what I learned." Had to redo
  the `FORWARD_MARKERS`/`_RANGE_START_RE`/`_is_forward_year` edit from
  scratch. From this point on used `shutil.copy` to a scratch path before
  each mutation and restored from that copy, never `git checkout`. If
  you're mutation-testing a file with uncommitted changes, do the same —
  the existing warning in this file is correct and was not exaggerated.

### What I learned

- The 08-27 entry's "this is now explicitly a human-merge-queue problem"
  framing has aged into something stronger tonight: it isn't just that
  fixes sit unmerged and get independently rediscovered (as happened four
  times with the `verify.py` guard) — it's that *this* run couldn't safely
  pick the two next-most-obvious targets (the "Timeline" finding's own part
  (a), or anything in `flags.py`) without either duplicating one of #11–#16
  or landing a second set of `flags.py`/`matching.py` edits that would
  conflict with them at merge time. The queue isn't just wasting effort
  now, it's actively narrowing what a new, small, independent branch can
  safely touch. `extract.py` was the correct choice tonight specifically
  because none of #11–#16 touch it.
- Confirming a "still unpinned on master" claim from a five-night-old
  NIGHTLY entry before trusting it paid off: two of the three guards it
  named turned out to already be solidly caught, which means something did
  land on `master` for them since 08-27 (or the 08-27 entry's own spot-check
  methodology under-tested them at the time) — either way, worth re-
  confirming rather than copying forward as still-broken.

### What the next run should pick up first

1. **Still the merge queue.** Six PRs, eleven nights, zero merges. Nothing
   an autonomous run can do about this directly, but keep restating it at
   the top of this file exactly as this entry and the 08-27 one did — it is
   the single highest-leverage fact for whoever has merge access to act on.
   Also worth flagging to a human: no `nightly/*` branch exists for 09-05,
   09-06 or 09-07 — check whether the schedule silently stopped firing
   those nights.
2. **"Timeline flag accuses ordinary CVs", part (a).** Now has a much more
   precise problem statement than before (see BACKLOG.md and "What I did"
   above): find a way to distinguish "this date marks the origin of the
   described career/venture" from "this date marks a role change within an
   already-established one" without breaking
   `test_career_slack_is_exactly_three_years`. A possible angle not yet
   tried: treat `founded`/`co-founded`/`established` specifically (verbs
   that assert creation of the thing being described) as a stronger anchor
   than an ordinary role-start date like "has led since," rather than
   trying to key off degree/education presence at all.
3. **The core gap, continued** (unchanged from every prior entry): the
   reverse-path architecture is still the standing highest-value item once
   the queue clears enough to safely build on. Re-verify the OpenAlex rate
   limits and response shapes live before extending `providers.py` — it's
   been three weeks since the last live check recorded in this file.
## 2026-09-09 (nightly run)

### ⚠ Open-PR queue: seven unmerged `nightly/*` PRs, dating back to 2026-08-30 (10 nights)

**Read this first — for human visibility, not something to act on by pushing
more commits to any of these.** `master`'s tip is the 2026-08-27 merge
(`9f71c98`); PRs #1–#10 (2026-08-15 through 2026-08-27) are all already
closed and their content is on `master` via manual merge commits (the human
reviewer merges locally rather than through GitHub's button, which is why
GitHub shows them `merged: false` despite the content being live — verified
by reading `master`'s own git log, not by trusting the PR list's flag). But
**every night since 2026-08-30 is still open, unreviewed, and unmerged**:

| PR | Branch | What it claims | CI / comments |
|----|--------|-----------------|-------|
| #11 | nightly/2026-08-30 | Flag an OpenAlex "best" pick that's likely a merged entity | no CI configured, 0 comments |
| #12 | nightly/2026-08-31 | An ordinary CV was mistaken for a LinkedIn paste and silently lost content | no CI configured, 0 comments |
| #13 | nightly/2026-09-01 | Confidential and pre-revenue work is not deception | no CI configured, 0 comments |
| #14 | nightly/2026-09-02 | A word-wrap can hide a denial from `is_negated` | no CI configured, 0 comments |
| #15 | nightly/2026-09-03 | A fixed-width context window clipped a disclaiming phrase far from its identifier | no CI configured, 0 comments |
| #16 | nightly/2026-09-04 | A self-applied doctoral title in lowercase or all-caps was invisible to flag 13 | no CI configured, 0 comments |
| #17 | nightly/2026-09-08 | A current student's own study dates read as a fabricated future claim | no CI configured, 0 comments |

All seven are drafts, all report `pending`/no status checks (there is no CI
workflow in this repo — `get_status` returns `total_count: 0` for every one
of them), and none has a single review comment. This isn't a blocked queue
in the sense of failing checks or unresolved conflicts — it's simply seven
nights of reviewed-by-nobody work sitting untouched, the oldest ten days
old. Per the 08-27 entry's own note, this was already "the single biggest
drag on this project" at five deep; it is now seven deep and has not moved
in two weeks. Not something tonight's branch can fix (merging is this
project's deliberate human-in-the-loop gate) — flagging it again because
letting it go unmentioned is exactly the state-drift failure the standing
instructions warn about.

### Backlog tally

**10 [FIXED] / 1 [PARTIALLY FIXED] / 4 still open**, of the 15 CRITICALs —
**this corrects the number two nights back**, not a change from new work
tonight. Counted directly (`grep -c` on `## CRITICAL (15)`'s own `### `
headers), not carried forward from memory: 10 carry `[FIXED]`, 1 carries
`[PARTIALLY FIXED]`, and the remaining 4 (lines 761, 832, 878, 922 — all
restatements of the same one-way-funnel/zero-registry-reach architectural
gap from different angles of the original 5-lens review) are open. The
2026-08-27 entry reported "8 / 1 / 6" and every night since carried that
number forward; it was a miscount when written, not a figure that changed
later — nothing in the CRITICAL section has flipped state since 08-27.
Full detail on how this was found in BACKLOG.md's new top entry.

### What I did

**Mandatory per-cycle mutation-testing pass, done as a full systematic
sweep this time** (~20 hand-applied mutations: comparison-operator flips,
boundary shifts, and/or inversions, dropped guards) across the three files
that hadn't had a fresh pass in a while — `names.py`, `verify.py`,
`flags.py` — rather than the usual single spot-check, specifically because
tonight also turned up a case (below) where a prior spot-check's own
conclusion was wrong. `scoring.py` was spot-checked (1 mutation, the
`coverage >= MIN_COVERAGE` boundary) and confirmed still caught; it has
extensive dedicated boundary/tie-break test classes already
(`TestLevelBoundaries`, `TestCoverageBoundaryIsInclusive`,
`TestFloorTieBreak`) from the 2026-08-16 sweep and its later top-ups, so it
did not get the full sweep treatment tonight.

**One real, pinned survivor** — `flags.py`'s buzzword short-text carve-out
(`f_buzzwords`, line 203): `ctx.word_count < 25` survived a mutation to
`< 24` with the full suite green. A 2026-08-17 test already pins the upper
edge (25 words must NOT get the carve-out); nothing pinned the lower edge,
and — this is why a quick "add the missing boundary case" pass would still
have missed it — the two directions are not symmetric. At 24 words with
*zero* buzzwords, both the real and mutated code return PASSED (different
message, same status), so a naive boundary test using a hype-free fixture
proves nothing. The mutation only becomes observable with a *sparse* hit:
one buzzword in 24 words. Real code: `UNKNOWN` ("too short to judge").
Mutated code: falls through to the ordinary density formula
(1/24×100 ≈ 4.2%, under the ≥4-distinct trigger gate) and returns `PASSED`
("density is normal") — turning an honestly-undecidable flag into a
decided, coverage-counting one on a technicality of exactly which one-word
boundary a profile happens to sit on. Wrote the test first, watched it
fail against the mutated line (`AssertionError: 'PASSED' != 'UNKNOWN'`),
confirmed it passes against the restored line, then re-ran the full suite
(474 tests, green). Detail and full mutation list in BACKLOG.md's new top
entry, including two mutations investigated as possible survivors
(`names.py` lines 59 and 152) and ruled out as equivalent — reasoned
through rather than guessed, since an untested equivalent mutant left
unexplained is exactly the kind of thing a future night re-discovers and
wastes a cycle on.

One process note for whoever reruns this kind of sweep: a stale
`__pycache__` directory produced a false reading mid-session — a `.pyc`
left over from an earlier `sed`-and-restore round briefly made an
*unmutated* file behave like a *mutated* one when invoked directly via
`python3 -c` (not through `python -m unittest`, which does its own
discovery-time import and wasn't affected). Caught it by noticing the
result was inconsistent with an identical check five minutes earlier, and
resolved by deleting `__pycache__` before re-testing. Worth remembering:
after any manual `sed`-in-place mutation-and-restore loop, clear
`__pycache__` before trusting a fresh interpreter session's output,
especially when checking a single flag function directly rather than
through the full suite.

**End-to-end pipeline check** (mandatory after touching `flags.py`,
including test-only changes): ran the CLI on two hand-written samples.
A clean profile (named subject, one attributable DOI, credentials matching
claimed field, no hype) came back `PASSED` on Buzzword Density and No
Verifiable Output, `INSUFFICIENT DATA` overall (14% coverage, no name/
`--verify` — expected, this profile is short). A deliberately larpy profile
("visionary disruptor... paradigm-shifting... synergy-driven... raising a
seed round... massive market traction") triggered Buzzword Density (8
distinct terms, 19.6/100 words) and Fundraising Without Traction, as
expected. Confirms the real pipeline reaches `f_buzzwords` as intended —
this change was test-only, but the failure pattern this project is
watching for is exactly "a unit test called the function directly and
never confirmed the pipeline reaches it the same way", so ran it anyway.

### What I confirmed / refuted in BACKLOG.md

- **Refuted (with a live repro, not by re-reading the old write-up)**: the
  2026-08-27 entry's claim that `verify.py`'s `verify_institution`
  `if wanted and wanted <= have:` guard was "confirmed still live and
  unpinned on master". It was not. The guard was pinned on `master` twice
  before that entry was written — 2026-08-23 (`7d07d08`,
  `test_a_claim_of_nothing_but_stopwords_cannot_be_verified`) and again
  2026-08-26 (`test_a_stopword_only_institution_claim_cannot_verify_
  against_any_hit`, this file's own entry immediately below tonight's).
  Live-reproduced tonight: mutating that guard on current `master` fails
  3 tests. The likely mechanism: PRs #4/#6/#7/#9 each branched from
  `master` *before* 2026-08-23 and so were each individually accurate about
  the commit they branched from, but by 08-27 the fix had already landed on
  `master` by a different path, and nobody re-ran the mutation against the
  actual tip before writing "still live" — see BACKLOG.md's new entry for
  the fuller account and the lesson for future nights (reproduce against
  current tip before citing other write-ups as corroboration).
- **Corrected**: the running backlog tally BACKLOG.md tracks (previously
  "8/1/6") — see "Backlog tally" above.
- **Confirmed** (live mutation, not reasoning from the docstring alone):
  `flags.py`'s buzzword short-text carve-out lower boundary was a real,
  unpinned gap — see "What I did" above. Now pinned.
- **Investigated and ruled equivalent, not pinned**: `names.py` line 152
  (`if not extra or all(w in mine for w in extra):`) and line 59 (the
  `split`-reading particle filter in `tokens()`). Reasoning in BACKLOG.md's
  new entry. Neither produced a false `True`/accusation in any scenario
  tried tonight; recorded rather than dropped in case a future pass finds
  a scenario this one didn't construct.
- Did **not** re-verify any BACKLOG.md entry outside tonight's own scope —
  in particular the 4 still-open CRITICALs and the 25 MAJOR findings were
  not re-examined tonight.

### Mutation-testing log (files swept so far, by night)

- `scoring.py`: 2026-08-16 (12 mutations, 6 real, all pinned) — direct to
  `master`. Spot-checked again tonight (1 mutation), still caught.
- `flags.py`: 2026-08-16/17 (33 mutations, 13 real, all pinned) — direct to
  `master`. **Tonight: full ~7-mutation targeted sweep of numeric/boundary
  comparisons** (word-count thresholds, buzzword variety/density gates,
  vague-partnership tie, logo-wall count, future-year and career-length
  boundaries) — 1 new real survivor found and pinned (the 24-word carve-out
  above); the other 6 were already caught.
- `names.py`: full 13-mutation sweep on unmerged `nightly/2026-08-19` (PR
  #5, still not on `master`). **Tonight: ~9 additional targeted mutations
  directly against `master`** (script-mismatch guard inversion, mononym
  branch condition, `present`-count boundary, `at_an_end` `or`→`and`,
  matched-membership inversion, particle-filter drop in two places) — all
  caught except the two investigated-and-ruled-equivalent cases above.
- `verify.py`: full 6-mutation sweep on unmerged `nightly/2026-08-18` (PR
  #4, still not on `master`). **Tonight: ~9 additional targeted mutations
  directly against `master`** (GitHub comparable-name threshold, ambiguous-
  acronym length, GitHub-token host check, HTTP 404/410 handling, arXiv
  error-page `or`→`and`, stopword-token filter, the `wanted and` guard
  itself, ROR best-overlap tie-break `>`→`>=`, org-stem `startswith`→
  `endswith`) — all caught, including a live re-confirmation that the
  `wanted and` guard (see correction above) is genuinely pinned now.

**All four required files have now had at least one real mutation-testing
pass directly reflected on `master` itself** (not only on an unmerged
branch) for every file except the two full sweeps that predate this
entry and still live only on PRs #4 and #5 — `scoring.py` and `flags.py`
are the most thoroughly covered; `names.py` and `verify.py` have a mix of
their original full sweep (unmerged) plus multiple later spot-checks/
targeted sweeps landed directly on `master`.

### What I learned

- Tonight's biggest finding wasn't a code bug — it was a *process* bug: a
  two-week-old false claim ("still live and unpinned") survived unnoticed
  in this file because nobody re-ran the mutation against the current tip
  before repeating it, and "N independent PRs describe the same thing" was
  read as corroboration when it was really N branches all forked before a
  since-landed fix, none of which had rebased. Multiple write-ups agreeing
  with each other is not the same evidence as one live reproduction against
  `HEAD`. Given how heavily this project's own process leans on nightly
  write-ups as the only memory between runs, this is worth taking
  seriously — a bad note doesn't just waste one night, it compounds.
- A stale `__pycache__` can make a manual mutation-and-restore loop lie to
  you when you invoke a function directly rather than through
  `python -m unittest` — see the process note above.
- Confirmed by direct construction, not just intuition: `names.py`'s
  `present`-set construction (searching *the subject's own tokens* against
  the registry blob, rather than the other way around) has a useful
  invariant baked in almost by accident — any candidate word that's also
  one of the subject's own tokens is *always* already counted in `present`
  before the "does this extra word match the subject's own name" fallback
  logic ever runs. That's why that fallback's `or` branch is unreachable-
  when-true. Worth knowing if anyone touches that function: the fallback
  reads like it's doing real work but, given the current shape of the
  function, it structurally cannot be.

### What the next run should pick up first

1. **Still a human-merge-queue problem, now worse (7 nights, 10 days).**
   Nothing new to do about it from inside a nightly run beyond keeping
   branches small, independent, and visible — see the note at the top of
   this entry.
2. **The core gap** (OpenAlex/Crossref hits becoming derived `Claim`s with
   provenance; a reconciliation step producing real `CONTRADICTED` status)
   is still fully open beyond the 08-27 visibility slice. Re-verify the
   OpenAlex rate-limit numbers live before extending that work further —
   it's been three and a half weeks since they were last checked against a
   real request.
3. Before trusting any older NIGHTLY.md/BACKLOG.md claim of the form "still
   live/unpinned on master" or "N other write-ups agree", reproduce it
   against the actual current tip first — see "What I learned" above. This
   applies to every remaining open item in this file, not just the one
   caught tonight.
4. `linkedin.py` red-team pass — still due a fresh look once the queue
   clears (PRs #3/#7's fixes are already on `master`; nobody has done an
   independent third pass since).
  line, `LEVELS` cut boundary) — still caught.
- `names.py`: full sweep 2026-08-19 (merged). Spot-checked again tonight
  (fresh line, `present`-count boundary) — still caught.
- `verify.py`: full sweep 2026-08-18 (merged) plus several later spot-checks
  (merged). Tonight: the `wanted <=` guard is still caught; the ROR tie-break
  is a confirmed-live, still-unpinned survivor whose fix sits only on
  unmerged PR #16 — see above.
- `flags.py`: full sweeps 2026-08-16/17 (merged). Spot-checked again tonight
  (fresh line, `f_contradicted`'s `or`/`and`) — still caught.
- `report.py`: **first mutation-testing attention this file has had** — not
  one of the four standing files, but tonight's own new code in it was
  mutation-tested directly (see "What I did" above), both mutations caught.
  The rest of `report.py` (the renderers, `_esc`/`_safe_href`'s HTML-escaping
  logic, `save_all`'s path handling) has never had a dedicated sweep — worth
  a full pass some future night given it's the one file that formats what a
  human actually reads.

### What I learned

- The "own account" caveat and flag 6's `f_output` read the identical
  `signals["openalex"]` value but had drifted to disagree about what counts
  as corroboration — flag 6 checks `scholar and scholar.get("works")`
  directly, `caveats()` checked nothing at all. Two consumers of the same
  signal silently diverging is the same shape of risk as the `_attribute`/
  `None` cross-boundary bug this project's own standing instructions call
  out by name; worth grepping for other places `ctx.signals`/`report["signals"]`
  is read in more than one file and checking each reader agrees on what a
  given value means, rather than assuming a signal's meaning is obvious from
  its name.
- A hand-built report dict test (report.py alone) and a real stubbed-pipeline
  test (through `cmd_text`) caught the identical bug identically here — but
  constructing the pipeline version surfaced a real constraint the isolated
  version didn't (needing a bio with decided flags yet zero
  `HANDLERS`-dispatchable claims, since a degree/institution claim alone
  flips `verification_effective` to True via ROR dispatch and hides the
  gap). Worth remembering: the "real pipeline" version of a test is not just
  a formality, it can force you to construct a more precise fixture than the
  unit-level one would have needed.
- The open-PR queue's own count (8 now) is no longer just a "flag it and
  move on" line — it has been repeated at escalating counts for eleven
  straight nights with zero response. Nothing in this file's advice changes
  as a result (still not a nightly run's call to merge anything), but it's
  worth being explicit that restating the same fact for an eleventh night
  running is itself informative: whatever mechanism is supposed to review
  and merge these has not engaged with this project in over a week and a
  half.

### What the next run should pick up first

1. **The open-PR queue — eight deep, eleven days, zero merges.** Still not
   something a nightly run can fix directly. Keep restating it prominently;
   consider that if it reaches a fifteenth night with no movement, that's
   worth a stronger statement in this file than a table, since the
   escalating-and-ignored pattern is itself now the notable fact.
2. **The core gap** — unchanged from every entry since 2026-08-15. Still the
   single biggest lever in the codebase; PR #11's unmerged `merge_risk`
   groundwork is still the only progress toward it anywhere, merged or not.
3. `report.py` has never had a full mutation-testing sweep — only tonight's
   own new lines were tested directly. `_esc`/`_safe_href`'s escaping logic
   in particular guards against a hostile bio injecting into the HTML
   report and would benefit from one.
4. PR #17's still-open "Timeline flag accuses ordinary CVs" part (a) — the
   recent-roles-only false accusation — still needs the semantic distinction
   its own write-up describes (a "founded X" origin date vs. an ordinary
   "has led since" role-change date) before it can be fixed without
   reintroducing a different false accusation.
| #13 | `nightly/2026-09-01` | Confidential and pre-revenue work is not deception |
| #14 | `nightly/2026-09-02` | A word-wrap can hide a denial from `is_negated` |
| #15 | `nightly/2026-09-03` | A fixed-width context window clipped a disclaiming phrase far from its identifier |
| #16 | `nightly/2026-09-04` | A self-applied doctoral title in lowercase or all-caps was invisible to flag 13, plus a pinned ROR nearest-name tie-break mutation survivor |
| #17 | `nightly/2026-09-08` | A current student's own study dates read as a fabricated future claim (timeline part (b) — see this entry's own primary item for part (a)) |
| #18 | `nightly/2026-09-09` | Mutation-testing sweep + a correction to a stale claim in this file |
| #19 | `nightly/2026-09-10` | The "own account" caveat only credited Wikipedia, never a genuine OpenAlex hit |

Every one of #11–#19 is small and independently authored, and each touches disjoint or near-disjoint files from the others — per every prior entry's own re-checking, this has never been a merge-conflict problem. It is a "nobody has pressed merge in over two weeks" problem, restated by name in the 2026-08-27, 09-01, 09-02, 09-03, 09-04, 09-08, 09-09, and 09-10 entries, at escalating counts each time (5 → 6 → 7 → 8 → 9 deep) with no response of any kind. Tonight's own branch (`nightly/2026-09-11`) is cut fresh from `master`'s tip regardless, per the standing instructions, and touches only `larp_meter/flags.py` and `tests/test_flags.py` — a file none of #11–#19 touch (checked against each PR's own file list), so it should not conflict with any of them.

**Given fifteen days and nine PRs of zero engagement, this run also sent a push notification flagging the queue directly to the human maintainer** rather than only restating it here for the tenth time — see the end of this session for that message. This doesn't change anything about tonight's own work (still small, still independent, still not a nightly run's job to merge), just makes sure the fact reaches a human through a channel that doesn't require reading NIGHTLY.md.

### Running backlog tally (15 CRITICALs)

**10 [FIXED] / 1 [PARTIALLY FIXED] / 4 still open — unchanged by tonight**, recounted directly against `master`'s current `BACKLOG.md` (grepping `^### ` under the `## CRITICAL (15)` section), matching the 2026-09-09/09-10 entries' own count exactly. Tonight's fix (below) is filed under "Shipped since the original review" against a MAJOR-severity finding, not one of the 15 CRITICALs, so the tally itself doesn't move. The 4 still-open CRITICALs remain the core one-way/claim-anchored funnel finding and its three near-duplicate write-ups from the original five-lens review.

### What I did

**Primary item:** fixed BACKLOG.md's "Timeline flag accuses ordinary CVs" finding, part (a) — the recent-roles-only false accusation, chosen because it's a fairness bug (punishes the single most common honest CV/LinkedIn shape), it was still fully unverified going into tonight, and it touches only `flags.py`/`tests/test_flags.py`, files none of the nine open PRs touch.

Confirmed live before writing anything: `f_timeline` on "Twelve years designing radiation-tolerant power electronics for satellite platforms. Since 2021 has led the analogue team. MSc in Electrical Engineering." returned **TRIGGERED** — "claims 12 years of experience, but the earliest date anywhere in the profile is 2021 — at most ~5 years are accounted for." The only date this bio states is when she took on her *current* role; the flag was reading that as when her entire career began. Exactly BACKLOG's own claim, reproduced exactly.

Wrote 4 tests in `tests/test_flags.py::TestTimelineFlag` first and watched 2 of them fail against the unmodified code (the false-accusation cases: the bio above, and BACKLOG's own "25-year veteran who lists only her last two dated roles" example); the other 2 (a genuine education-anchored contradiction, a genuine founding-anchored contradiction) already passed against the old code and exist to prove the fix doesn't overcorrect into silence.

Fixed `f_timeline` in `larp_meter/flags.py`: the claimed-years-vs-earliest-date comparison now only runs when the earliest dated year is a **career-start anchor** — its value appears inside a degree/institution claim's own extracted `context` string (an education date), or its own context contains an explicit origin verb (`founded|co-founded|founding|established|launched|graduated|started|began`) — or when the earliest date already covers the claimed duration on its own (nothing to falsify regardless). Without an anchor, the flag now returns UNKNOWN with an honest reason instead of TRIGGERED.

**Why an anchor via `context`-substring rather than tracking match positions properly:** `Claim` doesn't currently carry character offsets, only a pre-rendered `context` snippet (whitespace-collapsed, ±30 chars around the original match). Adding real position tracking to `Claim` and every extractor would be a much larger, riskier change than one night's "smallest safe slice" calls for. The substring check has a narrow false-positive surface (a coincidental exact-year digit string inside another claim's ±30-char window) that I judged acceptable for this scope; flagged in the diff's own comment for whoever eventually adds position tracking to `extract.py`.

**Getting the anchor wording right took two iterations, not one — worth recording so the next run doesn't redo this thinking.** My first pass required either "an explicit degree-anchored year" or "≥2 distinct years in the profile" (reasoning: a fuller timeline should have more than one dated point). That broke a currently-pinned mutation-guard test, `test_career_slack_is_exactly_three_years` ("20 years of experience in robotics. Founded the lab in 2009." — one year, no degree, expected PASSED/TRIGGERED at the exact +3 slack boundary). The actual reason that test is legitimate is that "Founded the lab in 2009" is itself an origin-marking event, not a mid-career date — a distinction "≥2 years" can't see but a founding-verb check can. Second pass added the origin-verb regex instead of the year-count heuristic, which is what's in the fix now. Also had to broaden the regex from requiring "started the company/venture/lab/..." to a bare `started`/`began`, because `test_the_current_year_is_not_a_future_date`'s fixture ("2 years of experience in robotics. Started in 2026.") uses the bare verb with no following object noun. Both iterations were caught by running the *existing* suite, not by anticipating them — a reminder that "run the full suite after every attempt," not just the new tests, is what actually catches this kind of interaction.

**Cross-boundary check (per the standing review question):** `f_timeline`'s signature and return type (`FlagResult` with the same three status values) are unchanged; only its internal logic and one of its UNKNOWN description strings changed. Grepped every caller — `evaluate()` iterates `REGISTRY` generically and treats all three statuses identically regardless of flag; `scoring.py` reads `.status` off the generic `FlagResult`, same as any other flag; nothing anywhere pattern-matches on flag 12's specific description text (grepped for the two changed strings — only `flags.py` itself and this file's own BACKLOG history mention them). No caller needed to change and none is silently mishandling a new case, because no new *status value* was introduced — only a different UNKNOWN message and a narrower TRIGGERED condition.

**Mandatory end-to-end pipeline check:** ran `larp-meter.py --file ... --name ...` directly (not just unit tests) on two hand-written samples. The honest veteran bio above landed INSUFFICIENT DATA (short bio, low flag coverage — expected and unrelated to this fix) with flag 12 correctly UNDECIDABLE, showing the new fair message, instead of TRIGGERED. A hand-written hype-heavy fabricator bio ("Dr. Marcus Vane, visionary Founder... 40 years of experience... published extensively...") landed INSUFFICIENT DATA with flags 4 (buzzword density) and 7 (fundraising without traction) correctly TRIGGERED — confirming the fix didn't make the flag inert, only narrower. Neither sample carries enough total material to reach a full GREEN/RED band on its own; that's a property of these short hand-written samples, not of tonight's change, and flag 12's own behavior in both is exactly what the fix targets.

**Mandatory per-cycle mutation-testing spot-check**, one mutation in each of the four required files, run against the full suite, then reverted:

| File | Mutation | Result |
|---|---|---|
| `scoring.py` | `_apply_floors`'s tie-break: `<= _SEVERITY_ORDER.index(level)` → `<` | **Caught** (`test_exact_tie_keeps_the_ordinary_summary_not_the_floor_message` failed) |
| `names.py` | `name_matches`'s `if len(present) >= 2:` → `>= 3` | **Caught** (18 failures + 5 errors) |
| `verify.py` | `verify_institution`'s ROR nearest-name tie-break: `if overlap > best_overlap:` → `>=` | **SURVIVED — still live and unpinned on `master`, see below** |
| `flags.py` | `f_contradicted`'s `if refuted or mismatched:` → `and` | **Caught** (`test_a_mismatched_identifier_is_a_contradiction` failed, +3 more) |

Also mutation-tested tonight's own new code directly: forcing the new anchor gate to always pass (`if True:` instead of the real condition) — caught by the two new false-accusation tests, confirming they actually discriminate rather than passing vacuously.

**The `verify.py` survivor is not new.** `nightly/2026-09-04` (PR #16) found and pinned this exact mutation; `nightly/2026-09-09` and `nightly/2026-09-10` each independently re-confirmed it live on `master` and declined to write a fourth/fifth copy of the same test, per the 2026-08-27 entry's own precedent ("the actual fix here is merging... not writing this test again"). Doing the same tonight for the same reason — recorded in BACKLOG.md instead of re-pinned again.

### What I confirmed / refuted in BACKLOG.md

- **Confirmed live, fixed**: Timeline flag part (a) (recent-roles-only false accusation) — reproduced exactly as the entry describes, fixed, tests added. Full write-up filed in-place as `[PARTIALLY FIXED]`.
- **Confirmed live, NOT fixed tonight**: Timeline flag part (b) (future graduation dates) — re-ran the entry's own repro (`'MSc Computer Science, Technische Universitat Munchen, 2025 - 2027.'`) and it still returns TRIGGERED on `master` tonight. A fix already exists on unmerged PR #17; did not duplicate it.
- **Re-confirmed live, not re-pinned**: `verify.py`'s ROR nearest-name tie-break survivor — matches PR #16/#18/#19's independent descriptions exactly, still unpinned on `master`.
- **Re-confirmed live**: the CRITICAL tally (10/1/4 of 15) is unchanged, counted directly rather than carried forward.
- Did not re-verify anything else in BACKLOG.md tonight, including the 4 still-open CRITICALs or any MAJOR/MODERATE/MINOR entry other than the timeline finding.

### Mutation-testing log (files swept so far, by night)

- `scoring.py`: full sweep 2026-08-16 (merged). Spot-checked again tonight (fresh line, `_apply_floors` tie-break) — still caught.
- `names.py`: full sweep 2026-08-19 (merged). Spot-checked again tonight (fresh line, `present`-count threshold) — still caught.
- `verify.py`: full sweep 2026-08-18 (merged) plus several later spot-checks. Tonight: the ROR tie-break survivor confirmed live again, still unpinned — fix sits only on unmerged PR #16.
- `flags.py`: full sweeps 2026-08-16/17 (merged). Spot-checked again tonight (fresh line, `f_contradicted`'s `or`/`and`) — still caught. Tonight's own new code (the timeline anchor gate) was also mutation-tested directly and caught.

### What I learned

- A mutation-guard test pinned against *today's* behavior can quietly encode an assumption the behavior itself later needs to change (here: "a single dated year is always enough to test a claimed duration against"). When a BACKLOG fix touches a flag with existing pinned tests, don't just add new tests for the new behavior — run the *whole* suite against each draft of the fix, because an old pinned test failing is sometimes telling you your fix's condition is too narrow (or too broad) rather than that the old test is simply wrong. Here, two rounds of "run everything, see what breaks, ask why" produced a materially better anchor condition (an origin-verb check) than my first idea (a year-count heuristic) would have.
- `Claim.context` (a rendered, whitespace-collapsed ±30-char text snippet) turned out to be a reusable general-purpose signal for "is this fact-fragment textually near that other fact-fragment," beyond its original purpose of showing evidence in a report. Worth remembering for future flags that want to correlate two extracted claims without adding real position tracking to `extract.py` — though see the caveat above about its narrow false-positive surface; this is a pragmatic shortcut, not a precise mechanism, and a future night adding character-offset tracking to `Claim` would make this and any similar future correlation check both simpler and more precise.
- The open-PR queue is no longer just worth flagging in this file — nine independent, non-conflicting, reviewer-ready PRs sitting for up to two weeks is itself a signal that whatever human process is supposed to review and merge this project's nightly output has not engaged in a long time. This run also pushed a notification directly rather than relying on this file being read.

### What the next run should pick up first

1. **The open-PR queue — nine deep, fifteen days, zero merges.** Still not a nightly run's call to fix by pushing code. If it keeps growing, keep restating it here AND consider another direct notification rather than assuming this file gets read.
2. **The core gap** — unchanged from every entry since 2026-08-15. Still the single biggest lever in the codebase; PR #11's unmerged `merge_risk` groundwork is still the only progress toward it anywhere, merged or not.
3. Timeline finding part (b) (future graduation dates / the `year`/`year_target` de-duplication gap) — fix already exists on unmerged PR #17; either merge it or re-verify and re-implement if PR #17 has drifted.
4. `report.py` has still never had a full mutation-testing sweep (per the 2026-09-10 entry) — only that night's own new lines were tested directly. Worth a full pass given it's the file that formats what a human actually reads.
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
files, full suite re-run, reverted before the next — plus one on tonight's
own new code:

| File | Mutation | Result |
|---|---|---|
| `flags.py` (tonight's new code) | `if retracted:` → `if False:` | **Caught** — `test_confirmed_but_retracted_paper_triggers_the_contradiction_floor` failed exactly as intended, confirming the new test actually exercises the new branch. |
| `scoring.py` | `coverage >= MIN_COVERAGE` → `coverage > MIN_COVERAGE` | **Caught** (`test_coverage_exactly_at_min_coverage_is_still_scored`) — still fully protected since the 2026-08-16 sweep. |
| `names.py` | `name_matches`: `parts[0] == matched or parts[-1] == matched` → `parts[0] == matched` (drop the trailing-surname half of the "which end is the surname" guard) | **Caught** — 5 tests failed, including the non-Western-surname-order regression this exact guard exists for. Still fully protected. |
| `verify.py` | `verify_institution`: `if not ok:` → `if ok:` (invert the network-failure branch) | **Caught** — 11 tests failed across the ROR institution suite. Still fully protected. |

**Result: all four mutations caught, 482 tests green after each revert.**
`scoring.py`, `names.py` and `verify.py` (the pre-existing ROR guard, not
tonight's new DOI code, which has its own dedicated tests above) remain
fully protected on `master`. Per-file sweep history: `scoring.py` full sweep
2026-08-16 (12 mutations, 6 real, all pinned); `flags.py` full sweep
2026-08-16/17 (33 mutations, 13 real, all pinned); `names.py` full sweep
merged via PR #5 (2026-08-19 merge commit `460c6ac`, already on `master` —
the queue-tracking table in the 2026-08-27 entry predates this merge and is
now stale on that point); `verify.py` full sweep merged via PR #4
(2026-08-18 merge commit `99388e9`, also already on `master`). **All four
required files now have at least one full mutation sweep merged to
`master`**, not just spot-checked — worth correcting explicitly since the
last entry to discuss this in detail (2026-08-27) still described `names.py`
and `verify.py`'s sweeps as sitting only on unmerged branches; both merged
before that entry was even written, going by commit order in `git log`, and
nobody had re-checked since.

### What I learned

- **The 2026-08-27 entry's mutation-sweep status was stale by the time it
  was written**, not just by the time it was read: `git log` shows the
  `names.py` (PR #5) and `verify.py` (PR #4) merges landing *before* the
  2026-08-27 merge commit, but that entry's text still describes both sweeps
  as unmerged. The lesson generalizes beyond mutation testing: a claim about
  what's merged is only as good as the `git log`/PR-list check behind it at
  the moment of writing, and this file has no way to flag its own staleness
  automatically — always re-verify "is X merged" against `git log`/
  `list_pull_requests` directly rather than trusting the previous entry's
  narrative, even a recent one.
- Crossref's retraction metadata is genuinely inconsistent about *which* DOI
  in a retraction pair carries the `update-to: retraction` relation — this
  cost real time to discover only because it was checked live against two
  real cases rather than assumed from the API's documented shape. Anyone
  extending this to OpenAlex's `is_retracted` field (the backlog's suggested
  next step) should verify live whether OpenAlex has the same inconsistency
  or resolves it centrally, rather than assuming a single boolean field is
  simpler and therefore more reliable.
- Constructing a genuinely "clean, honest" end-to-end sample DOI citation is
  fiddlier than it looks: my first attempt reused a DOI from the test suite
  fixtures (the NumPy paper) with an unrelated invented name and got a
  correct, expected MISMATCH — not a bug, just the wrong sample. Had to
  fetch the DOI's real author list live and use one of those exact names to
  build a true positive control. Worth remembering for the next person
  building a live "should-pass-cleanly" fixture: pull real author names from
  the actual registry response, don't assume a `10.1038/...`-shaped DOI is
  automatically "some anonymous real paper" safe to pair with any name.

### What the next run should pick up first

1. **The open-PR queue is the top priority for a human, not for an
   autonomous run** — flagging again rather than acting, per standing
   instructions. All eleven were checked to be independent of tonight's
   change; #11 (merged-entity flagging) and #19 (OpenAlex "own account"
   caveat) both touch OpenAlex signal-handling and may be worth merging
   together/in sequence since they're conceptually related, though not
   file-conflicting.
2. **The preprint/`posted-content` half of tonight's backlog entry** is the
   natural next slice: same finding, same `verify_doi`, needs a claim-linking
   mechanism (correlate a `doi`/`arxiv` claim with a separate `assertion`
   claim reading "peer-reviewed" elsewhere in the text) that doesn't exist
   yet. Smaller than it sounds if scoped to "does *any* dispatched doi/arxiv
   claim resolve to `type: posted-content`, and does the text separately
   assert peer-review anywhere" rather than true per-claim linkage.
3. **The core architectural gap** is still fully untouched by any run since
   2026-08-15, and still not attempted by any of the eleven queued PRs
   either — it remains the single highest-value, highest-risk piece of
   unbuilt work in the repo. Re-verify the OpenAlex rate-limit/response-shape
   numbers live before starting, per the standing brief's own instruction —
   they are now a month old as measured.
---

## 2026-09-14

### Open-PR queue — human visibility, not something acted on tonight

**12 open, unmerged, draft `nightly/*` PRs against `master`, none touched
tonight:** #11 (2026-08-30) through #22 (2026-09-13), all still draft, all
still open as of this writing. `master`'s last actual merge is still
`9f71c98` "Merge nightly/2026-08-27" — this queue has now gone **eighteen
consecutive nights** without a single merge landing. This entry's own
change branches fresh from `origin/master`'s current tip (unchanged since
08-27) and does not depend on, or attempt to resolve, any of the twelve —
per standing instructions, resolving this queue is a human merge decision,
not something an autonomous run should attempt. Flagging again, louder,
because the pattern the 2026-08-27 entry warned about (independent
rediscovery of the same fix by multiple nights because nothing merges) is
no longer hypothetical: tonight's own primary item overlaps in file and
in Crossref-response-field with the still-open PR #22 (2026-09-13,
retraction detection) — both read `msg.get("type")`/`msg.get("update-to")`
from the same Crossref response in `verify_doi` and both add a new boolean
`Claim` field consumed by flag 11. They do not conflict in *logic* (this
branch adds `is_preprint`/`claimed_peer_reviewed`, PR #22 adds `retracted`,
and neither reads the other's field), but they will very likely conflict
*textually* in `verify_doi` and in flag 11's `confirmed` branch when both
eventually land, and whichever merges second should union the two rather
than silently drop one. Noting this explicitly here so it isn't rediscovered
as a surprise at merge time.

### CRITICAL tally (BACKLOG.md, 15 total) — unchanged tonight

**10 [FIXED] / 1 [PARTIALLY FIXED] / 4 still open — unchanged by tonight**,
verified directly against `master`'s current `BACKLOG.md` (grepped `^### `
under `## CRITICAL (15)`: 10 lines carry `[FIXED]`, 1 carries `[PARTIALLY
FIXED]`, 4 carry neither). This is an *improvement* on the 2026-08-27
entry's own "8/1/6" tally — two more CRITICALs were fixed and merged to
`master` somewhere between 08-27 and now, though no entry in this file
documents which nights did it (another symptom of the queue: the PRs that
did those merges evidently landed, but their own NIGHTLY.md entries never
made it to `master` because — per the queue problem above — most nights'
entries sit on branches that haven't merged). Tonight's own change touches
none of the 15 named CRITICALs directly (it is a MAJOR-severity item, the
tool's own next-highest-value slice per last night's suggested next step),
so the CRITICAL tally itself does not move.

### What I did

**Primary item:** fixed the *other* half of the MAJOR finding "Nothing
checks whether a cited paper was retracted, or whether it is peer-reviewed
at all — and Crossref already returns the fields" — the preprint half, left
explicitly open by last night's entry (2026-09-13, PR #22) alongside its
own retraction fix. `verify_doi` fetched the full Crossref record for every
DOI claim but read only `title`/`author`, so a preprint cited as
"peer-reviewed work" verified identically to a genuine journal article —
BACKLOG.md's own motivating example, and a real, checkable form of
publication LARP (claiming a lower evidentiary bar than the work actually
cleared).

Chose this over the standing brief's core architectural gap for the same
reason every entry since 2026-08-15 has: the core gap needs the OpenAlex
disambiguation groundwork (merged entities, common-name collisions) before
any verdict stronger than an UNKNOWN-with-evidence line can be trusted, and
none of the twelve queued PRs attempt it either, so it remains correctly
deferred rather than newly neglected. Chose it over resuming the retraction
half specifically because that work already exists, complete and tested, on
unmerged PR #22 — writing a second copy would have been exactly the
rediscovery waste the queue-problem section above is about. The preprint
half was the one piece of this finding nobody had touched yet.

**Design, and the two false-accusation risks it exists to avoid:**

1. *Proximity, not "anywhere in the document".* A first instinct is: does
   the text contain BOTH a `doi` claim resolving to `type: posted-content`
   AND a `"peer-review claim"` assertion anywhere at all? Live-tracing this
   through a realistic counter-example rejected it before writing any code:
   "I have several peer-reviewed publications in my field. Preliminary
   results are also up at 10.1101/...". That subject is telling the truth
   on both counts — genuine peer-reviewed work exists somewhere unstated,
   and the preprint is honestly labeled as preliminary. Linking the two
   claims by mere co-occurrence would accuse them of exactly the
   misrepresentation they did not make. Fixed by making `claimed_peer_reviewed`
   a fact about one specific `doi` claim, set at extraction time by scanning
   only the sentence containing that identifier (`extract.py`'s new
   `_peer_review_claimed_nearby`, bounded to 300 chars each side and
   stopping at `.;:!?` — the same sentence-boundary approach unmerged PR #15
   (2026-09-03) independently arrived at for a different bug, `_context`'s
   fixed-width window; this branch does not touch `_context` itself, to
   avoid conflicting with that PR when it eventually lands).
2. *A fixed 60-character radius is not wide enough.* BACKLOG.md's own
   example — "My peer-reviewed work on room-temperature superconductivity
   (10.1038/...) established the field" — puts "peer-reviewed" well outside
   a 60-char window centered on the DOI. Confirmed this live by counting:
   the qualifier sits ~63 characters before the identifier's own start.
   `extract.py`'s existing `_context()` (60-char, fixed-width) could not
   have caught this even if reused as-is, hence the dedicated
   sentence-scanning helper rather than reusing `claim.context` directly.
3. *Self-disclosure must only ever suppress, never trigger.* "Our
   peer-reviewed methodology is also available as a preprint at (DOI) for
   early access" says "peer-reviewed" and cites the preprint in the same
   sentence — legitimate cross-posting, not deception. Added
   `_PREPRINT_DISCLOSURE_RE` (`preprint`, `pre-print`, `not yet
   peer-reviewed`, `under review`) as a guard that can only ever remove a
   potential TRIGGER, matching this file's own stated rule for every other
   guard in it ("failing to recognise a disclosure costs a missed
   accusation it would have been wrong to make anyway, never a false one").

Two new `Claim` fields, kept deliberately separate rather than combined into
one: `claimed_peer_reviewed` (set by `extract.py`, a fact about the text)
and `is_preprint` (set by `verify.py`'s `verify_doi` from Crossref's `type`,
a fact about the registry record). `flags.py`'s flag 11 is the only place
that combines them, and only inside the pre-existing `confirmed` branch —
after the existing `if not ctx.subject_name: return UNKNOWN` guard, so an
unattributed claim never reaches this check either, for free, the same way
last night's retraction fix inherited both of flag 11's existing guards.
Scoped to `doi` only, not `arxiv`: every arXiv paper is structurally
non-peer-reviewed (no peer-review layer exists there at all), which makes
it a *more* certain case than the DOI/Crossref-type check, but the same
cross-posting ambiguity applies and I did not have a real example on hand
to verify the self-disclosure guard against before writing this entry —
recorded as the explicit next step in BACKLOG.md rather than guessed at.

### Tests

Wrote 9 new tests first, watched each fail against the unmodified code
(`AttributeError: 'Claim' object has no attribute 'claimed_peer_reviewed'` /
`'is_preprint'`, and one genuine assertion failure once both attributes
existed but the flag logic didn't), then implemented:
- `tests/test_extract.py::TestPeerReviewClaimProximity` (4 tests): the
  far-apart-same-sentence case from BACKLOG.md's own example, a
  different-sentence negative control (the false-accusation risk above), the
  self-disclosed-preprint guard, and an ordinary DOI citation defaulting to
  `False`.
- `tests/test_verify.py::TestPreprintClaimedAsPeerReviewed` (5 tests):
  `verify_doi` setting `is_preprint` on `posted-content` vs. an ordinary
  journal article, the full contradiction TRIGGERING through `verify_all` +
  flag 11 together, and two regression guards — an honestly-cited preprint
  still PASSES, and a genuinely peer-reviewed paper correctly described as
  such still PASSES (the two cases a blanket "preprint == bad" rule would
  have wrongly conflated).

**482 tests green** (473 → 482).

**End-to-end CLI check, live network**, using the backlog's own motivating
DOI (`10.1101/2020.03.22.20040758`) — live-verified against `api.crossref.org`
before writing any code: `type: "posted-content"`, real author "Zhaowei
Chen" confirmed in the response.
- **Should-flag:** "Zhaowei Chen. ... My peer-reviewed work on
  hydroxychloroquine efficacy in COVID-19 patients (10.1101/...) established
  the field." with `--verify --name "Zhaowei Chen"`. Flag 11 TRIGGERED: "1
  identifier(s) cited as peer-reviewed work are, per the registry, preprints
  that have not been through peer review — the claim and the record do not
  match," evidence line showing the Crossref-sourced detail with the
  `posted-content` note appended.
- **Should-pass-cleanly (honest preprint):** same subject, same DOI, text
  changed to "Preliminary results are available as a preprint ... for early
  access; full peer review is ongoing." Flag 11 PASSED — "All 1 checked
  identifier(s) confirmed by their registries," confirming the
  self-disclosure guard actually reaches the real pipeline, not just its
  unit test.
- **Should-pass-cleanly (real peer-reviewed paper):** "Charles R. Harris ...
  Co-author of the peer-reviewed NumPy array programming paper,
  10.1038/s41586-020-2649-2, published in Nature," `--name "Charles R.
  Harris"`. Flag 11 PASSED, confirming the ordinary honest case — a real
  paper correctly described as peer-reviewed — is completely unaffected.

### Cross-boundary check (per the standing review question)

Grepped every reader and writer of both new fields fresh (not trusting
memory of having just written them): `claimed_peer_reviewed` is written
only in `extract.py`'s `add()` and read only in `flags.py`'s new line;
`is_preprint` is written only in `verify.py`'s `verify_doi` and read only in
that same `flags.py` line. No other file references either name.
`Claim.to_dict()` (`asdict`) picks up both automatically for the JSON
report — confirmed live in the end-to-end run above, both fields present
and correctly valued in the `claims` array. Grepped for any test asserting
an exact claim dict key set or `report.py` special-casing a claim field by
name — neither exists, so the new fields cannot silently break a JSON
consumer or a renderer. Every other artifact subtype (`orcid`, `github`,
`arxiv`, `nct`, `patent`) gets the dataclass defaults (`False`/`False`) for
both fields and is never touched by the new `verify_doi`/`extract.py` code
paths, so the new check is structurally inert for anything but a `doi`
claim — verified by reading, not assumed from the `subtype == "doi"` guard
alone.

### Mutation-testing log

Mandatory per-cycle pass, six mutations total: two on tonight's own new
code (to confirm the new tests actually discriminate, not just pass), and
one pre-existing-code spot-check in each of the four required files. Full
suite re-run after each, reverted before the next.

| File | Mutation | Result |
|---|---|---|
| `flags.py` (tonight's new code) | `if c.is_preprint and c.claimed_peer_reviewed` → `... or ...` | **Caught** — 2 tests failed (`test_an_honestly_cited_preprint_still_passes`, `test_a_real_peer_reviewed_paper_correctly_claimed_still_passes`), confirming the new AND is load-bearing. |
| `extract.py` (tonight's own new code) | `_peer_review_claimed_nearby`: dropped the `and not _PREPRINT_DISCLOSURE_RE.search(sentence)` guard | **Caught** — `test_self_disclosed_preprint_is_not_a_false_peer_review_claim` failed exactly as intended. |
| `scoring.py` | `coverage >= MIN_COVERAGE` → `coverage > MIN_COVERAGE` | **Caught** (`test_coverage_exactly_at_min_coverage_is_still_scored`) — still fully protected since the 2026-08-16 sweep. |
| `names.py` | `name_matches`: `parts[0] == matched or parts[-1] == matched` → `parts[0] == matched` | **Caught** — 5 tests failed, including the non-Western-surname-order regression this guard exists for. Still fully protected (merged via PR #5, 2026-08-19). |
| `verify.py` | `verify_institution`: `if wanted and wanted <= have:` → `if wanted <= have:` | **Caught** — 3 tests failed. Still fully protected (merged via PR #4, 2026-08-18). |
| `flags.py` (pre-existing) | flag 11: `if refuted or mismatched:` → `if refuted:` | **Caught** — 2 tests failed, including `test_a_mismatched_identifier_is_a_contradiction`. Still fully protected since the 2026-08-16/17 sweep. |

**Result: all six mutations caught, 482 tests green after each revert.**
Per-file sweep history unchanged from the 2026-09-13 entry: `scoring.py` full
sweep 2026-08-16; `flags.py` full sweep 2026-08-16/17; `names.py` full sweep
merged via PR #5 (commit `460c6ac`); `verify.py` full sweep merged via PR #4
(commit `99388e9`). All four required files remain fully covered on
`master` by a full sweep, with tonight adding a fresh spot-check on each
plus full coverage of tonight's own new code.

### What I learned

- The "is this merged" staleness trap the 2026-09-13 entry named is real and
  cuts both ways: this entry's own CRITICAL tally (10/1/4) is *better* than
  the last entry actually present on `master` (8/1/6, from 2026-08-27) even
  though nothing merged in between that this file documents — the fixes
  happened, the narrative just never caught up, because the entries
  documenting them are stuck on unmerged branches. Re-verifying directly
  against `BACKLOG.md`'s own `[FIXED]` tags on `master`, rather than trusting
  the last NIGHTLY.md entry's number, is the only way to catch this — did
  that here, and it changed the number.
- Two independent, unmerged nights (this one and PR #22) converging on the
  same function (`verify_doi`) and the same underlying Crossref field
  (`type`/`update-to`) for two different, correctly-separated findings
  (preprint-vs-claim, and retraction) is a natural, expected outcome of
  "keep branches small and independent" applied to a codebase this size —
  it is not a sign either branch did something wrong, just a sign the merge
  queue needs to actually run so these compose instead of silently
  colliding. Worth designing new `Claim` fields (as both nights did) rather
  than repurposing an existing one specifically so a future merge of both
  is a union, not a contradiction, regardless of merge order.
- Constructing a live "should-pass-cleanly, honest preprint" fixture needed
  the same care last night's entry noted for its own true-positive sample:
  reusing a real DOI (`10.1101/2020.03.22.20040758`) with an invented
  "no peer-review claimed" sentence around it was fine, but it had to be
  checked against the *same* live-fetched author list ("Zhaowei Chen") used
  for the should-flag sample, not a fresh invented name, or the sample would
  have exercised the pre-existing MISMATCH path instead of the new
  preprint-specific one.

### What the next run should pick up first

1. **The open-PR queue is still the single biggest lever available, and
   still not something an autonomous run can pull** — eighteen nights
   unmerged now, not the eleven the last entry counted. Flagging a third
   time, unchanged in substance from the last two entries, because nothing
   about the situation has changed except its size.
2. **arXiv's structurally-simpler version of tonight's fix** (see "Not
   fixed, left open" in BACKLOG.md's updated entry): live-check a handful of
   real arXiv cross-posting bios ("peer-reviewed elsewhere, also on arXiv as
   ...") before extending `claimed_peer_reviewed`/self-disclosure detection
   there — should be small once that check is done.
3. **Retraction + preprint, once both PR #22 and this branch have merged**:
   union `Claim.retracted` and the two fields added tonight rather than
   letting whichever merges second silently drop the other's field, per the
   queue-conflict note at the top of this entry.
4. **The core architectural gap** remains fully untouched by any run since
   2026-08-15 and by all twelve queued PRs. Re-verify the OpenAlex
   rate-limit/response-shape numbers live before starting — they are now a
   month old as measured, and the brief itself says not to trust them
   unverified past that point.
## 2026-09-15 (nightly run)

### ⚠ Open-PR queue: THIRTEEN unmerged `nightly/*` PRs, dating back to 2026-08-30 — read this first

**`master`'s tip is still `9f71c98` ("Merge nightly/2026-08-27").** Nothing
has merged in nineteen consecutive nights. Every entry in this file below
2026-08-27 that a previous run wrote describing NIGHTLY.md/BACKLOG.md
progress lives only on an unmerged branch — `master`'s own copies of both
files stop at 2026-08-27 until tonight's edit. The queue has grown from
seven PRs (as flagged on 2026-08-27) to **thirteen**:
## 2026-09-17 (nightly run)

### ⚠ Open-PR queue: FIFTEEN unmerged `nightly/*` PRs, dating back to 2026-08-30 — still the single biggest risk, read this first

**`master`'s tip is still `9f71c98` ("Merge nightly/2026-08-27").** Three
weeks and three days since the last merge. The queue grew again since
2026-09-16's count of fourteen: PR #25 (`nightly/2026-09-16`, "a
fabricated patent's Google 404 page and a ROR tie-break were both
untested in verify.py") is also open and unmerged, bringing the total to
**fifteen**, PRs #11 through #25, spanning 2026-08-30 through 2026-09-16.
Spot-checked two directly via the GitHub API rather than trusting each
PR's own description (`pull_request_read get` on the oldest, #11, and the
newest, #25): both report `mergeable_state: clean`, still open, still
draft, no reviews. Per every recent entry's own finding, this is a
human-merge-queue problem, not a code problem — flagging again, not
attempting to resolve it myself (that would mean rewriting other people's
unmerged branches, which the standing instructions rule out).

| PR | Branch | What it claims |
|----|--------|-----------------|
| #11 | nightly/2026-08-30 | Flag an OpenAlex "best" pick that's likely a merged entity |
| #12 | nightly/2026-08-31 | An ordinary CV mistaken for a LinkedIn paste, silently losing content |
| #13 | nightly/2026-09-01 | Confidential and pre-revenue work is not deception |
| #14 | nightly/2026-09-02 | A word-wrap can hide a denial from `is_negated` |
| #15 | nightly/2026-09-03 | A fixed-width context window clipped a disclaiming phrase far from its identifier |
| #16 | nightly/2026-09-04 | A self-applied doctoral title in lowercase/all-caps was invisible to flag 13 |
| #12 | nightly/2026-08-31 | An ordinary CV mistaken for a LinkedIn paste silently lost content |
| #13 | nightly/2026-09-01 | Confidential and pre-revenue work is not deception |
| #14 | nightly/2026-09-02 | A word-wrap can hide a denial from `is_negated` |
| #15 | nightly/2026-09-03 | A fixed-width context window clipped a disclaiming phrase far from its identifier |
| #16 | nightly/2026-09-04 | A self-applied doctoral title in lowercase or all-caps was invisible to flag 13 |
| #17 | nightly/2026-09-08 | A current student's own study dates read as a fabricated future claim |
| #18 | nightly/2026-09-09 | Pin flags.py's buzzword carve-out lower boundary |
| #19 | nightly/2026-09-10 | The "own account" caveat only credited Wikipedia, never a genuine OpenAlex hit |
| #20 | nightly/2026-09-11 | A truthful career read as impossible when only its most recent role was dated |
| #21 | nightly/2026-09-12 | An honest institution ROR doesn't index read as a fabricated credential |
| #22 | nightly/2026-09-13 | A retracted paper cited as your own published work read as VERIFIED |
| #23 | nightly/2026-09-14 | A preprint cited as your own peer-reviewed work verified identically to a real journal article |

Spot-checked `mergeable_state` on four of the thirteen (#11, #12, #22, #23,
spanning the oldest, a middle one, and the two newest) via the GitHub API
directly rather than trusting each PR's own description: all four report
**`clean`**, and each PR's own body already records having diffed itself
against every still-open branch at the time it was written and found no
conflicts. Real fixes for a growing list of distinct findings — including
two full mutation-testing sweeps of `verify.py` and `names.py` (PRs #4/#5,
themselves still unmerged from an *earlier*, now-resolved backlog check;
their guards were independently re-pinned straight to `master` on
2026-08-26/27) — are sitting unreleased. **This is a human-merge-queue
problem, not something an autonomous run can fix by pushing more commits**;
per standing instructions, tonight's branch is still cut fresh from
`master`'s current tip and scoped to avoid every file the thirteen branches
above touch (see "What I did").

### Running backlog tally (15 CRITICALs)

**10 [FIXED] / 1 [PARTIALLY FIXED] / 4 still open.** Verified directly
against `master`'s current `BACKLOG.md`, not carried over by assumption:
`sed -n '759,1062p' BACKLOG.md | grep '^### '` (the CRITICAL section's
actual line range, bounded by the next `## MAJOR (25)` header) returns
exactly 15 entries, of which 10 carry `[FIXED]` and 1 carries `[PARTIALLY
FIXED]`. The 4 still open are the core architectural gap and its three
near-duplicate phrasings from different lenses of the original five-lens
review — none of them touched tonight (see below). This is a higher FIXED
count than 2026-08-27 last recorded (8/1/6) — the difference is real merges
that landed between 2026-08-16 and 2026-08-27, not anything from the
current unmerged queue, which has not touched any of the 15 named
CRITICALs.

### What I did

**Mandatory per-cycle mutation-testing pass, all four required files —
this was tonight's primary work**, not a secondary check. Deliberately
picked `names.py` and `scoring.py` for the real sweep because neither is
touched by any of the thirteen open PRs above, so tonight's branch cannot
conflict with any of them at merge time; `flags.py` and `verify.py` (both
heavily touched by the open queue) got a lighter spot-check of
previously-pinned guards instead of a fresh sweep, to avoid duplicating
work already sitting unmerged.

Found **two real, previously-uncaught survivors**, both in already-correct
production code — a test-coverage gap, not a live bug on `master`:

- `names.py`'s `tokens()` unions two independent readings (hyphen-as-
  separator, hyphen-as-attachment), each filtering particles/honorifics
  with its own copy of the same clause. Deleting only the split reading's
  filter left all 475 prior tests green, because every existing test pairs
  a particle with its own real surname — the leak is inert noise there. But
  the union carries the leak into the final token set regardless, and a
  fabricator using a title ("Dr.") plus a particle ("Van") could pick up a
  false two-token "confident" match against a completely unrelated person
  who happens to share only the title and particle — the false-positive
  mirror of the false-MISMATCH failures the rest of `test_names.py` exists
  to prevent. Confirmed live: `name_matches("Dr. Van Helsing", ["Dr. Van
  Pelt"])` goes `False` (correct, on `master` today) to `True` under the
  mutation.
- `scoring.py`'s `category_scores` filters decided flags with `r.status not
  in (TRIGGERED, PASSED)`. Narrowing that to `(TRIGGERED,)` also left the
  whole suite green — every existing `category_scores` test used an
  all-TRIGGERED or an all-UNKNOWN-but-one fixture, never a real mix. The
  mutation reports any category with at least one trigger as a
  maximum-severity 100 regardless of how many flags in it actually passed,
  silently erasing the one thing the per-category breakdown exists to show.

Both pinned with new regression tests, each confirmed failing against the
mutated code and passing against the restored code before being kept (see
Mutation-testing log below for the exact commands). **No production code
changed** — both findings are new test coverage for behavior that was
already correct.

Also spent real effort chasing a *third* apparent survivor in `names.py`
(the single-token loop's `if not extra or all(w in mine for w in extra)`)
and concluded it is very likely dead code, not a gap — see BACKLOG.md's new
entry under "Shipped since the original review" for the reasoning. Did not
write a test for it, since the scenario it would need appears to be
structurally unreachable given how `present` is computed elsewhere in the
same function.

**End-to-end CLI check**: ran two hand-written samples through the real
`larp-meter.py` entry point (a plain honest-sounding bio, and an
over-the-top "Dr. Van Helsing" fabrication chosen to exercise the exact
name this cycle's fix concerns). Both ran cleanly with no crashes; both
landed INSUFFICIENT DATA, which is expected and unrelated to tonight's
change (it's the core gap, see below) — this check exists to confirm
nothing broke, not to move a verdict, and nothing did.

### BACKLOG.md: confirmed / refuted

Did **not** investigate any of the 15 CRITICALs or other BACKLOG.md
findings tonight — the two mutation-testing survivors above are new
findings of their own (now recorded in BACKLOG.md's "Shipped since the
original review" section), not confirmations of anything already listed.
The tally above is unchanged by tonight's work for that reason, exactly as
2026-08-27's flag-6 slice was.
Verified directly against `master`'s current `BACKLOG.md`: `sed -n
'759,1062p' BACKLOG.md | grep '^### '` (the CRITICAL section's own line
range, bounded by the next `## MAJOR (25)` header) returns exactly 15
entries, 10 carrying `[FIXED]` and 1 carrying `[PARTIALLY FIXED]`. The 4
still open are the core architectural gap and its three near-duplicate
phrasings from different lenses of the original five-lens review — none
touched tonight, and none of the fourteen open PRs above claims to touch
any of the 15 named CRITICALs either (checked each PR title against the
CRITICAL section's own headings).

### What I did

**Primary item — mandatory per-cycle mutation-testing pass, targeted at
`verify.py`.** Chose this file specifically because 2026-09-15's own "what
the next run should pick up" list named it (item 3) as still needing a
full sweep repeated directly against `master` — the two branches that did
full sweeps of `verify.py` (PR #4) and `names.py` (PR #5) are both still
sitting unmerged since August. Also chose it because, per each open PR's
own title, none of the fourteen in the queue appears to touch `verify.py`,
so a test-only change here carries the lowest possible collision risk at
merge time — this branch does not modify `larp_meter/verify.py` itself at
all, only `tests/`.

Six targeted mutations, four caught immediately by the existing suite
(`_is_ambiguous_acronym`'s `<= 5` boundary, arXiv's `"api/errors" in
entry_id or title == "error"` disjunction narrowed to `and`, GitHub's
`len(published.split()) >= 2` comparability guard, and a spot-check
re-confirmation that `verify_institution`'s `wanted and wanted <= have`
guard — pinned back on 2026-08-18/19 — is still caught). Two survived,
both real, previously-untested behavior in already-correct code — not live
bugs on `master` today:

1. `verify_patent`'s title-text "not found" check. Before writing a test,
   verified live against the real Google Patents endpoint (several
   malformed/nonexistent patent IDs, 2026-09-16) that a nonexistent ID
   normally 404s at the HTTP layer — already handled correctly by `_get`
   turning that into an empty body, never reaching this code — so the
   title-text check exists for the *other* failure shape: an HTTP 200 page
   whose own title says the patent wasn't found. No test drove
   `verify_patent` through that shape (the only two direct tests of this
   handler cover a real inventor match and an unrelated markup-drift
   failure). Under the mutation this reads as a scrape failure
   (UNCHECKABLE) instead of a nonexistent patent (NOT_FOUND) — weaker, not
   wrong-direction, since UNCHECKABLE still excludes it from scoring.
2. `verify_institution`'s overlap tie-break (`>` loosened to `>=`) lets a
   later, equally-scored, less-relevant ROR result silently overwrite an
   earlier one, contrary to ROR's own relevance ordering. Cosmetic only —
   it changes which name appears in the "Nearest listed name" hint inside
   a NOT_FOUND detail string, never `claim.status` — but real and
   previously untested.

Both pinned with new regression tests in the existing style (each
confirmed RED against the mutated code, GREEN against the restored code,
full command sequence in the Mutation-testing log below), full detail in
BACKLOG.md's new "Mutation-testing pass: `verify.py`, two real survivors in
the patent/ROR handlers" entry. `larp_meter/verify.py` is byte-identical to
`master` after this branch.

**End-to-end CLI check**: since this branch touches no production code,
skipped the full two-sample verification the brief requires "especially"
after touching verify.py/extract.py/names.py/flags.py/scoring.py — none of
those changed. Ran two hand-written samples anyway as a sanity check (a
plain honest engineer bio, and the BACKLOG.md "Marcus Vane" fabrication
with an added `US9999999` patent claim) through the real CLI without
`--verify`, to confirm nothing broke: both ran cleanly, both landed on
provisional/low-coverage scores as expected (11% and 32% decided
respectively), and the fabricated sample's flag 8 PASSED on the invented
institution exactly as BACKLOG.md's core-gap entry describes — an
unrelated, already-known, already-documented gap, not something tonight's
change touched.

### What I confirmed / refuted in BACKLOG.md

Did not investigate any of the 15 CRITICALs or other existing BACKLOG.md
findings tonight — the two mutation-testing survivors above are new
findings of their own (now recorded in BACKLOG.md), not confirmations of
anything already listed there. Separately confirmed live (see "What I did"
above) that Google Patents' real HTTP-404 behavior for malformed patent
IDs matches what `_get`'s existing 404/410 handling already expects —
this is a fact about the live API, not a BACKLOG.md finding, recorded here
because the task brief asks that API assumptions be checked live rather
than trusted from memory.
| #24 | nightly/2026-09-15 | Mutation-testing names.py and scoring.py finds two real, unpinned gaps |
| #25 | nightly/2026-09-16 | A fabricated patent's Google 404 page and a ROR tie-break were both untested in verify.py |

Per standing instructions, tonight's branch is cut fresh from `master`'s
tip regardless, and scoped as a **test-only change to `flags.py`'s test
file** — no open PR's title claims to touch `tests/test_flags.py`'s flag
10 boundary, so this should merge independently of all fifteen. I flagged
this to the user directly this run (a notification, not just this file)
given how long it's been sitting — see below.

### Running backlog tally (15 CRITICALs)

**10 [FIXED] / 1 [PARTIALLY FIXED] / 4 still open — unchanged by tonight.**
Verified directly against `master`'s current `BACKLOG.md`
(`awk '/^## CRITICAL/,/^## MAJOR/' BACKLOG.md | grep -c '\[FIXED\]'` → 10,
`grep -c '\[PARTIALLY FIXED\]'` → 1, 15 `### ` headings total under the
CRITICAL section). The 4 still open are the core architectural gap and its
three near-duplicate phrasings — untouched tonight. Tonight's mutation-
testing finding is new (not one of the 15 named CRITICALs), so the tally
itself doesn't move.

### What I did

**Primary item — mandatory per-cycle mutation-testing pass, all four
required files, direct against `master`'s tip.** Chose `flags.py` as the
main target since 2026-09-16's own "what the next run should pick up"
list named it as the file without a *fresh* pass directly on `master`
since 2026-08-16/17 (its only unmerged fresh pass sits on PR #18, still
open). Thirteen targeted mutations total: nine in `flags.py`, two each in
`scoring.py` and `names.py`, two in `verify.py`. Twelve caught immediately
by the existing suite. One real, previously-unpinned survivor:

**`flags.py`'s flag 10 ("No Independent Validation"): `if ctx.word_count
>= 40 and find_terms(...)` survived as `>= 20`.** Two pins already existed
from 2026-08-17 — a 9-word bio (well below any threshold) and exactly
40 words (right at the real one) — but neither rules out a threshold
lowered into the 20–39 word gap between them. Verified live against the
real, unmutated pipeline: a 29-word bio with a leadership claim
("Founder") and tech claims ("hardware", "satellite"), no source URLs, no
press language, correctly returns UNKNOWN ("too little material to expect
validation signals") today. Under the `>= 20` mutant it flips to TRIGGERED
("substantial claims with zero third-party validation") — a mid-length,
ordinarily terse bio wrongly condemned for a silence it has no room to
fill. This is the same fairness family the task brief calls out (short
profiles scored as deception), just a specific gap the existing pins
didn't close. Pinned with a new regression test
(`tests/test_flags.py::TestIndividualFlags::test_a_mid_length_bio_below_40_words_stays_undecided`),
confirmed RED against the mutant, GREEN against the restored code. No
production file changed — `larp_meter/flags.py` is byte-identical to
`master`; only `tests/test_flags.py` differs, chosen deliberately to keep
this branch's merge-collision risk as low as possible against the
fifteen-deep queue.

Full mutation-by-mutation list, including the twelve caught (already
correctly pinned) mutations across all four files, is in BACKLOG.md's new
"Mutation-testing pass: `flags.py`'s 'No Independent Validation' word-count
floor" entry.

**End-to-end CLI check**: ran two hand-written samples through the real
CLI (`python3 -m larp_meter --text ... --name ...`, no `--verify`, matching
the standing brief's requirement to run the actual pipeline, not just call
flag functions directly). A clean, honest firmware-engineer bio (BSc
Electrical Engineering, named employers, an open-source library) and the
BACKLOG.md "Dr. Marcus Vane" fabrication archetype (soft output claims,
self-referential partners, an active funding ask). Both landed
INSUFFICIENT DATA as expected given each profile's thinness — coverage
14% and 24% respectively, both below `MIN_COVERAGE`. The fabricated sample
correctly TRIGGERED flag 10 (well past the real 40-word threshold, with a
leadership+tech claim and no press) and flag 7 (fundraising with zero
traction); the honest sample TRIGGERED flag 6 only because "working on" is
in `building_claims` with no cited artifact — an already-documented,
unrelated instance of the core architectural gap (a truthful "I build
firmware" reads as an unverifiable claim exactly like a fabricator's would,
because nothing here reaches a registry), not something this branch
touched or should try to fix in passing.

### What I confirmed / refuted in BACKLOG.md

- **Confirmed** (live repro, not by reading a PR description): the flag 10
  word-count boundary gap above is real and reproduces on `master`'s
  actual, unmutated code exactly as described — new finding, now recorded.
- **Confirmed** (live repro): `verify.py`'s `_attribute` — the exact
  "a function's return contract grew a `None` case, a caller
  mis-handled it as `False`" bug class the standing instructions use as
  their worked cautionary example — is correctly guarded on `master`
  today (`elif match is None:` is a distinct branch from `elif match:`,
  and mutating it back to a bare truthy check is caught by the suite).
  Re-confirming this each cycle is cheap insurance given how much damage
  a regression here would do.
- Did not re-investigate any of the 15 CRITICALs or other existing
  BACKLOG.md entries beyond the mutation-testing spot-checks above.

### Mutation-testing log

| File | Mutation | Result |
|---|---|---|
| `names.py` | `tokens()` split reading: drop `and t not in PARTICLES` | **Survived — real, now pinned** (`TestSplitReadingAlsoFiltersParticles`) |
| `names.py` | script-mismatch guard: `!=` → `==` | Caught |
| `names.py` | two-token confidence: `len(present) >= 2` → `> 2` | Caught |
| `names.py` | `if not at_an_end:` → `if at_an_end:` | Caught |
| `names.py` | single-token loop: `if not extra or all(...)` → `if not extra and all(...)` | Survived — investigated, concluded unreachable, not pinned (see BACKLOG.md) |
| `names.py` | drop `if not mine: return None` | Caught |
| `names.py` | drop `if not usable: return None` | Caught |
| `names.py` | mononym branch: `return bool(present)` → `return True` | Caught |
| `names.py` | `tokens()` split reading length filter: `len(t) > 1` → `>= 1` | Caught |
| `scoring.py` | `scored = coverage >= MIN_COVERAGE` → `>` | Caught |
| `scoring.py` | floor equality: `<=` → `<` | Caught |
| `scoring.py` | `LEVELS` boundary: `larp < cut` → `larp <= cut` | Caught |
| `scoring.py` | `category_scores` filter: `(TRIGGERED, PASSED)` → `(TRIGGERED,)` | **Survived — real, now pinned** (`TestCategoryScoresBlendPassedAndTriggered`) |
| `flags.py` | flag 11: `if refuted or mismatched:` → `if refuted and mismatched:` | Caught (spot-check only, re-confirming a prior pin) |
| `verify.py` | `verify_institution`: `if wanted and wanted <= have:` → `if wanted <= have:` | Caught (spot-check only, re-confirming a prior pin) |

**Result: 476 tests green** (473 → 476: two new tests in `test_names.py`,
one in `test_scoring.py`, plus one already added since the last count).
`names.py` and `scoring.py` both got a real, fresh mutation-testing pass
tonight with new findings pinned directly to `master`. `flags.py` and
`verify.py` were spot-checked only (one guard each, both still holding) —
their own full sweeps still live exclusively on the unmerged `nightly/2026-
08-18`/`nightly/2026-08-19` branches (PRs #4/#5) referenced in the open-PR
section above; per-file mutation-testing coverage on `master` itself is
strongest for `scoring.py` and now `names.py`, weaker for `flags.py` and
`verify.py` until either the human merges PR #4/#5 or a future run repeats
their sweeps directly.

### What I learned

- A mutation surviving does not always mean a live bug — sometimes it means
  the branch it touches is unreachable given the rest of the function's own
  logic, and the right response is to document *why*, not to force a test
  onto a scenario the code can't actually produce. Spending the time to
  trace the "why" (rather than shrugging and moving on) is what makes that
  conclusion trustworthy enough to record instead of re-deriving next time.
- Deliberately choosing mutation-testing targets by which files the current
  open-PR queue does NOT touch is a cheap way to guarantee tonight's branch
  merges independently of the backlog above, without sacrificing the
  cycle's mandatory four-file requirement — worth doing again while the
  queue stays this deep.
- The false-MISMATCH direction (accusing an honest person) is this
  project's stated top priority, but tonight's `tokens()` finding is the
  opposite failure mode — a false MATCH that could validate a fabricator's
  stolen-identity claim against a real stranger's real record. Worth
  keeping both directions in mind during future `names.py` work: the
  project's own governing value is asymmetric on purpose, but a false
  positive still actively helps a LARPer evade detection, which is exactly
  what this tool exists to prevent.

### What the next run should pick up first

1. **The open-PR queue is now thirteen deep and nineteen nights old** —
   this is the single biggest risk to the project's own bookkeeping being
   trustworthy (BACKLOG.md's `[FIXED]` tags and this file's tally only
   reflect `master`, and real, independently-verified fixes for several
   more findings already exist unmerged). Flagging again, not acting — a
   human merge pass is overdue.
2. The core architectural gap remains fully untouched since 2026-08-27's
   visibility-only OpenAlex slice — still the single highest-value,
   highest-risk piece of unbuilt work in the repo. Every night that defers
   it (including tonight) is a legitimate scoping choice, but it cannot be
   deferred forever.
3. `flags.py` and `verify.py` need their own full mutation-testing sweeps
   repeated directly against `master` (not just the spot-checks tonight
   re-confirmed) if PRs #4/#5 continue to sit unmerged — both files have
   had real, unpinned survivors found and fixed by unmerged branches before,
   and a spot-check on one or two guards each cannot substitute for the
   full 6-and-13-mutation sweeps those PRs already did.
| `verify.py` | `_is_ambiguous_acronym`: `len(stripped) <= 5` → `< 5` | Caught |
| `verify.py` | arXiv error feed: `"api/errors" in entry_id or title == "error"` → `and` | Caught |
| `verify.py` | GitHub comparability: `len(published.split()) >= 2` → `> 2` | Caught |
| `verify.py` | `verify_institution`: `if wanted and wanted <= have:` → `if wanted <= have:` | Caught (spot-check, re-confirming the 2026-08-18/19 pin) |
| `verify.py` | `verify_patent`: `if not title or "not found" in title.lower():` → `if not title:` | **Survived — real, now pinned** (`test_google_patents_not_found_page_is_not_scraped_as_a_scrape_failure`) |
| `verify.py` | `verify_institution` tie-break: `if overlap > best_overlap:` → `>=` | **Survived — real, now pinned** (`test_ror_tie_break_keeps_the_registrys_own_higher_ranked_result`) |

**Result: 475 tests green** (473 on `master` → 475: two new tests, one in
`tests/test_regressions.py`, one in `tests/test_verify.py`). `verify.py`
has now had two mutation-testing passes on `master` itself: 2026-08-18's
spot-check (1 guard) and tonight's wider sweep (6 mutations, 2 pinned). The
**full** 6-mutation sweep PR #4 (`nightly/2026-08-18`) already did remains
unmerged and is the more complete pass — tonight's is a second, partially-
overlapping but independently-run pass, not a replacement for landing that
branch. `names.py`, `scoring.py` and `flags.py` were not touched tonight;
see 2026-09-15's entry for `names.py`/`scoring.py`'s own fresh sweep
(also still unmerged, on PR #24).

### What I learned

- Live-probing a real third-party endpoint before writing a mutation-
  testing regression test is worth the few extra minutes: my first
  instinct was to assume the "not found" title check was reachable via a
  straightforward nonexistent-patent-number request, and only checking
  live (several malformed IDs against the real Google Patents endpoint)
  showed that path actually 404s and never reaches this code — the check
  guards a narrower, HTTP-200-but-app-level-404 case instead. Getting the
  actual failure shape right made the pinning test test something real
  rather than a scenario that cannot occur — the exact trap PR #24's
  "unreachable branch" writeup from the night before also called out for a
  different function.
- Deliberately picking a mutation-testing target with zero overlap against
  every open PR's stated file list (by title alone, not by diffing each
  branch) is a cheap, repeatable way to guarantee a test-only branch merges
  independently while the queue stays this deep — 2026-09-15 did the same
  thing for `names.py`/`scoring.py`; worth continuing until the queue
  clears.

### What the next run should pick up first

1. **The open-PR queue is now fourteen deep and three weeks old.** This is
   the single biggest risk to the project's own bookkeeping (BACKLOG.md's
   `[FIXED]` tags, this file's tally) staying trustworthy, and to nightly
   runs continuing to waste effort re-discovering findings that already
   have a fix sitting on someone else's unmerged branch. Flagging again,
   not acting — a human merge pass is the single highest-value action
   available, full stop.
2. The core architectural gap remains fully untouched since 2026-08-27's
   visibility-only OpenAlex slice — still the single highest-value,
   highest-risk piece of unbuilt work in the repo, and still blocked on the
   same disambiguation groundwork (merged OpenAlex author entities,
   common-name collision, the per-affiliation `years`-array corroboration
   signal) every recent entry has named. Re-verify OpenAlex's live rate
   limits and response shapes before resuming this — the task brief's own
   numbers are already a month old as of tonight.
3. `flags.py` and `names.py`'s split-reading union (2026-09-15's finding)
   are the two remaining required files without a *fresh* mutation-testing
   pass directly on `master` (as opposed to on an unmerged branch) —
   `flags.py` specifically hasn't had one since 2026-08-16/17.
| `flags.py` | flag 10: `ctx.word_count >= 40` → `>= 20` | **Survived — real, now pinned** |
| `flags.py` | `f_education`: `not credentials and not degrees` → `or` | Caught |
| `flags.py` | `f_self_referential`: `partners and owned` → `or` | Caught |
| `flags.py` | `f_experience`: `not titles or not claimed` → `and` | Caught |
| `flags.py` | `f_timeline`: future-date detection dropped | Caught |
| `flags.py` | `f_fundraising`: `not asks` → `asks` | Caught |
| `flags.py` | `f_fundraising`: `traction_claims` → `not traction_claims` | Caught |
| `flags.py` | `f_credentials`: `not institutions` → `institutions` | Caught |
| `flags.py` | `f_logo_wall`: `>= 4` partner threshold → `>= 3` | Caught |
| `scoring.py` | `coverage >= MIN_COVERAGE` → `>` | Caught |
| `scoring.py` | floor-severity `<=` → `<` | Caught |
| `names.py` | `mine_is_latin != blob_is_latin` → `==` | Caught |
| `names.py` | `len(present) >= 2` → `>= 1` | Caught |
| `verify.py` | `_attribute`'s `elif match is None:` → `elif match:` | Caught |
| `verify.py` | `_attribute`'s `not self.subject_name` guard dropped | Caught |

**Result: 474 tests green** (473 on `master` → 474: one new test in
`tests/test_flags.py`). All four required files now have at least one
mutation-testing pass whose *pin* lives directly on `master` (flags.py:
tonight; scoring.py: 2026-08-16; names.py: the zero-candidates guard pinned
2026-08-27, script-mismatch/confidence-threshold spot-checked tonight;
verify.py: the `wanted`/`have` guard pinned 2026-08-27, `_attribute`
spot-checked tonight) — though the *full, exhaustive* sweeps for
`names.py` and `verify.py` still only exist on unmerged PRs #5 and #4
respectively.

### What I learned

- **A stale bytecode cache produced a false result mid-session.** After
  mutating `flags.py`, running the suite, and restoring the file via
  `git checkout`, a follow-up direct call to `f_validation` on the
  restored, verified-byte-identical source still returned the *mutated*
  behavior — until `find . -name __pycache__ -exec rm -rf {} +` was run.
  Python does check source mtimes against `.pyc` timestamps, but rapid
  mutate/restore/mutate cycles within the same second (or a restore that
  doesn't bump mtime past the cached one) can defeat that check. Any
  future mutation-testing pass should clear `__pycache__` before *every*
  single test run, mutated or restored — not just once at the start —
  or risk chasing a phantom bug for several minutes, as happened here.
- Keeping tonight's change to a test file only (zero production diff)
  continues to be the cheapest way to guarantee a branch merges
  independently while the queue stays this deep — the third night in a
  row to do this deliberately (2026-09-15 for names.py/scoring.py,
  2026-09-16 for verify.py, tonight for flags.py).

### What the next run should pick up first

1. **The open-PR queue is now fifteen deep and over three weeks old.**
   Notified the user directly about this tonight (not just this file) —
   it has now roughly doubled since 2026-08-27's seven-PR warning with
   zero merges in between. This remains the single highest-leverage
   action available on this project, full stop.
2. The core architectural gap remains untouched since 2026-08-27's
   visibility-only OpenAlex slice (plus PR #11's still-unmerged
   merge-risk qualifier). Still blocked on the same disambiguation
   groundwork every recent entry has named — re-verify OpenAlex's live
   rate limits and response shapes before resuming, the brief's numbers
   are now over a month old.
3. `names.py` and `verify.py` still only have their *exhaustive* sweeps
   sitting on unmerged PRs #5 and #4 — once the queue clears, `master`
   inherits full coverage for both; until then, tonight's and previous
   nights' spot-checks are a stopgap, not a substitute.
