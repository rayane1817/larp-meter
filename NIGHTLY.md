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
