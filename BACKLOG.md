# LARP Meter — verified-gap backlog

Recovered from workflow run `wf_f141facb-301` (5 independent code-review lenses,
63 raw findings, 46 after dedup). **These are UNVERIFIED** — every adversarial
verification agent and the design agent died on session rate limits, so nothing
here has survived a skeptic pass. Treat each as a lead to confirm, not a fact.

Two criticals from this run are already FIXED (marked below).

Severity mix: {'critical': 15, 'major': 25, 'moderate': 19, 'minor': 4}

---

## Shipped since the original review (not from the 63 findings above)

### `is_linkedin_paste` misfired on an ordinary CV, and the parser then silently dropped most of its content (2026-08-31, nightly run)

Not from the original 63 findings — flagged as untested speculation in the
2026-08-17 entry's "worth a dedicated look" list ("`is_linkedin_paste`'s
signal-scoring could plausibly misfire on an ordinary CV that uses bare
'Experience'/'Education' as section headers"). Reproduced live before
touching anything, and it's real and severe:

`is_linkedin_paste`'s signal count gives bare `"Experience"`/`"Education"`
section headers +2 each (4 total, already past the `signals >= 4` gate) with
no requirement that anything else in the text is actually LinkedIn-specific.
A plain resume using those two words as headers — the single most common CV
shape there is — clears the threshold on headers alone, or on headers plus a
bare `"2019 - Present"` date range (`_YEAR_RANGE_RE`), which is just as
common in an ordinary CV as in a LinkedIn paste. Neither signal is actually
LinkedIn-specific; only the month-based `"Jan 2020 - Present · 2 yrs"`
date/duration combo, the `"· Full-time"` employment-type suffix, and UI
chrome (`Message`/`Follow`, a connections count, endorsements) are.

The consequence is not a mislabelling — it's content loss. Once
`is_linkedin_paste` returns True, `cli._maybe_normalise` replaces the entire
audited text with `parse_linkedin_paste(text).to_prose()`.
`_parse_experiences` only tags an experience group as "dated" via the
month-based pattern above; a plain `"2019 - Present"` line doesn't match, so
every group in an ordinary CV is (wrongly) tagged `has_date=False` and all of
them get folded into one entry via the "merge a no-date group into the
preceding one" step, whose non-date branch keeps only the first two lines
(title, company) of the resulting blob. Concretely, on a two-job hand-written
CV fixture: the entire second job and both achievement sentences vanished —
75 words of pasted CV became 31 words of prose — before `extract_claims` ever
ran. This is data loss against an honest person's real claims, not a false
accusation, but it's still a real defect: an audited profile that no longer
contains what the subject actually wrote.

Fixed by requiring at least one genuinely LinkedIn-specific marker
(`has_linkedin_marker`: the date/duration regex, the employment-type regex,
or ≥2 chrome lines) in addition to the existing `signals >= 4` and
`(has_experience or has_education)` gates. This narrows detection, never
widens it — the module's own docstring already states the correct bias
("false positives are worse than false negatives... raw paste still works,
just with weaker extraction"), so trading a hypothetical false-negative
(an unusual LinkedIn paste with no month-based dates, no chrome, and no
"Full-time"/etc. suffix) for eliminating this false-positive is the right
direction per the module's own stated design intent.

Two tests, written first and watched fail against the unmodified code:
`test_ordinary_cv_with_bare_headers_is_not_mistaken_for_linkedin_paste`
(unit, `is_linkedin_paste` directly) and
`TestOrdinaryCvContentSurvives.test_second_job_and_achievements_survive_the_real_pipeline`
— the latter runs the real `larp_meter.cli.main()` end-to-end, per this
repo's standing lesson that a unit test on `is_linkedin_paste` alone proves
nothing about whether the real `--text` pipeline still contains the dropped
content once it gets there (the same shape as the ROR/HANDLERS dead-code bug
and the `_attribute`/`None` bug). Confirmed both existing LinkedIn fixtures
(`LINKEDIN_PASTE`, `MINIMAL_PASTE`) still detect correctly — both already
carry a real month-based date/duration match. 473 → 475 tests, green
throughout. Required end-to-end CLI check run on two additional hand-written
samples beyond the test suite: a clean LinkedIn paste with genuine markers
(still detected and normalised, `mode: text:linkedin`) and a fabricator's
plain-text CV with a self-applied "Dr." title and no matching credential
(no longer normalised, `mode: text`, flag 13 correctly TRIGGERED once
`--name` is supplied — UNKNOWN with no `--name`, exactly as flag 13's own
documented contract requires).
### `claim.context`'s fixed 60-character window clipped a disclaiming phrase far from its identifier (nightly/2026-09-03)

Found during a red-team pass on `_disclaims_authorship` (`verify.py`, added
2026-08-25 — see that entry further down) rather than in BACKLOG.md itself;
recorded here for the same reason every other "Shipped" entry is. The guard
only ever sees what `extract.py`'s `_context()` captures into `claim.context`,
and that was a fixed `match.start() - 30` .. `match.end() + 30` window,
inherited unmodified from a pre-existing display helper never designed for
this job. A disclaiming phrase sitting near the start of a longer sentence,
with the identifier landing further along, scrolled out of that window
before `_disclaims_authorship` ever saw it. Confirmed live before touching
anything:

```python
text = ("I have spent my career as outside patent counsel prosecuting numerous "
        "filings on behalf of corporate clients, including for instance "
        "US9876543 which I filed for a sensor startup.")
extract_claims(text)[...].context
# -> 'ients, including for instance US9876543 which I filed for a sensor st'
# "on behalf of" -- the only disclaiming phrase in the sentence -- is gone.
```

An honest patent attorney's or research consultant's own sentence, written
in one continuous clause with no period before the identifier, produced a
false `MISMATCH` — floored at ORANGE by flag 11 — purely because their
sentence was long enough for the disclaimer to sit more than 30 characters
before the identifier it qualifies. This is the same finding shape as the
"any identifier is treated as a personal authorship claim" CRITICAL further
down (already `[FIXED]`), one layer deeper: that fix taught `_attribute` to
recognize a disclaiming sentence at all, but never asked whether the
sentence fragment it was given was ever wide enough to contain one.

**The fix**, `larp_meter/extract.py`'s `_context()`: scan outward from the
match to the nearest sentence-ending punctuation on each side (capped at 300
characters to bound the scan on a pathological unpunctuated document, the
same reason `matching.py`'s `is_negated` caps its own lookback) instead of a
fixed character count. `claim.context` is consumed nowhere else in the
codebase (confirmed by grep before relying on that: `_disclaims_authorship`
is its only reader), so this could be widened freely with zero risk to any
other caller. Two follow-on bugs surfaced by the same testing discipline
this fix itself demanded, both fixed in the same PR rather than shipped
separately:

1. **A bare newline must not be a sentence boundary.** The first cut of this
   fix included `\n` in the boundary character set, by analogy with
   `matching.py`'s clause boundaries. But `claim.context` has no equivalent
   need to stop negation from bleeding into the next bullet point — it only
   ever *widens* a window to catch a disclaimer, and an ordinary
   word-wrapped line break (a plain-text paste, a PDF-extracted CV, a
   hard-wrapped email) reintroduced the exact bug one line-length away: a
   disclaiming phrase on one physical line and the identifier on the next
   went right back to being severed. Caught by the standing "run the CLI
   end-to-end on a real file" requirement — a heredoc-written sample text
   file line-wraps at ~80 characters by construction, and the live run came
   back MISMATCH where the offline unit test (a single Python string
   literal, never wrapped) had already gone green. Fixed by dropping `\n`
   from the boundary set entirely; the 300-character cap alone is enough to
   bound cost, and over-widening into an adjacent paragraph in the rare case
   this misses can only ever add a disclaiming phrase, never remove one —
   the same "costs coverage, never accuses" direction this file is already
   allowed to fail in.
2. **`_NON_ATTRIBUTION_CONTEXT_RE`'s citation alternative matched the passive
   voice.** `cit(?:e|es|ed|ing|ation)` was written for "citing prior art" /
   "cited in our review" (the subject citing someone else's work) but also
   matched "is cited BY" — other people citing the *subject's own* paper,
   which is corroboration, not a disclaimer. This existed before tonight but
   rarely fired: the word "cited" needed to land within the old 30-character
   radius of an identifier by accident. Widening the window to the whole
   sentence made that collision realistic — live-confirmed with a fabricated
   "Dr. John Smith... his landmark paper, `<doi>`, is considered
   foundational... and is cited by thousands of researchers worldwide" (the
   DOI is a real, unrelated author's paper): the word "cited" 83 characters
   after the identifier let a genuine fabrication escape from `MISMATCH` to
   `UNCHECKABLE`. Also caught by the standing end-to-end requirement, not by
   re-reading the diff. Fixed with a negative lookahead,
   `cit(?:e|es|ed|ing|ation)(?!\s+by\b)`; "citing prior art" and "cited in"
   still match, "is cited by" no longer does.

**Verification:** 8 new tests across `tests/test_extract.py` (context
captures a distant same-sentence disclaimer; does not cross a preceding or a
following sentence boundary; survives an ordinary word-wrap), `tests/test_verify.py`
(the "cited by" false-negative and its "citing ... as prior art" negative
control; a full end-to-end test through `run_audit` with the realistic
distant-disclaimer sentence), and `tests/test_round4.py` (a 20,000-match
unpunctuated-document perf guard, matching the file's existing hype-heavy-
document test). Each was written first, watched fail against the
unmodified code, then fixed. Mutation-tested the new boundary logic directly
(inverting the "closest boundary wins" comparison on both the backward and
forward scan) — both caught, both confirmed with a clean `__pycache__` first
(see "what I learned" in NIGHTLY.md's 2026-09-03 entry: a mutate-then-restore
cycle inside the same wall-clock second can leave a stale `.pyc` that
silently serves the *previous* mutation's bytecode instead of the restored
source, producing a false "no test caught this" reading if you don't clear
it). Ran the real CLI end-to-end, live against Crossref, on both directions:
an honest, hard-wrapped disclaiming sentence citing a real, unrelated DOI now
correctly reads `UNCHECKABLE` (was `MISMATCH`); a fabricator attaching the
same real DOI to a fake author's name with no disclaiming language anywhere
still correctly reads `MISMATCH`, flag 11 `TRIGGERED`. Full suite: 473 → 481
tests, green throughout the whole sequence (after the primary fix, after
each of the two follow-on fixes, and at the end).
### Mutation-testing sweep: `flags.py`'s buzzword short-text carve-out, plus two write-up corrections (nightly/2026-09-09)

Mandatory per-cycle mutation pass, all four required files. Systematic sweep
(~20 hand-applied mutations across `names.py`, `verify.py`, `flags.py`)
rather than a single spot-check, since a prior night's write-up (see
correction below) turned out to have reported a false survivor — worth the
extra rigor of re-confirming CAUGHT results too, not just trusting the
narrative.

**One real survivor, pinned:** `flags.py`'s `f_buzzwords`, the short-text
carve-out at `if ctx.word_count < 25:` (line 203), survived a mutation to
`< 24`. An existing test (`test_buzzword_flag_does_not_use_the_short_text_
carve_out_at_25_words`, 2026-08-17) pins the *upper* edge — 25 words must
NOT get the carve-out — but nothing pinned the lower edge, and the two
directions are not symmetric. A 24-word text with zero buzzwords is PASSED
either way (the carve-out's "no distinct terms" branch and the ordinary
density formula both land on 0 distinct — same status, different message),
which is exactly why a naive "add a boundary test" attempt would still miss
it. The gap only surfaces with a *sparse hit*: one buzzword in 24 words
should be UNKNOWN ("too short to judge") under the real `< 25` guard, but
under the mutated `< 24` it falls through to the ordinary density formula
(1/24×100 ≈ 4.2%, still under the ≥4-distinct trigger gate) and comes back
PASSED ("density is normal") — silently manufacturing a decided,
coverage-counting verdict for a profile with exactly the wrong-sided amount
of data to tell "no hype" from "too little text to say". Confirmed live:
the new test fails against the mutated line and passes against the
restored one. Pinned in `tests/test_flags.py::TestIndividualFlags::
test_buzzword_flag_still_uses_the_short_text_carve_out_at_24_words`. No
production change — the guard was already correct, just unasserted in this
direction.

Every other mutation tried in `names.py` and `verify.py` this pass was
already caught by the existing suite (see NIGHTLY.md's 2026-09-09 entry for
the full list attempted). Two were investigated as possible survivors and
ruled out as equivalent mutants rather than pinned: `names.py`'s
`if not extra or all(w in mine for w in extra):` (line 152) is provably
unreachable-when-true in its `or`-branch, because any candidate word that
is also one of the subject's own tokens would already have been counted in
`present` earlier in the function, contradicting the `len(present) == 1`
branch it sits inside — so `and` in place of `or` cannot change any
reachable outcome. `names.py`'s particle filter on the un-hyphenated
`split` reading of `tokens()` (line 59) has the same non-effect in the
scenarios checked: dropping it lets a particle leak into `mine`'s token
count, but the later `parts` recomputation inside `name_matches` re-applies
its own particle filter independently, and in every scenario tried this
downgrades an already-correct `False` (confident mismatch) to `None`
(unanswerable) rather than ever producing a wrong `True` — the safe
direction per this project's own governing value, not a new accusation
risk. Recorded here rather than silently dropped, since either could
still matter for a scenario this pass didn't think to construct.

**Correction to the 2026-08-27 entry below** ("Mutation-testing spot-check:
`names.py`'s 'zero usable candidates' guard confirmed still live on
master"): that entry also claimed `verify.py`'s `verify_institution`
`if wanted and wanted <= have:` guard was "confirmed still live and
unpinned on master", re-found independently on four then-open PRs
(#4/#6/#7/#9). This was wrong, and had been wrong since before it was
written. Direct history check: the guard was pinned on `master` via commit
`7d07d08` on 2026-08-23 (`test_verify.py::
test_a_claim_of_nothing_but_stopwords_cannot_be_verified`), four days
*before* the 08-27 entry, and re-pinned a second time by this file's own
2026-08-26 entry immediately above
(`test_a_stopword_only_institution_claim_cannot_verify_against_any_hit`) —
one day before the 08-27 entry claimed it was unpinned. Live-reproduced
tonight on current `master`: mutating that exact guard now fails 3 tests
(one in `test_mutation_guards.py`, two in `test_verify.py`), confirming
it is caught, not exposed. The likely cause: PRs #4/#6/#7/#9 were all
independently branched from `master` *before* the 08-23 fix landed, so
their own descriptions were accurate for the commit they branched from —
but by the time the 08-27 nightly run wrote "still live... unpinned on
master", the fix had already reached `master` twice over, and nobody
re-ran the mutation to check before asserting it as a live finding. Lesson
for future nights: "matches N other independent write-ups" is not the same
as "reproduced against the actual current tip" — reproduce live before
citing agreement as corroboration, especially once several nights have
passed and unrelated commits may have already landed the fix another way.

**Also corrects the running backlog tally**, which the same 08-27 entry
carried forward as "8 [FIXED] / 1 [PARTIALLY FIXED] / 6 still open". A
fresh direct count against `BACKLOG.md`'s current `## CRITICAL (15)`
section (`grep -c` on the section's own `### ` headers, not a remembered
figure) gives **10 [FIXED] / 1 [PARTIALLY FIXED] / 4 still open** — the
count itself has not changed since 08-27 (no CRITICAL item was marked
either way in between), so 8/1/6 appears to have been a miscount at the
time it was written, not a stale-but-then-accurate figure. See NIGHTLY.md's
2026-09-09 entry for the full per-item breakdown.
### The "own account" caveat only checked Wikipedia, never a genuine OpenAlex hit (nightly/2026-09-10)

Not from the original 63 findings — found while reading `report.py`'s `caveats()`, a file with no full mutation-testing pass and untouched by any of the eight then-open `nightly/*` PRs (see NIGHTLY.md's 2026-09-10 entry for the queue state). `caveats()`'s single most consequential disclaimer — "Nothing here was checked against an outside source: the passing flags rest on the subject's own account of themselves" — is meant to fire only when a GREEN/YELLOW verdict rests on nothing but the subject's own text. It already excused itself correctly when `signals["wikipedia_about_subject"]` was set (the 2026-08-15 registry-wiring work), but never checked `signals["openalex"]` at all, even though flag 6 (`f_output`) reads that exact signal to PASS with "Independent scholarly record found: N works with M citations (OpenAlex)" — genuine outside-source corroboration, from the same `_subject_registry_signals` gather that sets `wikipedia_about_subject`.

**Confirmed live before touching anything:**
```python
>>> caveats({"level": "GREEN", "verification_effective": False,
...          "signals": {"openalex": {"works": 12, "citations": 340}}})
["Nothing here was checked against an outside source: the passing flags rest on the "
 "subject's own account of themselves. A well-written fabrication passes this easily..."]
```
A subject with zero identifiers in their bio but a real, name-matched OpenAlex author record — the exact case the 2026-08-15 registry-wiring work exists to give credit for — got told nothing had been externally checked, one paragraph below a flag whose own evidence text said the opposite. This doesn't manufacture a false accusation (the underlying score/level is unaffected), but it actively misleads a reader about how much of the report is unverified self-report versus how much rests on a real outside source — exactly the distinction this caveat exists to draw.

**Fix:** `caveats()` now also treats a real OpenAlex hit (`scholar and scholar.get("works")`, mirroring flag 6's own truthiness check exactly) as outside-source corroboration, alongside `wikipedia_about_subject`. A completed-but-empty OpenAlex search (`signals["openalex"]` is `None` — the genuine "asked, and found nothing" case the 2026-08-27 entry made visible) is deliberately NOT treated as corroboration and still gets the full caveat; pinned as its own test so the fix doesn't overcorrect into silencing the disclaimer on a negative or absent result.

**Verification:** 3 new tests — 2 in `tests/test_report.py` (the fix itself, and the negative-search-must-not-silence-it guard) and 1 true end-to-end test in `tests/test_cli_registry_wiring.py` running the real `cmd_text` → `run_audit` → `caveats` chain with the network stubbed, confirming `_subject_registry_signals`'s OpenAlex signal reaches `caveats()` in the exact shape it expects rather than only a hand-built dict in a report.py-only test. All three written first and confirmed to fail against the unmodified code (and, for the two isolated tests, re-confirmed by reverting the fix and re-running — both failed identically to the pre-fix repro above), then pass after the fix. Mutation-tested the new code directly (dropping the new clause entirely; renaming `"works"` to a wrong key) — both caught. Full suite: 473 → 476 tests, green throughout.

**Also, a mutation-testing spot-check finding, not duplicated as a fifth test:** the mandatory per-cycle sweep found `verify.py`'s ROR nearest-name tie-break (`if overlap > best_overlap:` → `>=`) still **survives** on current `master`. This is not new — it's the same survivor `nightly/2026-09-04` (PR #16, still unmerged as of tonight) already found and pinned with `test_nearest_name_tie_break_is_deterministic_not_last_writer_wins` — but that fix lives only on the unmerged branch, so `master` itself is still exposed. Per the 2026-08-27 entry's own precedent ("the actual fix here is merging... not writing this test again"), recorded here rather than re-pinned a second time. `scoring.py` (`LEVELS` cut boundary), `names.py` (`present`-count boundary) and `flags.py` (`f_contradicted`'s `or`/`and`) were all spot-checked the same way and remain caught — no new gap in those three.
### Mutation-testing spot-check: all four required files (2026-09-11, nightly run)

Mandatory per-cycle sweep. `scoring.py` (`_apply_floors`'s `<=` tie-break), `names.py` (`name_matches`'s `len(present) >= 2` threshold), and `flags.py` (`f_contradicted`'s `if refuted or mismatched:`) were each mutated one line at a time and **all three were caught** — no new production gap in those three tonight.

`verify.py`'s ROR nearest-name tie-break (`verify_institution`: `if overlap > best_overlap:` → `>=`) **still survives on `master`**, confirmed live tonight. This is not new — `nightly/2026-09-04` (PR #16) already found and pinned it with `test_nearest_name_tie_break_is_deterministic_not_last_writer_wins`, and `nightly/2026-09-09`/`nightly/2026-09-10` both re-confirmed it live and declined to write a sixth copy of the same test, per the 2026-08-27 entry's own precedent ("the actual fix here is merging... not writing this test again"). Doing the same tonight — this is now the fourth or fifth independent re-confirmation. `master` remains exposed to it until PR #16 (or any of the later PRs that inherited its fix) merges.

### Mutation-testing spot-check: `verify.py` + `names.py` (2026-08-26, nightly run)

Not a full sweep (that's `nightly/2026-08-18`'s and `nightly/2026-08-19`'s work, still
unmerged — see NIGHTLY.md's 2026-08-26 entry for the open-PR state). One
per-cycle mutation each in all four required files
(`scoring.py`, `flags.py`, `verify.py`, `names.py`), re-targeting guards those two
still-open PRs already found and described, to check whether `master` itself is still
exposed. `scoring.py`'s `coverage >= MIN_COVERAGE` boundary and `flags.py`'s
`if refuted or mismatched:` guard were both **caught** — already pinned by the
2026-08-16 direct-to-master sweeps. Two **survived on `master`**, confirming both PRs'
findings are still real and unprotected there:

- **`verify.py`'s `verify_institution`: `if wanted and wanted <= have:` → `if wanted <= have:`
  survived.** An institution claim that reduces to nothing but stopwords (`_significant_tokens`
  strips them) has an empty `wanted` set, and an empty set is a subset of every set — without the
  `wanted and` guard, the *first* ROR item returned, named nothing like the claim, "verifies" a
  claim that named nothing at all. Same bug `nightly/2026-08-18` (PR #4) already found; pinned
  directly here (`tests/test_verify.py::test_a_stopword_only_institution_claim_cannot_verify_against_any_hit`)
  rather than leave `master` unpinned a second time.
- **`names.py`'s `name_matches`: the `if not usable: return None` zero-candidates guard
  survived.** Deleting it did not move a single existing test — every one of them pairs a
  Latin-script subject with the empty-candidates case, and the *separate* script-mismatch guard
  independently also returns `None` for that input, masking whether this guard does anything.
  Un-masked with a non-Latin subject: `name_matches("Михаил Иванов", [])` goes `None` → `False`
  with the guard deleted (the Latin equivalent, `name_matches("Ada Lovelace", [])`, stays `None`
  either way — it never reaches this guard's absence). Same bug `nightly/2026-08-19` (PR #5)
  already found; pinned directly here (`tests/test_names.py::TestZeroCandidatesIsUnanswerable`,
  both the non-Latin case that actually discriminates and the Latin case that documents the
  masking) rather than leave `master` unpinned a second time.

Both mutations reconfirmed CAUGHT after their pinning tests were added, and reconfirmed PASSING
against the restored, unmutated file. Neither file needed a production change — the guards were
already correct, just unasserted on `master`.

---
### Flag 6: a genuine negative OpenAlex search becomes visible in the report (nightly/2026-08-27)

First slice of the core architectural gap's own recommended first step (see
the CRITICAL entry below, its "[IN PROGRESS]" note): "start by making the
'0 works found for a researcher claiming 40 papers' case visible in the
report at all, even as an UNKNOWN-with-evidence line." Deliberately did NOT
attempt a `CONTRADICTED`/reconciliation verdict — that still needs the
disambiguation groundwork (merged entities, common-name collisions) the core
gap entry describes, and pushing to TRIGGERED off an absence alone is exactly
what the OpenAlex research constraints warn against.

`f_output` (flag 6) already read `ctx.signals.get("openalex")`, but a bare
`.get()` cannot distinguish "no --verify/--name, nothing was ever queried"
from "a real search ran and found nothing" — both come back falsy. Confirmed
live: `providers.OpenAlex.search` always sets the `"openalex"` key once a
search actually completes (`signals = {"openalex": best}`, where `best` is
`None` on zero name-matched candidates), and only omits the key entirely on
an unreachable/unparseable response (`if not body: return [], {}`) — so the
key's mere presence already carries the exact distinction flag 6 needed and
was throwing away.

Added `_openalex_search_note()`: when the key is present and the record
carries no works (either no matching author entity at all, or one that
resolves with zero works — both already collapse to the same "nothing to
report" case one line above in `f_output`), the flag 6 "only unsourced
assertions" message now appends one hedged sentence naming the negative
search result. Deliberately conservative in three ways, following the task
brief's own live-measured OpenAlex constraints: (1) status stays UNKNOWN,
never escalated — absence is a lead, not proof; (2) the note is worded to
flag its own limitation (name-based search under-matches transliterated or
diacritic variants), so the report doesn't read as more confident than the
method deserves; (3) it only fires on the "assertion"-only branch (soft
phrases like "peer-reviewed" with no hard identifier and no "building"
language) — the exact archetype BACKLOG's core-gap entry names ("Dr. Marcus
Vane... published extensively in peer-reviewed venues"), not a blanket
change to every UNKNOWN path.

**Verification:** 4 new tests in `tests/test_flags.py` (two positive, two
negative controls), plus one true end-to-end test in
`tests/test_cli_registry_wiring.py` that runs the real `cmd_text` pipeline
with a stubbed empty OpenAlex response — per this repo's own standing
lesson (the ROR/HANDLERS dead-code bug), a flags.py-only test cannot prove
the real pipeline threads the distinction through `_subject_registry_signals`
into `ctx.signals` at all. Mutation-tested the new guard directly: deleting
the "key present" check makes `ctx.signals["openalex"]` raise `KeyError` on
the exact case the negative control exists to guard, which `evaluate()`'s
per-flag exception catch silently converts into a generic "evaluator error"
UNKNOWN — an early version of the negative-control test used `assertNotIn`
and did not notice this failure mode; rewritten to assert the exact expected
message, which does fail on the mutation. Ran live against the real OpenAlex
API (network reachable this session): a fabricated "Dr. Marcus Vane... peer-
reviewed venues" bio now shows the negative-search sentence under `--verify`
and stays INSUFFICIENT DATA (coverage unchanged at 5% — the note does not
manufacture coverage, flag 6 stays UNKNOWN either way); a real prolific
researcher (Yoshua Bengio) with the same "peer-reviewed" phrasing and no
identifiers still lands on the pre-existing PASSED "Independent scholarly
record found" branch, confirming the positive path is untouched.

**Still fully open** (unchanged by tonight): items (1) and (3) of the core
gap's fix direction — OpenAlex/Crossref hits becoming derived `Claim`s with
provenance, and a reconciliation step that can produce an actual
`CONTRADICTED` status for a quantitative mismatch ("published extensively"
vs. 2 works). Tonight only makes the existing UNKNOWN path honest about what
was actually checked; it adds no new verdict.

### Affiliation-count merge-risk caveat on the OpenAlex "best" pick (nightly/2026-08-30)

The disambiguation groundwork every entry since 2026-08-15 has named as the
prerequisite for any stronger reconciliation verdict — "do the
affiliation/`years`-array corroboration work first" — had never actually
been started. This is a first, deliberately narrow slice of it: `best`
(the OpenAlex candidate `providers.OpenAlex.search` picks when several
name-matched authors exist) was chosen purely by `works_count` plurality,
which the task brief's own research explicitly calls dangerous — a merged
entity typically has a *higher* works_count than any real single person, so
plurality actively prefers the merged record over a genuine one.

Re-verified the brief's core claim live against the real API today rather
than trusting the file's own older numbers: `GET /authors/A5100391883`
(the "Wei Wang" example) now lists **873** affiliations (was 863 when
originally measured) spanning education, healthcare, government and company
institutions across at least China and the US — confirms the merged-entity
problem is still exactly as real as described, with fresh numbers. Also
discovered something the brief didn't have: `GET /authors?search=...` (the
endpoint `providers.py` actually calls) is now hitting OpenAlex's own USD
rate limiter with **`$0` remaining for the rest of today** in this
environment (`"dailyRemainingUsd":0`, `retryAfter` ~21.8h) — even a bare
`/authors?per_page=1` with no search term costs money now. The free
singleton `/authors/{id}` and `/autocomplete/authors` endpoints are
unaffected (`cost_usd: 0.0` on autocomplete, confirmed live) and remain the
only OpenAlex calls this environment could make today. This didn't block
tonight's change (implemented and tested entirely against stubbed fetch
responses, per this repo's own convention — no live-search dependency), but
it's a live, current data point for whoever picks up the reverse-path work
next: prefer the free singleton/autocomplete endpoints over the costed
`/authors?search=` list endpoint wherever the design allows it.

Added `providers._affiliation_institution_count()`: counts distinct
institutions from the full `affiliations` array (`{institution, years}`
pairs — richer than the handful summarised in `last_known_institutions`,
and, per a live check today, present on the singleton response; not
independently confirmed present on the list-endpoint response due to the
$0 search budget above, so the function defensively falls back to
`last_known_institutions` if `affiliations` is absent). `best` now carries
`institution_count` and `merge_risk` (institution count `>=
MERGE_RISK_INSTITUTION_COUNT`, set to 15 — comfortably above even a
well-travelled genuine career of a PhD, postdoc, two or three faculty jobs
and an industry stint, comfortably below the 873 a merged entity actually
shows).

**Deliberately does not change which candidate `best` picks, and cannot
produce a new TRIGGERED anywhere.** `f_output` (flag 6) still reads
`scholar.get("works")` exactly as before and still returns PASSED on any
real record — a merged entity still proves *someone* by this name
published, which remains true, weak corroboration. The only change is that
a `merge_risk` record's PASSED evidence text now carries an explicit
caveat naming the institution count and warning it may blend several
careers, so a human reading the report knows not to treat "OpenAlex found a
huge record" as strong personal corroboration. This is intentionally the
narrowest usable slice: real infrastructure (the institution-count signal
now exists in `ctx.signals["openalex"]`) for the reconciliation step every
prior night has deferred, without itself attempting reconciliation, a new
verdict, or a change to which candidate gets picked as `best` (that's a
separate, larger question — see "Where to pick up next" in NIGHTLY.md).

**Verification:** 5 new tests in `tests/test_providers.py` (including an
exact `>=` boundary pin at 14 vs. 15 institutions — this repo's flags.py
mutation sweeps have repeatedly shown that a threshold with no test sitting
exactly on the cut survives a `>=`/`>` mutation silently), 2 in
`tests/test_flags.py` (the caution appears on a merge-risk record, stays
absent on an ordinary one — including a fixture using the OLD signal shape
with no `institution_count`/`merge_risk` keys at all, to pin that every
pre-existing caller of this code keeps working unchanged), and 1 true
end-to-end test in `tests/test_cli_registry_wiring.py` using the real raw
JSON shape (`affiliations` array, not a hand-summarised dict) through the
actual `cmd_text` pipeline — per this repo's standing lesson, a
flags.py-only test cannot prove the real `OpenAlex.search` → `ctx.signals`
→ flag pipeline actually produces this shape. All 6 written first, watched
fail (`KeyError`/plain assertion failures against the unmodified code),
then made to pass. Mutation-tested the new code directly: inverted the
`>=` to `>` (caught by the boundary test), deleted the `merge_risk` gate in
`flags.py` (caught by both the flags.py unit test and the end-to-end test),
and dropped the `affiliations`-array branch in
`_affiliation_institution_count` (caught by two tests) — all three
mutations caught, all reverted, suite green throughout (473 → 480).

Ran the real CLI end-to-end (`larp_meter.cli.main()`, stubbed fetcher, not
just the test harness's direct function calls) on two hand-written samples:
a clean single-institution honest researcher (flag 6 PASSED, plain evidence,
no caution — unchanged from before tonight) and a "Wei Wang"-shaped merged
record (flag 6 PASSED, now with the institution-count caution appended).
Both stayed INSUFFICIENT DATA overall (thin bios, as expected) — confirms
the change doesn't manufacture coverage or move a verdict, only qualifies
an existing PASSED's evidence text.

**Still fully open**: `best` is still chosen by works_count alone even when
`merge_risk` is true — a genuine future reconciliation step would need to
either avoid trusting `best` at all under merge_risk, or use the
per-affiliation `years` array (not yet consumed anywhere) to check temporal
overlap against the subject's own claimed career dates. Neither attempted
tonight; this only makes the merge-risk fact visible.

### Mutation-testing spot-check: `names.py`'s "zero usable candidates" guard confirmed still live on master (nightly/2026-08-27)

Mandatory per-cycle mutation pass. `names.py`'s `name_matches` function has
an `if not usable: return None` guard that was already independently found
and described on the still-unmerged `nightly/2026-08-19` branch (PR
#5), but that branch has never merged, so `master` itself has carried this
gap, unpinned, for over a week. Re-confirmed live rather than trusting the
PR description: reverting the guard on a scratch copy leaves the full
(then-422-test) suite green, and `name_matches("Михаил Иванов", [])` goes
from `None` (unanswerable) to `False` (reported mismatch) — silently, and
**only** for non-Latin-scripted subject names, since a Latin-scripted
subject's equivalent case is already caught earlier by the script-mismatch
guard (an empty candidate blob normalizes to `""`, which reads as
Latin-compatible, so it never reaches this guard for a Latin subject at
all). Left unpinned, a registry that returns zero comparable names would
quietly mismatch every non-Western-scripted subject it was asked about,
while the identical situation for a Western name stayed protected — exactly
the kind of asymmetric fairness gap the task brief's audit lens exists to
catch.

Pinned directly on `master` via tonight's branch (2 new tests in
`tests/test_names.py`, one per script, so a future refactor that merges or
reorders the two guards cannot silently regress either half without a test
noticing), rather than leaving `master` exposed a second time waiting on
PR #5 to merge. `names.py` itself needed zero production changes.

Also mutation-spot-checked `scoring.py` (`coverage >= MIN_COVERAGE` boundary)
and `flags.py` (flag 11's `if refuted or mismatched:`) — both **caught** by
existing pinning tests, confirming the direct-to-master sweeps from
2026-08-16/17 are still holding. And `verify.py`'s `verify_institution`
"empty `wanted`" guard (`if wanted and wanted <= have:`) — **confirmed still
live and unpinned on `master`**, exactly as already described independently
on three separate open, unmerged PRs (#4, #6, #7, #9 — see NIGHTLY.md's
2026-08-27 entry for the open-PR state). Deliberately did **not** re-pin it
a fourth time on yet another branch: that would only add a fifth near-
duplicate test for whoever eventually merges the queue. Recorded here as
confirmation, not as a new finding — the fix is to merge one of the
branches that already has it, not to write it again.

### Mutation-testing sweep: `flags.py` (2026-08-16, same interactive session)

33 hand-authored mutations across all 13 flags plus `evaluate()` — every
guard, boundary, compound condition and status filter. Same harness
discipline as the `scoring.py` sweep below: each mutation applied to a
pristine copy, full suite run, reverted before the next.

**13 of 33 survived the first pass.** Three deliberate controls (the
guards added earlier the same day — flag 11's no-name check, flag 13's
name-anchoring and no-education guards) were all caught, confirming the
harness actually discriminates rather than reporting noise.

The two most serious survivors were both on verdict-changing paths:

- **`if refuted or mismatched:` → `if refuted:` survived** on flag 11 —
  the heaviest flag (weight 2.5, `floor="ORANGE"`). Nothing in the suite
  covered a `MISMATCH` claim reaching flag 11; only `NOT_FOUND` was
  tested. `MISMATCH` is the *classic* fabricator case — the artifact is
  real, it just isn't theirs — so losing it would have silently dropped
  exactly the signal this flag exists to raise, on the tool's strongest
  verdict. This is the same blind spot family as the github/nct and
  `--name` attribution bugs fixed earlier today.
- **`claimed > available + 3` → `claimed > available` survived** on flag
  12. The three-year slack exists because a career can predate the
  earliest date a bio happens to mention; removing it makes the tool
  accuse honest people whose bios simply don't list their first job. Now
  pinned at the exact boundary (20 claimed against 17 available is the
  largest gap the slack still permits) plus one year beyond it.

Three more were fairness-relevant: the current year being treated as a
"future" date (flag 12 — would accuse anyone writing this year's date as
a past fact), the 40-word floor on flag 10 (would condemn a one-line bio
for not citing press), and an OpenAlex entity resolving with **zero
works** counting as verifiable output on flag 6 (the same "existence is
not attribution" error the verify layer is built to avoid).

The rest were unasserted boundaries: buzzword density at exactly 2.0 and
the 4-distinct variety floor, the vague/concrete strict comparison and
its `and`/`or`, the logo-wall 4-partner threshold, flag 8's
`ctx.verified` guard, flag 2's `or` guard, and `evaluate()`'s per-flag
exception guard (which survived only because no flag in the suite ever
raises — now pinned with one that deliberately does).

One fixture needed correcting mid-sweep and is worth recording as a
method note: the first attempt at flag 2's test used a subject with a
title but no prior roles, which returns UNKNOWN via a *second* guard
(`if not roles`) regardless of the mutation — so it passed without
discriminating anything. A test that passes but does not separate the
mutated code from the original proves nothing. The corrected fixture (a
title plus real roles but no claimed domain) was verified to give
UNKNOWN originally and PASSED mutated before being committed.

**Result: 33/33 caught on re-sweep, 0 survivors. 417 tests green.**
`flags.py` itself needed zero production changes — every survivor was
real, intended behaviour with no test asserting it, not a bug in the
current logic.

`verify.py` is now the only one of the four named files without a
dedicated mutation pass.

---

### Mutation-testing sweep: `scoring.py` (2026-08-16, same interactive session)

12 hand-authored mutations across every decision point in `score()`,
`_apply_floors()` and `category_scores()` — status comparisons, the two
division-by-zero guards, the `MIN_COVERAGE` threshold, the `LEVELS` cut
values, the floor eligibility check, the floor tie-break, and the
category-bucket exclusion filter. Each mutation applied to a scratch copy,
full suite run, reverted before the next one — see
`tests/test_scoring.py` for the pinning tests these produced.

**6 of 12 survived the first pass** — the full suite stayed green with the
mutated logic in place, meaning nothing exercised that exact behavior.
Two were the boundaries flagged as suspect going in and turned out to be
real gaps, not false alarms:

- `coverage >= MIN_COVERAGE` (line 28): nothing pinned coverage landing
  **exactly** on 0.35. A `>=` → `>` mutation survived untouched.
- `larp < cut` in the `LEVELS` lookup (line 40): nothing pinned a score
  landing **exactly** on 20, 40, or 65. A `<` → `<=` mutation survived —
  every profile scoring precisely at a cut would have silently
  reclassified into the wrong severity band.

Two more were real but lower-severity — they change what the report SAYS,
not what verdict it reaches:

- `_apply_floors`' `<=` vs `<` tie-break (line 79): at an exact tie
  between the naturally-computed level and the floor, the `level` value is
  identical either way — only whether the summary reads "Held at ORANGE
  by..." or the ordinary weighted-score text differs. That's why it
  survived: every existing test asserts on `level`, and `level` doesn't
  move at a tie.
- `decided_flags` in the INSUFFICIENT DATA message (line 29): drops
  PASSED from its own count without touching `scored`/`level`/`score` at
  all, so "Only 1 of 13 flags could be decided" could say 1 when 3 were
  actually decided, and nothing would notice.

One more, `category_scores`' UNKNOWN-exclusion filter, meant an UNKNOWN
result's weight could dilute a category's decided-weight denominator
without ever having been decided, both understating the category score
and inflating `flags_decided`.

All five are now pinned in `tests/test_scoring.py` (11 new tests). **404
tests green, all mutations now caught on re-sweep.** `scoring.py` itself
needed zero production changes — every survivor was a genuine, real
behavior with no test asserting it, not an actual bug in the current
logic.

**One mutation deliberately left uncovered, on purpose, not an oversight:**
the `TOTAL_WEIGHT` zero-division guard (`coverage = decided_w /
TOTAL_WEIGHT if TOTAL_WEIGHT else 0.0`, line 25). `TOTAL_WEIGHT` is a
module-level constant computed at import time from `REGISTRY`, which is
populated exclusively by the `@flag(...)` decorators in `flags.py` — there
is no code path in this codebase that can make it zero without editing
`flags.py` itself to remove every flag. Testing it would mean monkeypatching
`REGISTRY`/`TOTAL_WEIGHT` to simulate a state the program can never actually
reach. Left as a defensive guard, consistent with the rest of the codebase's
style, not promoted to a pinned behavior.

`flags.py` and most of `verify.py` still have not had a dedicated mutation
pass — this covered `scoring.py` only, per the specific request that
started it.

### Mutation-testing sweep: `names.py` (2026-08-19, nightly run)

The `flags.py` sweep above closes with "`verify.py` is now the only one of
the four named files without a dedicated mutation pass" — but no
`names.py` sweep exists anywhere in this file or in `git log`. What
actually happened on 2026-08-16 was the surname-order and diacritics
fairness *fixes*, each landing with targeted regression tests for the bug
being fixed — real and valuable, but not a systematic sweep of every
comparison in the file. That closing line was wrong; this entry is the
first real one. (`verify.py` did get its dedicated sweep since, in the
still-open `nightly/2026-08-18` PR — see NIGHTLY.md's running tally for
current merge state.)

13 hand-authored mutations across every boundary and guard in `names.py`:
both `len(t) > 1` significant-token filters in `tokens()`, the `not mine`
and `not usable` early-return guards, the `mine_is_latin != blob_is_latin`
script-gate, the mononym `len(mine) == 1` branch, the `len(present) >= 2`
confident-match threshold, the `len(present) == 1` single-token branch,
the `or` between `parts[0] == matched` and `parts[-1] == matched`, the
`matched not in words` continue-guard, the `extra` word length filter, the
`all(...)` consistency check on `extra`, and dropping the
hyphen-collapsed `blob_variants` entry. Same harness discipline as the two
sweeps above: each mutation applied to a scratch copy, full suite run,
reverted before the next.

**5 of 13 survived the first pass.** One turned out to be an equivalent
mutant on inspection (see below); the other four are real gaps, all on
the accusation-risk side the module's own docstring exists to prevent:

- Both `len(t) > 1` filters in `tokens()` (the "no bare initials" guard):
  loosening to `len(t) > 0` lets a bare single-letter given-name initial
  with no period (e.g. the subject typing their own name as "A Zhu") into
  the significant-token set. `tokens("A Zhu")` stops being the length-1
  mononym set `{"zhu"}` and becomes `{"a", "zhu"}`; a full candidate
  record "Zhu Wei" then satisfies only one of two required tokens instead
  of the one-token mononym rule, flipping a correct match into MISMATCH.
  Measured live: `name_matches("A Zhu", ["Zhu Wei"])` goes `True` → `False`.
- The `not mine` guard (subject name absent or reduces to nothing but
  particles/honorifics, e.g. `""` or `"Dr."`): every existing test for
  this guard pairs it with a Latin-script candidate, where a *different*
  guard six lines later (the script-mismatch check) also independently
  returns `None` — masking whether the guard actually under test does
  anything. Deleting it outright passed the full suite. Paired against a
  non-Latin candidate instead (nothing left to coincidentally catch it):
  `name_matches("", ["Михаил Иванов"])` and `name_matches("Dr.", [...])`
  both go `None` → `False` with the guard gone — an empty or
  honorific-only subject name would be reported as *not* matching a real
  registry record, an accusation built from having nothing to compare at
  all.
- The `not usable` guard (registry returned zero candidates), same
  masking problem in reverse: paired with a non-Latin *subject* name
  (equally "not Latin" as an empty blob, so the script-mismatch guard
  doesn't fire either), `name_matches("Михаил Иванов", [])` goes `None` →
  `False` with the guard gone. This one lands disproportionately on
  non-Western names specifically — a Latin-script subject's empty-blob
  case is always masked by the script-mismatch guard first, but a
  non-Latin subject's is not, so the "no candidates ever means MISMATCH,
  never UNCHECKABLE" bug would only ever bite the names this project's
  fairness audits exist to protect.

The fifth survivor, `all(w in mine for w in extra)` → `any(...)` on the
single-token branch's per-candidate consistency check, was investigated
and found to be an **equivalent mutant**: `present` (which gates whether
this branch is even reached with exactly one token) is built by searching
the *same* `blob` that `extra`'s words are drawn from, for every token in
`mine` — so any `extra` word that is also `in mine` would, by
construction, already have been found in `blob` and counted into
`present`, contradicting the `len(present) == 1` precondition for reaching
this branch at all. A 200,000-case random differential fuzzer (comparing
the `all` and `any` variants directly, not through the test suite) found
zero diverging inputs, consistent with that analysis. Not pinned — a test
asserting current behavior here would not be verifying anything a future
change could actually break.

All four real survivors are now pinned in `tests/test_names.py`
(`TestBareInitialIsNotASignificantToken`,
`TestEmptyInputsStayUnanswerableAgainstNonLatinData`), individually
reconfirmed to fail on their mutation and pass on the restored file. **417
→ 421 tests, green.** `names.py` itself needed zero production changes —
every real survivor was already correct, untested behavior, not a bug in
the current logic.

With this sweep, three of the four named files (`scoring.py`, `flags.py`,
`names.py`) have had a dedicated mutation pass on `master`. `verify.py`'s
sweep exists only on the still-open `nightly/2026-08-18` branch — it will
be the fourth once that PR merges.
### Mutation-testing spot-check: all four required files (2026-08-23, nightly run)

Not a full sweep — the primary item tonight was the DEGREE_RE fix above, so
this was the mandatory time-boxed pass (one hand-authored mutation per file,
scratch-copy-run-revert, same harness as the sweeps above), not a repeat of
the exhaustive per-file campaigns. Worth doing anyway: `scoring.py` and
`flags.py`'s sweeps are on `master`; `names.py`'s and `verify.py`'s sweeps
(nightly/2026-08-19 and nightly/2026-08-18) are sitting in still-unmerged
PRs, so from `master`'s own test suite alone, only two of the four files
had ever actually been checked.

- `scoring.py` (`_apply_floors`'s `<=` → `<` tie-break): **caught** —
  `TestFloorTieBreak.test_exact_tie_keeps_the_ordinary_summary_not_the_floor_message`
  failed on the mutation, confirming the 2026-08-16 sweep's pinning test is
  still doing its job on `master`.
- `flags.py` (`if refuted or mismatched:` → `if refuted:` on flag 11):
  **caught** — `TestMutationSurvivorsFlags.test_a_mismatched_identifier_is_a_contradiction`
  failed on the mutation, same confirmation.
- `names.py` (`if len(present) >= 2:` → `>= 3:`): **caught** — 18 failures
  across the name-matching and attribution suites, confirming the
  2026-08-19 sweep's coverage of this exact boundary (that sweep's tests
  are not yet on `master`, but its pinning tests for other boundaries
  already exercise this path incidentally).
- `verify.py` (`if wanted and wanted <= have:` → `if wanted <= have:` in
  `verify_institution`): **SURVIVED on `master`** — the full 419-test suite
  stayed green with the guard dropped. This is the exact mutation the
  nightly/2026-08-18 sweep (PR #4, still unmerged) already found and
  described as "the closest to an actual bug": a claim value that
  decomposes to nothing but stopwords (e.g. "Of The") gives `wanted` an
  empty set, and an empty set is a subset of any ROR hit by definition —
  without the guard, the FIRST institution ROR happens to return for a
  claim naming nothing at all comes back `VERIFIED`, manufacturing a
  confirmed credential from an empty query. Since `master` does not yet
  have PR #4's pinning test for it, added one directly tonight rather than
  leaving it unpinned a second time: `TestRegistries.test_a_claim_of_nothing_but_stopwords_cannot_be_verified`
  in `tests/test_verify.py`, confirmed to fail on the mutation and pass on
  the restored file. (PR #4 will likely carry a near-duplicate of this test
  when it eventually merges — a small, known collision, flagged here so
  whoever merges it isn't surprised.)

**Tally after tonight: all four of `scoring.py`/`names.py`/`flags.py`/`verify.py`
now have at least one real mutation pass with evidence, and — as of
tonight's `verify.py` pinning test — `master` itself (not just an unmerged
PR) carries a regression test for the one survivor found. `names.py`'s and
verify.py's exhaustive sweeps (13 and 6 mutations respectively, full
per-file campaigns) are still only on unmerged branches; see "Open PRs at
the start of this run" at the top of tonight's NIGHTLY.md entry.**

### Flag 13 — Self-Applied Doctoral Title Without a Matching Credential

Built from a strategic discussion (2026-08-16, same-day interactive session,
not a nightly run) about a specific real-world archetype: a subject who
self-presents as "Dr. [Name]" while their own stated education lists nothing
past Master's/CAS level. Design goal was explicitly to generalize past that
one case — see the discussion for the full four-heuristic architecture this
was drawn from (circular entity referencing, academic discipline mismatch,
title inflation, absence-of-identifiers-as-signal). Title inflation was
picked to build first because it needs **zero external registry calls** — it
is pure internal-consistency checking against the subject's own text, which
makes it the safest and cheapest of the four to get right.

**How it works:** finds "Dr."/"Prof."/"Professor" anchored to the subject's
own name tokens (`names.tokens`, so diacritics/particles are already
handled) — critically, NOT anchored to any other name in the text, so a
title attached to a named collaborator or advisor is never misread as the
subject's own. Cross-references the extracted `degree` claims (and a small
supplementary phrase list — see below) for a doctorate. Weight 1.5,
CREDENTIALS category, no `floor` — this is pattern evidence sourced from the
subject's own text, not a registry contradiction, and deliberately cannot
push the verdict past what flag 11's registry-contradiction floor can.

**Deliberately incomplete, documented rather than silently gapped:**
`DEGREE_RE` (extract.py) has no level token for MD, EdD, DBA, DPhil, PsyD or
DSc at all — a real physician's "MD" is invisible to the whole tool today,
not just this flag. The supplementary phrase list here only recognises the
full, unambiguous spelled-out forms ("Doctor of Medicine", "Doctor of
Education", etc.) and deliberately does NOT scan for the bare abbreviations.
Reason: "MD" collides with the Maryland postal abbreviation and similar
short tokens too often to scan a whole free-text profile for safely — a
false negative here (missing a real doctor's degree) is a far smaller harm
than a false positive (accusing an honest physician of title inflation)
would be. A real physician whose bio only ever writes "MD" and never spells
out "Doctor of Medicine" will not be recognised by this flag. Next step, if
picked up: a narrower, name-anchored trailing-credential pattern ("{subject
name}, MD") the same way the leading-honorific detection is anchored, rather
than a whole-text scan for the bare abbreviation.

**Verified against the actual motivating profile**, not just synthetic
fixtures: run against a reconstruction of the real archetype's stated
education (BASc Physiotherapy, MBA Healthcare Management, MSc European
Public Health, Advanced European Bioethics — no doctorate anywhere) with
"Dr." self-applied to the name → correctly `TRIGGERED`. Mutation-tested:
removing the name-anchor check, forcing `has_doctorate` to always be False,
and removing the "no education at all" guard were each tried in isolation —
all three were caught by the test suite (1, 3, and 1 failures respectively;
none survived silently). 9 tests in `tests/test_flags.py::TestTitleInflationFlag`,
including explicit counter-fixtures per the fairness-regression discipline
from the strategy discussion: a real PhD holder passes, a real MD (spelled
out) passes, a title attached to someone OTHER than the subject does not
trigger, a legitimately networked person with several small real titles and
no self-applied "Dr." stays UNKNOWN rather than false-triggering, and no
title claimed at all is UNKNOWN (not PASSED) — matching flag 7's "the flag
does not apply" convention rather than reading absence as a clean bill of
health.

**Not built from this discussion, still open:** circular entity referencing
(needs a company-registry lookup to be safe — see the existing "no company
registry" finding below), academic discipline mismatch for named
collaborators (deliberately the most dangerous of the four — risks libeling
a third party via OpenAlex disambiguation error, see
`openalex-disambiguation-limits` — recommended to ship unscored as a report
caveat, never as a flag, if built at all), and the `INSUFFICIENT DATA`
message strengthening for high-jargon/zero-coverage profiles (cheapest of
all four, purely a caveat-string change, no new false-accusation surface —
recommended as the actual next pick-up if continuing this thread).

**[FIXED — nightly/2026-09-04] Case sensitivity was a free evasion.**
`_DOCTORAL_HONORIFIC_RE` had no `re.I`, so only the exact title-case spelling
"Professor"/"Prof"/"Dr" was ever recognised. An all-lowercase bio ("dr. Anke
Verstraeten...") or an all-caps resume header self-applies the identical
title and read as no title claimed at all — a false negative a fabricator
gets for free from an ordinary stylistic choice, not from trying to game the
flag. Confirmed live: the flag's own motivating fixture, re-cased to
lowercase, went TRIGGERED → UNKNOWN pre-fix. Fixed by adding `re.I`; the
name-adjacency check immediately below the regex (title must sit next to
the subject's own name, on the same line, within a short capped window) is
what actually guards against false accusation here, and is completely
unaffected by letter case, so this can only close the false-negative gap.
Verified end-to-end via the real CLI, not the regex in isolation.

**Mandatory mutation-testing pass, same night:** `names.py` stayed fully
caught. Three real, previously-unpinned survivors in the other three
required files are described in the commit and pinned with regression
tests; none needed a production fix (each guard was already correct, just
untested): `scoring.py`'s `category_scores` PASSED-only-category exclusion,
this flag's own 60-character same-line tail cap, and `verify.py`'s ROR
nearest-name tie-break determinism. See NIGHTLY.md's 2026-09-04 entry for
full detail and the running mutation-testing log.

### `linkedin.py` red-team pass, first dedicated review of the module (2026-08-17, nightly)

Not from the original 63 findings — the standing brief has called this module
out as least-reviewed since it was added, and it had never had a red-team
pass. Two real bugs found and fixed, both reproduced live before touching
anything, both with a failing test written first:

1. **A short description sentence with a comma was misread as a location and
   silently deleted.** `_parse_experiences` treated the first line after a
   date/duration as a location whenever it was short and contained a comma.
   `to_prose()` never renders `exp.location` at all, so a genuine achievement
   like "Led cross-functional team of 12, shipped v2 platform." vanished
   from everything the extractors and flags ever see — not mislabelled,
   *gone*. This is a real-content-loss bug against an honest profile: their
   actual accomplishment claim never reached scoring. Fixed by replacing the
   comma-only heuristic with `_looks_like_location()`, which requires the
   line to have no digits, no closing sentence punctuation, and (when
   matched by comma rather than a remote/hybrid/area keyword) every
   comma-separated part to read as Title-Case place-name words. Verified the
   fix doesn't regress the case it exists to handle (`"Antwerp, Belgium"`,
   `"San Francisco Bay Area"` both still classified as locations).

2. **`Profile.to_prose()` never rendered `profile.name` at all — a
   self-applied "Dr."/"Prof." title in the LinkedIn display name was
   completely invisible to flag 13.** Found while running the required
   end-to-end CLI check after the fix above, not from a code-reading pass:
   a hand-written "Dr. Marcus Vane" LinkedIn-paste fixture with no
   doctorate in the stated education did not trigger flag 13, when the
   equivalent plain-prose text does (per `tests/test_flags.py`'s existing
   `TestTitleInflationFlag`). Root cause: `to_prose()` builds its output from
   `headline`/`about`/`experiences`/`educations`/`skills` and never touches
   `name`. Flag 13 anchors its "Dr."/"Prof." search to the subject's own name
   tokens inside `ctx.text` — if the honorific-bearing name never reaches
   that text, the flag has nothing to find, no matter how blatant the title
   inflation. This is the cheapest possible evasion of flag 13: it costs a
   fabricator nothing but typing "Dr." in front of their own LinkedIn display
   name, which is exactly how a real LinkedIn profile with a self-applied
   title actually looks pasted in. Fixed by rendering `self.name + "."` as
   the first line of `to_prose()` when present. Verified against both
   directions: the fabricated case now reaches flag 13 TRIGGERED end-to-end
   (`extract_claims` → `evaluate`), and a plain name with no title
   (`LINKEDIN_PASTE`'s "Jan Fictief") still produces the same claims as
   before — no new false-positive surface from adding the name line.

6 new tests in `tests/test_linkedin.py` (`TestLocationMisclassification`,
`TestNameSurvivesNormalisation`), each written to fail against the
pre-fix code first. Full suite: 422 tests green (up from 404 at the start
of the night, +18 counting the flags.py mutation-testing pass below).

**Not otherwise covered by this pass:** this was a fix-what-you-find pass
during the required end-to-end CLI check, not an exhaustive line-by-line
red-team of every regex in the module (`_DEGREE_LEVEL_RE`'s English-only
vocabulary, the institution-is-always-line-one assumption, `is_linkedin_paste`
firing on a plain CV that happens to use "Experience"/"Education" as bare
section headers). Worth a dedicated pass if picked up again — see "Where to
pick up next" in NIGHTLY.md.

### Mutation-testing sweep: `flags.py` (2026-08-17, nightly)

Completes the four-file mutation-testing requirement from the standing
brief (`scoring.py` and `flag13`'s own diff were swept 2026-08-16 same-day
interactive; `names.py` and `verify.py`'s `_attribute` seam were swept
2026-08-16 nightly). `flags.py` had never had a dedicated pass.

13 hand-authored mutations across boundary comparisons and guard conditions
in flags 3–13 (flags 1/2 are pure domain-matching logic with no bare
numeric/boolean comparisons to mutate the same way). Each applied to a
scratch copy, full suite run, reverted before the next one.

**12 of 13 survived the first pass** — only the flag-3 (self-referential
partners) `if overlap:` inversion was caught by the existing suite. All 12
survivors are real, previously-unpinned gaps — not false alarms — and are
now pinned as regression tests in `tests/test_flags.py`, re-confirmed
individually as CAUGHT after the tests were added:

- Boundary-only gaps (verdict is correct today but was resting on no test
  pinning the exact cut value — same shape as the `scoring.py` sweep's
  `MIN_COVERAGE`/`LEVELS` findings): flag 4's `density >= 2.0` and
  `len(distinct) >= 4` (buzzword density), flag 4's `word_count < 25`
  short-text carve-out, flag 5's `len(vague) >= 2` and `len(vague) >
  len(concrete)` tie-break, flag 9's `len(distinct) >= 4` (logo wall), flag
  10's `word_count >= 40`, flag 12's `claimed > available + 3` slack and
  `y > ctx.now_year` future-date check.
- Two are real behavioral gaps with actual accusation/evasion consequence,
  not just untested boundaries:
  - **Flag 11's `if refuted or mismatched:` survived as `if refuted:`.**
    This is the tool's only severity-floor flag. A claim that exists but is
    MISMATCHED (registry record exists, lists someone else) with nothing
    separately NOT_FOUND would silently fall through to the generic
    "nothing could be attributed" UNKNOWN branch instead of TRIGGERED,
    dropping the ORANGE floor for exactly the case flag 11 exists to catch.
    No existing test constructed a MISMATCH-only scenario — every test used
    NOT_FOUND. Now pinned.
  - **Flag 6's `hard = [c for c in artifacts if c.subtype != "assertion"]`
    survived with the filter dropped.** `assertion` claims come from
    SOFT_EVIDENCE phrases like "peer-reviewed" that carry no identifier any
    registry could look up. Counting them as "hard" output means a
    fabricator who writes identifier-free output language PASSES the flag
    built to catch exactly that — this is the same evasion shape as this
    file's top CRITICAL finding ("vagueness beats the tool"), just one flag
    deep instead of architecture-wide. Now pinned.
  - **Flag 8's `i.status == ex.NOT_FOUND` survived as `== ex.UNCHECKED`.**
    No test in `tests/test_flags.py` exercised flag 8's TRIGGERED branch
    through `evaluate()` at all — every flag-8 test here only reaches
    PASSED/UNKNOWN. This is the same dead-registry-check shape that
    disabled the ROR institution check for months (see the `[FIXED]`
    entries below): the TRIGGERED branch existed and worked when called
    directly, but nothing proved `evaluate()` could actually reach it with
    a real NOT_FOUND status. Now pinned with a test that goes through
    `evaluate()`, not `verify_institution()` directly.

11 new tests in `tests/test_flags.py`. `flags.py` itself needed zero
production changes — every survivor was a genuine, real behavior with no
test asserting it, not an actual bug in the current logic (same conclusion
as the `scoring.py` sweep). All four files in the standing brief's
mutation-testing requirement (`scoring.py`, `names.py`, `flags.py`,
`verify.py`) have now had at least one dedicated pass.

---

### Mutation-testing sweep: `verify.py` (2026-08-18, nightly run)

`verify.py` was the last of the four files named in the standing brief
(`scoring.py`, `names.py`, `flags.py`, `verify.py`) without a dedicated
broad sweep — `names.py` and `verify.py`'s `_attribute` had only been
spot-checked around specific fixes (the surname-order and unanswerable-name
bugs), never mutated systematically end to end. Six hand-authored mutations
across `_get`'s HTTPError handling, `verify_institution`'s subset-match
guard, `_is_ambiguous_acronym`'s boundary, `_significant_tokens`' length
filter, and `verify_arxiv`'s error-page detection. Each applied to a
scratch copy, full 417-test suite run, reverted before the next.

**All six survived the first pass** — production code needed zero changes;
every survivor was a genuine untested behavior, not an actual bug in the
current logic:

- Dropping HTTP 410 ("Gone") from the `(404, 410)` not-found tuple in `_get`
  survived: only 404 had a real-dispatch test (`test_a_404_is_an_answer...`
  in `test_mutation_guards.py`); 410 would have silently become a network
  failure — an unreachable-registry claim in place of the real "removed
  record" answer the registry gave.
- `verify_institution`'s `if wanted and wanted <= have:` — dropping the
  `wanted and` half survived, and this is the most serious of the six: an
  empty `wanted` set (a claim value that decomposes to nothing but
  stopwords, e.g. a garbled extraction) is a subset of every registry hit
  by definition, so without the guard ANY institution ROR returns would
  satisfy the query and come back VERIFIED. That is exactly the
  "manufacture coverage" failure mode the standing brief warns against,
  just reached through a different door than the ones it names.
- `_is_ambiguous_acronym`'s `<= 5` boundary survived narrowing to `< 5` —
  only a 3-character acronym ("MIT") had ever been tried, so a 5-character
  one silently losing its ambiguity caveat went unnoticed. Cosmetic
  (affects the caveat text, not the VERIFIED status), but a real gap.
- `_significant_tokens`' `len(t) > 1` filter survived being dropped —
  single-letter fragments from ampersands/initials ("A & M" -> "a", "m")
  would count as significant, adding noise to the token-overlap match and
  to the "nearest listed name" hint.
- `verify_arxiv`'s error-page detection, `"api/errors" in entry_id or
  title.casefold() == "error"`, survived `or` -> `and`. The existing
  regression test (`test_arxiv_error_feed_is_not_a_mismatch`) always
  supplies both tells at once, so it can't see that they've stopped being
  independent. This is the one with real teeth if it ever regressed live:
  under the mutation, a title-only error page fell all the way through to
  `_attribute` and came back **MISMATCH** against the stubbed author name —
  a false contradiction on the tool's strongest verdict, from what was
  purely a mismatch between the two signals arXiv happens to send today.

All six now pinned in `tests/test_mutation_guards.py` (`TestInstitutionMatchGuards`,
`TestArxivErrorSignalsAreIndependent`, plus one addition to the existing
`TestRegistryAnswerVsSilence`), individually re-confirmed CAUGHT on re-sweep.
**423 tests green.** `flags.py` and `scoring.py` had already been swept on
prior nights (the entries above, plus a further independent flags.py pass
pushed directly by the repo owner between nights — see NIGHTLY.md's
2026-08-18 entry for the collision this caused with the still-open
nightly/2026-08-17 PR). `names.py` remains the one file of the four with
no *dedicated* broad sweep of its own — only the spot-checks from the
surname-order/unanswerable-name fix. Worth doing properly next time this
lens comes up.

---

### `linkedin.py`: self-applied title in the name field was invisible to flag 13, and an achievement sentence could be silently swallowed into an unrendered field (2026-08-24, nightly run)

First re-verification of `linkedin.py` since the 2026-08-17 red-team pass —
that pass (PR #3, `nightly/2026-08-17`) found and fixed both of these bugs,
but the PR was never merged and `master` never received the fix. Confirmed
both were still live on `master` (commit `7699b72`) before touching
anything, then re-implemented and re-verified independently rather than
cherry-picking the unmerged branch, per the standing "don't push more
commits to a stale open PR" instruction.

**1. `Profile.to_prose()` never rendered `profile.name`.** Flag 13 (Self-
Applied Doctoral Title) scans `ctx.text` for a "Dr."/"Prof." honorific
anchored next to the subject's own name tokens — but the LinkedIn normaliser
never put the name into the text it hands the rest of the pipeline at all.
A fabricator who types "Dr. Marcus Vane" into their own LinkedIn display
name field — the cheapest possible evasion, no crafting of prose required —
was completely invisible to flag 13 whether reached via `--text` auto-
detection or `--from-json`. Confirmed live: a hand-written paste with "Dr.
Marcus Vane" as the name, MSc-only education, came back flag 13 `UNKNOWN`
("no title self-applied... nothing to check") before the fix. Fixed by
rendering `self.name` as the first line of `to_prose()`; re-ran the same
sample after the fix and flag 13 correctly `TRIGGERED`
("Self-applies 'Dr. Marcus Vane', but the entire stated education (MSc
Biology) contains no doctorate").

**2. A short achievement sentence with a comma, appearing on its own line
right after the date/duration line, was misread as the location** (the
existing heuristic was just "under 60 chars and contains a comma, or
mentions remote/hybrid/area"). Since `to_prose()` never renders
`exp.location` at all — it exists only for `--from-json` round-tripping —
this wasn't a mislabel, it was silent content loss: "Led cross-functional
team of 12, shipped v2 platform." vanished from everything the extractors
and flags ever see, no crafting required, just an ordinary post-date
achievement line. Fixed with a tighter `_looks_like_location()`: reject
anything with a digit, anything ending in sentence punctuation, and any
comma-separated part that doesn't start with a capital letter — a real
achievement sentence fails at least one of those, a real location
("Antwerp, Belgium", "Greater London Area", "Remote") passes all of them.

Both fixes mutation-tested (reverted each in isolation, confirmed the
suite's own new tests catch it, restored): reverting the name-rendering
line fails 2 tests, reverting the location tightening fails 1. Verified
through the real `--text`/`--from-json` CLI entry points (`report["flags"]`),
not `flags.py`/`linkedin.py` in isolation, since a component correct in
isolation but never reached by production is this repo's most repeated bug
shape (ROR/HANDLERS, then `_attribute`'s `None` handling). 5 new tests in
`tests/test_linkedin.py`. 417 → 422 tests, green throughout.

**Left untouched:** the rest of `linkedin.py` (experience/education parsing,
section-header ambiguity handling) got no changes — this was a targeted
re-verification of two specific, previously-identified findings, not a
fresh red-team pass.

### Mandatory mutation-testing spot-check, four required files (2026-08-24, nightly run)

Not the primary item tonight (the `linkedin.py` fixes above were), but the
standing brief requires a time-boxed mutation pass every cycle regardless.
One hand-authored mutation each in `scoring.py`, `verify.py`, `names.py`,
`flags.py` — scratch-edit, run the full suite, revert — specifically
targeting the boundaries/guards the still-unmerged `nightly/2026-08-18`
(PR #4, `verify.py`) and `nightly/2026-08-19` (PR #5, `names.py`) branches
already found and described, to check whether `master` itself is still
exposed while those PRs sit open.

- **`scoring.py`** (`MIN_COVERAGE` boundary, `>=` → `>`): **caught**. Already
  pinned by the 2026-08-16 sweep on `master`.
- **`flags.py`** (flag 12's `+3` timeline slack, `> available + 3` →
  `> available`): **caught**. Already pinned by the 2026-08-16 sweep on
  `master`.
- **`verify.py`** (`verify_institution`'s `if wanted and wanted <= have`
  guard, dropping the `wanted and`): **survived on `master`** — confirmed
  exactly the gap PR #4 and PR #6 both independently found and described,
  still real because neither PR is merged. An empty `wanted` set (a claim
  that decomposes to nothing but stopwords) is a subset of any non-empty
  ROR name by definition, so without the guard the first hit "verifies" a
  claim that named nothing. Pinned directly on this branch — see
  `tests/test_verify.py::TestRegistries::test_stopword_only_claim_is_not_verified_by_the_first_hit`
  — rather than leaving `master` unpinned a second time (PR #6 already set
  this precedent once).
- **`names.py`** (`name_matches`'s "zero usable candidates" guard, removing
  `if not usable: return None`): **survived on `master`** — same shape,
  confirmed exactly the gap PR #5 found. Masked for Latin-script subjects by
  the independent script-mismatch guard, so it only shows up for a
  non-Latin, single-token subject name against an empty or blank-only
  candidate list — where it silently returns a confident `False` (mismatch)
  from zero registry evidence instead of `None` (unanswerable). Pinned:
  `tests/test_names.py::TestNoCandidatesIsUnanswerable`.

Both survivors reconfirmed CAUGHT after their pinning tests were added, then
the mutation reverted and the full suite re-run green. `scoring.py` and
`flags.py` need no changes tonight — the still-open item is `verify.py` and
`names.py` getting a **full** dedicated sweep (not just this one guard each)
merged to `master`; PRs #4 and #5 already did that work, they just haven't
landed. See "Open PRs" below.

---

## CRITICAL (16)

### Verification is a one-way, claim-anchored funnel: the tool can only check identifiers the subject volunteered, never what the subject's actual public record says

The verification layer's only question is "does this string the subject gave us resolve, and does the resolved record name them?" Data flows in exactly one direction: text -> regex -> identifier -> registry -> status enum. There is no reverse path (subject -> registry -> record -> compare against claims), so the set of verifiable things is bounded by the tool's design, not by the world.

The entry point makes this literal. `verify_all` at verify.py:423 is `checkable = [c for c in claims if c.subtype in self.HANDLERS]`, and HANDLERS (verify.py:415-419) covers exactly seven identifier subtypes. Everything else extract.py produces is structurally unverifiable: `degree` (extract.py:188), `leadership` (201), `owned_org` (205), `partner_org` (208), the traction subtypes (214), `claimed_experience_years` (218), `year` (226). These are not an oversight — no registry answers "does the string 'PhD Quantum Information' exist"; they answer "what does the record say about this person." The pipeline has no way to ask that question, so the entire credentials / employment / traction surface — i.e. the substance of a professional profile — is permanently outside the verifiable set.

The subsystem that DOES ask the subject-anchored question is architecturally walled off. providers.py:174-243 queries OpenAlex and Crossref BY AUTHOR NAME and already solves the hard parts honestly (`name_matches` gating at providers.py:193 and 236, `ambiguous_identity` when several researchers share the name at providers.py:212, `about_subject` corpus gating at providers.py:65). But it is invoked only from cli.py:97 (`cmd_web`) and cli.py:235 (`cmd_batch`), its output lands in `ctx.signals` as opaque dicts (audit.py:38, flags.py:43), and it never produces or touches a `Claim`. So run_audit never compares the claimed record to the found record — it feeds them to different flags. Flag 6 reads `ctx.signals['openalex']` (flags.py:242) and flag 11 reads `c.status` (flags.py:412), and neither can see the other. A subject claiming "published extensively" whose OpenAlex record shows 2 works produces PASSED on flag 6 (flags.py:244-249) — the provider data is used only as corroboration, never as contradiction.

Self-rebuttal, and why it does not hold. (a) "Subject-anchored lookup is out of scope — the design forbids treating absence as evidence (verify.py:4-7)." But the unlock is not "no record found -> guilty"; it is "record found and it contradicts the claim" — precisely the MISMATCH logic `_attribute` already implements at verify.py:164-189, the tool's strongest and best-defended verdict. And the namesake-ambiguity machinery that makes reverse lookup safe already exists in providers.py; it is merely on the wrong side of the wall. (b) "The real problem is scoring: VERIFIED conflates a first-authored DOI with an empty repo." That is real (see separate finding) but strictly downstream — it mis-ranks claims that got verified, whereas this bounds which claims can be verified at all, and for a typical LinkedIn paste or CV that set is empty. (c) "It's just a missing handler or two." No: adding handlers cannot help, because the claim-anchored direction has nothing to send them.

**Evidence:** verify.py:421-432 `verify_all` — `checkable = [c for c in claims if c.subtype in self.HANDLERS]`; HANDLERS at verify.py:415-419 = {doi, orcid, github, arxiv, nct, patent, institution}.
audit.py:26-30 — the Verifier is constructed and `verify_all(claims)` is called once, before `evaluate(ctx)`; no flag can request a lookup and no verification result re-enters extraction.
audit.py:32-40 — `AuditContext` receives `claims` (verified) and `signals` (provider output) as two unrelated fields.
providers.py:179-213 (OpenAlex by author name) and providers.py:221-243 (Crossref by author name) — subject-anchored lookups that return `Finding`/dict, never `Claim`.
cli.py:97 and cli.py:235 — `gather(...)` called only in web/batch modes; cmd_text (cli.py:77), cmd_url (cli.py:125) and cmd_from_json (cli.py:181) never touch providers.
Measured: extracting the 8-claim bio "PhD in Quantum Information from MIT / MSc Physics from ETH Zurich / CTO of Vane Quantum Systems / 15 years / 40 enterprise customers / holds several patents" yields subtypes {assertion, degree, degree_institution, mentioned_institution, leadership, owned_org} and `[c for c in claims if c.subtype in v.HANDLERS]` == `[]`.

**Fails on:** A fluent LARPer who names no identifiers is invisible to the entire verification layer. Bio: "Dr. Marcus Vane, quantum computing researcher and CTO of Vane Quantum Systems. PhD in Quantum Information from MIT, MSc Physics from ETH Zurich. Over 15 years he has published extensively in peer-reviewed venues... 40 enterprise customers and 12M in ARR... previously Head of Research at CERN... holds several patents." Run with `--verify --name "Marcus Vane"`: 8 claims extracted, 0 routed to verify_all, `verifier_stats` = {api_calls: 0, network_failures: 0}, flag 11 returns UNKNOWN ("No claim carries an identifier that a registry could confirm or refute"). Every one of those assertions is checkable in the real world — MIT and ETH have alumni verification, CERN publishes staff, OpenAlex would show the publication count, ORCID/Crossref would show the patent and paper record — and the architecture cannot ask any of it. The tool is hardest to defeat against honest people who cite DOIs and easiest to defeat by citing nothing.

**Fix direction:** Make the subject, not the claim, a first-class verification input. Give Verifier a subject-anchored pass that runs alongside verify_all: resolve the subject to registry identities (ORCID search, OpenAlex author, ROR-affiliation) and emit *derived* Claims from what the record contains, then reconcile claimed-vs-found as a first-class comparison rather than as two disconnected flag inputs. Concretely: (1) merge providers.py into the claim layer so OpenAlex/Crossref hits become Claims with provenance, not `signals` dicts; (2) run the provider chain in every mode when `--name` is present, not only in web/batch; (3) add a reconciliation step between verify_all and evaluate that can produce a CONTRADICTED status for a *quantitative* claim ("published extensively" vs 2 works; "15 years" vs a record starting 2022) — the same asymmetric standard `_attribute` already uses, where only a positive contradicting record counts and absence stays UNCHECKABLE.

**[IN PROGRESS — nightly/2026-08-15]** Confirmed live: `cmd_text`, `cmd_url`, `cmd_from_json` and the batch-text branch of `cmd_batch` never called `providers.gather`, exactly as measured here — item (2) of the fix direction. Closed *that specific* gap: those four entry points now run a subject-anchored OpenAlex + Wikipedia lookup under `--verify --name`, reusing providers.py's existing `name_matches`/`about_subject`/`ambiguous_identity` gating unchanged (see `cli._subject_registry_signals`, `tests/test_cli_registry_wiring.py`). This gets a truthful "published extensively" claim corroborated, and a fabricated one still reported UNKNOWN when no record exists — it does **not** yet produce a CONTRADICTED verdict for a *quantitative* mismatch (items 1 and 3 of the fix direction: OpenAlex/Crossref hits still land as `signals` dicts, not derived `Claim`s, and there is still no reconciliation step). That remains the highest-value work open in this file. Building it safely needs the OpenAlex disambiguation groundwork described in NIGHTLY.md (merged author entities, common-name collision) before any negative or contradicting verdict can be trusted.

**[IN PROGRESS — nightly/2026-08-27]** Made the specific "0 works found for a researcher claiming 40 papers" scenario visible in the report for the first time, exactly as this entry's own fix direction names as the safe first step. Flag 6 now distinguishes "OpenAlex was never queried" from "OpenAlex was queried and found no scholarly record" (previously both read as the same falsy `.get()` result) and appends a hedged, UNKNOWN-only sentence naming the negative result when the subject's only output claim is a soft, identifier-free assertion. See "Flag 6: a genuine negative OpenAlex search becomes visible in the report" above for full detail. Deliberately still does **not** touch items (1) and (3) of the fix direction below — no derived `Claim`s, no reconciliation, no verdict above UNKNOWN from this alone. The disambiguation groundwork this entry's own note calls out (merged author entities, common-name collision, transliteration under-matching) is the reason the note is worded as a lead rather than a finding, and is still the blocking prerequisite for anything stronger than UNKNOWN.

**[IN PROGRESS — nightly/2026-08-30]** First actual piece of the disambiguation groundwork itself (as opposed to another visibility-only slice of the flag 6 UNKNOWN path): `providers.OpenAlex.search`'s `best` pick now carries `institution_count`/`merge_risk`, computed from the full `affiliations` array, so a merged-entity record (re-confirmed live today: the brief's "Wei Wang" example now shows 873 affiliations, up from 863) is at least *visible* as such in flag 6's PASSED evidence text, instead of being silently trusted at face value the way plurality-by-works-count did before. `best` itself is still chosen by works_count alone even when `merge_risk` is true — this does not yet make the pipeline avoid or discount a merged record, only label it. See "Affiliation-count merge-risk caveat on the OpenAlex 'best' pick" above for full detail, including a live finding not in the brief: `/authors?search=` is now hitting OpenAlex's own $0-remaining-today USD rate limit in this environment, while the free singleton/autocomplete endpoints are unaffected — worth designing around for whoever builds the next slice. Items (1) and (3) of the fix direction are still fully open: no derived `Claim`s, no reconciliation step, no verdict above UNKNOWN/PASSED from any of this.

---

### [FIXED] Institution verification has been silently dead in the real pipeline since commit 6488c6d — HANDLERS keys on a subtype extraction no longer emits

`Verifier.HANDLERS` maps `"institution" -> verify_institution` (verify.py:418), but extract.py has not emitted the subtype `"institution"` since commit 6488c6d ("Fix false-accusation paths found by adversarial review"), which split it into `"degree_institution"` (extract.py:191) and `"mentioned_institution"` (extract.py:199). Nothing updated HANDLERS. `verify_all` silently skips unrecognised subtypes (verify.py:423) with no diagnostic and no accounting anywhere in the report, so ~55 lines of the most carefully-reasoned code in the file — the ROR integration, the fuzzy-match disqualification guard at verify.py:348-367, the acronym-ambiguity handling at verify.py:357-360 — are unreachable from `run_audit`.

The consequence propagates into scoring. Flag 8 `f_credentials` reads `fake = [i for i in institutions if i.status == ex.NOT_FOUND]` over `degree_institution` claims (flags.py:295, 315), whose status is permanently `UNCHECKED`. So flag 8 can never TRIGGER, even under `--verify`. It falls through to flags.py:327 and returns PASSED — "Degree tied to a named institution (X)" — crediting the profile 1.0 of weight for naming any string that matches the institution regex.

This is the seam failure that makes the primary architectural finding concrete: `subtype` is an unconstrained `str` on the Claim dataclass (extract.py:26), HANDLERS is a plain str->str dict, and no shared enum, validation, or contract binds producer to consumer. The test suite cannot catch it because every test that touches Verifier hand-builds `Claim(subtype="institution")` — test_verify.py:114, 126, 138, 150, 160, 171, 188 and test_regressions.py:108, 116 — and no test in the repo ever feeds `extract_claims(text)` output into `verify_all`.

**Evidence:** verify.py:415-419 HANDLERS includes `"institution": "verify_institution"`.
extract.py:191 `add("degree", "degree_institution", institution, _context(text, m))` and extract.py:199 `add("degree", "mentioned_institution", name, _context(text, m))`. Repo-wide grep for the literal subtype `"institution"` outside tests returns only verify.py:418.
git show 6488c6d -- larp_meter/extract.py: `-  add("degree", "institution", institution.strip(), ...)` / `+  add("degree", "degree_institution", institution, ...)`.
flags.py:315 `fake = [i for i in institutions if i.status == ex.NOT_FOUND] if ctx.verified else []` — over claims that are always UNCHECKED.
Documentation still advertises the dead path: README.md:31 ("| Institution | ROR | Is this a real organization? |"), README.md:111 (flag 8 = "Degree with no institution, or one absent from ROR"), cli.py:369 (`--explain` prints "Institution  -> ROR (Research Organization Registry)").

**Fails on:** Verified by running the real pipeline: `run_audit("Marcus Vane", "Dr. Marcus Vane holds a PhD in Quantum Information from the Fictional Institute of Advanced Quantum Studies. He is CTO of Vane Quantum Systems, has 15 years of experience building superconducting hardware, and is currently raising a Series A.", subject_name="Marcus Vane", verify=True)` produces `verifier_stats: {'api_calls': 0, 'network_failures': 0}` — ROR is never contacted despite --verify — all 6 claims stay UNCHECKED, and flag 8 returns **PASSED: "Degree tied to a named institution (the Fictional Institute of Advanced Quantum Studies)."** The tool affirmatively credits a fabricated university as a satisfied credential check, while its own --explain output tells the operator that institutions were checked against ROR.

**Fix direction:** Immediate: route `degree_institution` (and decide explicitly about `mentioned_institution`) to `verify_institution`. Structural, so it cannot recur: define subtypes as a shared constant/enum in extract.py that both the ARTIFACT_PATTERNS/`add()` calls and HANDLERS import; assert at import time that every HANDLERS key is a subtype extraction can actually produce; have `verify_all` record skipped-subtype counts into `verifier_stats` (audit.py:77-79) so a silently-unverified claim class is visible in the report; and add one end-to-end test that runs `extract_claims(text)` into `verify_all` with a stubbed network and asserts which URLs were requested.

---

### [FIXED] ROR is wired into the verifier but no claim ever reaches it — the institution check is dead code

`Verifier.HANDLERS` dispatches on `claim.subtype` and registers the key `"institution"`, but `extract_claims` never emits that subtype. It emits `degree_institution` (institution bound to a degree) and `mentioned_institution` (employer/venue). `verify_all` filters with `c.subtype in self.HANDLERS`, so every institution claim is silently skipped and stays `UNCHECKED`. Consequence: the only registry on the credentials side of the tool never runs in production, and flag 8's `NOT_FOUND` branch is unreachable — it tests `i.status == ex.NOT_FOUND` on claims that are always `UNCHECKED`. The 7-source claim in the README and in `--explain` is really 6, and the missing one is the only one covering education. Every ROR test in the suite constructs `Claim(..., subtype="institution", ...)` by hand, so the wiring gap is invisible to CI.

**Evidence:** larp_meter/verify.py:415-419 `HANDLERS = {... "institution": "verify_institution"}`; larp_meter/verify.py:423 `checkable = [c for c in claims if c.subtype in self.HANDLERS]`; larp_meter/extract.py:191 `add("degree", "degree_institution", institution, _context(text, m))`; larp_meter/extract.py:199 `add("degree", "mentioned_institution", name, _context(text, m))`; larp_meter/flags.py:295 `institutions = ex.claims_by(ctx.claims, "degree", "degree_institution")` and larp_meter/flags.py:315 `fake = [i for i in institutions if i.status == ex.NOT_FOUND] if ctx.verified else []`. Tests only build the phantom subtype: tests/test_verify.py:114,126,138,150,160,171,188. Advertised at larp_meter/cli.py:369 `Institution  -> ROR (Research Organization Registry)` and README.md:31. Measured: `extract_claims("PhD in Physics from Delft University of Technology. Founder of Acme.")` yields subtypes `degree, degree_institution, leadership, owned_org` and `checkable == []`.

**Fails on:** "PhD, Applied Cryogenics, from the Zurich Institute of Advanced Photonic Sciences" — an entity that exists in no registry. Run with `--verify --name`: the institution claim is never submitted to ROR, flag 8 returns PASSED ("Degree tied to a named institution"), and the fabricated school contributes positively to the score.

**Fix direction:** Register both real subtypes (`degree_institution`, `mentioned_institution`) in `HANDLERS`, and add an integration test that asserts `Verifier.HANDLERS.keys()` is a subset of the subtypes `extract_claims` can actually produce, so a rename can never orphan a registry again. `mentioned_institution` should route to a different verifier than `degree_institution` (employer vs. school are different questions and want different sources — see the company-registry finding).

---

### [FIXED] GitHub and ClinicalTrials.gov are checked for existence only — they never attribute, so citing someone else's work lowers your larp score

`_attribute` is the function that turns existence into attribution, and it is called by `verify_doi`, `verify_orcid`, `verify_arxiv` and `verify_patent`. It is not called by `verify_github` or `verify_nct`. Both of those set `claim.status = VERIFIED` unconditionally whenever the record exists. The attribution data is already inside the response body they parse and is thrown away: the GitHub repo payload carries `owner`, and `/repos/{o}/{r}/contributors` sits on the same keyless API; the ClinicalTrials.gov v2 payload carries `protocolSection.sponsorCollaboratorsModule` (lead sponsor, responsible party) and `contactsLocationsModule.overallOfficials` (the principal investigators) — `verify_nct` reads only `briefTitle` and `overallStatus` from a body it has already JSON-parsed. This is not a missing data source; it is a discarded one. Because flag 11 counts `VERIFIED` identifiers as PASSED and flag 6 passes on artifact presence, a fabricator is rewarded for name-dropping famous identifiers: 4.0 of the 17.0 total flag weight (~24%) moves in their favour on work they had nothing to do with.

**Evidence:** larp_meter/verify.py:253-267 — the GitHub repo branch sets `claim.status = VERIFIED` and builds a detail string from `stargazers_count`/`pushed_at`/`size` with no `_attribute` call; the user branch likewise ignores the `name` field GitHub returns. larp_meter/verify.py:313-321 — `verify_nct` extracts only `identificationModule` and `statusModule`, then `claim.status = VERIFIED`. Contrast the sources that do attribute: larp_meter/verify.py:209, 233, 300, 407. Scoring path: larp_meter/flags.py:414 `confirmed = [c for c in checkable if c.status == ex.VERIFIED]` → larp_meter/flags.py:426-428 PASSED at weight 2.5 (larp_meter/flags.py:397); larp_meter/flags.py:251-256 PASSED at weight 1.5 (larp_meter/flags.py:234); `TOTAL_WEIGHT` = 17.0 (larp_meter/flags.py:468).

**Fails on:** Measured, with GitHub and CT.gov responses stubbed to their real values: "Rex Falsum, Chief Medical Officer and visionary AI leader. I am principal investigator on NCT01234567 and my team ships code at https://github.com/tensorflow/tensorflow. We are raising a seed round and have 50,000 users. 10 years of experience since 2016." run with `--verify --name "Rex Falsum"` returns **larp_score 0, GREEN, 47% coverage**, with flag 6 PASSED ("2 independently checkable artifact(s) cited"), flag 11 PASSED ("All 2 checked identifier(s) confirmed by their registries"), flag 7 PASSED. Rex has claimed Google's repository and a pharma trial and the tool certifies him.

**Fix direction:** Route both through `_attribute`. For NCT, pass `overallOfficials[].name` + `sponsorCollaboratorsModule.leadSponsor.name` — zero extra network calls, the body is already parsed at verify.py:313. For a GitHub repo, compare the subject against `owner.login`/`owner` metadata and, when the claim is one of ownership, one extra keyless call to `/repos/{o}/{r}/contributors`; also surface `created_at` (a three-week-old account backing a "ten-year open-source track record" is a signal the tool currently cannot see). Where attribution genuinely cannot be established, the existing `UNCHECKABLE` path is the right answer — not `VERIFIED`.

---

### Citing no identifiers disables the entire verification half of the tool, including its only severity floor

Every registry check, and the single mechanism that can force a bad verdict, is gated on the profile containing a DOI, ORCID, GitHub URL, arXiv ID, NCT number, or patent number. A fabricator has none of these by definition, so the gate closes on its own. `f_contradicted` (flag 11) is the highest-weighted flag in the battery (2.5 of 17.0 total) and the ONLY flag carrying `floor="ORANGE"` — the mechanism scoring.py uses to stop a registry contradiction being averaged away. With no identifiers it returns UNKNOWN, which scoring.py excludes from both numerator and denominator, so the floor never arms. `f_output` (flag 6) then degrades from TRIGGERED to UNKNOWN as well. The result is that the half of the tool that touches the real world simply does not run, and its absence costs the subject nothing.

**Evidence:** larp_meter/verify.py:423 `checkable = [c for c in claims if c.subtype in self.HANDLERS]` — the only entry point into every registry.
larp_meter/flags.py:404-407 `checkable = [c for c in ctx.claims if c.subtype in ("doi", "orcid", "github", "arxiv", "nct", "patent")]` / `if not checkable: return FlagResult(UNKNOWN, "No claim carries an identifier that a registry could confirm or refute.")`
larp_meter/flags.py:397-399 flag 11 is the sole `floor="ORANGE"` registration.
larp_meter/scoring.py:73-75 `floored = [FLAG_BY_ID[i] for i, r in results.items() if r.status == TRIGGERED and FLAG_BY_ID[i].get("floor")]` / `if not floored: return level, summary`.
larp_meter/scoring.py:22-26 UNKNOWN flags enter neither `trig_w` nor `pass_w`.

**Fails on:** I ran a wholly invented bio through `run_audit` — fake PhD from a nonexistent "Institute of Advanced Photonic Systems", fake MSc from "Universidad Tecnica de Valdoria", fabricated 15-year semiconductor/quantum career, fabricated Nature/Forbes/IEEE Spectrum coverage, fabricated 12,000 customers and Thales/Airbus contracts. Result: **GREEN, larp_score 0/100, coverage 56%**, summary "Claims and verifiable substance broadly align." Flags 6 and 11 both UNKNOWN. The identical text with two cosmetic differences (the phrase "working on" instead of "delivered", and no career start year) scored YELLOW 27 — meaning the tool's entire response to this fabrication was driven by verb choice, not by any fact.

**Fix direction:** A profile that makes strong output/research claims while carrying zero checkable identifiers should be a TRIGGERED state on flag 6/11, not UNKNOWN — the absence of any identifier alongside heavy claims is itself the signal. Alternatively, attach the ORANGE floor to a flag that can fire without registry input, so the floor is not co-extensive with the identifier gate.

---

### [FIXED] Institution claims are never verified — verify_all's dispatch key does not exist in the extractor's output

`Verifier.HANDLERS` maps subtype `"institution"` to `verify_institution`, but `extract_claims` never emits that subtype. It emits `"degree_institution"` and `"mentioned_institution"`. Because `verify_all` filters on `c.subtype in self.HANDLERS`, institution claims are never dispatched and retain status `UNCHECKED` forever, even under `--verify`. `f_credentials` (flag 8) then tests `i.status == ex.NOT_FOUND`, a condition that is unreachable in production, and falls through to its PASSED branch. So the ROR lookup — 55 lines of carefully written anti-false-positive logic explicitly built to catch "a fabricated name like 'Institute of Advanced Fictional Studies'" — is dead code on the real path, and naming an invented university actively *improves* the score by adding 1.0 of passing weight.

**Evidence:** larp_meter/verify.py:418 `"institution": "verify_institution",` inside HANDLERS.
larp_meter/extract.py:191 `add("degree", "degree_institution", institution, _context(text, m))` and extract.py:199 `add("degree", "mentioned_institution", name, _context(text, m))` — the only two institution subtypes ever produced.
larp_meter/verify.py:423 the dispatch filter.
larp_meter/flags.py:315 `fake = [i for i in institutions if i.status == ex.NOT_FOUND] if ctx.verified else []` — unreachable.
larp_meter/flags.py:327 `return FlagResult(PASSED, f"Degree tied to a named institution ({institutions[0].value}).", ...)`.
Run confirming it: extract_claims on "PhD in Astrophysics from the Institute of Advanced Quantum Studies" yields subtypes `['degree', 'degree_institution', 'mentioned_institution']`; `[c for c in cs if c.subtype in Verifier.HANDLERS]` == `[]`.
The tests mask this: tests/test_verify.py:114, :126, :150 and tests/test_regressions.py:108, :116 all hand-construct `Claim(kind="degree", subtype="institution", ...)` — the phantom subtype — and call `v.verify_institution(claim)` directly. Even tests/test_verify.py:186-192 `test_verify_all_only_touches_checkable_subtypes` builds `subtype="institution"`, so the one test covering the dispatch validates a path production never produces.

**Fails on:** "PhD in Astrophysics from the Institute of Advanced Photonic Systems" — an institution that does not exist — returns flag 8 PASSED: "Degree tied to a named institution (the Institute of Advanced Photonic Systems)." Under `--verify` the outcome is byte-identical to a real Delft or ETH degree. A diploma mill, an invented university, or a plausible-sounding "Institute of X" is completely free, and pays a +1.0 weight bonus into the pass column.

**Fix direction:** Either emit subtype `"institution"` from the extractor, or key HANDLERS on `"degree_institution"` (and decide deliberately whether `mentioned_institution` should also be checked). Add one end-to-end test that runs extract_claims -> verify_all -> f_credentials on a fabricated institution and asserts TRIGGERED, so the dispatch contract is covered rather than the handler in isolation.

---

### [FIXED] ROR institution verification is unreachable: HANDLERS keys on a subtype extract.py never emits

`Verifier.HANDLERS` (verify.py:415-419) maps `"institution" -> verify_institution`, but production code never creates a claim with subtype `"institution"`. `Claim(...)` is constructed in exactly one place in the whole package — extract.py:168 — and the institution branches emit `"degree_institution"` (extract.py:191) and `"mentioned_institution"` (extract.py:199). The dispatch filter `checkable = [c for c in claims if c.subtype in self.HANDLERS]` (verify.py:423) therefore drops every institution claim, so `verify_institution` — 55 lines of careful ROR fuzzy-match defence, verify.py:324-378 — is dead code in the pipeline. The knock-on is that flags.py:315 `fake = [i for i in institutions if i.status == ex.NOT_FOUND] if ctx.verified else []` can never be non-empty, because `institutions` (flags.py:295) are `degree_institution` claims that `verify_all` skipped and which stay `UNCHECKED` forever. Flag 8 ("Unverifiable Credentials") is structurally incapable of ever returning TRIGGERED in production; it can only PASS or return UNKNOWN. The test suite cannot catch this because every ROR test (tests/test_verify.py:112-174, six tests) hand-builds `Claim(kind="degree", subtype="institution", ...)` and calls `v.verify_institution(claim)` directly, bypassing `verify_all`; no test anywhere calls `run_audit(..., verify=True)`.

**Evidence:** verify.py:415-419 `HANDLERS = {... "institution": "verify_institution"}`; verify.py:423 `checkable = [c for c in claims if c.subtype in self.HANDLERS]`; extract.py:168 is the sole `Claim(...)` construction in larp_meter/; extract.py:191 `add("degree", "degree_institution", ...)`; extract.py:199 `add("degree", "mentioned_institution", ...)`; flags.py:315. Run against the real pipeline: `HANDLERS keys: ['arxiv','doi','github','institution','nct','orcid','patent']` vs `subtypes emitted: ['assertion','claimed_experience_years','degree','degree_institution','installations','mentioned_institution','year','year_target']`, `intersection: []`. Direct call with a stubbed ROR body returns NOT_FOUND; the identical value routed through `verify_all` with subtype `degree_institution` returns `UNCHECKED` with empty detail.

**Fails on:** Profile text: "PhD in Applied Cryptography from the Institute of Advanced Fictional Studies. I have 10 years of experience building secure systems since 2015." Run with `--verify --name "..."`. The invented school is extracted as `degree_institution`, never submitted to ROR, and flag 8 returns **PASSED — "Degree tied to a named institution (the Institute of Advanced Fictional Studies)"**. tests/test_verify.py:142-154 asserts this exact string returns NOT_FOUND — but only when the verifier is called directly. The one thing the ROR verifier was written to catch is the one thing it never sees.

**Fix direction:** Key `HANDLERS` on the subtypes `extract.py` actually emits (`degree_institution`, and optionally `mentioned_institution` at a lower confidence), or normalise institution claims to a canonical `institution` subtype before `verify_all`. Add an end-to-end test that asserts `run_audit(text_with_fake_school, verify=True)` produces a non-UNCHECKED status on the institution claim and TRIGGERS flag 8 — the current tests assert the verifier's logic but never its reachability.

---

### Zero registry reach on a realistic prose profile: 0 of 13 extracted claims are submitted to any registry

All verification is gated on six literal-identifier regexes in `ARTIFACT_PATTERNS` (extract.py:38-45): a raw DOI string, an `arxiv.org/abs/` URL, a bare ORCID, a `github.com/` URL, an `NCT` number, or a `US|EP|WO` patent number. Nothing else in the pipeline can reach a registry. A mid-career engineer's bio written the way real people write — naming journals, employers, patents and clearances in prose without pasting identifiers — yields claims whose subtypes have no handler, so `verify_all` (verify.py:421-432) iterates an empty list. Consequently flag 11 "Contradicted Verifiable Claim" (flags.py:397-411) is permanently UNKNOWN, and flag 11 is both the heaviest flag (weight 2.5 of TOTAL_WEIGHT 17.0, flags.py:468) and the *only* flag carrying a severity floor (`floor="ORANGE"`, flags.py:399; the floor machinery lives at scoring.py:63-85). The entire external-authority layer can move at most 3.5/17.0 = 20.6% of the score, and since flag 8's registry branch is dead (see finding 1), effectively only 2.5/17.0 = 14.7% — and only when the subject volunteers a machine-readable identifier about themselves. The verdict that ships is produced 100% by prose heuristics reading the subject's own self-description.

**Evidence:** extract.py:38-45 `ARTIFACT_PATTERNS`; verify.py:423; flags.py:404-405 `checkable = [c for c in ctx.claims if c.subtype in ("doi","orcid","github","arxiv","nct","patent")]`; flags.py:397-399 flag 11 weight 2.5 `floor="ORANGE"`; flags.py:468 `TOTAL_WEIGHT = sum(...)` = 17.0. Measured on the trace profile with `verify=True`: `registry HTTP calls attempted: 0`, `verifier_stats: {'api_calls': 0, 'network_failures': 0}`, `claim_status_counts: {'UNCHECKED': 13}`, `claims with a registry handler: 0`.

**Fails on:** A truthful Philips MRI engineer's bio (MSc TU Delft, BSc Antwerp, 12 years, IEEE TMI/TBME co-authorship, two granted patents, FDA clearance 2019, ASML, Karolinska collaboration, 400 installations) contains ~14 assertions a human would call checkable. The tool extracts 13 claim objects and submits **0** of them to any registry, even with `--verify`. It then prints `YELLOW · LARP score 33/100 · evidence coverage 44% · verified`, with the 33 coming entirely from flag 6 ("cites no checkable artifact") and flag 10 ("zero third-party validation") — i.e. it penalises the subject for not pasting identifiers into their bio, having made no attempt to look for them.

**Fix direction:** Add name-and-affiliation registry queries that do not require the subject to volunteer an identifier: Crossref/OpenAlex author search, ORCID name+affiliation search, EPO/Google Patents inventor search, ClinicalTrials.gov investigator search, FDA 510(k) applicant search. These already partly exist as *providers* for web mode; wire them as verifiers keyed on `degree_institution`, employer names and `subject_name`, so a prose claim ("co-author in IEEE TMI") becomes a lookup rather than an unchecked string.

**[IN PROGRESS — nightly/2026-08-15]** See the note on the duplicate of this finding above (line ~35). `--verify --name` on exactly this kind of prose bio now fires at least one real HTTP query (OpenAlex + Wikipedia by name) from every text-based mode, and the Philips-engineer example would now show a PASSED flag 6 if OpenAlex actually has their record. Still open: no per-claim reconciliation, so an *individual* unverifiable assertion ("co-author in IEEE TMI", "FDA clearance 2019") stays exactly as unchecked as before — only the coarse "does this person have some independent scholarly record at all" question got answered. ORCID name+affiliation search, EPO/Google Patents inventor search, ClinicalTrials.gov investigator search and FDA 510(k) search are all still unbuilt.

---

### [FIXED] `--verify` suppresses the 'nothing was checked' warning while performing zero checks

**Verified and fixed 2026-08-26.** Confirmed live before touching anything: `--verify` on a
zero-identifier fabrication (the `NO_IDENTIFIERS` text in `tests/test_report.py`) produced
`verified` in the header badge and dropped the "own account" disclaimer, exactly as this entry
describes — 0 API calls, `verified: true`. Fixed by adding a second field, `verification_effective`
(`audit.py`): true only when `verify_all` actually changed at least one claim's status away from
`UNCHECKED`. This is `True` for a real network *failure* too (a dispatched-but-unreachable claim
still becomes `UNCHECKABLE`, not `UNCHECKED` — the "network failure is never evidence of deception"
rule still applies), and `False` only in the exact case this finding names: nothing in `HANDLERS` had
anything to dispatch to. `report.py` now derives the header badge (`_verification_label`, a shared
helper across the terminal/Markdown/HTML renderers — three states: `unverified`, `verify attempted,
0 checked`, `verified`) and the "own account" disclaimer's gate from `verification_effective`, not
from the raw flag, and `caveats()` emits an explicit new line when `--verify` ran but checked nothing.
Left as-is on purpose: `verifier_stats` is still JSON-only, not printed inline in the terminal — the
new caveat line covers the specific harm (a misleading "verified" claiming more than happened);
surfacing the full stats block is a smaller, separate follow-up. Regression tests in
`tests/test_report.py` (`TestCaveats`/`TestRenderers`), each confirmed to fail against the pre-fix
code and pass against the fix.

Original finding, kept for context: `run_audit` sets `"verified": bool(verify)` (audit.py:51) from the *flag*, not from whether any lookup succeeded. The renderer then keys three separate honesty affordances off that boolean. report.py:124 prints the header badge `'verified' if report['verified'] else 'unverified'`. report.py:72-77 gates the single most important disclaimer in the tool — "Nothing here was checked against an outside source... A well-written fabrication passes this easily" — on `not report.get("verified")`. And report.py:166 `checked = [cl for cl in report["claims"] if cl["status"] != UNCHECKED]` suppresses the entire "Claim ledger (registry lookups)" block when nothing was checked, so there is no place in the output where a zero appears. `verifier_stats: {"api_calls": 0}` is carried in the JSON (audit.py:77-79) but never surfaced in the terminal, markdown or HTML renderers. Passing `--verify` therefore *strictly reduces* the caveats shown to the reader while changing nothing about the evidence.

**Evidence:** audit.py:51 `"verified": bool(verify)`; report.py:124; report.py:72-77 (`and not report.get("verified")`); report.py:166-168; audit.py:77-79 `verifier_stats`. Measured A/B on the same profile — WITHOUT `--verify`: "Read this before acting: • Nothing here was checked against an outside source... • Only 44% of the flag weight could be decided". WITH `--verify`: only the 44% line remains; header now reads `· verified`; score identical (33/100), zero API calls, no claim ledger printed.

**Fails on:** An analyst runs `larp-meter.py --file bio.txt --name "Jan de Vries" --verify`, sees `🟡 YELLOW LARP score 33/100 · evidence coverage 44% · verified` with no ledger and no "nothing was checked" caveat, and reasonably concludes the score survived registry scrutiny. Zero HTTP requests were made. The user paid for a stronger-looking result by removing the warning that would have told them the truth.

**Fix direction:** Derive the badge and the disclaimer gate from actual work done, not from the flag: set `verified` only when `verifier.calls > 0` and at least one claim left `UNCHECKED`, or introduce a distinct `verification_attempted` vs `verification_effective`. Print `verifier_stats` in the terminal renderer, and emit an explicit line when `--verify` was requested but nothing was checkable ("--verify ran but no claim carried an identifier any registry could resolve; 0 lookups performed").

---

### Verification is identifier-keyed and one-way: the verifiable set is bounded by what the subject volunteered, not by what registries can answer

The verification layer has exactly one shape of question: "here is an identifier the subject wrote down — does it exist, and does it list them?" There is no subject-keyed direction. `Verifier.__init__` takes `subject_name` (verify.py:104-113) but that name is never a query key; it is used only as a post-hoc filter inside `_attribute` (verify.py:167-192) and `_name_matches` (verify.py:163-165). Every handler builds its URL from `claim.value`: Crossref (verify.py:196), ORCID (verify.py:216), GitHub (verify.py:242-243), arXiv (verify.py:274), ClinicalTrials (verify.py:307), ROR (verify.py:337), Google Patents (verify.py:385).

Three consequences compound:

(1) **Reach.** `verify_all` filters to `c.subtype in self.HANDLERS` (verify.py:430). HANDLERS has 7 keys (verify.py:422-426) against 26 emitted subtypes (extract.py:33-38). The other 19 — `leadership`, `owned_org`, `partner_org`, all 9 traction subtypes, `claimed_experience_years`, `year`, `year_target`, `degree`, `mentioned_institution`, `assertion` — are counted into `self.skipped` (verify.py:433) and never checked. The entire RELATIONSHIPS category (flags 3, 5, 9 — 4.0 of 17.0 total weight, flags.py:173/217/342) is decided purely on regex patterns inside the subject's own prose.

(2) **Write-set.** The verifier's only output is a mutation of three fields on an existing claim — `claim.status`, `claim.detail`, `claim.source` (verify.py:180-192). It cannot append a claim, cannot emit an evidence record, and cannot express "I asked a registry about this person and found nothing." Structured payload is discarded on read: `verify_doi` keeps title+authors and drops `issued`/affiliation (verify.py:209-212); `verify_github` keeps stars/pushed/archived/size and drops `created_at`/owner (verify.py:257-264). Nothing verification learns can corroborate a *different* claim.

(3) **The severed channel.** A subject-keyed path already exists — but it is wired around the verifier, not into it. providers.py queries by name: OpenAlex `authors?search=` (providers.py:180), Crossref `works?query.author=` (providers.py:222), Wikipedia (providers.py:149). Its results are flattened by `Finding.as_text()` (providers.py:46) into `Gathered.corpus` (providers.py:65), passed to `run_audit` as `text` (cli.py:107), and re-parsed by `ex.extract_claims` (audit.py:23) — so third-party evidence *about* the subject re-enters the pipeline as *claims by* the subject, and is then measured for buzzword density as if the subject wrote it (flags.py:192-213 reads `ctx.text`). The structured `signals` dict survives but only three flags read it (flags.py:242, 373, 386). `--url` mode collects an exact identity anchor and sets `signals["profile_facts"]` (cli.py:169) — grep shows no consumer anywhere; it is dead on arrival.

The asymmetry is the tell: name-keyed matching is already trusted enough to *exonerate* (flags.py:245 `if scholar and scholar.get("works")` → PASSED; providers.py:193), but there is no structural place to put the same evidence when it points the other way. `f_output` never compares the OpenAlex works count to the magnitude claimed, so a single work by a namesake PASSES "No Verifiable Output" for someone claiming forty.

**Evidence:** verify.py:422-426 — `HANDLERS = {"doi": ..., "degree_institution": "verify_institution"}` (7 entries) vs extract.py:33-38 `EMITTED_SUBTYPES` (26). verify.py:430 `checkable = [c for c in claims if c.subtype in self.HANDLERS]`; verify.py:433 `self.skipped[c.subtype] = self.skipped.get(c.subtype, 0) + 1`.

verify.py:104-113 stores `subject_name`, but its only uses are verify.py:165 `names.name_matches(self.subject_name, candidates)` and verify.py:177 inside `_attribute` — never in a URL. Handler URLs are all `claim.value`-keyed: verify.py:196, 216, 242-243, 274, 307, 337, 385.

verify.py:180-192 — `_attribute` writes only `claim.status`, `claim.detail`, `claim.source`. No return of new facts. audit.py:29-30 `verifier.verify_all(claims, progress=progress)` — return value ignored; the pass mutates in place and ends.

providers.py:180 `"https://api.openalex.org/authors?search=" + urllib.parse.quote(subject)` — subject-keyed, but providers.py:65 `return "\n".join(f.as_text() for f in self.findings if f.about_subject)` → cli.py:107 `run_audit(target, bundle.corpus, ...)` → audit.py:23 `claims = ex.extract_claims(text)`.

flags.py:242-249 — `scholar = ctx.signals.get("openalex"); if scholar and scholar.get("works"): return FlagResult(PASSED, ...)`. Truthiness only; the claimed count is never read.

cli.py:169 `signals["profile_facts"] = profile.facts` — sole occurrence in the repo.

flags.py:414-417 — `checkable = [c for c in ctx.claims if c.subtype in ("doi","orcid","github","arxiv","nct","patent")]`; empty → `UNKNOWN, "No claim carries an identifier that a registry could confirm or refute."` The ORANGE floor (flags.py:409, scoring.py:73-85) therefore cannot fire on a profile that cites no identifiers.

**Fails on:** Profile (fabricated end to end), run as `--verify --name "Marcus Vane"`:

"Dr. Marcus Vane, CEO of Helion Neurotech. 20 years of experience in translational neuroscience. Over 40 peer-reviewed publications and 6 granted patents. PhD Neuroscience from Karolinska Institutet, 2004. Strategic partnerships with Siemens Healthineers, Philips and Mayo Clinic. 12,000 users on our platform. We are raising a Series A."

I ran this through `audit.run_audit` with ROR stubbed to its real answer (Karolinska Institutet exists). Result: **GREEN, larp_score 14, coverage 41%** — above the 0.35 floor (scoring.py:18), so it grades, and the summary printed is "Claims and verifiable substance broadly align."

`extract_claims` produced 8 claims; exactly **one** was reachable by any verifier — `degree_institution: Karolinska Institutet`. `verifier_stats.skipped_subtypes` = `{assertion:1, claimed_experience_years:1, degree:1, leadership:1, owned_org:1, users:1, year:1}`. Per-flag:
- [8] PASSED — "Degree tied to an institution confirmed in ROR (Karolinska Institutet)". The only thing `--verify` established is that a Swedish university exists; the report phrases it as a confirmed credential.
- [11] UNKNOWN — "No claim carries an identifier that a registry could confirm or refute." No floor applies.
- [6] UNKNOWN — "Only unsourced assertions of output ('peer-reviewed')". "40 publications" lands as subtype `assertion` (extract.py:69, 196-199), which has no handler; "6 granted patents" matches nothing at all, since PATENT_RE needs a US/EP/WO number (extract.py:63).
- [7] PASSED — "Fundraising alongside quantified traction" on the strength of the invented "12,000 users".
- [9] UNKNOWN, [3] UNKNOWN — the three named partners were never verified, and in fact `PARTNER_ORG_RE` (extract.py:112-116) did not even match "partnerships with" (plural + `with` breaks the pattern), so the logo-wall and self-referential checks had nothing to look at.

In web mode this profile gets *worse*, not better: OpenAlex would be queried by name and return 0 works for Marcus Vane, but flags.py:245 only reads that signal when it is non-zero, so the correct finding — "claims 40 papers, scholarly record shows 0" — has nowhere in the data model to live. A namesake with one paper would instead flip flag 6 to PASSED with "Independent scholarly record found: 1 works".

The honest profile that pastes its DOIs gets audited. The competent LARP that pastes nothing gets GREEN.

**Fix direction:** Add a second dispatch dimension to the Verifier and a type distinct from Claim.

1. **Subject-keyed probes.** Alongside `HANDLERS: subtype → handler(claim)`, add `PROBES: subject_name → probe()` returning `Evidence` records: OpenAlex/ORCID search-by-name for a works count, Crossref `query.author`, PatentsView for an inventor count, GitHub user search. These are the same free, key-free endpoints providers.py already calls (providers.py:180, 222) — the world is not the constraint here, the dispatch shape is.

2. **Make `verify_all` return evidence, not just mutate claims.** `return claims` (verify.py:442) becomes `return claims, evidence`; `audit.run_audit` threads evidence into `AuditContext` as a first-class field rather than the `signals` dict that three flags happen to consult (flags.py:36-45).

3. **Quantity reconciliation.** Extract the number in "40 peer-reviewed publications" / "6 granted patents" (today collapsed to a bare `assertion`, extract.py:67-72) and compare it to the probe count. That yields a status the model currently cannot represent — call it `UNSUPPORTED_AT_SCALE`, distinct from `NOT_FOUND` and from `UNCHECKABLE`.

4. **Score it honestly, not aggressively.** Name-keyed absence is genuinely weaker than an identifier-keyed contradiction (name variants, transliteration, initials-only publishing), so it should not inherit flag 11's ORANGE floor. But it must be *expressible* and *printable*: even reported as UNKNOWN-with-evidence, "claims 40 papers; OpenAlex lists 0 under this name — confirm by hand" is the single line a due-diligence reader most needs, and today no code path can emit it.

5. **Stop laundering evidence into claims.** `bundle.corpus` (providers.py:65) should not be fed to `extract_claims` (cli.py:107 → audit.py:23). Provider findings are facts about the subject; folding them into `ctx.text` makes flag 4 measure Wikipedia's prose style as the subject's rhetoric and lets a third-party snippet manufacture an `owned_org` claim. Also wire `signals["profile_facts"]` (cli.py:169) to a consumer or delete it — `--url` mode collects an exact identity anchor, the one thing that would make name-keyed probes safe, and then throws it away.

---

### [FIXED] GitHub is the only registry with no attribution check — any repo on earth verifies as the subject's

Every other verifier funnels through `_attribute()` (verify.py:167-192), which is the mechanism that turns "the artifact exists" into "the artifact is theirs". `verify_github` bypasses it entirely and hardcodes VERIFIED for both branches. The GitHub API response already in hand contains `owner.login` (repo) and `name` (user), and `/repos/{o}/{r}/contributors` is one more keyless call — the data source is integrated, the discriminating fields are simply discarded. A GitHub URL is the single most commonly pasted 'proof of building things' in a tech bio, and it is the one identifier the tool cannot refute.

**Evidence:** larp_meter/verify.py:239-271 `verify_github`. Repo branch, lines 256-264: `stars = data.get("stargazers_count", 0)` … `claim.status = VERIFIED` / `claim.detail = (f"Repo exists: {stars} stars, last push {pushed…}")` — no reference to `self.subject_name`, no `self._attribute(...)` call anywhere in the method. User branch, lines 265-270: `repos = data.get("public_repos", 0)` … `claim.status = VERIFIED`, even though `data["name"]` is available (it is read for exactly this purpose in profiles.py:194 `data.name = payload.get("name") or ref.handle`). Contrast verify.py:212 (`self._attribute(claim, authors, …)`) and verify.py:303/410. The consequence propagates: flags.py:414-438 `f_contradicted` treats `github` as a hard identifier (`checkable = [c for c in ctx.claims if c.subtype in ("doi", "orcid", "github", …)]`) and can only ever see VERIFIED for it. tests/test_verify.py:91-110 tests stars, emptiness and 404 — no test constructs a subject name for a GitHub claim, so the hole is invisible to the suite.

**Fails on:** `--name "Rex Falsum" --verify` on "I architected the core scheduler — see github.com/torvalds/linux". verify_github returns VERIFIED, detail "Repo exists: 190000 stars, last push 2026-08-13". Flag 6 returns PASSED ("1 independently checkable artifact(s) cited"), flag 11 returns PASSED ("All 1 checked identifier(s) confirmed by their registries"), and the ORANGE floor never engages. The identical claim expressed as a DOI would return MISMATCH and floor the verdict at ORANGE.

**Fix direction:** Route the repo branch through `_attribute()` using `[data["owner"]["login"], data["owner"].get("name")]` plus a second keyless GET to `/repos/{path}/contributors?per_page=100` (login list), and the user branch through `_attribute()` on `data.get("name")`. Note that a repo the subject genuinely contributed to but does not own must resolve to VERIFIED, and an unreachable contributors call must degrade to UNCHECKABLE, not MISMATCH — the same discipline verify.py:402-409 already applies to unparsed patent inventors.

---

### [FIXED] ClinicalTrials.gov is queried for title and status only; the investigator fields go unread

`verify_nct` reads `identificationModule.briefTitle` and `statusModule.overallStatus` and then unconditionally sets VERIFIED. The v2 API response already returned by the same call carries `protocolSection.sponsorCollaboratorsModule.responsibleParty.investigatorFullName`, `.leadSponsor.name`, and `protocolSection.contactsLocationsModule.overallOfficials[].name` — precisely the names needed to test 'I ran this trial'. Zero additional network cost. This is the highest-stakes claim class the tool touches (medical authority) and it is the one where existence and attribution are furthest apart: a trial has one PI and hundreds of uninvolved people who can cite its NCT number.

**Evidence:** larp_meter/verify.py:306-325. Lines 316-319: `ident = json.loads(body)["protocolSection"]["identificationModule"]` / `status_mod = json.loads(body)["protocolSection"].get("statusModule", {})` — only two of the ~10 modules in the payload are touched, and the body is parsed twice. Lines 322-324: `claim.status = VERIFIED` / `claim.detail = f'Registered trial "{title[:70]}" — {overall}'`, with no call to `_attribute` and no use of `self.subject_name`. Registered as a hard identifier at flags.py:414-415 alongside doi/orcid/arxiv, so it counts toward the 2.5-weight, ORANGE-flooring flag 11 while being incapable of ever contradicting anything. tests/test_verify.py:176-184 asserts only VERIFIED + "COMPLETED".

**Fails on:** A bio reading "Principal Investigator, NCT00000102 (NIH phase II)" audited with `--name "Rex Falsum" --verify` yields VERIFIED, 'Registered trial "Congenital Adrenal Hyperplasia…" — COMPLETED'. Flag 11 reports "All 1 checked identifier(s) confirmed by their registries" for a trial run by strangers three decades ago.

**Fix direction:** Parse the payload once and pass `responsibleParty.investigatorFullName` + `overallOfficials[].name` + `leadSponsor.name` into `_attribute()`. When the record publishes no personal names at all (common for industry-sponsored trials, where responsibleParty is the sponsor), that is exactly the `usable == []` path at verify.py:183-186 and must return UNCHECKABLE. Also extract EudraCT (`\d{4}-\d{6}-\d{2}`) and CTIS numbers, which are not in ARTIFACT_PATTERNS at all (extract.py:57-64), so every EU-only trial is currently invisible.

---

### [FIXED] Attribution assumes the surname is the last token, so surname-first and multi-surname names produce false MISMATCH

**Verified 2026-08-16.** `name_matches('Zhang Wei', ['W. Zhang'])` measured `False` exactly as claimed, and the identical failure reproduced for Wang Xiaoming, Kim Ji-woo and Nguyen Van An. Fixed in `larp_meter/names.py`: the one-token fallback now accepts a match at EITHER end of the subject's name (`parts[0] in present or parts[-1] in present`), not just the last token, which covers Chinese/Korean/Vietnamese/Hungarian family-name-first order. To avoid the mirror-image bug — a shared GIVEN name ("Jan" in both "Jan Vermeulen" and "Jan Peeters") now also sitting at an end — the match is only accepted when the specific candidate string's other words are consistent with an abbreviation (bare initials, particles, or the subject's own tokens); a full unrelated word still returns False, and `tests/test_mutation_guards.py`'s existing Jan Vermeulen/Jan Peeters and Maria Garcia/Maria Rodriguez guards still pass unmodified. A single token matching in the MIDDLE of a 3+-part name (the Hispanic double-surname truncation case, 'Jose Ramirez Ortega' publishing as 'J. Ramirez') now returns `None` (UNCHECKABLE) instead of `False`, per the fix direction. Regression tests in `tests/test_names.py`, plus an end-to-end test through the real `verify_doi` dispatch in `tests/test_verify.py`.

Original finding, kept for context: `names.name_matches` accepted a one-token match only when the matching token is the FINAL significant token of the subject's name (`parts[-1] in present`). Registries routinely abbreviate the given name ('W. Zhang', 'J. Ramirez'), leaving exactly one full token to match. For every naming convention where the family name is not last — Chinese, Korean, Japanese, Vietnamese, Hungarian written in native order — and for Hispanic/Lusophone double surnames where the bibliographic surname is the FIRST of two, the surviving token is not `parts[-1]`, so the function returns False. False (not None) flows into `_attribute`, whose only remaining branch is MISMATCH: 'exists but does NOT list the subject'. That feeds flag 11 (weight 2.5) which carries `floor="ORANGE"`, so a single such record dictates the verdict. This directly contradicts the module's own promise at names.py:5-7 that it will 'only report a mismatch when no meaningful part of the name is present at all'. No test covers a non-Western name (tests only exercise 'Ada Lovelace', 'Jan van Dijk', 'Maria Garcia').

**Evidence:** larp_meter/names.py:68-73 — `if len(present) == 1: parts = [...]; if parts and parts[-1] in present: return True; return False`. Consequence at larp_meter/verify.py:190-191 — `claim.status = MISMATCH; claim.detail = f"{label} exists but does NOT list the subject ({shown})."`. Scored at larp_meter/flags.py:407-409 (weight 2.5, floor='ORANGE') and larp_meter/scoring.py:73-85. Measured: name_matches('Zhang Wei',['W. Zhang'])=False; ('Wang Xiaoming',['X. Wang'])=False; ('Nguyen Van An',['V. A. Nguyen'])=False; ('Kim Ji-woo',['J. Kim'])=False; ('Jose Ramirez Ortega',['J. Ramirez'])=False. Test coverage gap: tests/test_providers.py:41-73 and tests/test_mutation_guards.py:40-48 are all Western given-name+surname.

**Fails on:** Zhang Wei, an honest ML researcher, pastes a bio citing his own paper (doi:10.1145/...). Crossref returns authors ['W. Zhang','M. Chen']. Actual run output: flag 11 TRIGGERED — 'Paper "A sparse attention kernel for edge inference" exists but does NOT list the subject (W. Zhang, M. Chen)' — verdict ORANGE 39/100, summary 'Held at ORANGE by Contradicted Verifiable Claim: a public registry contradicts a specific claim.'

**Fix direction:** When exactly one significant token matches and the name has 2+ tokens, the honest answer is 'cannot tell', not 'someone else'. Return None (→ UNCHECKABLE) instead of False for the one-token case unless BOTH names are full (no initials) and the non-matching tokens are all full words too. Accept the token at either end of the subject name (surname-first and surname-last), and treat any single-initial candidate token as a wildcard against the corresponding subject token.

---

### [PARTIALLY FIXED] normalize() folds only combining marks, so non-decomposable Latin letters and every non-Latin script mismatch

**Verified 2026-08-16.** `name_matches('Bjorn Odegard', ['Bjørn Ødegård'])` and the Þorsson/Ivanov cases measured `False` exactly as claimed. Fixed in `larp_meter/names.py`:
- Added an explicit fold table for the non-decomposable Latin letters (ø→o, ł→l, đ→d, ð→d, þ→th, æ→ae, ı→i, ħ→h, ŋ→n), applied after casefold.
- `tokens()` now unions a hyphen/apostrophe-collapsed reading with the plain split, so 'Al-Sayed' and 'Alsayed' compare equal without breaking 'Smith-Jones' still matching on either half.
- A complete script mismatch (subject name is Latin-script, candidate has zero Latin letters, or vice versa) now returns `None` (UNCHECKABLE) rather than falling through to a token-search `False` — 'Mikhail Ivanov' vs a Cyrillic 'Михаил Иванов' record is correctly unanswerable, not a mismatch.

**Not fixed, left as a known gap:** true transliteration-spelling variance (e.g. 'Petrov' vs 'Petroff' for the same Cyrillic surname under different romanization schemes) is unaddressed — that needs a phonetic/transliteration equivalence table, which is a separate and much larger piece of work than a fold table. `name_matches('Ivan Petrov', ['Ivan Petroff'])` still returns a token-mismatch result today. Next run should scope this properly rather than bolt on an unreliable heuristic.

Regression tests in `tests/test_names.py`.

Original finding, kept for context: `normalize` does NFKD and drops combining characters. That handles é/ü/ś, but Unicode has no decomposition for ø, ł, đ, ð, þ, æ, ħ, ı, ŋ — so Nordic, Polish, Icelandic, Croatian, Turkish and Maltese names do not fold to their ASCII forms, which is exactly the form registries, publishers and legacy metadata often carry (and vice-versa: the user types ASCII, ORCID holds the accented original). There is also no transliteration layer at all: an ORCID or Crossref record whose name is deposited in Cyrillic, Chinese, Japanese, Korean, Arabic, Hebrew or Devanagari shares zero tokens with a Latin-script subject name, and Arabic article attachment ('Al-Sayed' vs 'Alsayed') breaks the word-boundary search at names.py:56. Every one of these lands on the same MISMATCH branch as finding #1. The docstring's own example only works by accident of `str.casefold` mapping ß→ss.

**Evidence:** larp_meter/names.py:21-25 — `decomposed = unicodedata.normalize("NFKD", text or ""); stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))`; token search at names.py:56 uses `re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", blob)`. Measured: name_matches('Bjorn Odegard',['Bjørn Ødegård'])=False and the reverse also False (tokens('Bjørn Ødegård') == {'bjørn','ødegard'} — å folded, ø did not); ('Halldor Thorsson',['Halldór Þorsson'])=False; ('Mikhail Ivanov',['Михаил Иванов'])=False; ('Ahmed Al-Sayed',['Ahmed Alsayed'])=False; ('Ivan Petrov',['Ivan Petroff'])=False.

**Fails on:** Bjørn Ødegård lists his ORCID. ORCID holds the ASCII form 'Bjorn Odegard' (or he typed ASCII into --name and ORCID holds the accented original). Zero tokens match, so verify.py:236 reports 'ORCID record exists but does NOT list the subject' → flag 11 TRIGGERED → verdict floored at ORANGE. Same for any Russian or Chinese researcher whose ORCID name is deposited in native script.

**Fix direction:** Add an explicit fold table for non-decomposable Latin letters (ø→o, ł→l, đ→d, ð→d, þ→th, æ→ae, ı→i, ħ→h) before comparison, strip hyphens/apostrophes inside tokens so 'Al-Sayed'/'Alsayed' collapse, and treat a candidate name written in a different script from the subject name as unanswerable (None → UNCHECKABLE) rather than as a mismatch.

---

### [FIXED] Any identifier appearing anywhere in the text is treated as a personal authorship claim

`extract_claims` harvests every DOI, arXiv ID, ORCID, NCT and patent number in the text with no ownership context whatsoever, and `verify.py` then asks 'does this record list the subject?' of all of them. The `Claim.context` field is captured at extract.py:171-174 but is never read again anywhere in the codebase — no first-person framing, no possessive, no section awareness. Citing literature you build on, prior art, a standard you implement, an employer's patent you are not the named inventor on, or a client's patent you prosecuted is normal professional writing; here every one of them becomes 'exists but does NOT list the subject', which is flag 11's TRIGGERED condition at weight 2.5 with an ORANGE floor. The codebase applies exactly the right reasoning elsewhere — GitHub repos (verify.py:265-278) and ClinicalTrials.gov records (verify.py:346-358) are deliberately left UNCHECKABLE because 'ownership does not establish authorship' and 'a trial record does not list every contributor' — but DOIs, arXiv IDs and patents get no equivalent guard.

**Evidence:** larp_meter/extract.py:190-194 — `for subtype, rx in ARTIFACT_PATTERNS: for m in rx.finditer(text): ... add("artifact", subtype, value, _context(text, m))`; `grep -rn "\.context" larp_meter/` returns nothing outside extract.py. larp_meter/verify.py:167-192 `_attribute` has no caller-supplied confidence. larp_meter/flags.py:414-415 — `checkable = [c for c in ctx.claims if c.subtype in ("doi", "orcid", "github", "arxiv", "nct", "patent")]`, then flags.py:422-435 turns MISMATCH into the TRIGGERED evidence string. Reproduced: a bio containing doi:10.5555/3295222.3295349 with subject 'Sofia Almeida' → MISMATCH, 'Paper "Attention is all you need" exists but does NOT list the subject (Ashish Vaswani).'

**Fails on:** A patent attorney's bio: 'I prosecuted US 9876543 for a client in the sensor space.' The patent exists, the inventors are the client's engineers, so flag 11 fires: '1 exist but do not list the subject. A claim contradicted by its own registry is the strongest single signal this tool can produce', and scoring.py:82-85 holds the verdict at ORANGE. Identical outcome for any engineer who writes 'our approach builds on <doi>'.

**Fix direction:** Gate attribution on the claim's own context: only treat an identifier as an authorship claim when its surrounding fragment carries first-person/possessive framing ('my', 'our', 'I published', a publications heading), and mark the rest as EXISTENCE-ONLY/UNCHECKABLE the way GitHub repos and NCT records already are. At minimum, a non-attributable identifier must not be able to trip a floor-carrying flag.

**[FIXED — nightly/2026-08-25]** Confirmed live before touching anything, exactly as measured above: a stubbed Crossref record for the real "Attention Is All You Need" DOI, subject "Sofia Almeida", text framed as "I prosecuted patent applications... for a client... I was not an inventor on this work; I simply cited it as prior art" — came back flag 11 **TRIGGERED**, claim status **MISMATCH**, on a claim the subject's own sentence explicitly disclaims.

Took the narrower half of the two fix directions the entry offers, not the broader "require positive first-person framing" one: requiring an explicit ownership marker before ANY identifier counts as attributable would flip the tool's default for the ordinary case too (a CV that just lists "Publications: 10.xxx, 10.yyy" under a heading, with no "my"/"I" nearby) from checkable to UNCHECKABLE, which is a much larger behavior change than one night should ship unreviewed. Instead added `_disclaims_authorship()` in `verify.py`: `_attribute` — the single shared tail for DOI, ORCID, GitHub-user, arXiv and patent claims — now checks `claim.context` (already captured by `extract.py`, previously read nowhere) for an explicit third-party/citation signal ("prior art", "cit-ed/ing/ation", "based/built/building on", "not the inventor/author/credited/own", "client", "employer", "colleague", "co-worker", "teammate", "on behalf of", "someone else's", "another's") before deciding VERIFIED/MISMATCH, and routes a match straight to UNCHECKABLE — the same "existence recorded, attribution not asserted either way" treatment `verify_github`'s repo branch and `verify_nct` already give ownership-ambiguous artifacts. An unrecognised disclaiming phrase costs coverage, never accuses: this can only ever turn a would-be VERIFIED or MISMATCH into UNCHECKABLE, never the other direction, so a phrasing the guard misses is no worse than the pre-fix behavior.

Regression-checked that this does not become a blanket downgrade: `Claim`s built without a `context` (every existing hand-constructed `Claim(...)` in the test suite — none of them pass `context=`) are completely unaffected (`bool("")` is falsy), and a same-shape DOI claim whose context carries no disclaiming language still resolves to MISMATCH exactly as before (`tests/test_verify.py::test_doi_without_disclaiming_context_is_still_checked_normally`). Verified end-to-end through `run_audit`, not `_attribute` in isolation: a patent claim with disclaiming context now resolves UNCHECKABLE and flag 11 does not TRIGGER (`test_end_to_end_patent_citation_does_not_trigger_the_contradiction_floor`); confirmed live via the real CLI too — the patent-attorney sample from this entry's own "Fails on" now reports flag 11 UNKNOWN ("none could be attributed to the subject") instead of TRIGGERED, while a control run of the unrelated Dr. John Smith / real-DOI fabrication sample (no disclaiming language) still correctly reports flag 11 TRIGGERED / MISMATCH — the guard does not blunt genuine fraud detection, only the false-accusation case it targets.

Mutation-tested the fix itself: reverting the `_disclaims_authorship` guard in `_attribute` fails exactly the 3 new regression tests built for it (`test_patent_prosecuted_for_a_client_is_not_a_mismatch`, `test_doi_cited_as_prior_art_is_not_a_mismatch`, `test_end_to_end_patent_citation_does_not_trigger_the_contradiction_floor`), confirmed, then restored.

**Left open, deliberately:** the broader "require positive ownership framing" direction (flip the default rather than deny-list disclaiming phrases) is still not attempted — it would meaningfully change coverage on ordinary bios and needs its own dedicated review, not a same-night bolt-on. The phrase list is also necessarily incomplete (a fabricator who never writes "prior art"/"client"/"cited" and simply lists a stolen identifier bare is unaffected — this fix protects the honest-citation case, it does not add new fraud detection). `verify_orcid`, `verify_arxiv`, `verify_patent` and the GitHub-user branch of `verify_github` all route through the same `_attribute` tail so all four benefit uniformly; `verify_institution` (ROR) and the GitHub-repo/ClinicalTrials branches were already blanket-UNCHECKABLE-on-ambiguity before tonight and are unaffected either way.

---

### Word-wrapped negation loses its scope at every bare newline
### [FIXED] Word-wrapped negation loses its scope at every bare newline

`is_negated` (matching.py:64-87), the guard every `skip_negated=True` call in the file relies on to stop a denied claim being read as an asserted one, treats a bare `\n` as a clause boundary (`_CLAUSE_END_CHARS = ".;:!?\n•|"`, matching.py:57). That is correct for an intentional line break — a new bullet, a new field on its own line — but a `\n` is equally what any word-wrapped paragraph contains: pasted plain text, a PDF-extracted CV, or an email client that hard-wraps at 72-80 columns all insert a bare newline in the middle of an ordinary sentence, with no clause boundary intended. When a negator sits right before the wrap and the negated word sits right after it, the clause-boundary scan stops at the newline and the negator is invisible to the token that follows — the exact same failure this file's own docstring describes fixing for same-line text ("We have no customers and no revenue" — see matching.py:29-32), reintroduced by nothing more than where the source text happens to wrap.

**Evidence:** matching.py:57 `_CLAUSE_END_CHARS = ".;:!?\n•|"`; matching.py:74-77 `for ch in _CLAUSE_END_CHARS: i = text.rfind(ch, 0, start); ... boundary = i + 1` — a `\n` anywhere before the match sets `boundary` past it, so `tokens_before` (matching.py:80-81) never includes anything from before the newline. Measured directly against `is_negated`/`find_terms`:
```
>>> find_terms("We are not raising a Series A at this time.", banks["funding_ask"], skip_negated=True)
[]
>>> find_terms("We are not\nraising a Series A at this time.", banks["funding_ask"], skip_negated=True)
['raising']
```
Same collapse on the traction bank with a mid-sentence wrap: `"...with no customers or revenue disclosed yet."` correctly finds nothing; `"...with no customers or\nrevenue disclosed yet."` (line-wrapped at a plausible column) finds `['revenue']`.

**Fails on:** Any ordinary word-wrapped bio that happens to negate a funding_ask, traction, building_claims or vague_partnership term across a line break. Concretely: a founder pastes a plain-text bio (or one extracted from a PDF) reading "We are not\nraising a Series A at this time; the team is heads-down on the product." `f_fundraising` reads `asks = ['raising']` (the "not" that denies it is now invisible), sees no traction language, and returns **TRIGGERED**: "Actively raising ('raising') with no customer, revenue or usage figure of any kind." — accusing someone of doing the literal opposite of what they wrote, purely because of where their word processor happened to wrap a line. The same mechanism can null out a stated `confidentiality_reasons`/`pre_revenue_stage` escape phrase (this file's "Confidential work and pre-revenue fundraising..." finding, [PARTIALLY FIXED] above) if the negation guarding it is wrapped away, or work in the tool's favor by nulling a real denial the wrong direction (missing a legitimate PASS) — either way the report depends on line-wrap position, which is not a fact about the subject.

**Fix direction:** Stop treating every bare `\n` as a clause boundary; a paragraph/field break is better signalled by a blank line (`\n\s*\n`) or a line that starts with a bullet/field marker, not by the mere presence of one `\n`. The minimal, most defensible first step: before scanning, collapse a single `\n` that is not followed by another `\n` or a bullet-like marker into a space (or extend `_CLAUSE_END_CHARS`'s newline handling to look at what follows the break, not just its presence) so a genuinely wrapped sentence reads as one clause while an intentional new bullet/field still ends one. This touches shared infrastructure (`is_negated` backs every `skip_negated=True` call across every flag in `flags.py`), so it needs its own dedicated night: a full mutation-testing pass against `matching.py` (never yet swept — see the mutation-testing log in NIGHTLY.md, which has only ever covered `scoring.py`/`names.py`/`flags.py`/`verify.py`) plus new regression tests pinning both directions (a wrapped negation preserved, and a genuine bullet-separated list still NOT bleeding negation across items — e.g. "No revenue.\nRaising a seed round." must still count as a real ask on the second line).

**Fails on:** Any ordinary word-wrapped bio that happens to negate a funding_ask, traction, building_claims or vague_partnership term across a line break. Concretely: a founder pastes a plain-text bio (or one extracted from a PDF) reading "We are not\nraising a Series A at this time; the team is heads-down on the product." `f_fundraising` reads `asks = ['raising']` (the "not" that denies it is now invisible), sees no traction language, and returns **TRIGGERED**: "Actively raising ('raising') with no customer, revenue or usage figure of any kind." — accusing someone of doing the literal opposite of what they wrote, purely because of where their word processor happened to wrap a line.

**Fix direction:** Stop treating every bare `\n` as a clause boundary; a paragraph/field break is better signalled by a blank line (`\n\s*\n`) or a line that starts with a bullet/field marker, not by the mere presence of one `\n`.

**[FIXED — nightly/2026-09-02]** Confirmed live first, exactly as measured above, then wrote 7 failing unit tests (`tests/test_negation.py::TestNewlineClauseBoundary`) plus one failing end-to-end flag test before touching `matching.py`. Implemented the fix direction's own suggestion, not the cruder "collapse every lone `\n` to a space" alternative it also floated: `_CLAUSE_END_CHARS` no longer includes `\n` at all; a new `_hard_newline_before()` walks backward through consecutive newlines (bounded by the existing `_MAX_LOOKBACK_CHARS` window, so this cannot reintroduce the quadratic cost the same file's own history warns about) and only counts one as a boundary when it is a genuine blank-line paragraph break or is immediately followed by a bullet/numbered-list marker (`_BULLET_START_RE`: `•`, `▪`, `‣`, `*`, `-`, an en/em dash, or `1.`/`1)`-style numbering). An ordinary mid-sentence word-wrap matches neither condition and is now treated as whitespace, so negation reaches across it exactly as it would on one line.

Both directions are pinned, not just the reported bug: `test_word_wrapped_negation_still_applies` / `test_word_wrap_mid_phrase_still_applies` cover the fix itself; `test_paragraph_break_still_stops_negation`, `test_hyphen_bullet_list_item_stops_negation` and `test_numbered_list_item_stops_negation` cover the failure mode the fix direction itself worried about — a real list-item break must still stop negation, or "No revenue" in one bullet would wrongly suppress "Raising a seed round" in the next. Each of those three was written to fail specifically on the newline/bullet logic being disabled, not merely on the unrelated 6-token lookback cap happening to save it by coincidence (an earlier draft of the paragraph-break test didn't discriminate this way — caught it while mutation-testing my own diff, see below).

**End-to-end CLI check**, two hand-written samples run through the real `run_audit` pipeline via `larp-meter.py --file`: (1) an honest, word-wrapped bio explicitly denying an active raise across a line break ("We are not\nseeking investment and are not raising...") — flag 7 correctly reports UNDECIDABLE ("Not visibly fundraising; the flag does not apply"), where before the fix it would have read the wrapped "raising" as asserted; (2) a fabricator bio asserting a real raise across an unrelated word wrap ("We are actively\nraising a Series A round...40 enterprise customers and 12M in ARR") — flag 7 still correctly reports PASSED ("Fundraising with stated traction"), confirming the fix does not over-correct and suppress a genuine, wrapped assertion.

Mutation-tested the fix itself, one deliberate revert at a time, confirmed a real test failure, then restored: disabling the blank-line check alone (4 failures once the discriminating test above was fixed), disabling the bullet-marker check alone (2 failures), and reverting to the old always-hard-newline behavior entirely (4 failures). Also added `tests/test_round4.py::test_a_newline_heavy_document_stays_tractable`, mirroring the file's existing hype-heavy-document perf regression test, since the new backward walk touches exactly the kind of unpunctuated pathological input that test class exists to guard against.

**Cross-boundary check:** `is_negated`'s signature and return contract (bool) are unchanged — only its internal boundary computation changed — so both call sites (`matching.py`'s own `_matches()` and `extract.py:251`'s `negated=zero or is_negated(...)`) needed no changes and were re-verified by the full suite, not just the module's own tests.

---

## MAJOR (25)

### VERIFIED is a single token that means both "first author of this paper" and "this string resolved" — two of seven handlers never attempt attribution at all

The verification layer's entire output vocabulary is the five-value enum at extract.py:15-19, and `VERIFIED` carries no strength. `_attribute` (verify.py:164-189) implements the tool's stated design rule #2 ("Existence is not attribution", verify.py:8-10), but only four handlers call it: verify_doi (209), verify_arxiv (300), verify_orcid (233), verify_patent (407). `verify_github` (verify.py:253-267) and `verify_nct` (verify.py:319-321) set `claim.status = VERIFIED` unconditionally on existence, with no name comparison — because their registries do not expose a person list that fits `_attribute`'s signature. verify_github even computes the disconfirming facts (`stars`, `archived`, `size == 0` at verify.py:255-257) and writes them into the human-readable `detail` string, where no scoring code can read them; the status is VERIFIED for an empty archived 0-star repo exactly as for a flagship project.

Flag 11 is where this becomes a scoring error. It is the heaviest flag in the battery (weight 2.5, `floor="ORANGE"`, flags.py:397-399) and partitions purely on the enum: `confirmed = [c for c in checkable if c.status == ex.VERIFIED]` (flags.py:414), then reports "All N checked identifier(s) confirmed by their registries" (flags.py:427). It has no way to distinguish "the registry confirms this person wrote this" from "this identifier is a real string that belongs to someone else."

**Evidence:** extract.py:15-19 — the five-value status enum, the whole vocabulary.
verify.py:164-189 `_attribute` — the three-outcome attribution logic, called from verify.py:209, 233, 300, 407 only.
verify.py:253-261 — `if is_repo: ... claim.status = VERIFIED` with stars/archived/empty folded into `claim.detail` text; verify.py:262-266 same for users; `self.subject_name` is never consulted.
verify.py:319-321 — `claim.status = VERIFIED; claim.detail = f'Registered trial "{title[:70]}" — {overall}'`, no attribution check.
flags.py:412-428 — flag 11 partitions on `c.status` alone.

**Fails on:** Bio: "Dr. Marcus Vane, CTO of Vane Quantum Systems. Our work is at github.com/torvalds/linux and our clinical programme is registered as NCT00000102. 15 years building deep tech." Run with `--verify --name "Marcus Vane"`. Both identifiers resolve (they are real, public, and belong to other people), and the measured report gives: github torvalds/linux -> VERIFIED "Repo exists: 190000 stars"; nct NCT00000102 -> VERIFIED "Registered trial ... COMPLETED"; and **flag 11 = PASSED, "All 2 checked identifier(s) confirmed by their registries"** — the tool's heaviest and most authoritative flag actively rewarding a subject for citing a stranger's repository and an unrelated NIH trial. Registry identifiers are public and enumerable, so this is the cheapest possible way to farm the one flag the tool treats as ground truth.

**Fix direction:** Give the verification layer a strength dimension the scorer can read, not just prose in `detail`: either add an `attribution` field to Claim (CONFIRMED / NOT_ATTEMPTED / MISMATCH / UNAVAILABLE) orthogonal to existence, or split VERIFIED into EXISTS vs ATTRIBUTED. Then have flag 11 count only attributed confirmations as PASSED and treat existence-only results as UNKNOWN rather than as evidence for the subject. For GitHub specifically, attribution is available: compare the subject name against the owner/`login`, `name`, and contributor list rather than stopping at repo existence, and surface `size == 0` / `archived` / low `pushed_at` recency as structured fields.

---

### ORCID — the one authoritative structured record of exactly the claims the tool cannot verify — is fetched and then read for a name only

Both places the tool reaches ORCID hit the `/person` endpoint and extract only the display name. `verify.py:213` fetches `https://pub.orcid.org/v3.0/{id}/person` and reads `given-names` + `family-name` (verify.py:224-227) to answer "does this record name the subject." `profiles.py:213` — the `--url orcid.org/<id>` path, which is the tool's strongest identity anchor because the URL names exactly one person (profiles.py:1-8) — fetches the same endpoint and keeps name plus the free-text `biography` (profiles.py:223-228), which is then handed back to `run_audit` as prose (cli.py:158-171) and re-parsed by the same regexes that read a pasted LinkedIn blurb.

ORCID publishes `/educations`, `/employments`, `/qualifications` and `/works` as separate structured endpoints on the same public, key-free API the tool is already calling. Those are the exact records that would settle flag 1 (education vs claimed domain), flag 2 (experience vs title), flag 8 (credential tied to a checkable institution) and flag 12 (timeline), all four of which are today decided purely lexically from `ctx.text` (flags.py:79-135, 141-169, 290-328, 435-464). The tool holds an authoritative, institution-vetted record of the subject's degrees, employers and publication list in its hand and reads one string out of it. This is the primary architectural finding in miniature: the verifier's contract is "confirm the identifier," so it stops the moment attribution resolves, and has no concept of "harvest what the record contains."

**Evidence:** verify.py:212-234 `verify_orcid` — URL is `.../person`; the only fields read are `name['given-names']['value']` and `name['family-name']['value']`; result goes to `_attribute(claim, [full] if full else [], "ORCID record", url)`.
profiles.py:211-232 `_read_orcid` — same `/person` URL; keeps `data.name` and `biography.content`; `data.facts` is left empty (contrast profiles.py:196-202, where the GitHub reader does populate structured facts).
cli.py:146-174 — the profile's text is concatenated with any paste and fed to `run_audit` as unstructured prose; `signals` carries only `profile_anchor`, `profile_reachable`, and `profile_facts`.
flags.py:81 and 85 — flag 1 derives the claimed domain and the supporting credentials from `ctx.text` via `dom.claimed_domain` / `dom.supporting_domains`; there is no path for registry-sourced education to reach it.

**Fails on:** `python larp-meter.py --url orcid.org/0000-0002-1825-0097 --verify` on a subject whose ORCID record lists a BSc from one institution, while the pasted bio claims "PhD, Stanford." The tool fetches that person's authoritative ORCID record, reads their name to confirm the record is theirs, discards the education and employment sections, then runs `DEGREE_RE` (extract.py:77-84) over the bio, extracts `degree: "PhD"` + `degree_institution: "Stanford"`, routes neither to any verifier (see the dead-handler finding), and reports flag 8 PASSED. The single case where the tool has an unambiguous identity anchor and an authoritative credential record in the same HTTP session is the case where it verifies nothing about the credential.

**Fix direction:** Treat a resolved ORCID as an identity anchor that unlocks a record harvest, not as a claim that terminates on confirmation. Fetch `/educations`, `/employments` and `/works` (or `/record`) once the `/person` name check passes, populate `ProfileData.facts` with the structured result the way `_read_github` already does (profiles.py:196-202), and emit derived Claims for each degree/employer/work so the reconciliation step can compare them against the text-extracted ones. That single change gives flags 1, 2, 8 and 12 registry-grounded input instead of keyword matching, for every subject who has an ORCID.

---

### No company or legal-entity registry: every role, ownership and partnership claim is pure self-assertion

The extractor produces `role/owned_org`, `role/leadership` and `partnership/partner_org` claims, and not one of them has a handler in `HANDLERS`. The only cross-check that exists is `f_self_referential`, which compares the text against itself — it can catch someone listing their own company as a partner, but it cannot tell whether either company exists. ROR does not help here: it indexes research organizations, so a startup, a consultancy or an invented "Group" is legitimately absent. The result is that the single most common professional LARP — being CEO/founder of an entity that was incorporated last month, was dissolved three years ago, or never existed — is completely outside the tool's evidence surface, while the far rarer academic LARP is checked against four registries.

**Evidence:** larp_meter/extract.py:204-208 emit `owned_org` and `partner_org`; larp_meter/extract.py:201-202 emits `leadership`. None appear in larp_meter/verify.py:415-419. larp_meter/flags.py:175-186 `f_self_referential` operates entirely on `ex.owned_and_partner_orgs(ctx.claims)` (larp_meter/extract.py:251-259), i.e. text-vs-text. larp_meter/flags.py:334-347 `f_logo_wall` likewise only counts names. README.md:216 concedes the shape of the gap: "every registry this tool consults is academic or corporate" — in practice only the academic half is implemented.

**Fails on:** "Founder and CEO of Helios Grid Systems. Partnership with Northwind Energy AG. We are in a consortium with the Baltic Power Institute." All three entities are invented. Every flag that touches them returns PASSED or UNKNOWN; no registry is consulted; the profile reads as substantiated.

**Fix direction:** Add a company-verification handler for `owned_org` / `partner_org` / `mentioned_institution`, chaining keyless sources and treating absence as coverage-lowering (the ROR philosophy at verify.py:369-377), never as a finding. Genuinely keyless and documented: **GLEIF LEI** (`api.gleif.org/api/v1/lei-records?filter[entity.legalName]=`, JSON:API, global, returns legal name, registration status ACTIVE/LAPSED/RETIRED, jurisdiction, initial registration date, parent/child relationships) — but be honest that LEI coverage skews to financial-market participants, so a five-person startup will usually be absent; and **SEC EDGAR** (`data.sec.gov/submissions/CIK##########.json` plus `efts.sec.gov` full-text search, keyless but requires the descriptive User-Agent the tool already sets at verify.py:34-35) for US-listed and fund entities. Deliberately do **not** pursue OpenCorporates: its API is now key-gated with commercial terms and does not fit the zero-key posture. UK Companies House and NL KVK are free but key-required, which means extending `_get`'s per-host auth (currently hardcoded to GITHUB_TOKEN at verify.py:130-133) before any of them can be added.

---

### [PARTIALLY FIXED] Nothing checks whether a cited paper was retracted, or whether it is peer-reviewed at all — and Crossref already returns the fields

`verify_doi` fetches the full Crossref record and reads exactly two fields: `title` and `author`. The same response carries `type` (`journal-article` vs `posted-content` — i.e. a preprint), `update-to` (populated with a `retraction` relation when the work has been retracted), `is-referenced-by-count`, and `published`. So the tool will certify a retracted paper as VERIFIED, and will certify a preprint as satisfying an explicit "peer-reviewed" claim. That claim is even extracted — `SOFT_EVIDENCE` records `"peer-review claim"` as an `artifact/assertion` — but `assertion` has no handler, and flag 6 explicitly gives up on it. Retraction and preprint-inflation are two of the highest-signal, most-checkable forms of publication LARP, and the tool is blind to both while already holding the data.

**Evidence:** larp_meter/verify.py:203-209 — `msg = json.loads(body)["message"]`, then only `msg.get("title")` and `msg.get("author")` are used. larp_meter/extract.py:51 `(re.compile(r"\bpeer[\s-]reviewed\b", re.I), "peer-review claim")` → larp_meter/extract.py:180 `add("artifact", "assertion", label, ...)`; `assertion` is absent from larp_meter/verify.py:415-419; larp_meter/flags.py:263-264 `return FlagResult(UNKNOWN, "Only unsourced assertions of output (e.g. 'peer-reviewed') — no identifiers to check.")`. larp_meter/flags.py:404-405 restricts flag 11 to `("doi", "orcid", "github", "arxiv", "nct", "patent")`, so an assertion can never be refuted.

**Fails on:** "My peer-reviewed work on room-temperature superconductivity (10.1038/s41586-023-06774-2) established the field." That DOI is a retracted Nature paper. The tool reports VERIFIED, flag 11 PASSED, flag 6 PASSED. Same failure with a bioRxiv DOI presented as peer-reviewed: `type: posted-content` is in the response and ignored.

**Fix direction:** Zero-network-cost half: read `type` and `update-to` from the body already fetched at verify.py:203, and let a `posted-content` type contradict an extracted `peer-review claim`. Best value-per-work new source: **OpenAlex works-by-DOI** — one keyless GET to `api.openalex.org/works/doi:{doi}` returns `is_retracted`, `type`, `cited_by_count`, `primary_location.source` (venue, `is_in_doaj`) and `authorships[].institutions` in a single response, and OpenAlex is already a trusted dependency of this codebase (providers.py:174), so it costs no new trust decision. Add `mailto=` to enter OpenAlex's polite pool — providers.py:180 currently omits it, which puts the tool in the throttled common pool. **DOAJ** (`doaj.org/api/search/journals/issn:`) is keyless and adds a venue-legitimacy signal; note it is a whitelist, so absence must not be treated as evidence.

**[PARTIALLY FIXED — nightly/2026-09-13]** Took only the zero-network-cost retraction half — the exact half this entry itself calls out first — and left the preprint/`posted-content` half and the OpenAlex-works/DOAJ extensions open (below). Before touching anything, live-checked the entry's own "Fails on" DOI (`10.1038/s41586-023-06774-2`) against api.crossref.org: it turned out to be the *retraction notice*, not the original paper (title "Retraction Note: Evidence of near-ambient superconductivity..."), and the entry's claim that the tool reports this DOI VERIFIED/flag-11-PASSED reproduced exactly as described before the fix.

Live-checking the general case turned up a real data-quality wrinkle the "Fix direction" above doesn't anticipate: the *original* retracted paper's own DOI (`10.1038/s41586-023-05742-0`) does NOT carry an `update-to` entry of type `"retraction"` on itself — only `"expression_of_concern"` and `"correction"` — because Crossref/Retraction Watch attaches that relation to the separate notice DOI instead. Relying on `update-to` alone, as suggested, would have silently missed this exact live retraction. Cross-checked against a second real case (The Lancet's Surgisphere hydroxychloroquine paper, `10.1016/S0140-6736(20)31180-6`) where `update-to` DOES carry `"retraction"` directly — so the relation's location is genuinely inconsistent across publishers/records, not a one-off. Fixed by checking two independent signals in `verify._is_retracted()` and trusting either: an `update-to` entry of type `"retraction"` (catches the Lancet-style case), OR the record's own title starting with a publisher-applied prefix (`"retracted"`, `"retraction"`, `"withdrawn"` — anchored at the start, so a paper merely discussing retraction as a research topic is not caught by a substring match).

`verify_doi` now sets a new `Claim.retracted` field (default `False`, does not disturb existing VERIFIED/MISMATCH/UNCHECKABLE attribution logic or any exact-dict test) and appends a plain-language note to `claim.detail`. Deliberately did **not** touch `claim.status` — retraction is a fact about the artifact's continued validity, orthogonal to whether the subject wrote it, and conflating the two would have made a citation-of-someone-else's-retracted-paper (disclaimed, UNCHECKABLE) look identical to the subject's own retracted work. Wired into flag 11 (`f_contradicted`) rather than a new flag: a confirmed (subject-attributed, `--name` given) DOI claim that is also retracted now TRIGGERS with its own message, distinct from the pre-existing NOT_FOUND/MISMATCH branches, and still carries the ORANGE floor — this is squarely "a public registry actively refutes a specific claim," the flag's own charter. Guarded against the two false-accusation shapes this flag has been bitten by before: (1) without `--name`, attribution was never checked at all, so a retracted-but-unattributed claim stays in the existing "existence alone is not confirmation" UNKNOWN branch rather than newly reading as TRIGGERED; (2) a citation the subject's own text disclaims as prior art/someone else's work (`_disclaims_authorship`, the 2026-08-25 fix above) stays UNCHECKABLE regardless of retraction status — the fact is recorded, but never asserted against the subject. Message wording is deliberately neutral ("no longer standing evidence... whatever the reason for the retraction") rather than accusatory, since a retraction can follow from a co-author's misconduct or a journal's own error with no fault on the subject's part at all.

Regression tests in `tests/test_verify.py` (`TestRetraction`: both detection signals independently, the topic-paper false-positive guard, the disclaimed-citation case, and one full `run_audit` pipeline test using a real, live-shaped Crossref response) and `tests/test_flags.py` (`TestContradictionFlag`: confirmed+retracted TRIGGERS, confirmed+standing still PASSES, retracted-without-a-name still does not confirm). All five new/changed lines were watched to fail before the fix and pass after. Confirmed live end-to-end via the actual CLI against the real network, both directions: the entry's own retracted-paper sample now reports flag 11 TRIGGERED with the retraction message (previously PASSED); an honest researcher citing a real, standing DOI (Charles R. Harris / the NumPy paper) still reports flag 11 PASSED with no retraction wording, landing INSUFFICIENT DATA only on the pre-existing thinness gate, unrelated to this change.

**Still open:** the preprint/`posted-content`-contradicts-`peer-review-claim` half (needs correlating a `doi`/`arxiv` claim against a separate `artifact/assertion` claim elsewhere in the text — a claim-linking capability that does not exist yet, out of scope for tonight), and the OpenAlex-works-by-DOI / DOAJ venue-legitimacy extensions the "Fix direction" describes as the higher-value next step. Next run should pick up the preprint half first — it is the more common real-world case (a fabricator citing a bioRxiv/SSRN posting as "peer-reviewed") and does not need any new provider, only the claim-linking groundwork.

---

### No external time anchor: the timeline flag can only check the profile against itself

`f_timeline` compares extracted `claimed_experience_years` against the earliest extracted `year` and against `now_year`. Both inputs come from the same text the subject wrote, so the flag catches arithmetic sloppiness and nothing else — a fabricator who states a consistent set of dates is untouchable. There is no source anywhere in the tool that can independently date anything: not a company, not a product, not a domain, not a web presence. Two keyless, zero-auth sources would close this, and neither is currently represented in `providers.py` (which has no web-infrastructure provider at all) or in `HANDLERS`.

**Evidence:** larp_meter/flags.py:435-464 — inputs are `ex.claims_by(ctx.claims, "timeline", "claimed_experience_years")` and `ex.claims_by(ctx.claims, "timeline", "year")`, both from `extract_claims` over the subject's own text (larp_meter/extract.py:217-226). larp_meter/flags.py:456 `if claimed > available + 3` is the entire external-reality test, and `available` is derived from `min(years)` in the same text. `ALL_PROVIDERS = (Wikipedia, OpenAlex, Crossref, DuckDuckGo)` at larp_meter/providers.py:274 — no infrastructure or archival provider.

**Fails on:** "Founded Aurora Fusion Labs in 2013. Twelve years building magnetic-confinement systems. auroraflabs.com" — internally consistent, so flag 12 returns PASSED. The domain was registered four months ago and has no archived snapshot before this year. The tool has no way to notice.

**Fix direction:** Add two keyless providers whose answers are dates rather than text. **RDAP** (`https://rdap.org/domain/{host}`, IETF standard, JSON, no key, IANA bootstrap handles the registry redirect) returns the domain's `registration` event date — directly contradicts "since 2013" claims tied to a company URL. **Wayback CDX** (`http://web.archive.org/cdx/search/cdx?url={host}&output=json&limit=1`) returns the first archived snapshot timestamp, which bounds when a web presence actually existed. Both are best-effort — some registries redact RDAP dates, and Wayback is occasionally slow or 5xx — so both belong on the `UNCHECKABLE`-on-failure path. Feed the earliest external date into `f_timeline` as a second, non-self-reported anchor alongside `min(years)`.

---

### Traction claims have no source at all, and stating an unverifiable number scores better than staying silent

`TRACTION_RE` extracts customers/users/revenue/ARR/employees/installations into `traction` claims, and no traction subtype appears in `HANDLERS`. Worse than merely unchecked: `f_fundraising` PASSES the moment any non-negated traction claim exists. So a subject who invents "50,000 users" gets a PASS on a 1.5-weight flag, while an honest subject who omits numbers gets TRIGGERED. The scoring gradient points toward fabrication on the one dimension where the tool has zero verification capability. This is the structural mirror of the artifact side, where at least existence is checked.

**Evidence:** larp_meter/extract.py:106-109 `TRACTION_RE` → larp_meter/extract.py:210-215 `add("traction", m.group(2).lower(), ...)`; no traction subtype in larp_meter/verify.py:415-419. larp_meter/flags.py:274 `traction_claims = [c for c in ex.claims_by(ctx.claims, "traction") if not c.negated]` then larp_meter/flags.py:277-279 `if traction_claims: return FlagResult(PASSED, "Fundraising alongside quantified traction.", ...)` — the branch is reached on claim *presence*, with `c.status` never consulted. Flag weight 1.5 at larp_meter/flags.py:269.

**Fails on:** "We're raising a $4M seed. 50,000 users on our SDK, 120 enterprise customers, $1.2M ARR." Every figure invented. Flag 7 PASSED. In the measured run above this contributed to a GREEN 0/100 verdict. Remove the numbers and describe the same company honestly as pre-revenue, and flag 7 TRIGGERS instead.

**Fix direction:** Two changes. (1) Scoring: presence of an unverified traction number should be `UNKNOWN`, not `PASSED` — an unverifiable assertion must not be able to clear a flag, which is the principle already applied to credentials at flags.py:314-315 ("Only an actual registry lookup can contradict"). (2) Add the narrow slice of traction that *is* keyless-checkable: the **npm registry** (`registry.npmjs.org/{pkg}`, plus `api.npmjs.org/downloads/point/last-month/{pkg}`) and **PyPI** (`pypi.org/pypi/{pkg}/json`, `pypistats.org/api/packages/{pkg}/recent`) turn "our SDK has 500k downloads" into a checkable claim, and GitHub's already-fetched `stargazers_count`/`subscribers_count` bounds "widely adopted open source". This requires new extractor patterns for package names, which do not exist today (extract.py:38-45).

---

### No biomedical literature source, and no PMID pattern — the tool checks clinical trials but cannot check the papers they produce

The tool verifies NCT numbers, which means it explicitly targets the medical/biotech archetype. But `ARTIFACT_PATTERNS` has no PMID or PMCID entry, so the identifier that dominates medical CVs is not even extracted, let alone verified. Crossref covers DOI-bearing journal articles but misses a large slice of PubMed-indexed content, older literature and preprints, and it is only queried by DOI in the verifier (author search exists only in the web-mode provider). The gap is asymmetric: the tool can confirm that a trial exists but cannot ask whether it ever produced a publication, or whether the subject appears anywhere in the biomedical literature.

**Evidence:** larp_meter/extract.py:38-45 — the complete pattern list is `doi, arxiv, orcid, github, nct, patent`; no PMID (`PMID: 12345678`), no PMCID, no ISRCTN/EUCTR. larp_meter/verify.py:303-322 `verify_nct` reads only title and status. larp_meter/providers.py:216-243 `Crossref` provider does author search, but its output feeds only `crossref_works` (providers.py:243), which no flag in larp_meter/flags.py reads.

**Fails on:** "Twenty-two PubMed-indexed publications (PMID 31234567, PMID 30111222) and PI on NCT04567890." Neither PMID is extracted — they do not match any pattern — so they are invisible to the report, and the NCT is rubber-stamped by existence alone. The subject presents eight identifiers and the tool checks one of them, badly.

**Fix direction:** Add PMID/PMCID patterns to `ARTIFACT_PATTERNS` and a handler backed by **Europe PMC REST** (`https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID:{pmid}&format=json`) — genuinely keyless, no token, well documented, stable, and it covers PubMed + PMC + preprints + agricola in one endpoint, returning `authorString` for `_attribute` to consume. The same endpoint answers the author-side question (`query=AUTH:"Lastname F"`) that Crossref's provider only half-answers. Prefer Europe PMC over raw NCBI E-utilities: E-utilities is keyless but rate-limits hard at 3 req/s without a key and returns XML.

---

### The score is a ratio over decided flags, so piling on unverifiable claims monotonically lowers it

`score()` computes `larp = 100 * trig_w / decided_w` where `decided_w = trig_w + pass_w`. Almost every flag that can reach PASSED does so on the subject's own unverified assertion (flag 5 on the word "contract", flag 8 on a named school, flag 9 on having few partners, flag 10 on naming a magazine, flag 12 on mentioning an early year). Each such sentence adds weight to the denominator only, dragging the ratio down. Fabrication is therefore self-diluting: the more a person invents, the better they score, provided the inventions are of the kind the tool cannot check — which is all of them.

**Evidence:** larp_meter/scoring.py:22-26 `trig_w = sum(...)` / `pass_w = sum(...)` / `decided_w = trig_w + pass_w` / `larp = round(100 * trig_w / decided_w) if decided_w else 0`.
larp_meter/scoring.py:11-16 LEVELS cut at 20/40/65.
PASSED-on-self-assertion branches: flags.py:230 (flag 5), flags.py:327 (flag 8), flags.py:344-346 (flag 9), flags.py:373 and :387 (flag 10), flags.py:463 (flag 12).

**Fails on:** A hype-heavy fabrication ("visionary thought leader pioneering revolutionary disruptive groundbreaking cutting edge quantum AI... Building the next generation platform. Seeking investment now. Signed an MoU and a letter of intent...") scored **RED, 100/100**. Appending four sentences of pure additional fabrication — a fake Delft PhD, fake "featured in Forbes and covered by Reuters", a fake joint development contract, fake 900 customers — moved the identical text to **YELLOW, 25/100**. Nothing was removed and nothing was substantiated; two verdict levels were bought with four invented sentences.

**Fix direction:** Weight the denominator by evidential strength: a flag PASSED purely on the subject's own text should not offset a TRIGGERED flag at parity. Consider separating "passed on self-assertion" from "passed on external evidence" and only letting the latter dilute, or cap the dilution contribution of self-asserted passes.

---

### Standard CV layout defeats extraction wholesale and yields INSUFFICIENT DATA

The role, ownership, partnership and degree-institution regexes all require prose connectives that ordinary CV formatting does not use. ROLE_RE demands `(of|at|@)` between title and company; OWNED_ORG_RE demands the same; PARTNER_ORG_RE demands the literal word "partnership/collaboration... with"; DEGREE_RE only binds an institution across `,`, `at` or `from`. A CV written the normal way — "Chief Technology Officer, Helios Photonics (2019-present)", "PhD Astrophysics - Institute of Advanced Photonic Systems", partners as a comma list under a PARTNERSHIPS heading — produces zero role claims, zero owned_org claims, zero partnership claims, zero traction claims and zero degree_institution claims. Coverage collapses below MIN_COVERAGE and the tool returns a non-committal verdict. This requires no knowledge of the tool at all; it is what a CV looks like.

**Evidence:** larp_meter/extract.py:99-101 ROLE_RE `...\b\s*(?:of|at|@)\s+([A-Z]...)`.
larp_meter/extract.py:87-90 OWNED_ORG_RE requires `(?:of|at|@)`.
larp_meter/extract.py:93-97 PARTNER_ORG_RE requires `partner(?:ship|ed|s)?|collaborat\w+|mou|...` followed by `with|between`.
larp_meter/extract.py:83 the institution group `(?:\s*(?:,|\bat\b|\bfrom\b)\s*(?P<inst>...))?` — a dash or newline does not bind.
larp_meter/scoring.py:18 `MIN_COVERAGE = 0.35`, scoring.py:28 `scored = coverage >= MIN_COVERAGE`.

**Fails on:** A conventionally formatted fabricated CV (three invented jobs, two invented degrees from two invented institutions, six name-dropped defence primes as partners) extracted only: 2 bare degrees ("PhD", "MSc" — the fields were dropped), 2 `mentioned_institution` entries, and 4 years. No roles, no partnerships, no traction. Verdict: **INSUFFICIENT DATA, coverage 29%** — precisely the non-committal outcome a fabricator wants. Routing it through the real `cmd_text` path did not help: `is_linkedin_paste` returns True on the bare EXPERIENCE/EDUCATION headings, and the normaliser mangled it further (it dropped two of the three jobs and merged a bullet into the company field), still producing INSUFFICIENT DATA at 29%.

**Fix direction:** Accept line-structured input: treat newline, dash, en-dash, pipe and tab as valid title/org and degree/institution separators, and treat a comma-separated list under a partners/clients heading as partner claims. Add a fixture set of real-world CV layouts (dash-separated, tab-separated, two-column) to the test suite — the current tests exercise prose almost exclusively.

---

### "No Independent Validation" passes on the subject's own words about themselves

`f_validation` scans the subject's own text for the names of press outlets and for validation phrases, and returns PASSED on either. `outlets = find_terms(ctx.text, b["press_outlets"])` is a plain word-boundary match against the profile the subject wrote. Typing the word "Forbes" satisfies a flag whose stated question is "Any third-party coverage not originating from the subject?" — the one flag in the battery specifically meant to distinguish an echo chamber from real outside attention. No URL, citation, date or corroboration is required.

**Evidence:** larp_meter/flags.py:355-356 `markers = find_terms(ctx.text, b["external_validation"], ...)` / `outlets = find_terms(ctx.text, b["press_outlets"], ...)`.
larp_meter/flags.py:369-373 `if outlets or independent:` -> `return FlagResult(PASSED, f"Third-party validation present{note}.", ev)`.
larp_meter/flags.py:386-387 `if markers: return FlagResult(PASSED, f"Claims third-party recognition ...")` — the description says "Claims", yet it is scored as a pass.
Banks at larp_meter/matching.py:236-246: `external_validation` = ["featured in", "awarded", "keynote", ...]; `press_outlets` = ["techcrunch", "forbes", "wired", "reuters", "nature", ...].

**Fails on:** In my fabricated run, the sentence "His work has been published in Nature and featured in Forbes and IEEE Spectrum" — entirely invented, no link, no article title, no date — produced flag 10 PASSED: "Third-party validation present." Adding "was awarded the Kessler Prize in 2019" (a prize that does not exist) is equally free. Every fabricator writes exactly these sentences without any intent to game the tool.

**Fix direction:** Outlet and award mentions inside the subject's own text are claims, not validation — they should be UNKNOWN at best, or TRIGGERED when strong claims of coverage appear with no resolvable citation. Reserve PASSED for `independent` source URLs or the `wikipedia_about_subject` signal, which are the only genuinely external inputs this flag receives.

---

### [FIXED] GitHub and ClinicalTrials verification check existence only and never call the attribution path

`verify_doi`, `verify_arxiv` and `verify_patent` all end in `self._attribute(...)`, which is what produces MISMATCH when a real artifact does not list the subject. `verify_github` and `verify_nct` never call it. Both set `claim.status = VERIFIED` unconditionally the moment the registry confirms the object exists. So a repository or clinical trial belonging to anyone at all counts as the subject's own verified output — and this is true even when `--name` is supplied, so the documented "existence is not attribution" guarantee simply does not hold for two of the six identifier types.

**Evidence:** larp_meter/verify.py:253-261 `if is_repo:` ... `claim.status = VERIFIED` / `claim.detail = (f"Repo exists: {stars} stars, ...")` — no name comparison anywhere in the branch.
larp_meter/verify.py:262-266 the user branch: `claim.status = VERIFIED` / `f"GitHub user '{path}': {repos} public repos, ..."`.
larp_meter/verify.py:319-321 `claim.status = VERIFIED` / `f'Registered trial "{title[:70]}" — {overall}'`.
Contrast larp_meter/verify.py:209 (`self._attribute(claim, authors, ...)`), :233, :300, :407.
Confirmed by introspection: `'_attribute' in Verifier.verify_github.__code__.co_names` -> False; same for `verify_nct`; True for `verify_doi`.
larp_meter/verify.py:8-10 states the opposite as a design rule: "Existence is not attribution."

**Fails on:** Writing "Reference implementation: github.com/tensorflow/tensorflow" extracts a github claim for `tensorflow/tensorflow`, which verifies as VERIFIED ("Repo exists: N stars..."). That single line flips flag 11 from UNKNOWN to PASSED (2.5 weight) and flag 6 to PASSED (1.5 weight) — 4.0 of 17.0 total weight moved into the pass column, and the ORANGE floor is now not merely disarmed but actively contradicted. Any real NCT number copied from clinicaltrials.gov does the same for a fake clinical career.

**Fix direction:** Route GitHub through `_attribute` using the repo owner login, contributor list and the user's `name` field; route NCT through the trial's sponsor/investigator fields. Where a registry genuinely exposes no attributable names, return UNCHECKABLE rather than VERIFIED, matching the ORCID/patent handling.

---

### --verify without --name marks every artifact VERIFIED regardless of who wrote it

`_attribute` short-circuits when no subject name was supplied: it sets VERIFIED and appends "Pass --name to check attribution" to the detail string. The status field — the only thing the flags read — records a clean pass. `--name` is optional and, in text mode, defaults to `args.name or profile_name`, which is None for any input that is not a recognised LinkedIn paste. The CLI prints a note about this, but a printed note does not alter the score, and the note is suppressed under `--quiet` and `--json`.

**Evidence:** larp_meter/verify.py:176-179 `if not self.subject_name:` / `claim.status = VERIFIED` / `claim.detail = f"{label} exists ({shown or 'no names listed'}). Pass --name to check attribution."`
larp_meter/cli.py:81 `subject_name = args.name or profile_name`.
larp_meter/cli.py:84-86 the warning is gated on `not args.quiet` and is advisory only.
larp_meter/cli.py:415 `--name` is an optional behaviour flag.
Verified directly: `Verifier('.', subject_name=None)._attribute(claim, ['Someone Else Entirely','Another Person'], ...)` -> status VERIFIED.

**Fails on:** `larp-meter.py --text "<bio citing 10.1038/nature12373 and three other real DOIs>" --verify` with no `--name`: all four papers resolve VERIFIED, flag 11 returns "All 4 checked identifier(s) confirmed by their registries" (PASSED, 2.5 weight), flag 6 PASSED. The subject wrote none of them. Copying four DOIs out of a real researcher's publication list is the single highest-leverage thing a fabricator can do, and it requires no understanding of the tool — attaching DOIs to a fake publication list is what makes the fake list look credible to humans too.

**Fix direction:** Without a subject name, attribution is unanswerable, so the correct status is UNCHECKABLE, not VERIFIED — that keeps it out of the score instead of crediting it. Alternatively make `--name` required whenever `--verify` is passed.

---

### Web mode finds real registry identifiers and discards them before extraction

The `Crossref` provider resolves the subject by name and builds `Finding(f"https://doi.org/{doi}", title, ...)` (providers.py:236-242), and `OpenAlex` returns an `orcid` field into signals (providers.py:207). But the text handed to the pipeline is `Gathered.corpus` (providers.py:65), which joins `f.as_text()` — and `as_text` is `f"{self.title}. {self.snippet}"` (providers.py:46-47), which never includes `f.url`. The DOI survives only in `used_urls`, which `run_audit` passes as `source_urls` (cli.py:107) where it is consumed solely by flag 10's independence check (flags.py:357-359). Since `claims = ex.extract_claims(text)` (audit.py:23) sees only the corpus, a DOI the tool itself just retrieved from Crossref is never extracted as a `doi` claim and never verified. The `orcid` in the OpenAlex signal is likewise never turned into a claim. Web mode's own discoveries cannot reach its own verifier.

**Evidence:** providers.py:46-47 `def as_text(self): return f"{self.title}. {self.snippet}".strip()`; providers.py:65 `return "\n".join(f.as_text() for f in self.findings if f.about_subject)`; providers.py:240 Finding url = `https://doi.org/{doi}`; providers.py:207 `"orcid": a.get("orcid")`; audit.py:23. Measured with a stubbed Crossref response containing DOI 10.1109/TMI.2019.1234567: `finding url: https://doi.org/10.1109/TMI.2019.1234567`, `corpus text: 'Gradient amplifier thermal modelling. authors: Jan de Vries'`, `DOI in corpus?: False`, `claims from corpus: []`.

**Fails on:** `larp-meter.py "Jan de Vries" --verify --name "Jan de Vries"` — Crossref returns five real papers with DOIs authored by the subject. Those DOIs go into `source_urls`, the corpus keeps only the titles, extraction yields zero `doi` claims, and flag 11 reports "No claim carries an identifier that a registry could confirm or refute" while the tool is literally holding five resolvable DOIs. The attribution check in `_attribute` (verify.py:164-189) — the tool's strongest signal — never runs on evidence the tool already fetched.

**Fix direction:** Include `f.url` in `as_text()` (or add the provider-supplied DOIs/ORCIDs directly as pre-populated `Claim` objects before `verify_all`) so identifiers discovered by providers are extracted and then verified. Cheapest correct form: have `providers.gather` return a list of hard identifiers alongside `signals`, and have `run_audit` merge them into `claims` before the verification pass.

---

### Employment, job titles and employment dates are neither extracted nor verifiable

`ROLE_RE` (extract.py:99-101) only matches a closed list of C-suite/founder titles — `CEO|CTO|President|Founder|Co-founder|Chairman|Managing Director|Head of X` — followed by `of|at|@`. Ordinary professional titles produce no claim at all: no `role` claim, no employer claim, no employment-date claim. There is also no employment verifier anywhere in `HANDLERS` (verify.py:415-419). Employment is the single most commonly falsified item on a professional profile and the tool has no representation for it whatsoever — it is not merely unverified, it is invisible to the claim ledger, so it does not even appear in the report as something a human should check by hand. `TRACTION_RE` (extract.py:106-109) is similarly gated on a closed noun list, so "1.2 million patient scans" and "30 countries" also vanish.

**Evidence:** extract.py:99-101 `ROLE_RE = re.compile(r"\b(CEO|CTO|President|Founder|Co-founder|Chairman|Managing Director|Head of [A-Z]\w+)\b\s*(?:of|at|@)\s+...")`; extract.py:106-109 `TRACTION_RE` noun list `(customers|clients|users|subscribers|revenue|arr|mrr|employees|units|installations)`; verify.py:415-419 contains no employment handler. Measured on the trace profile: the full claim dump contains **zero** `role` claims despite "Senior Staff Engineer at Philips Healthcare", "four years at ASML as a systems engineer", and "technical lead on a joint programme with Karolinska Institutet"; the only traction claim captured is `'400 installations'`.

**Fails on:** A subject who has never worked at Philips writes "Senior Staff Engineer at Philips Healthcare, Eindhoven" and "Before Philips I spent four years at ASML as a systems engineer." Both fabrications produce zero claims, appear nowhere in the claim ledger or the report, and cost the profile nothing. Meanwhile flag 2 ("Experience ≠ Declared Title", weight 1.5) returns UNKNOWN — "No senior title tied to a specific domain to test" — because the fabricated title is not in the C-suite list, so the fabrication also *lowers coverage*, pushing the profile toward INSUFFICIENT DATA rather than toward scrutiny.

**Fix direction:** Add a general `role`/`employer` extractor (title + preposition + capitalised org, with a stopword guard) emitting `employment` claims with date ranges, and record them as UNCHECKED-by-design in the ledger so the report tells the reader these are the claims a human must verify. Optionally verify employer *existence* against ROR/Wikidata/Crunchbase-free sources, which is weak but non-zero, and surface the employment claims in the "Read this before acting" block.

---

### Crossref already returns preprint status, retraction links and citation counts — the verifier throws them away

`verify_doi` fetches the full Crossref work record with no `select` filter, so `type`, `publisher`, `member`, `is-referenced-by-count`, `relation` and `update-to` all arrive in the response body. The code reads only `title` and `author`. The result is that the tool can confirm a DOI resolves and names the subject, but cannot distinguish a peer-reviewed article from a preprint, a live paper from a retracted one, or a heavily cited work from one with zero citations. These are the three questions a 'published researcher' claim actually turns on, and answering them costs zero extra API calls. OpenAlex (already a dependency, providers.py:174) exposes `is_retracted` and `primary_location.source.is_in_doaj` on the work object for the same purpose.

**Evidence:** larp_meter/verify.py:196 `url = f"https://api.crossref.org/works/{urllib.parse.quote(claim.value)}"` — no `select` parameter, so the whole record is fetched and cached. Lines 209-212 consume it: `title = (msg.get("title") or ["untitled"])[0]` / `authors = [...]` / `self._attribute(claim, authors, f'Paper "{title[:70]}"', url)`. Nothing else in the file references `msg`. Meanwhile extract.py:70 records `peer[\s-]reviewed` as a SOFT_EVIDENCE `assertion` that no verifier ever adjudicates (it is absent from Verifier.HANDLERS, verify.py:422-426), and flags.py:263-264 sinks such assertions into UNKNOWN: "Only unsourced assertions of output ('peer-reviewed') — no identifiers to check." Note also verify.py:34-35: the User-Agent carries a `+https://` URL but no `mailto=`, which is what Crossref's polite pool actually keys on.

**Fails on:** "Peer-reviewed work on COVID transmission — 10.1101/2020.03.22.20040758." That prefix is medRxiv. Crossref returns it with `type: "posted-content"`, `subtype: "preprint"`, and the subject genuinely is an author, so `_attribute` returns VERIFIED and flag 11 reports "All 1 checked identifier(s) confirmed by their registries." The peer-review claim — the actual falsehood — is never touched. The same silence covers a retracted paper still listed as a career highlight.

**Fix direction:** In `verify_doi`, branch on `msg.get("type")`: `posted-content` should verify authorship but downgrade any co-occurring peer-review assertion, and `msg.get("update-to")` / `relation.is-retracted-by` should raise a distinct RETRACTED detail. Surface `is-referenced-by-count` in the detail string so "seminal paper" claims can be read against 0 citations. Add `mailto=` to the UA for the polite pool. For retraction specifically, prefer OpenAlex `https://api.openalex.org/works/doi:{doi}` → `is_retracted`, since Crossref's retraction linkage is only as good as the publisher's deposit.

---

### ORCID is used as a name lookup only — /works, /employments and /educations are free, keyless, and unread

Both ORCID call sites fetch `/person` and extract given+family name. The same host, same v3.0 API, same no-auth public endpoints expose `/works` (the subject's own claimed publication list), `/employments` and `/educations` (affiliation records, each carrying a `source` attesting who asserted it — when an institution asserted it via the member API, that is institutional confirmation, not self-report). This is the single largest new capability available per unit of work in the whole codebase: two extra GETs against a host already integrated, no new auth, no new parsing idiom, and it converts the two claim classes the tool currently cannot check at all — employment history and degree-to-person binding — into checkable records. Today ROR can only confirm that a university exists (verify.py:327-381); nothing anywhere links the subject to it.

**Evidence:** larp_meter/verify.py:216 `url = f"https://pub.orcid.org/v3.0/{claim.value}/person"`, lines 226-236 read only `name.given-names` / `name.family-name` and call `_attribute(claim, [full] if full else [], "ORCID record", url)`. Identically in larp_meter/profiles.py:213 `body = fetch(f"https://pub.orcid.org/v3.0/{ref.handle}/person")` — profiles.py:196-202 builds a `facts` dict for GitHub (repos, followers, account_created) but the ORCID reader at 223-231 populates nothing beyond name and biography. Consequence in flags.py:290-338: `f_credentials` can only ever report "Degree tied to a named institution … not itself checked against a registry" (line 336) or a ROR hit on the institution's mere existence (line 330-335).

**Fails on:** "PhD, Karolinska Institutet. 60 peer-reviewed publications. ORCID 0000-0002-XXXX-XXXX." The ORCID name matches the subject, so the record verifies. The tool never sees that the same ORCID's /works lists 3 items and its /employments contains no Karolinska affiliation. Flag 8 PASSES (institution exists in ROR), flag 11 PASSES, flag 6 PASSES. Every element of the inflation survives a `--verify` run.

**Fix direction:** Add `verify_orcid_record` fetching `/works` and `/employments`+`/educations` after the name match succeeds. Emit a new claim-derived signal: works_count from ORCID vs. any numeric publication count in the text; and cross-check `degree_institution` claims against `educations[].organization.name` with the existing `_significant_tokens` org matcher (verify.py:68-72). Keep the asymmetry honest — ORCID is self-curated, so absence of an affiliation is UNCHECKABLE-grade, while a *contradicting* institution list is a genuine MISMATCH only when the record is institution-sourced.

---

### No external time anchor exists anywhere — the timeline flag compares the profile against itself

Flag 12 is the tool's only temporal test, and both of its inputs are strings the subject wrote. It can catch internal arithmetic inconsistency and nothing else. Two keyless, unrate-limited, well-documented HTTP endpoints would give it an outside anchor: RDAP (`https://rdap.org/domain/{domain}`, JSON, IETF-standard, no key, replaces WHOIS) returns the domain registration date, and the Wayback CDX API (`http://web.archive.org/cdx/search/cdx?url={domain}&output=json&limit=1`) returns the first archived snapshot. Together they answer "did this organization exist before date D" for any subject with a website — including the non-academic subjects README:216 concedes the tool currently scores at 0% coverage. Value per unit of work is the highest of any genuinely new source here: two GETs, no parsing beyond one JSON field each, and applicable to plumbers and consultancies as well as researchers.

**Evidence:** larp_meter/flags.py:445-474 `f_timeline`. Line 446 `exp_claims = ex.claims_by(ctx.claims, "timeline", "claimed_experience_years")` and line 450 `years = sorted({int(c.value) for c in ex.claims_by(ctx.claims, "timeline", "year")})` — both come from `extract_claims` over the profile text (extract.py:236-245). The only comparison against reality is `future = [y for y in years if y > ctx.now_year]` (line 455), i.e. against the system clock. Line 472-473: `if parsed and years: return FlagResult(PASSED, "Claimed durations are consistent with the dates given.")` — 'the dates given' is the point. No domain, URL host, or founding date is fetched anywhere: `Verifier.HANDLERS` (verify.py:422-426) has no URL/domain subtype, and `ALL_PROVIDERS` (providers.py:274) is Wikipedia/OpenAlex/Crossref/DuckDuckGo only.

**Fails on:** "Helios Robotics, founded 2016. Twelve years of experience in autonomous systems. 40 customers, €2.1M revenue. heliosrobotics.io" — self-consistent (2026-2016=10, 12 ≤ 10+3 slack), so flag 12 returns PASSED, 'Claimed durations are consistent with the dates given', contributing 1.5 weight of PASS. One RDAP call would show the domain registered four months ago and no Wayback snapshot before this year.

**Fix direction:** Extract bare domains/URLs as a `web_presence` claim subtype, add a `verify_domain` handler doing RDAP + Wayback CDX, and feed the earliest external date into `f_timeline` as a third input alongside stated years. Guard the inference: a company can predate its current domain (rebrand, acquisition), so a young domain against an old claim is a YELLOW-grade discrepancy to report, never a NOT_FOUND-grade contradiction — the same reasoning verify.py:372-379 applies to ROR absence.

---

### openFDA is free and keyless, but the code asserts regulatory claims cannot be checked without a key

The comment above SOFT_EVIDENCE states that FDA/CE clearance claims are 'checkable in principle, but not via a free API'. That is factually wrong for the FDA half: api.fda.gov requires no key (240 req/min, 1000/day per IP; a free key raises it), is officially maintained, and exposes `/device/510k.json`, `/device/pma.json`, `/device/classification.json`, `/drug/drugsfda.json` and `/device/recall.json` — all searchable by `applicant` or `device_name`. 'FDA-cleared' is one of the highest-value lies in the medtech-founder genre precisely because it sounds falsifiable and nobody checks. Because of that wrong comment, the claim is captured as an inert `assertion` that no handler ever touches and that actively *lowers* coverage.

**Evidence:** larp_meter/extract.py:66-72: `# Claims of regulatory clearance — checkable in principle, but not via a free API` followed by `SOFT_EVIDENCE = [(re.compile(r"\b(?:FDA|CE)[\s-](?:cleared|approved|marking|marked|certified)\b", re.I), "regulatory clearance"), …]`. Emitted as subtype `assertion` at extract.py:196-199 (`add("artifact", "assertion", label, …)`). `assertion` is not a key in Verifier.HANDLERS (verify.py:422-426), so verify_all counts it into `self.skipped` (verify.py:431-433) and no registry is contacted. flags.py:263-264 then returns `FlagResult(UNKNOWN, "Only unsourced assertions of output (e.g. 'peer-reviewed') — no identifiers to check.")`. A 510(k) number is not extracted either: ARTIFACT_PATTERNS (extract.py:57-64) has no `K\d{6}` or `P\d{6}` pattern.

**Fails on:** "Our FDA-cleared continuous ECG patch is deployed in 12 hospitals." One `assertion` claim, never verified, flag 6 → UNKNOWN, coverage drops by 1.5 weight, and the strongest checkable claim in the profile is treated as unfalsifiable. A single GET to `api.fda.gov/device/510k.json?search=applicant:"Helios+Medical"` returns either the K-number, decision date and device name, or an empty `results` with `error.code: NOT_FOUND`.

**Fix direction:** Add `K\d{6}` / `P\d{6}` / `DEN\d{6}` to ARTIFACT_PATTERNS and a `verify_510k` handler; separately, when a `regulatory clearance` assertion co-occurs with an `owned_org`, query openFDA by applicant name and report hit/miss as a lead rather than a contradiction (device clearances are held by companies, and applicant names drift after acquisitions). Correct the comment on extract.py:66 — leaving a wrong 'not possible' note in the source is what keeps the gap closed. CE marking genuinely has no equivalent (EUDAMED's public API is partial); keep that half as an assertion and say so.

---

### No biomedical literature source, and PMIDs are not even extracted

The artifact patterns cover DOI, arXiv, ORCID, GitHub, NCT and patents. PMID and PMCID — the identifiers every clinician, biologist and pharma researcher actually pastes into a CV — are absent, so a medically-oriented profile can list twenty publications and produce zero artifact claims. Europe PMC's REST API (`https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID:{pmid}&format=json&resultType=core`) is keyless, stable, versioned, generously rate-limited, covers PubMed plus preprint servers plus patents citing literature, and returns author lists, journal, and an explicit retraction flag in one call. NCBI E-utilities is the alternative but is stricter (3 req/s without a key) and returns XML. Note also that arXiv IDs are only matched inside a URL, so the canonical `arXiv:2401.12345` citation form is missed entirely.

**Evidence:** larp_meter/extract.py:57-64 ARTIFACT_PATTERNS — six entries, none matching `PMID:?\s*\d{7,8}` or `PMC\d{6,8}`. Line 59: `("arxiv", re.compile(r"arxiv\.org/abs/(\d{4}\.\d{4,5})", re.I))` requires the URL form; a bio writing `arXiv:2401.12345` yields nothing. Downstream, flags.py:236-238 `artifacts = ex.claims_by(ctx.claims, "artifact")` / `hard = [c for c in artifacts if c.subtype != "assertion"]`, and with `hard` empty the flag falls to TRIGGERED (line 258-262) if any building_claims term is present, or UNKNOWN (line 265). extract.py:33-38 EMITTED_SUBTYPES confirms the closed set. README:216 documents the resulting blind spot for non-CS professions.

**Fails on:** A physician's CV: "Selected publications: PMID 28460551; PMID 31978945; PMID 33301246. Currently developing a sepsis prediction model." extract_claims returns zero artifacts; flag 6 sees `building` ('developing') with no hard artifact and TRIGGERS "cites no checkable artifact — no DOI, patent number, repository, trial registration or certification appears anywhere" — a false accusation produced by a missing regex, against a subject who supplied three checkable identifiers.

**Fix direction:** Add PMID/PMCID patterns and a `verify_pmid` handler against Europe PMC, routing `authorList` through the existing `_attribute()`. Also relax the arXiv pattern to `arXiv:\s*(\d{4}\.\d{4,5})` alongside the URL form. Europe PMC's `core` resultType also returns `commentCorrectionList` with type `Retraction`, giving retraction detection for the biomedical corpus at no extra cost.

---

### Companies and employers are never checked against any registry — the entire relationships category runs on the subject's own text

Four claim subtypes concern legal entities — `owned_org`, `leadership`, `partner_org`, `mentioned_institution` — and none has a handler. The exclusion of `mentioned_institution` is deliberate and correctly reasoned (ROR indexes research orgs), but the conclusion drawn was 'therefore check nothing', not 'therefore use a company registry'. Three flags worth 4.0 combined weight adjudicate corporate relationships purely by reading the text back to itself. Realistic keyless options, ranked by actual availability: (1) GLEIF — `https://api.gleif.org/api/v1/lei-records?filter[entity.legalName]=X`, genuinely keyless JSON:API, returns legal name, registration authority ID, status ACTIVE/LAPSED and jurisdiction, but only for entities that needed an LEI; (2) SEC EDGAR — `https://efts.sec.gov/LATEST/search-index?q=` full-text and `https://data.sec.gov/submissions/CIK*.json`, keyless and official, and Form D filings directly test 'we raised $X'; (3) EU VIES VAT check, keyless, returns registered name+address when a VAT number is present; (4) Wikidata `wbsearchentities`+`wbgetentities`, keyless, covers notable firms with inception date (P571), founder (P112), employee count (P1128). Be sceptical of OpenCorporates: its open API is gone, current access is key-gated and commercially licensed, so it does not fit this codebase's zero-friction posture. UK Companies House and Dutch KVK are free but key-required.

**Evidence:** larp_meter/verify.py:422-426 `HANDLERS = {"doi": …, "degree_institution": "verify_institution"}` — no org subtype. The preceding comment, verify.py:419-421: "`mentioned_institution` is deliberately absent: those are employers and venues, and ROR indexes research organizations, so an ordinary company's absence would manufacture a finding out of nothing." Subtypes produced but unverified: extract.py:223-227 `add("role", "owned_org", …)`, `add("partnership", "partner_org", …)`, extract.py:220-221 `add("role", "leadership", …)`. The dependent flags: flags.py:175-186 `f_self_referential` (weight 2.0) operating on `ex.owned_and_partner_orgs(ctx.claims)` — a pure string-overlap test between two lists the subject wrote (extract.py:270-278); flags.py:344-357 `f_logo_wall` (weight 1.0) counting `distinct = sorted({ex.norm_org(p) for p in partners})`.

**Fails on:** "Founder of Helios Robotics BV. Strategic partnership with Siemens Mobility, ESA and Port of Rotterdam." Flag 3 returns UNKNOWN ('no ownership information to cross-check'), flag 9 returns PASSED ('Only a handful of partners named'), flag 5 returns PASSED if the word 'contract' appears anywhere. Neither the existence of Helios Robotics BV nor any of the three partnerships is tested against anything. The Belgian/Dutch company register would show no such BV; GLEIF would show no LEI.

**Fix direction:** Add an `owned_org` handler that tries GLEIF first (keyless, authoritative where present) and Wikidata second, and report on the same three-state discipline already used for ROR: found → VERIFIED with jurisdiction and status, absent → NOT_FOUND phrased as a lead (verify.py:375-379 is the model), unreachable → UNCHECKABLE. Wire a jurisdiction hint from the org suffix already parsed at extract.py:163-164 (`gmbh|ltd|llc|inc|bv|nv|sa|ag|plc`), since the suffix names the registry to consult. Do not add OpenCorporates on the assumption it is free.

---

### Award and press claims satisfy the independent-validation flag on the subject's word alone

Flag 10 is the tool's validation dimension, and its fallback branch returns PASSED when the text merely contains phrases like 'awarded', 'featured in' or 'keynote' — no URL, no source, no lookup. So the cheapest possible fabrication (three adjectives) clears the flag that exists to detect exactly that. This is a datasource gap as much as a logic one: there is no source in the chain that can adjudicate an award or press claim, so the flag has nothing to fall back on but the text. Wikidata (P166 award received, P1411 nominated for) is keyless and covers named prizes; a host-scoped search against the `press_outlets` bank would test 'featured in TechCrunch'; and Wikipedia is already integrated (providers.py:143-171) but its result is only consulted for articles *about* the subject.

**Evidence:** larp_meter/flags.py:363-403 `f_validation`. Line 365 `markers = find_terms(ctx.text, b["external_validation"], skip_negated=True)`; lines 396-397: `if markers: return FlagResult(PASSED, f"Claims third-party recognition ({', '.join(markers[:3])}).", markers[:3])`. The bank, matching.py:236-240: `"external_validation": ["featured in", "as seen on", "interviewed by", "published in", "recognized by", "awarded", "award winner", "keynote", "covered by", "profiled in", "cited by", "shortlisted for"]`. `press_outlets` (matching.py:241-246) is likewise matched as a *word in the text* at line 366, not as a source that was consulted. The only real check is the Wikipedia signal at flags.py:374-378, which requires an article titled with the subject's name.

**Fails on:** Text mode on "Award-winning founder, featured in Forbes and TechCrunch, keynote speaker at three summits" with no links at all: `markers` = ['featured in', 'awarded'…] and `outlets` = ['forbes','techcrunch'], so line 379-383 returns PASSED, 'Third-party validation present', and flag 10's full 1.0 weight lands in the PASS column. The tool rewards naming a magazine over citing one.

**Fix direction:** Demote the bare-marker branch to UNKNOWN when no URL, DOI or provider finding corroborates it — an assertion of validation is not validation, which is the same principle already enforced for artifacts at flags.py:263-264. Then add the sources that can decide it: Wikidata P166 for named awards, and a host-restricted query for each matched `press_outlets` term. The existing `about_subject` discrimination in providers.py (Finding.about_subject, lines 44/166/266) is the right mechanism to reuse.

---

### [FIXED — nightly/2026-08-23] DEGREE_RE's re.I defeats the capitalisation anchors, so the institution sent to ROR is corrupted prose

`_INSTITUTION_CORE` relies on `[A-Z]` to bound institution names, but it is interpolated into `DEGREE_RE`, which is compiled with `re.I`. Under IGNORECASE, `[A-Z][\w-]*` matches lowercase words, so the optional trailing group runs past the real name into the following prose. The corrupted string is stored as the `degree_institution` claim, sent verbatim to ROR (which of course has no such organisation), and then printed to the user as the flag's evidence — an institution name the subject never wrote. A second failure mode in the same pattern truncates real names: the trailing group only continues across a connector word ('of', 'de', 'van'…), so 'Technische Universität München' is cut to 'Technische Universitat' and 'Universiteit Gent' to 'Universiteit'. Note `INSTITUTION_RE` at extract.py:90 is compiled WITHOUT re.I and extracts the same string correctly as `mentioned_institution`, which is what makes the discrepancy visible in the report.

**Evidence:** larp_meter/extract.py:86-88 (`_INSTITUTION_CORE`, capital-anchored) interpolated at extract.py:102 into DEGREE_RE, closed with `re.I` at extract.py:103. Measured on 'She earned an MBA from Rotterdam School of Management and a BSc in Industrial Engineering.': claims are `('degree_institution', 'Rotterdam School of Management and a')` alongside a correct `('mentioned_institution', 'Rotterdam School of Management')`. Full audit output: flag 8 TRIGGERED — 'Named institution has no match in the Research Organization Registry: Rotterdam School of Management and a.' Also measured: 'MSc Electrical Engineering, Technische Universitat Munchen, 2014.' → degree_institution 'Technische Universitat'.

**Fails on:** Anyone who writes two degrees in one sentence ('an MBA from X and a BSc in Y') has the first institution mangled into a nonexistent name, which is then reported to the reader as a credential that no registry can confirm — the tool quotes a string the subject never wrote as if it were their claim.

**Fix direction:** Compile the institution sub-pattern case-sensitively (build DEGREE_RE from case-insensitive degree/connector fragments plus an inline `(?-i:...)` block for `_INSTITUTION_CORE`, or match the degree and institution in two passes), and allow the name to continue across non-connector capitalised tokens so 'Technische Universität München' survives intact. Never send a claim value to a registry that a case-sensitive re-scan of the source text does not reproduce.

**[FIXED — nightly/2026-08-23]** The corruption half (this entry's primary harm) is closed, but NOT the way the fix direction above proposed. `(?-i:...)` was tried first and does stop the "and a" overrun — but it also broke a standing invariant the test suite already enforced (`TestDeterminism.test_cosmetic_variation_does_not_move_the_verdict`, `tests/test_round4.py`): this repo deliberately guarantees identical claims for an all-caps or all-lowercase paste of the same profile, and reintroducing case-sensitivity into `_INSTITUTION_CORE` broke that determinism test immediately (an all-caps or all-lowercase "Delft University of Technology" no longer matched `[A-Z]` at all). Caught only because the full suite was run after the change, not just the new tests — the exact failure mode the standing brief's "review across function boundaries" step exists to catch, one regex flag deep instead of one function call deep.

Shipped instead: `_INSTITUTION_CORE`'s trailing connector group keeps re.I (so the whole-document case invariance holds) but the up-to-two-more-words continuation after a connector ('of'/'de'/...) now carries a negative lookahead excluding a short list of function words ('and', 'but', 'or', 'nor', 'with', 'a', 'an', 'the', 'who', 'which', 'that') that can follow an institution mention in prose but are never part of one. `'Rotterdam School of Management and a BSc'` now correctly yields the `degree_institution` claim `'Rotterdam School of Management'`; `'Universidad de Sevilla and Roberto Diaz co-authored...'` yields `'Universidad de Sevilla'`. Verified live through the real pipeline (not just the handler): `run_audit` on the Rotterdam sentence now reports flag 8 evidence as "Degree tied to a named institution (Rotterdam School of Management)" — matching what the subject actually wrote. Full 419→420 test suite green throughout, including the determinism test, which was re-confirmed still passing on all six of its cosmetic variants (trailing space, CRLF, doubled spaces, uppercase, lowercase, no final period) after the fix.

**Deliberately NOT fixed tonight, and confirmed still open:** the second failure mode this entry names — real institution names truncated after the first word when no connector follows ('Technische Universitat Munchen' → 'Technische Universitat', losing 'Munchen'/'München'). Re-measured live: this is NOT specific to `DEGREE_RE`'s re.I leak — `INSTITUTION_RE` (extract.py:90, `mentioned_institution`, already case-sensitive, untouched tonight) produces the identical truncation on the identical input. It is a shared, pre-existing limit of `_INSTITUTION_CORE`'s continuation logic (only continues past the institution-type word across one of the listed connector words, never across a bare adjacent capitalised token), affecting both subtypes equally. Left open as a separate, smaller-severity issue — a truncated-but-still-real name is a weaker false claim than a fabricated one — and is the natural next pick-up if extending this area.
---

### [PARTIALLY FIXED — nightly/2026-09-08, part (b) only] Timeline flag accuses ordinary CVs: recent-roles-only bios and future graduation dates
### [PARTIALLY FIXED] Timeline flag accuses ordinary CVs: recent-roles-only bios and future graduation dates

**Part (a) verified and fixed 2026-09-11.** Confirmed live before touching anything, exactly as this entry describes: `f_timeline` on the bio 'Twelve years designing radiation-tolerant power electronics for satellite platforms. Since 2021 has led the analogue team. MSc in Electrical Engineering.' returned TRIGGERED — 'claims 12 years of experience, but the earliest date anywhere in the profile is 2021 — at most ~5 years are accounted for.' A truthful engineer whose bio, like nearly every real CV, only dates her current role was told her timeline was impossible.

Fixed in `larp_meter/flags.py`'s `f_timeline`: the claimed-vs-available duration comparison now only runs when the earliest dated year is anchored to something that plausibly marks where a career could first have started — the year appears inside a degree/institution claim's own extracted context (an education date), or its own context contains an explicit origin verb (founded/co-founded/founding/established/launched/graduated/started/began) — or when the earliest date already accounts for the claimed duration on its own (nothing to falsify either way). Absent an anchor, the flag now returns UNKNOWN ('a claimed duration cannot be tested against a single date that isn't tied to an education or founding event') instead of TRIGGERED. A genuine contradiction anchored to a real education or founding date (e.g. '30 years of experience in robotics. MSc Robotics, 2020.') still triggers — this narrows the check, it does not disable it.

4 new tests in `tests/test_flags.py::TestTimelineFlag`, written first and confirmed to fail against the pre-fix code (2 for the false-accusation cases, 2 confirming the fix does not silence a genuine education/founding-anchored contradiction). Mutation-tested the new anchor gate directly (forcing it to always pass) — caught by the same two new tests. Full suite: 473 → 477 tests, green throughout. Ran the CLI end-to-end on a hand-written honest veteran bio and a hand-written fabricator bio (`larp-meter.py --file ...`) and confirmed flag 12 reads UNDECIDABLE with the new fair message on the honest sample rather than TRIGGERED.

**Part (b) — the future-graduation-date / de-duplication-key gap — is UNCHANGED and still live**, confirmed by re-running this entry's own repro tonight: `'MSc Computer Science, Technische Universitat Munchen, 2025 - 2027.'` still returns TRIGGERED — 'date(s) stated as past but in the future: 2027' as of tonight, on `master`. A fix for this half already exists on the still-unmerged `nightly/2026-09-08` branch (PR #17, "A current student's own study dates read as a fabricated future claim") — see NIGHTLY.md's open-PR queue note. Did not duplicate that work tonight; the actual remaining step here is merging PR #17, not re-deriving its fix.

Original finding, kept for context: `f_timeline` has two independent false-accusation modes. (a) It compares the largest claimed years-of-experience against `now_year - min(year mentioned in the text)` with only 3 years of slack. A bio that states a long career but dates only current/recent roles — the single most common CV and LinkedIn shape — is declared 'Timeline does not add up'. (b) Any year greater than the current year that lacks a FORWARD_MARKERS cue within the preceding 60 characters is reported as a 'date stated as past but in the future'. Study date ranges ('2025 - 2027'), expected graduation, 'Class of 2027' and multi-year grant/contract end dates all lack a cue, so current students and anyone with a scheduled completion date are flagged. The de-duplication key at extract.py:182-186 is (kind, subtype, value), so the same year emitted once as `year_target` and once as `year` still leaves a bare `year` behind to trip the check.

**Evidence:** larp_meter/flags.py:461-463 — `future = [y for y in years if y > ctx.now_year]` → 'date(s) stated as past but in the future'; flags.py:470-474 — `if claimed > available + 3: problems.append(...)`. Cue detection at extract.py:150-153 and 243-245. Measured, honest bio ('twelve years designing radiation tolerant power electronics … since 2021 has led the analogue team'): flag 12 TRIGGERED — 'claims 12 years of experience, but the earliest date anywhere in the profile is 2021 — at most ~5 years are accounted for'. Measured, student profile ('MSc Computer Science, Technische Universitat Munchen, 2025 - 2027'): flag 12 TRIGGERED — 'date(s) stated as past but in the future: 2027' — overall ORANGE 46/100.

**Fails on:** A master's student writes 'MSc Computer Science, TU München, 2025 – 2027'. The tool returns ORANGE 46/100 with 'Timeline Implausibility: Timeline does not add up: date(s) stated as past but in the future: 2027.' Separately, a 25-year veteran who lists only her last two dated roles is told her stated experience is unaccounted for.

**Fix direction:** For (a): only compare durations against dates when the text plausibly covers the whole career (e.g. an education date exists, or the earliest year is at least `claimed` years back); otherwise return UNKNOWN — an undated early career is missing information, not a contradiction. For (b): suppress the future-date check entirely for years that appear inside a range whose start is past, and treat any future year adjacent to an education/degree claim as an expected completion date rather than a falsified history.

**[PARTIALLY FIXED — nightly/2026-09-08]** Part (b) only, confirmed live on
`master` before touching anything (both measured repros above reproduced
exactly as written). `extract.py`'s `FORWARD_MARKERS` now also recognises
`class of`, and a new `_is_forward_year()` helper additionally exempts the
back half of an ascending `YYYY - YYYY` range (`_RANGE_START_RE`) — "2025 -
2027" no longer trips the future-date check on 2027, and neither does
"Class of 2027". The student-profile repro above now reads `[12] Not enough
dated detail to test the timeline` instead of ORANGE 46/100. The
`year`/`year_target` de-duplication note above (same value, two subtype
keys) is real but turned out not to matter for this fix — the ambiguity
only arises when the *same* year is independently classified both ways
within one document, which none of tonight's fixtures did; worth a look if
a future night finds an actual case of it misfiring.

Part (a) — the recent-roles-only false accusation — is **still fully
open**, and turns out to be a harder design problem than the fix direction
above suggested: I drafted the direction's own proposed gate ("only trigger
when a dated education anchor exists") and it broke an existing,
apparently-intentional test, `test_flags.py`'s
`test_career_slack_is_exactly_three_years`'s second half —
`"21 years of experience in robotics. Founded the lab in 2009."` (expects
TRIGGERED) — that fixture has no degree/education claim at all, only a
"founded" date, and under an education-anchor gate it would flip to
UNKNOWN right alongside the genuine false-accusation case this finding
describes. The two are textually almost identical shapes ("since/founded
YEAR, N years of experience") and neither the anchor-based gate nor a
minimum-dated-years-count gate (also tried, also breaks the same test)
distinguishes them — what actually differs is a semantic one: "founded the
lab" plausibly asserts *that* is the origin of the described career,
whereas "has led the team since 2021" only dates a role change within an
already-established one. Detecting that distinction from text reliably
enough not to trade one false-accusation mode for another needs real
design thought, not a quick heuristic — left for a future night rather
than rushed in under this one's time-box. The live repro above
('twelve years... since 2021 has led the analogue team' → TRIGGERED,
'at most ~5 years are accounted for') is unchanged and still reproduces
on current `master`.

---

### [FIXED] ROR absence is scored as a triggered credential flag despite the code's own disclaimer

**Verified and fixed 2026-09-12.** Confirmed live before touching anything, against ROR's real API (not from docs): `verify_institution` requires that EVERY significant token of the claimed name appear in a single ROR name variant (`wanted <= have`), otherwise NOT_FOUND, and `f_credentials` TRIGGERED on that NOT_FOUND at full weight. Ran six real institutions with exactly the shape this entry names through the tool's own verifier — 'Rotterdam School of Management', 'London Guildhall University' (merged into London Metropolitan in 2002), 'Ecole Superieure d Electricite' (Supélec, merged into CentraleSupélec in 2015), 'Karachi Grammar School', 'Yeshiva Torah Vodaath', 'Ecole 42' — all six returned NOT_FOUND. Then measured whether the token-overlap ROR itself offers against its nearest candidate could separate them from a genuinely fabricated name: it cannot. The six real institutions overlap their nearest ROR hit at 0.25-0.67; a fabricated 'Institute of Advanced Fictional Studies' overlaps at 0.75 — higher than four of the six real ones. There is no threshold on this signal that catches invention without also accusing real institutions, which settles the choice between this entry's two fix-direction options in favour of the first.

Fixed `f_credentials` (`larp_meter/flags.py`): a ROR NOT_FOUND on a `degree_institution` claim now returns UNKNOWN with an advisory note (naming the institution and ROR's own caveat that it indexes research organizations under their current name) instead of TRIGGERED. This is a real narrowing, not a wording change: flag 8 can no longer TRIGGER via this path at all — see the flag's own new comment and README.md's updated row 8 / flag-11 paragraph for why deliberately, given the overlap evidence above shows no safe threshold exists.

Also fixed the "inverse looseness" this entry's own evidence bullet named as the same investigation's other half: `_ORG_STOPWORDS` (`larp_meter/verify.py`) listed 'universite' (the accent-stripped 'université') as a word carrying no identifying information, so 'Universite Paris Sud' reduced to `{paris, sud}` — trivially a subset of ROR's unrelated 'Geosciences Paris Sud', which is not a university. Every other language's word for university/institute/school already folds to a common stem via `_ORG_STEMS` instead of being discarded; 'universite' (and the already-dead, encoding-mismatched 'università' entry alongside it) were the sole exceptions. Removed both; 'universite' now stems to 'univ' like every other spelling.

**Deliberately left open, and now the natural next pick-up for this area:** the other half of the same "inverse looseness" bullet, 'Le Wagon' → VERIFIED as 'Health Wagon', is a different mechanism (a coding-bootcamp name with only one significant token after generic-word stripping, so a single shared word like 'wagon' trivially satisfies the subset test against any registry hit) and was not fixed tonight — narrowing scope to the university-type-word bug this entry's evidence actually demonstrated, rather than also redesigning the single-token case under time pressure. A future night should look at requiring `len(wanted) >= 2` for a subset-match VERIFIED (every institution name in the current test suite's VERIFIED cases produces 2-3 significant tokens, e.g. 'Ghent University' → `{univ, ghent}`, so this guard would not obviously regress them — not exhaustively checked against short legitimately-named real schools generally, which is exactly the risk to weigh before shipping it).

Regression tests: `tests/test_verify.py` (`test_a_non_english_word_for_university_is_not_discarded_as_a_stopword`, plus a paired positive control that a genuine French university still verifies) and `tests/test_flags.py` (`test_a_verified_ror_miss_is_a_lead_not_an_accusation`, replacing the old test that pinned the now-corrected TRIGGERED behaviour, plus a paired `test_an_unchecked_institution_is_not_reported_as_a_ror_miss` guarding the adjacent UNCHECKED path this change did not touch). All confirmed to fail against the pre-fix code and pass against the fix. Full suite: 476 tests, green throughout. Ran the CLI end-to-end (see NIGHTLY.md) on hand-written samples naming RSM Rotterdam and a fabricated institute; both now read UNKNOWN on flag 8 rather than one TRIGGERING and the other not.

Original finding, kept for context: `verify_institution` requires that EVERY significant token of the claimed name appear in a single ROR name variant (`wanted <= have`), otherwise NOT_FOUND. `f_credentials` then TRIGGERS on that NOT_FOUND — its own text concedes 'ROR indexes research organizations, so a small or non-research institution may be absent legitimately', yet the flag still contributes its full weight to the score's numerator rather than returning UNKNOWN. ROR's index is structurally biased toward research-active organisations and toward organisations as they are named TODAY: business schools that are faculties of a parent university, institutions merged or renamed since the subject graduated, religious schools, secondary schools, and coding academies are systematically absent. The person is penalised for their institution's indexing status and for when they graduated.

**Evidence:** larp_meter/verify.py:384-414 — subset test at verify.py:391 `if wanted and wanted <= have`, else NOT_FOUND at verify.py:408-413. larp_meter/flags.py:315-326 — `fake = [i for i in institutions if i.status == ex.NOT_FOUND] ...; return FlagResult(TRIGGERED, ...)`. Live ROR queries through the tool's own verifier returned NOT_FOUND for: 'Rotterdam School of Management', 'London Guildhall University' (real, merged into London Metropolitan University in 2002), 'Ecole Superieure d Electricite' (Supélec, merged 2015), 'Karachi Grammar School', 'Yeshiva Torah Vodaath', 'Ecole 42'. The same run shows the inverse looseness: 'Universite Paris Sud' → VERIFIED as 'Geosciences Paris Sud', 'Le Wagon' → VERIFIED as 'Health Wagon'.

**Fails on:** An RSM Rotterdam MBA holder, or a 1998 graduate of London Guildhall University, is reported under 'Unverifiable Credentials' as: 'Named institution has no match in the Research Organization Registry.' The reader sees a triggered credential flag; the graduate's only offence is that their school is a faculty of a parent university, or that it was merged out of existence after they attended.

**Fix direction:** NOT_FOUND from ROR should decide nothing: return UNKNOWN with an advisory note (the same treatment `verify_github` gives repositories) rather than TRIGGERED, or trigger only when the name also fails a second, non-research-biased source. Relax the strict subset to a high-overlap threshold so faculty/sub-unit and historic names still resolve, and query ROR's historic-name labels explicitly.

---

### [PARTIALLY FIXED] Confidential work and pre-revenue fundraising are scored as deception

`f_output` triggers whenever the text contains a building_claims word ('building', 'developing', 'creating', 'working on') and no public identifier — which describes every engineer whose work is proprietary, classified, under NDA, or simply not academic. `f_fundraising` triggers whenever a funding_ask word appears with no quantified traction — which is the definition of a pre-seed or pre-product raise, and the normal state of deep-tech and biotech companies for years. Neither flag has an escape hatch for a stated reason (an explicit 'covered by customer NDAs' does not suppress f_output), and together they carry 3.0 of the 17.0 total weight. Because the score is a ratio over decided flags only (scoring.py:21-27), a short honest bio decides few flags, so these two alone can dominate the verdict.

**Evidence:** larp_meter/flags.py:239 and 257-262 — `building = find_terms(ctx.text, ctx.banks["building_claims"], ...)` → TRIGGERED 'Claims to be {building[0]} something, yet cites no checkable artifact'. larp_meter/flags.py:272-284 — `if not asks: UNKNOWN … return FlagResult(TRIGGERED, "Actively raising … with no customer, revenue or usage figure of any kind.")`. Bank contents at larp_meter/matching.py:217-230. Measured on a hype-free, factually specific bio (12 yrs radiation-tolerant power electronics, MSc TU Delft, seed round, 'most of her work is covered by customer NDAs and cannot be published'): flags 6, 7 and 12 all TRIGGERED → ORANGE 50/100, 'Significant concerns across weighted flags. Deep due diligence required.'

**Fails on:** A satellite-power-electronics engineer with a real MSc, a real 12-year record and an NDA'd product raising a seed round scores ORANGE 50/100 with zero registry contradictions anywhere in the report. Every triggered flag is a description of her industry, not of her honesty.

**Fix direction:** Make both flags UNKNOWN rather than TRIGGERED when the text supplies a legitimate reason for the absence (NDA/classified/proprietary/stealth for f_output; explicitly pre-product or pre-revenue stage for f_fundraising), and cap their combined contribution so that 'no public artifacts' cannot by itself move a profile past YELLOW without any contradicted claim.

**[PARTIALLY FIXED — nightly/2026-09-01]** Confirmed live, exactly as measured: the NDA'd satellite-engineer bio TRIGGERED both flags before this fix. Implemented the first half of the fix direction only — two new keyword banks, `confidentiality_reasons` (nda, non-disclosure, confidential, proprietary, classified, export controlled, itar, trade secret, stealth mode, ...) and `pre_revenue_stage` (pre-revenue, pre-seed, pre-product, not yet generating revenue, early stage startup, ...) — and both `f_output`/`f_fundraising` now check for a stated reason before returning TRIGGERED, moving to UNKNOWN with an explanatory detail string instead when one is present. A bare building/funding-ask claim with no stated reason still TRIGGERs exactly as before (regression-tested). Re-ran the motivating bio end-to-end: flags 6 and 7 now both read UNKNOWN with the reason quoted back, instead of TRIGGERED.

Deliberately **not done**: the "cap their combined contribution" half of the fix direction — capping flag 6+7's combined weight contribution even when both legitimately TRIGGER (no stated reason, genuinely no output/traction) is a separate, riskier scoring-level change and out of scope for one night. Also not done: quantifying how often a genuine fabricator could now type "stealth mode" or "pre-seed" to blanket-suppress these two flags. That trade-off (a stated reason silences the flag with no cross-check) is the same one the project already made for the LinkedIn-detector narrowing on 2026-08-31 and is consistent with the project's stated preference for missing a fraud over accusing an honest person, but it hasn't been red-teamed specifically for these two banks yet — worth a dedicated look if a future review is hunting for cheap evasions.

Also found, live-reproduced, and NOT fixed while implementing this (see new CRITICAL finding "Word-wrapped negation loses its scope at every bare newline" below): `find_terms(..., skip_negated=True)` treats a single `\n` as a clause boundary, so a negated claim split across an ordinary line wrap ("we are not\nraising a Series A") loses its negation and reads as an active claim. This is a pre-existing bug in `is_negated`/`_CLAUSE_END_CHARS`, unrelated to tonight's two banks, but it was found by hand-testing exactly this kind of fundraising sentence — recorded separately because it's bigger than tonight's slot and touches shared infrastructure every `skip_negated` call depends on.

---

## MODERATE (19)

### No contract and no observability at the extract->verify seam: unhandled subtypes are dropped silently and no test crosses the boundary

The two halves of the pipeline are coupled only by convention. `Claim.subtype` is an unconstrained `str` (extract.py:26) with its permitted values documented in a comment (extract.py:24-25), and `verify_all` filters on `c.subtype in self.HANDLERS` (verify.py:423) and drops everything else without a diagnostic, a counter, or a report field. `verifier_stats` in the report exposes only `api_calls` and `network_failures` (audit.py:77-79), so an operator running `--verify` cannot distinguish "this claim class was checked and came back clean" from "this claim class was never submitted to anything."

The test suite reinforces the gap rather than covering it. Every test that exercises a verifier constructs `Claim(...)` with a literal subtype string by hand; the only two test files that import both `extract_claims` and `Verifier` (test_mutation_guards.py, test_regressions.py) use them in separate test methods and never pipe one into the other. So the seam has zero coverage, which is precisely why the institution handler could go dead across a commit and survive a 17-file, ~120KB test suite plus a 13-agent adversarial review.

Smaller symptom of the same drift: `Verifier._name_matches` (verify.py:160-162) is defined and never called anywhere in the repo — `_attribute` calls `names.name_matches` directly at verify.py:174 — a leftover from an earlier design where the verifier owned name comparison.

**Evidence:** extract.py:22-31 — `subtype: str` with allowed values only in a trailing comment.
verify.py:423 — `checkable = [c for c in claims if c.subtype in self.HANDLERS]`; no else branch, no logging, no counter.
audit.py:77-79 — `"verifier_stats": {"api_calls": verifier.calls, "network_failures": verifier.network_failures}`; nothing records how many claims were skipped as unhandled.
verify.py:160-162 `_name_matches` — repo-wide grep finds the definition and no call site.
Test seam: `Claim(kind=..., subtype=<literal>)` at test_verify.py:39, 45, 56, 65, 114, 126, 138, 150, 160, 171, 188 and test_regressions.py:108, 116, 300; no test in tests/ passes the output of `extract_claims` to `verify_all`.

**Fails on:** An operator audits a candidate with `--verify --name "Jane Doe"` on a CV naming a university, sees `verifier_stats: {api_calls: 0}` alongside a report whose flag 8 reads PASSED and whose `--explain` output states institutions are checked against ROR, and reasonably concludes the credential was checked and cleared. Nothing in the JSON report contradicts that reading: `claim_status_counts` shows `{"UNCHECKED": 6}`, which is indistinguishable in the terminal render from a run where the registries were simply not asked. The same silent-drop mechanism will re-fire the next time extraction renames or splits a subtype — e.g. splitting `github` into `github_repo`/`github_user`, which the code at verify.py:238 already distinguishes internally.

**Fix direction:** Make the seam explicit and observable: define subtype constants in extract.py and import them in verify.py's HANDLERS; add an import-time or first-call assertion that every HANDLERS key is producible by extraction; record `unhandled_subtypes` (with counts) into `verifier_stats` and surface it in the terminal/HTML render so "not checked" is visibly different from "checked and clean"; and add an end-to-end test that runs a fixture bio through `extract_claims` -> `verify_all` against a stubbed `_get`, asserting the exact set of URLs requested. Delete the dead `_name_matches`.

---

### ORCID is queried for a name and nothing else — its employments and educations sections, the exact answer to the tool's central credential question, are never fetched

`verify_orcid` hits `/person`, which returns only the name block, and uses it solely to decide whether the ORCID belongs to the subject. The public ORCID API — same host, same absence of authentication, plumbing already proven — also exposes `/employments` and `/educations`, each entry carrying an organization name, a disambiguated identifier (ROR or GRID), and start/end dates. That is a registry-backed answer to "did this person actually study at X" and "did they actually work at Y", which is the question flags 1, 2 and 8 all try to answer from prose alone. The tool holds an authenticated-by-identifier handle on the subject and asks it one question.

**Evidence:** larp_meter/verify.py:213 `url = f"https://pub.orcid.org/v3.0/{claim.value}/person"`; larp_meter/verify.py:222-233 parse only `given-names`/`family-name` and pass the single joined name to `_attribute`. The consumers that would use affiliations: larp_meter/flags.py:290-328 `f_credentials` works entirely from extracted text claims; larp_meter/flags.py:141-169 `f_experience` from `dom.supporting_domains(ctx.text, "roles", prof)` — text again.

**Fails on:** A profile giving a valid ORCID plus "MSc, ETH Zürich; formerly Senior Scientist at CERN". The ORCID resolves and names the subject, so it is VERIFIED — but the record's own educations section lists a single unrelated institution and no CERN employment. The tool never looks and reports the credentials as unremarkable.

**Fix direction:** Extend `verify_orcid` to also GET `/v3.0/{id}/record` (one call returns person + employments + educations) and cross-check `degree_institution` and `mentioned_institution` claims against the `organization.name` and `disambiguated-organization` values, with date ranges. Treat ORCID affiliations as self-asserted-but-frequently-institution-validated: a match is corroboration, a non-match is a lead, never a MISMATCH on its own — consistent with the existing doctrine at verify.py:167-170.

---

### OpenAlex is used for one boolean, and there is no CS-specific bibliography — the dominant LARP domain has the weakest coverage

The OpenAlex provider builds a rich signal (works count, citations, affiliations, ORCID, and an `ambiguous_identity` count) and exactly one flag reads it, as a truthiness test on `works`. The affiliation list it retrieves is printed as evidence but never compared against any claimed institution. Separately, there is no source specialised for computer science — the field that produces the most "AI researcher" and "ML expert" claims this tool exists to triage. OpenAlex author-matching there is weak precisely where it matters: common names, no ORCID, and OpenAlex author disambiguation is machine-derived, which is why `providers.py` has to guard against a "prolific stranger" by name string alone.

**Evidence:** larp_meter/providers.py:190-213 build `best = {"works", "citations", "institutions", "orcid", "display_name"}`; the only consumer is larp_meter/flags.py:242-249 `scholar = ctx.signals.get("openalex")` / `if scholar and scholar.get("works")` → PASSED. `scholar["institutions"]` is interpolated into an evidence string at larp_meter/flags.py:248-249 and compared to nothing. `crossref_works` (providers.py:243) and `wikipedia_articles` (providers.py:170) have no consumer at all. Author matching relies on `names.name_matches` over a display string — larp_meter/providers.py:192.

**Fails on:** "Leading researcher in transformer efficiency; my work is widely cited." The subject shares a name with a productive chemist. OpenAlex's author search returns the chemist, `name_matches` accepts the display name, flag 6 PASSES on 140 works and 3,000 citations that belong to someone else — and the `ambiguous_identity` signal only fires when two OpenAlex records both match the name, not when the single match is the wrong person.

**Fix direction:** Cross-check `openalex.institutions` against extracted `degree_institution`/`mentioned_institution` claims — the data is already in hand and would turn a decorative evidence string into a real credentials check. Add **DBLP** (`https://dblp.org/search/author/api?q={name}&format=json`, `/search/publ/api`) as a CS-specific source: keyless, stable, and its curated author disambiguation (explicit homonym pages) is materially better than name-string matching for exactly the population that LARPs about AI. Note DBLP throttles under load, so cache and fail soft. Deprioritise **Semantic Scholar**: its unauthenticated tier runs on a shared pool with frequent 429s, and OpenAlex is a coverage superset for this use — it would add rate-limit fragility for little new signal.

---

### Patents rest on a single scraped HTML page with no keyless authoritative fallback

`verify_patent` scrapes `patents.google.com` and pulls inventors out with a regex against a `<dd itemprop="inventor">` element. The code correctly refuses to accuse anyone when the scrape yields nothing, returning `UNCHECKABLE` — but that means the day Google changes its markup, every patent claim in the tool silently degrades to unverifiable while still counting as reduced coverage rather than as a broken source. The extractor matches US, EP and WO prefixes, i.e. three different patent systems, all routed through one scraped consumer surface with no structured fallback.

**Evidence:** larp_meter/verify.py:380-408; the URL at verify.py:382 `https://patents.google.com/patent/{pid}/en`; the parse at verify.py:399-400 `re.findall(r'<dd itemprop="inventor"[^>]*>([^<]+)</dd>', body)`; the self-aware comment at verify.py:395-398 ("Scraped markup, not an API: if Google changes this element every patent claim would silently become a weight-2.5 accusation"). The identifier pattern spanning three systems: larp_meter/extract.py:44 `r"\b((?:US|EP|WO)\s?\d{7,11}(?:\s?[ABC]\d?)?)\b"`.

**Fails on:** A profile citing "US 11,234,567 — my patent on adaptive beamforming" where the subject is not an inventor. If Google's markup has shifted (or the page is served from a bot-mitigation interstitial, which `_get` will happily cache as a 200 body for 30 days per verify.py:32), the result is UNCHECKABLE, flag 11 never sees the mismatch, and the strongest available contradiction is lost — silently, with no signal that the source itself is broken.

**Fix direction:** Be honest that there is no good keyless option here, and pick deliberately. **EPO OPS** (free registration, OAuth2 client credentials, 4GB/month) is the authoritative fix and covers exactly the US/EP/WO span the regex matches; **PatentsView** now also requires a free key, its legacy keyless `api.patentsview.org` endpoint having been retired — so neither preserves the zero-key posture. Adding either means generalising `_get`'s auth, which today hardcodes a single host (verify.py:130-133 `if token and urllib.parse.urlsplit(url).hostname == "api.github.com"`). A keyless partial: **EPO's linked-open-data SPARQL endpoint** (`data.epo.org/linked-data`) covers EP publications with inventor names — useful for EP-prefixed claims only. Minimum viable improvement regardless of source choice: emit a distinct "source is broken" signal when the scrape parses zero inventors across every patent in a run, so a markup drift surfaces as a tool failure rather than as thin coverage.

---

### ROR is the wrong registry for the education question, and no accreditation source distinguishes a small college from a diploma mill

`verify_institution` (once it is actually reachable — see the first finding) consults ROR, which indexes *research* organizations. Flag 8's own text concedes this. The consequence is that ROR returns `NOT_FOUND` identically for a legitimate community college, a vocational academy, a foreign teaching-only university, and an outright diploma mill. The tool therefore cannot answer the one question that matters for credential LARP — is this institution accredited? — and its output on non-research schools is systematically noisy in a way that penalises non-elite and non-Anglophone education. There is also no institution source that covers companies, so `mentioned_institution` (employers) has no correct registry either.

**Evidence:** larp_meter/verify.py:369-377 — the comment "ROR indexes research organizations. Absence is a lead, not a finding" and the resulting `NOT_FOUND` with "confirm directly before drawing any conclusion". larp_meter/flags.py:320-325 repeats the caveat in the user-facing description. README.md:219 and README.md:227 both state "ROR and OpenAlex skew academic". The fuzzy-match guard at larp_meter/verify.py:348-364 requires `wanted <= have` (every significant claim token present in a registry name), which correctly rejects invented names but also rejects any legitimate institution ROR simply does not list.

**Fails on:** Two profiles, same output. (a) "BSc, Almeda University" — a well-known unaccredited degree mill. (b) "BSc, Hogeschool West-Vlaanderen" — a real Belgian institution outside ROR's research-org scope. Both return NOT_FOUND with the same hedged "confirm directly" language, so the tool has produced zero discriminating information on the exact claim it was asked about.

**Fix direction:** Layer, don't replace. **Wikidata** (`wikidata.org/w/api.php?action=wbsearchentities`, plus SPARQL at query.wikidata.org — both keyless, SPARQL needs a descriptive UA and has query timeouts) covers universities, colleges *and* companies, and carries `instance of` (P31) and `accreditation` (P1416) statements — a far better second opinion than ROR alone for the education question, and the only keyless source that also serves the employer question. For US accreditation specifically, the discriminating data is the Department of Education's DAPIP / College Scorecard datasets; these are downloadable rather than dependably keyless as live APIs, so ship a bundled JSON snapshot in the repo — which actually fits the zero-dependency promise better than a network call. Explicitly skip **GRID**: it stopped issuing identifiers in 2021 and formally hands off to ROR, so adding it is negative value.

---

### Name matching joins all candidate names into one string, so tokens from different people combine into a match

`name_matches` normalises every candidate name into a single space-joined blob and then asks which of the subject's tokens appear anywhere in it. Token co-occurrence across *different* authors therefore counts as a match. Separately, a single matching token is accepted when it is the subject's last token, so any shared surname is sufficient. Multi-author papers make both failure modes near-certain.

**Evidence:** larp_meter/names.py:55-56 `blob = normalize(" ".join(usable))` / `present = {t for t in mine if re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", blob)}` — the join destroys per-person boundaries.
larp_meter/names.py:63-64 `if len(present) >= 2: return True`.
larp_meter/names.py:68-72 the surname-only acceptance.
Verified: `name_matches('Marcus Vale', ['Marcus Hoffmann','Elena Vale','Wei Chen','Priya Nair','Tom Becker'])` -> **True** (no Marcus Vale on the paper). `name_matches('Wei Chen', ['L. Chen','A. Novak'])` -> True. `Verifier(subject_name='Marcus Vale')._attribute(c, ['R. Vale','Another Person'], ...)` -> VERIFIED, "exists and lists the subject".

**Fails on:** A fabricator named Wei Chen cites any of the thousands of real papers with a Chen among the authors: VERIFIED, flag 11 PASSED. A fabricator named Marcus Vale cites a five-author paper containing a Marcus and a Vale who are two different people: VERIFIED. Since a fabricator picks which papers to claim, and large-collaboration papers are the most impressive to claim, the selection pressure runs straight at this bug. Choosing a common surname when inventing a persona defeats attribution outright.

**Fix direction:** Compare against each candidate name individually rather than a joined blob, and require given-name evidence (full token or matching initial) alongside the surname before returning True. Where only a surname matches, return None (unanswerable) rather than True.

---

### Timeline implausibility is defeated by mentioning any single early year anywhere in the text

`f_timeline` is the only flag that can catch inflated seniority from text alone. It compares the largest claimed experience figure against `now_year - min(years)`, where `years` is every retrospective 4-digit year anywhere in the document, plus three years of slack. The earliest year need not relate to the career at all — a citation year, a company founding date, a birth year, a date in an award name. One number defuses the flag and converts it into a PASSED that also dilutes the score.

**Evidence:** larp_meter/flags.py:440 `years = sorted({int(c.value) for c in ex.claims_by(ctx.claims, "timeline", "year")})` — all years in the text, with no association to the subject.
larp_meter/flags.py:451-458 `claimed = max(parsed)` / `earliest = min(years)` / `available = ctx.now_year - earliest` / `if claimed > available + 3:`.
larp_meter/flags.py:462-463 otherwise `return FlagResult(PASSED, "Claimed durations are consistent with the dates given.")`.
larp_meter/extract.py:127 `YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")`.

**Fails on:** My fabricated bio triggered flag 12 ("claims 15 years of experience, but the earliest date anywhere in the profile is 2019"). Inserting the two words "Since 2008" flipped it to PASSED and, combined with one verb change, moved the whole report from YELLOW 27 to GREEN 0. Any real CV states a career start date, so essentially every fabricator clears this flag without trying — and the flag then pays them 1.5 of passing weight for it.

**Fix direction:** Only count years that sit in a role/education context attributable to the subject, and treat a claimed-experience figure with no supporting dated role as UNKNOWN rather than PASSED. A PASSED here should require dated positions covering the claimed span, not the mere presence of an old number.

---

### Network failure, rate-limiting and the default no-verify run are all scored identically to a clean audit

`--verify` is opt-in, so the default invocation leaves flags 8 and 11 UNKNOWN. When verification does run, any non-404 failure — timeout, DNS, 403, 429, TLS — is converted to UNCHECKABLE by design, and flag 11 then returns UNKNOWN. The design rationale (a network failure must never be evidence of deception) is right, but the consequence is that an audit which reached nothing produces the same flag statuses as an audit with nothing to reach, and the report surfaces the difference only in `verifier_stats`, which does not feed the score. Unauthenticated GitHub is 60 requests/hour, so this state is reachable without any deliberate action.

**Evidence:** larp_meter/cli.py:409-410 `beh.add_argument("--verify", action="store_true", ...)` — off by default.
larp_meter/verify.py:141-150 `except urllib.error.HTTPError as e:` ... `else: self.network_failures += 1; return "", False` and `except Exception: self.network_failures += 1; return "", False`.
larp_meter/verify.py:410-412 `_uncheckable` sets UNCHECKABLE.
larp_meter/flags.py:429 `return FlagResult(UNKNOWN, "Verification ran but every registry was unreachable — nothing decided.")`.
larp_meter/flags.py:408-411 the no-verify branch, also UNKNOWN.
larp_meter/audit.py:77-79 `verifier_stats` is emitted but never read by scoring.

**Fails on:** A fabricator submitting to a reviewer who runs the tool the default way (`--text "..."`, no `--verify`) gets flags 8 and 11 decided as UNKNOWN with certainty. If the reviewer does pass `--verify` behind a corporate proxy, or after 60 GitHub calls in an hour, every identifier returns UNCHECKABLE and flag 11 lands on the same UNKNOWN. In all three cases the top-line GREEN/score is presented without any visual distinction from an audit where the registries actually answered.

**Fix direction:** Make `--verify` the default for any mode with network access, and surface unreachability in the verdict itself — e.g. force INSUFFICIENT DATA, or a prominent "unverified" qualifier on the level, whenever `network_failures > 0` or checkable identifiers exist that were never resolved. `verifier_stats` should influence the coverage figure rather than sitting inert in the JSON.

---

### The phrase "peer-reviewed" converts the no-verifiable-output flag from TRIGGERED to UNKNOWN

SOFT_EVIDENCE records unsourced assertions ("peer-reviewed", "FDA cleared", "ISO 9001") as artifact claims with subtype `assertion`. In `f_output` the ordering means that when no `building_claims` vocabulary is present, the presence of a bare assertion routes to an UNKNOWN return instead of the TRIGGERED one. So claiming publications without citing any is treated as an open question, while claiming nothing at all would have been treated the same — but the assertion is what lets a heavy research claim escape the flag entirely.

**Evidence:** larp_meter/extract.py:48-53 SOFT_EVIDENCE patterns for regulatory clearance, `peer[\s-]reviewed`, and ISO.
larp_meter/extract.py:177-180 `add("artifact", "assertion", label, ...)`.
larp_meter/flags.py:257-262 the TRIGGERED branch requires `building` terms.
larp_meter/flags.py:263-264 `if [c for c in artifacts if c.subtype == "assertion"]: return FlagResult(UNKNOWN, "Only unsourced assertions of output (e.g. 'peer-reviewed') — no identifiers to check.")`.
Bank at larp_meter/matching.py:217-220 `building_claims` = ["building","developing","creating","working on","patent pending","stealth",...].

**Fails on:** "He is the author of 40 peer-reviewed papers" with no DOI produced flag 6 = UNKNOWN ("Only unsourced assertions of output") in my GREEN run. The strongest possible research claim, backed by nothing, is scored as unanswerable. Meanwhile an honest founder who writes "currently building a diagnostics platform" and cites nothing gets TRIGGERED — the flag punishes the modest present-tense phrasing and excuses the grandiose past-tense one.

**Fix direction:** An assertion of peer-reviewed output, regulatory clearance or certification with no identifier is a specific unsupported claim, not an absence of claims — it should be TRIGGERED (or at least feed a lower-weight flag), and it should not depend on whether the text happens to contain a `building_claims` word.

---

### A common name grants the subject a stranger's OpenAlex publication record, and the ambiguity warning never reaches the score

In web mode, the OpenAlex provider searches by name and keeps any author whose display name satisfies `names.name_matches` — inheriting the surname-only and blob-join weaknesses above. `f_output` treats the resulting record as decisive: "A scholarly record found independently outsettles anything the text asserts", returning PASSED before any other branch runs. The code does detect when several distinct researchers share the name and emits an `ambiguous_identity` signal, but that signal is only printed by the CLI; no flag reads it, so it cannot affect the verdict.

**Evidence:** larp_meter/providers.py:193 `if not names.name_matches(subject, [display]): continue`.
larp_meter/providers.py:205-207 `if best is None or works > best.get("works", 0): best = {...}` — it selects the *most prolific* colliding author.
larp_meter/providers.py:211-212 `if matches > 1: signals["ambiguous_identity"] = matches`.
larp_meter/flags.py:242-249 `scholar = ctx.signals.get("openalex")` / `if scholar and scholar.get("works"): return FlagResult(PASSED, f"Independent scholarly record found: {scholar['works']} works with {scholar.get('citations', 0)} citations (OpenAlex).", ...)`.
larp_meter/cli.py:119 the ambiguity is printed only; grepping flags.py shows the only signals consumed are `openalex`, `wikipedia_about_subject` and `search_ok`.

**Fails on:** A fabricator operating under a common surname is audited in web mode. OpenAlex returns a real, unrelated academic with the same surname and 180 works; `best` selects them precisely because they are the most prolific; flag 6 returns PASSED citing 180 works and thousands of citations as the subject's own independent record. The `ambiguous_identity` warning scrolls past in the terminal and is absent from the HTML/Markdown verdict a reader actually keeps. Choosing a persona with a common name — the natural choice for a fabricator wanting to be hard to check — maximises this.

**Fix direction:** Require corroboration beyond the name before treating an OpenAlex record as the subject's (ORCID agreement, affiliation overlap with the profile, or field overlap), and make `ambiguous_identity` suppress the PASSED to UNKNOWN rather than merely printing a note.

---

### Identifier regexes miss the standard human citation forms, so even identifier-citing profiles evade verification

The six patterns in `ARTIFACT_PATTERNS` (extract.py:38-45) recognise machine-pasted forms but not how people actually cite. arXiv requires a literal `arxiv.org/abs/` URL (extract.py:40), so the canonical form `arXiv:2101.00001` is missed. The patent pattern `(?:US|EP|WO)\s?\d{7,11}` (extract.py:44) permits at most one space and no commas, so `US Patent 10,123,456`, `US Pat. No. 9,876,543` and `EP 3 456 789 B1` all miss, as does a bare `Patent number 10123456`. GitHub requires a `github.com/` URL, so `GitHub under @janedoe` misses. There is no pattern at all for PMID/PMC (the dominant identifier in medicine and life sciences), Scopus Author ID, Google Scholar profile, ISBN, or professional-licence numbers (NPI, state bar, PE). Since verification is gated entirely on these regexes, an honest subject who cites their work the normal way is treated identically to one who cites nothing.

**Evidence:** extract.py:38-45. Measured over 17 realistic citation strings, only 6 reach a registry handler: `arXiv:2101.00001` → NONE; `Inventor on US Patent 10,123,456.` → NONE; `US Pat. No. 9,876,543 (granted 2021).` → NONE; `Patent number 10123456 issued to me.` → NONE; `EP 3 456 789 B1 covers the cooling loop.` → NONE; `Code on GitHub under @janedoe.` → NONE; `PMID 31021795.` → NONE; `PubMed ID: 31021795` → NONE; `Scopus Author ID 7005432198.` → NONE; `Published in IEEE Trans. Med. Imaging 38(9), 2019.` → NONE.

**Fails on:** A biomedical researcher writes "Lead author on PMID 31021795 and 31021796; preprint at arXiv:2101.00001; inventor on US Patent 10,123,456." That is four resolvable identifiers stated in the most conventional forms in their field. The tool extracts none of them, flag 11 returns UNKNOWN ("No claim carries an identifier that a registry could confirm or refute"), and flag 6 TRIGGERS with "cites no checkable artifact — no DOI, patent number, repository, trial registration or certification appears anywhere" — a statement that is factually false about the text in front of it.

**Fix direction:** Broaden the patterns: accept `arXiv:NNNN.NNNNN` and legacy `arch-ive/NNNNNNN`; normalise punctuation and whitespace inside patent numbers before matching (`re.sub(r'[,\s]','',...)` on a candidate span) and accept a bare 7-8 digit number when preceded by patent language; add PMID/PMCID with a PubMed E-utilities verifier; add ORCID/Scholar/Scopus profile URLs. Each new pattern needs a matching handler in `HANDLERS`, otherwise it silently repeats the finding-1 failure mode.

---

### `re.I` on DEGREE_RE destroys the capitalisation anchor, garbling the institution string the report prints and would query

`DEGREE_RE` is compiled with `re.I` (extract.py:84), and `_INSTITUTION_CORE` — interpolated into its `inst` group at extract.py:83 — relies on `[A-Z]` character classes to bound the organisation name (the design intent is stated explicitly at extract.py:86, "Case-insensitive trigger word, case-sensitive org name (orgs are capitalised)"). Under `IGNORECASE` those `[A-Z]` classes also match lowercase, so the trailing optional group `(?:\s+(?:of|de|...|und|et|en|...)\s+[A-Z][\w-]*(?:\s+[A-Z][\w-]*){0,2})?` walks past the institution into following prose. `INSTITUTION_RE` (extract.py:71) is compiled *without* `re.I` and produces the clean value, which is why `mentioned_institution` is correct while `degree_institution` from the same sentence is garbled — the two disagree on the same input.

**Evidence:** extract.py:84 `re.I)` closing `DEGREE_RE`; extract.py:71 `INSTITUTION_RE = re.compile(...)` with no flags; extract.py:67-69 `_INSTITUTION_CORE` prefix `(?:[A-Z][\w-]*\s+){0,3}`. Measured: input "MSc in Electrical Engineering from Delft University of Technology and a Bachelor of Applied Physics..." yields `degree_institution -> 'Delft University of Technology and a'` alongside `mentioned_institution -> 'Delft University of Technology'`. The garbled value reaches the user: flag 8 renders `PASSED — Degree tied to a named institution (Delft University of Technology and a).`

**Fails on:** Any bio listing two degrees in one sentence ("an MSc from Delft University of Technology and a Bachelor of Applied Physics from the University of Antwerp") prints a visibly broken institution name in the report, undermining reader trust in the parse. More consequentially, once finding 1 is fixed this is exactly the string that will be sent to ROR as `urllib.parse.quote(claim.value)` (verify.py:334) — querying the registry for "Delft University of Technology and a" — and `_significant_tokens` (verify.py:68-72) would carry the junk token into the `wanted <= have` subset test at verify.py:354, risking a spurious NOT_FOUND against a real university.

**Fix direction:** Drop `re.I` from `DEGREE_RE` and instead make only the degree-level alternation case-insensitive via an inline `(?i:...)` group, matching the technique already used correctly in `OWNED_ORG_RE` (extract.py:87-90) and `PARTNER_ORG_RE` (extract.py:93-97). Add a regression test asserting `degree_institution == mentioned_institution` for the same institution in a two-degree sentence.

---

### Grant and funding claims have no registry, though NIH RePORTER and NSF are keyless

'Grant' and 'funded by' sit in the concrete_partnership bank, so their mere presence in the text flips flag 5 from TRIGGERED to PASSED. Funding is one of the few claim types with excellent free public registries: NIH RePORTER (`https://api.reporter.nih.gov/v2/projects/search`, keyless POST, JSON, documented, searchable by PI name and organization, returns award amount, project number and fiscal year) and NSF Award Search (`https://api.nsf.gov/services/v1/awards.json?keyword=`, keyless GET). EU CORDIS is weaker — the Horizon dataset is distributed as bulk CSV/XML on data.europa.eu rather than a clean per-query REST endpoint, so treat it as a batch enrichment rather than a live lookup, and be honest that it is more work per unit of value than the US pair.

**Evidence:** larp_meter/matching.py:211-216 `"concrete_partnership": ["grant", "funded by", "contract", …]`. Consumed at flags.py:220-230 `f_vague_partnerships`: `concrete = find_terms(ctx.text, ctx.banks["concrete_partnership"], skip_negated=True)` … line 230 `return FlagResult(PASSED, f"Concrete deal terms present ({', '.join(concrete[:4]) …})")`. No grant identifier is extracted (extract.py:57-64 has no `R01[A-Z]{2}\d{6}` or Horizon grant-agreement-number pattern) and no funder appears in Verifier.HANDLERS (verify.py:422-426).

**Fails on:** "Principal Investigator on $3.4M in NIH and Horizon Europe grants; extensive collaboration agreements across the consortium." Flag 5 returns PASSED on the words 'grant' and 'collaboration agreement'; flag 7 returns PASSED on the funding figure. `matching.py:182` also has 'principal investigator' in leadership_titles, so the title is registered but never tested. A RePORTER POST with `{"criteria":{"pi_names":[{"any_name":"Rex Falsum"}]}}` returns zero projects.

**Fix direction:** Extract NIH activity-code project numbers and Horizon grant agreement numbers as a `grant` subtype; add a RePORTER handler that checks both the identifier and the PI name via `_attribute()`. Absence must stay a lead, not a contradiction — RePORTER covers HHS only, so a genuinely EU- or industry-funded PI must not be penalised, which is the same coverage caveat verify.py:372-379 already articulates for ROR.

---

### No professional licensure source — the NPI Registry is keyless and closes the largest non-academic gap

README:216 concedes that every registry consulted is academic or corporate and that non-academic professionals score 0% coverage. The NPI Registry API (`https://npiregistry.cms.hhs.gov/api/?version=2.1&first_name=&last_name=&state=`) is an official CMS service, keyless, documented, and lists every enumerated US healthcare provider with legal name, credential string (MD/DO/RN/PA), primary taxonomy (specialty), practice address and enumeration date. That directly feeds flags 1 and 2, which currently guess at domain fit from keyword banks. It is the one people-level licensure registry with a real free API — state bar associations, engineering boards and trade licensure bodies mostly have none, so the honest scope is US healthcare only, which is nonetheless where 'Dr.' inflation concentrates.

**Evidence:** larp_meter/flags.py:79-135 `f_education` decides credential-vs-domain fit entirely from `dom.claimed_domain(ctx.text, prof)` and `dom.supporting_domains(ctx.text, "credentials", prof)` — both text-derived. matching.py:178-185 includes 'chief medical officer' in leadership_titles, so the tool recognises medical authority claims but has no source that can test them. Verifier.HANDLERS (verify.py:422-426) contains no person-level registry: the only person identifier verified is ORCID, which is academic. README.md:216: "A master plumber with fifteen years and 400 installations yields 0% evidence coverage: every registry this tool consults is academic or corporate."

**Fails on:** "Dr. Rex Falsum, board-certified interventional cardiologist and Chief Medical Officer at Helios Health, 15 years of clinical practice." No DOI, no ORCID, no NCT. Every artifact-dependent flag returns UNKNOWN, coverage falls below MIN_COVERAGE (scoring.py:18, 0.35) and the verdict is INSUFFICIENT DATA — a shrug at a claim that one keyless GET could confirm or refute by name, state and taxonomy.

**Fix direction:** Add an optional `--jurisdiction`-scoped NPI lookup keyed on `--name` when medical-domain markers are present, emitting a signal (like the existing `openalex` signal, providers.py:208) that flags 1/2/6 can consult. Report a miss as UNCHECKABLE-with-note rather than NOT_FOUND: common names return many NPIs and a non-US clinician returns none, so the absence is only meaningful with a state filter.

---

### [FIXED — nightly/2026-09-12, see the duplicate MAJOR entry above] ROR-only institution checking produces false positives against real non-research schools

**Fixed as a side effect of fixing the duplicate MAJOR write-up above** ("ROR absence is scored as a triggered credential flag"): flag 8 no longer TRIGGERS on any ROR miss at all, so a Le Cordon Bleu-shaped miss (a real, famous, non-research-indexed institution) now reads UNKNOWN rather than TRIGGERED — the exact correctness fix this entry asks for, reached by the simpler of its own two suggested routes (stop triggering on an unsettled miss) rather than the Wikidata P31 cross-check below, which remains unbuilt. The Wikidata idea is still worth doing eventually to let flag 8 *positively* credit "real institution, not research-indexed" rather than only refrain from accusing it — but the accusation this entry is actually about is gone.

Original finding, kept for context: ROR indexes research organizations. Flag 8 TRIGGERS on a ROR miss with a hedge in the prose, but the flag still fires and still contributes 1.0 weight to the triggered numerator — the caveat is in the text, not in the arithmetic. Wikidata (`wbsearchentities` then `wbgetentities` for P31 instance-of, P571 inception, P17 country) is keyless and covers conservatories, art academies, culinary schools, business schools, seminaries and hospitals that ROR legitimately omits. Consulting it as a second opinion before triggering converts a false accusation into a correct PASS. Given the codebase's stated priority that accusing an honest person is the failure mode that matters (README:229, verify.py:172-174), this is a correctness fix, not an enrichment.

**Evidence:** larp_meter/verify.py:337 `url = "https://api.ror.org/organizations?query=" + …` is the only institution source. verify.py:375-379 sets NOT_FOUND with the hedge "which indexes research organizations — confirm directly before drawing any conclusion." flags.py:315-326: `fake = [i for i in institutions if i.status == ex.NOT_FOUND] if ctx.verified else []` … `return FlagResult(TRIGGERED, …)` — the hedging language at lines 322-325 does not change the status, and scoring.py:22 sums weight by status only: `trig_w = sum(FLAG_BY_ID[i]["weight"] for i, r in results.items() if r.status == TRIGGERED)`.

**Fails on:** "Diploma in Culinary Arts, Le Cordon Bleu Paris, 2011." — a real, famous institution with no ROR entry (it is not a research organization). `verify_institution` returns NOT_FOUND, flag 8 TRIGGERS, and an honest CV takes 1.0 of triggered weight plus a report line naming the school as unmatched. The same happens to conservatory graduates, seminary graduates and most vocational qualifications.

**Fix direction:** On a ROR miss, query Wikidata for the name and check P31 against a set of education-institution classes before deciding. A Wikidata hit should return VERIFIED-with-note ('real institution, not research-indexed'); only a miss in both should reach flag 8, and even then the wording at flags.py:320-326 suggests it should probably be UNKNOWN rather than TRIGGERED.

---

### Author identity is matched by name string only — no disambiguated author registry is consulted

OpenAlex and Crossref are both queried by name and filtered with `names.name_matches`, a deliberately permissive comparator that accepts two shared tokens or a surname plus an initial. The code recognises the resulting conflation risk and emits an `ambiguous_identity` signal, but the strongest available answer is not used: DBLP (`https://dblp.org/search/author/api?q={name}&format=json`) returns *disambiguated author entities* with stable PIDs and per-author publication lists, and OpenAlex itself exposes canonical author IDs and `orcid` on the author object — which the provider already reads but only stores, never uses to pin identity. For software and CS subjects DBLP also has far better conference coverage than Crossref, which matters because CS publishes at conferences.

**Evidence:** larp_meter/providers.py:179-213 `OpenAlex.search`: line 180 `"https://api.openalex.org/authors?search=" + urllib.parse.quote(subject)`; line 193 `if not names.name_matches(subject, [display]): continue`; line 206-207 stores `"orcid": a.get("orcid")` into the `best` dict — and nothing in flags.py ever reads `signals["openalex"]["orcid"]` (flags.py:244-249 uses only `works`, `citations`, `display_name`, `institutions`). Lines 210-213: `if matches > 1: signals["ambiguous_identity"] = matches`, consumed only as a printed warning at cli.py:118-119. The comparator itself, names.py:63-73, returns True on two matching tokens. providers.py:274 `ALL_PROVIDERS = (Wikipedia, OpenAlex, Crossref, DuckDuckGo)` — no DBLP.

**Fails on:** Web mode on a common name, e.g. 'Wei Zhang, ML engineer'. OpenAlex returns a prolific homonym; `name_matches` accepts both tokens; flag 6 returns PASSED with "Independent scholarly record found: 412 works with 9,800 citations (OpenAlex)" — a stranger's record credited to the subject, and it outranks every other consideration because that branch returns before the artifact check (flags.py:243-249). The `ambiguous_identity` warning prints to the console but does not change any flag.

**Fix direction:** When the profile supplies an ORCID, pin the OpenAlex author by `filter=orcid:{id}` instead of name search — that turns a fuzzy match into an exact one for free. Add DBLP as a fourth provider for CS-domain subjects and prefer its disambiguated author entity. And make `ambiguous_identity` actually suppress the flag 6 PASSED branch rather than only printing, since a credited stranger is the same class of error as a false MISMATCH.

---

### Independent-validation flag punishes not name-dropping press, and discards real coverage whose headline omits the name

`f_validation`'s last branch TRIGGERS on any text of 40+ words containing a leadership title or a tech word when no external-validation vocabulary ('featured in', 'awarded', 'keynote'…) or press-outlet name appears. In text mode there are no source URLs at all, so the flag is decided purely on whether the subject advertises their own coverage — modesty is scored as absence of validation. In web mode, a second problem compounds it: findings are kept only if `names.name_matches` finds the subject's name in the result TITLE, and only those survive into `source_urls`, so headline-style press coverage ('Antwerp startup lands €4M for chip tech') is discarded and the remaining LinkedIn/own-site results trip the 'Pure echo chamber' branch. Both filters also inherit the name-matching gaps in findings #1 and #2, so non-Western-named subjects lose their genuine coverage first and are then flagged for having none.

**Evidence:** larp_meter/flags.py:398-402 — `if ctx.word_count >= 40 and find_terms(ctx.text, b["leadership_titles"] + b["tech_claims"]): return FlagResult(TRIGGERED, "Substantial claims with zero third-party validation …")`. Echo-chamber branch at flags.py:390-395. Title gate at larp_meter/providers.py:266 `is_about = bool(names.name_matches(subject, [title]))`; only about_subject URLs reach the audit via larp_meter/cli.py:107 `source_urls=bundle.used_urls`. Measured: an ordinary researcher bio in text mode returned flag 10 TRIGGERED — 'Substantial claims with zero third-party validation — no press, award or independent coverage is referenced anywhere.'

**Fails on:** An honest CTO pastes a 60-word factual bio mentioning 'hardware'. With no press bragging in the text, flag 10 fires. In web mode, the same person's actual Reuters article is discarded because the headline says 'the company' rather than her name, leaving only her LinkedIn — which the tool then calls a 'Pure echo chamber'.

**Fix direction:** Absence of self-reported press should be UNKNOWN, not TRIGGERED — the flag should only decide when a search layer actually ran and returned results. In web mode, match the name against title AND snippet (and the fetched page body) before discarding a finding, and report discarded-but-independent sources to the flag as 'unresolved' rather than dropping them silently.

---

### PARTNER_ORG_RE captures people's names as partner organisations, inflating the logo-wall count

`PARTNER_ORG_RE` grabs any run of capitalised words after a collaboration verb, guarded only against a short honorific list (Dr/Mr/Mrs/Ms/Prof/Sir/Dame/Rev/The). A bare personal name — which is how academics and clinicians normally describe collaboration — is captured as an organisation. `f_logo_wall` then triggers at four distinct 'partner organizations' with no deep-collaboration vocabulary, so naming four human collaborators produces 'no sign of substantive joint work'.

**Evidence:** larp_meter/extract.py:112-116 — `PARTNER_ORG_RE = re.compile(r"(?i:partner…|collaborat\w+|…)\s+(?i:with|between)\s+(?!(?:Dr|Mr|Mrs|Ms|Prof|Sir|Dame|Rev|The)\b)([A-Z][\w&-]*(?:[ \t][A-Z][\w&-]*){0,3})")`. larp_meter/flags.py:344-352 — `if len(distinct) >= 4 and not deep: return FlagResult(TRIGGERED, …)`. Measured on a bio naming four human collaborators: extracted partner_org values were 'Ngozi Okafor', 'Yuki Tanaka', 'Laura Beck', 'Diego Santos', and flag 9 TRIGGERED — '4 partner organizations named with no sign of substantive joint work'.

**Fails on:** A research fellow writes 'collaborated with Ngozi Okafor on assay design, partnered with Yuki Tanaka on imaging, worked in collaboration with Laura Beck, and teamed up with Diego Santos'. Flag 9 reports a logo wall of four partner organisations — for describing four real scientific collaborations by the collaborators' names.

**Fix direction:** Reject captures that look like personal names (two capitalised tokens with no organisational suffix/keyword, or a token present in a given-name list) before recording a partner_org, and require an organisational cue (Inc/GmbH/University/Institute/Labs/Foundation, or a known-org list) for the logo-wall count specifically.

---

### A pseudonymous or non-legal GitHub display name is reported as 'does NOT list the subject'

`verify_github` treats a user URL as an identity claim and compares the account's published display name to the subject. It correctly refuses to judge a one-word display name, but any two-word value is passed straight to `_attribute`, whose failure branch is MISMATCH. Pseudonymous or stylised display names ('Pixel Pusher'), handles-as-names, names rendered in a non-Latin script, and accounts held under a former or married name are all common and entirely legitimate; each becomes a weight-2.5, ORANGE-floored contradiction. This is the one place in verify.py where a naming choice — rather than a registry fact — decides the verdict.

**Evidence:** larp_meter/verify.py:284-289 — `published = (data.get("name") or "").strip(); comparable = [published] if len(published.split()) >= 2 else []; … self._attribute(claim, comparable, …)`; MISMATCH branch at verify.py:190-191; floor at larp_meter/flags.py:407-409 + larp_meter/scoring.py:73-85. Reproduced with a canned GitHub payload `{'name': 'Pixel Pusher'}` and subject 'Sofia Almeida': status MISMATCH — "GitHub user 'pixelpusher' (41 public repos, 300 followers) exists but does NOT list the subject (Pixel Pusher)."

**Fails on:** Sofia Almeida links her own GitHub, whose display name is her long-standing handle 'Pixel Pusher'. The tool reports that the account does not list her, flag 11 triggers, and the verdict is held at ORANGE — for the offence of not using her legal name on GitHub.

**Fix direction:** Apply the same reasoning already used for repositories: a display name is self-asserted metadata, not a registry attribution. Downgrade a non-matching GitHub user name to UNCHECKABLE (existence recorded, attribution not checked), or require corroboration (matching name on a linked ORCID/commit email) before asserting a mismatch.

---

## MINOR (4)

### No book or ISBN source, though the attribution logic already anticipates books

`_attribute`'s docstring names "books with no author array" as a case it must handle gracefully — but no code path can ever produce a book record, because there is no ISBN pattern in the extractor and no book registry in `HANDLERS`. "Author of" is a cheap, high-status, frequently-fabricated claim, and the most damning detail about a fake book (that its publisher is a self-publishing imprint) is one keyless field lookup away.

**Evidence:** larp_meter/verify.py:168-169 — "A registry that returns no usable names (books with no author array, ORCID records set to private, scraped markup that drifted) tells us nothing about attribution". No ISBN pattern in larp_meter/extract.py:38-45; no book handler in larp_meter/verify.py:415-419.

**Fails on:** "Author of *Sovereign Systems: Rebuilding Trust in Distributed Infrastructure* (2021)." The book does not exist, or exists as a 40-page KDP release with sales rank in the millions. No claim is extracted, nothing is verified, and the credential passes through the report as unremarked prose.

**Fix direction:** Add an ISBN-10/13 pattern to `ARTIFACT_PATTERNS` and a handler backed by **OpenLibrary** (`https://openlibrary.org/isbn/{isbn}.json` → `/books/{key}.json` for authors and publisher; keyless, no token, stable, and it gracefully 404s, which maps onto the existing `NOT_FOUND` path at verify.py:143-144). Route the author list through `_attribute` like every other artifact. The publisher field is the real payload: "Independently published", "KDP", or an author-name imprint distinguishes a self-published title from a trade book, and no other source the tool consults can make that distinction. Google Books works without a key at low volume but has unversioned quota behaviour — use it only as a fallback, not the primary.

---

### FORWARD_MARKERS misreads past achievements as future targets, silently removing dates from the timeline check

`FORWARD_MARKERS` (extract.py:131-134) includes `through`, `launch(?:ing)?`, `shipping` and `will` in a lookbehind window of 40 characters. Those words appear routinely in *past-tense* accomplishment prose. When one precedes a year, extract.py:226 files it as `year_target` instead of `year`. Flag 12 reads only `subtype="year"` (flags.py:440 `years = sorted({int(c.value) for c in ex.claims_by(ctx.claims, "timeline", "year")})`), so the date is removed from both the future-date check and the experience-vs-earliest-date consistency check. The guard was added for a real reason (a stated goal is not a claimed credential) but it over-fires on achievement language, and the effect is to shrink the evidence available to the one flag that tests internal consistency.

**Evidence:** extract.py:131-134 `FORWARD_MARKERS = re.compile(r"\b(?:by|target(?:ed|ing)?|projected|expected|planned|planning|roadmap|horizon|due|forecast|goal|aim(?:ing)?|launch(?:ing)?|shipping|will|anticipated|scheduled|from now until|through)\b[^.;\n]{0,40}$", re.I)`; extract.py:225-226; flags.py:440. Measured: "took the scanner through FDA clearance in 2019" → `year_target 2019`; the near-identical "shipped the product in 2019" → `year 2019`.

**Fails on:** A subject writes "I claim 25 years of experience" and "we took the product through certification in 2019", with no other date in the profile. 2019 is filed as `year_target` and excluded, so `years` is empty, the `if parsed and years` consistency test at flags.py:450 never runs, and flag 12 returns UNKNOWN ("Not enough dated detail to test the timeline") instead of flagging that 25 years cannot fit behind a 2019 anchor. The over-broad marker converts a detectable inconsistency into lost coverage.

**Fix direction:** Restrict the forward-marker test to markers in a genuinely prospective grammatical frame — require future/modal tense adjacency (`will`, `is targeted`, `is scheduled`) rather than any occurrence of `through`/`launch`/`shipping` within 40 characters — or gate on the year being greater than `now_year` before honouring the marker at all, since a past year preceded by "through" is far more likely an achievement than a target.

---

### Package registries are unused, though 'creator of X' is a standard tech claim

GitHub is the only code-provenance source. The package registries answer a different and more falsifiable question — who publishes this package and how much is it actually used — and all three are keyless single GETs returning JSON: `https://registry.npmjs.org/{pkg}` (maintainers array, versions, time.created), `https://pypi.org/pypi/{pkg}/json` (info.author, author_email, project_urls), `https://crates.io/api/v1/crates/{name}/owners`. Download counts come from `https://api.npmjs.org/downloads/point/last-month/{pkg}` and pypistats, both keyless. Low value ceiling but near-zero implementation cost, and it is the natural companion to the GitHub attribution fix.

**Evidence:** larp_meter/extract.py:61 is the only code-related pattern: `("github", re.compile(r"github\.com/([A-Za-z0-9](?:[\w.-]*[A-Za-z0-9])?(?:/[\w.-]+)?)", re.I))`. No npm/PyPI/crates pattern exists in ARTIFACT_PATTERNS (extract.py:57-64) and none in EMITTED_SUBTYPES (extract.py:33-38). matching.py:171-177 `tech_claims` matches technology *topics* only, so a package name in a bio is invisible to both the extractor and the flags.

**Fails on:** "Creator and maintainer of fastqueue, 4M downloads a month." No claim is extracted at all — flag 6 sees no hard artifact and either TRIGGERS on 'building' language or returns UNKNOWN. A single GET to registry.npmjs.org would show the maintainer list and whether the subject is on it, and the downloads endpoint would test the 4M figure.

**Fix direction:** Extract `npmjs.com/package/{x}`, `pypi.org/project/{x}` and `crates.io/crates/{x}` URLs as a `package` subtype and verify maintainers via `_attribute()`. Registry author fields are free-text and often an email or an org, so a non-match must be UNCHECKABLE unless a real maintainer/owner list is returned — the same distinction verify.py:175-191 already draws.

---

### Several of the obvious candidate sources are not actually keyless — and the one scraped source has no free successor

A datasource expansion should not be planned on wrong availability assumptions. Semantic Scholar's Graph API is nominally keyless but the unauthenticated pool is a shared, aggressively throttled bucket that returns 429 under any real load — adopting it as a primary would silently convert claims to UNCHECKABLE and quietly erode coverage in a way that looks like network flakiness. PatentsView now requires a (free but registered) API key; EPO OPS requires OAuth credentials; WIPO Patentscope has no public API. So the Google Patents HTML scrape has no keyless replacement, and the codebase already contains the right pattern for this case: an optional environment-variable key with graceful degradation, exactly as done for GitHub. OpenCorporates likewise no longer offers a usable open tier.

**Evidence:** larp_meter/verify.py:383-411 `verify_patent` fetches `https://patents.google.com/patent/{pid}/en` as HTML and parses inventors with `re.findall(r'<dd itemprop="inventor"[^>]*>([^<]+)</dd>', body)` (line 402-403). The comment at lines 399-401 is candid: "Scraped markup, not an API: if Google changes this element every patent claim would silently become a weight-2.5 accusation." The optional-key pattern already exists at verify.py:132-136: `token = os.environ.get("GITHUB_TOKEN")` … `if token and urllib.parse.urlsplit(url).hostname == "api.github.com": headers["Authorization"] = f"Bearer {token}"` — host-checked, not substring-checked. The failure path is sound too: `_get` returns `("", False)` on non-404 HTTP errors (verify.py:148-150), so a 429 becomes UNCHECKABLE rather than evidence.

**Fails on:** Adopting Semantic Scholar as the publication backbone: a batch run over 50 profiles (cli.py:229-241 loops `run_audit` per entry) hits 429 on most requests, every DOI-adjacent check returns UNCHECKABLE, coverage drops below the 0.35 floor (scoring.py:18) and a whole batch reports INSUFFICIENT DATA with no visible cause beyond `network_failures` in verifier_stats (audit.py:78-79).

**Fix direction:** Prefer OpenAlex and Europe PMC over Semantic Scholar for keyless scholarly lookups. For patents, add `EPO_OPS_KEY` / `PATENTSVIEW_KEY` support following the verify.py:132-136 host-checked pattern, use the registry API when a key is present, and keep the scrape as the degraded default with its existing UNCHECKABLE-on-parse-failure behaviour. Add a per-source note in `verifier_stats` recording which backend answered, so a report reader can tell a scrape-backed patent result from an API-backed one.

---

