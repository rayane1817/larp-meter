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
