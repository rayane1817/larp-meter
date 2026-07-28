# LARP Meter v2 — Claim-vs-Evidence Auditor

**Audit professional self-presentation (LinkedIn bios, pitch text, "About" pages) against verifiable substance. Quantify the gap between image and evidence.**

A due-diligence *triage* tool: it surfaces red flags worth investigating by hand. It does not render verdicts about people.

---

## What's new in v2 (methodology)

v1 counted keyword hits with substring matching and treated every flag it couldn't evaluate as "passed". v2 fixes the methodology from the ground up:

| Problem in v1 | Fix in v2 |
|---|---|
| `"ai" in text` matched *said*, *email*, *airline* | Word-boundary regex matching; hyphen/space variants (`edge-AI` = `edge ai`) |
| Absence of evidence counted as innocence → inflated GREEN | **Three-state flags**: TRIGGERED / PASSED / UNKNOWN. Undecidable flags reduce *evidence coverage*, never the risk score |
| All 10 flags weighed equally | **Weighted scoring** — structural deception (self-referential partners ×2.0, credential mismatch ×1.5) outweighs stylistic signals (buzzwords ×1.0) |
| Buzzword count triggered on any long text | **Normalized density** (occurrences per 100 words) + minimum distinct-term threshold |
| Self-referential partner detection hardcoded specific org names | **Generic detection**: extracts orgs the subject *leads* and orgs they call *partners*, flags the overlap |
| No notion of how much evidence the verdict rests on | **Evidence coverage %** — below 35 % coverage the tool refuses to score and returns `INSUFFICIENT DATA` |
| Nothing measured "specific vs vague" | **Specificity index** — verifiable details (years, amounts, URLs, DOIs, patent IDs, named institutions) per 100 words |
| ~250 lines of duplicated logic between modes | One `analyze()` engine shared by text, web, and file modes |

### Scoring model

```
LARP score = 100 × (weight of TRIGGERED flags) / (weight of all DECIDED flags)
coverage   = (weight of decided flags) / (total weight)
```

| Verdict | Condition |
|---|---|
| ⚪ INSUFFICIENT DATA | coverage < 35 % — refuse to score |
| 🟢 GREEN | score < 20 |
| 🟡 YELLOW | 20–39 |
| 🟠 ORANGE | 40–64 |
| 🔴 RED | ≥ 65 |

### The 10 flags (with weights)

| # | Flag | W | Detects |
|---|---|---|---|
| 1 | Education ≠ Claimed Domain | 1.5 | Non-technical degree + deep-tech expertise claims |
| 2 | Experience ≠ Declared Title | 1.5 | "President @ AI startup" with only policy/advocacy history |
| 3 | Self-Referential Partners | 2.0 | Own organizations listed as "partners" (circular validation) |
| 4 | Buzzword Density | 1.0 | Hype language, normalized per 100 words |
| 5 | Vague Partnerships Only | 1.0 | MoUs/NDAs/"in talks" instead of contracts, grants, revenue |
| 6 | No Verifiable Output | 1.5 | "Building/developing" without any checkable artifact (DOI, patent no., repo, trial ID, certification) |
| 7 | Fundraising Without Traction | 1.5 | Raising money with zero customers/revenue mentioned |
| 8 | Unverifiable Credentials | 1.0 | Degree claimed without naming an institution |
| 9 | Logo Wall Syndrome | 1.0 | ≥4 partner names, zero deep-collaboration evidence |
| 10 | No Independent Validation | 1.0 | Big claims, zero third-party coverage |

Hard-evidence patterns that flip flag 6 to PASSED: DOIs, patent numbers (US/EP/WO), GitHub repos, arXiv IDs, ORCID, FDA/CE clearance, ClinicalTrials.gov registrations.

---

## Install

Python 3.8+, stdlib only — no dependencies.

```bash
git clone https://github.com/rayane1817/larp-meter.git
cd larp-meter
python larp-meter.py --selftest   # verify the methodology tests pass
```

## Usage

```bash
# Text mode (most reliable) — paste a bio / About page / pitch
python larp-meter.py --text "President @ DeepTech. MoU signed. Seeking 8-12M. MSc Public Health."

# From a file
python larp-meter.py --file bio.txt

# Web-search mode (DuckDuckGo HTML endpoint, 7-day cache in cache/)
python larp-meter.py "Jane Doe"

# Guided 10-question assessment
python larp-meter.py --interactive

# Machine-readable output / no report files
python larp-meter.py --text "..." --json --no-save

# List past audits
python larp-meter.py --list
```

### Example output

```
  ────────────────────────────────────────────────────────
  🔴 RED  |  LARP score: 92/100  |  evidence coverage: 100%
  ────────────────────────────────────────────────────────
  Strong LARP pattern: claims structurally unsupported by any verifiable evidence.
  Specificity index: 1.59 verifiable details per 100 words (low — vague profile)

  🔴 TRIGGERED (9):
  [3] Self-Referential Partners  (weight 2.0)
      Organization(s) led by the subject also appear as their 'partners': ...
  ...
  ❔ UNDECIDABLE (1) — not counted as passed:
  ...
```

## Output files

| Artifact | Location |
|---|---|
| JSON report | `output/YYYYMMDD_HHMMSS_<slug>.json` |
| Obsidian note | `$OBSIDIAN_VAULT_PATH/research/YYYYMMDD-larp-<slug>.md` (only if the vault's `research/` folder exists) |
| Search cache | `cache/*.json` (TTL 7 days) |

## Limitations & ethics

- **Keyword heuristics, not semantics.** Longer, richer input → better results. A short bio will honestly return `INSUFFICIENT DATA` instead of a fake verdict.
- **Web mode depends on search engines tolerating automated queries**; if results are empty, use `--text`.
- **Use responsibly.** This tool is for due diligence on *public professional claims* (investors, hiring, partnerships). Flags are leads to verify by hand, not conclusions about a person. Don't publish raw outputs as accusations.

## License

MIT.
