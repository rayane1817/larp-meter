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
