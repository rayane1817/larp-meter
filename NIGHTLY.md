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
