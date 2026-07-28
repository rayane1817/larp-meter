# LARP Meter — OSINT Tool

**Audit LinkedIn profiles against real-world achievements. Quantify the gap between image and substance.**

---

## What It Does

Paste any LinkedIn bio, company description, or personal claims — LARP Meter scans the text for **10 red flags** that indicate a gap between someone's self-declared position and their actual track record.

**Scores on a 4-level scale:**

| Level | Meaning |
|---|---|
| 🟢 GREEN | Likely legitimate. Claims and background align. |
| 🟡 YELLOW | Questionable. Some gaps. Investigate before engaging. |
| 🟠 ORANGE | Significant concerns. Buzzword-heavy, circular validation. |
| 🔴 RED | Likely LARP. Claims unsupported by background or output. |

---

## Installation

```bash
# Extract the zip
unzip larp-meter.zip -d ~/larp-meter

# Or move it wherever you want
cd ~/larp-meter
```

**Dependencies:** Python 3.8+ (no external packages required — uses stdlib only).

**Optional (for web search):** `curl`, `requests`, or `httpx` for better fallback searching.

---

## Usage

The tool has three modes. **Text mode is the most reliable.**

### 1. Text Analysis (recommended)

Paste a LinkedIn bio, company website "About" page, or pitch text:

```bash
python larp-meter.py --text "President @ ExampleCo. Building Radiation-Tolerant Edge-AI Health Tech. Space-Origin Dual-Use for Defense. TRL 4 lab-validated. MoU signed with VUB. Seeking 8-12M funding. MSc European Public Health."
```

Output:
```
🟠 LEVEL: ORANGE  |  Red Flags: 5/10
  🔴 Claims deep-tech expertise but education background is in non-technical fields.
  🔴 Self-declared tech title but background is in policy/advocacy.
  🔴 Multiple organizations owned by same person — circular validation.
  🔴 No verifiable publications, patents, or products mentioned.
  🔴 No external validation — only forward-looking language.
```

### 2. Web Search Mode

Search the web for a person's public footprint:

```bash
python larp-meter.py "Jan Fictief"
```

**Note:** Most search engines (Google, Bing, DuckDuckGo) block automated requests from cloud/VPS IPs. Results may be unreliable. Use `--text` instead for accurate analysis.

### 3. Interactive Mode

Answer 7 questions about the subject:

```bash
python larp-meter.py --interactive
```

The tool walks you through: claimed role, education, domain, partners, traction, output, and press coverage. Good for quick gut-checks.

### 4. List Recent Audits

```bash
python larp-meter.py --list
```

Shows last 10 audits with level, score, and date.

---

## The 10 Red Flags

Each flag is a discrete, verifiable check:

| # | Flag | What It Detects |
|---|---|---|
| 1 | **Education ≠ Claimed Domain** | Public Health MSc claiming Space Hardware expertise |
| 2 | **Experience ≠ Declared Title** | "President @ Deep-Tech AI" but only policy roles in background |
| 3 | **Self-Referential Partners** | Own organizations listed as "partners" for circular validation |
| 4 | **Buzzword Density > 5** | "Paradigm-shifting exponential deep-tech synergist" language |
| 5 | **Vague Partnerships Only** | MoUs and NDAs instead of contracts, grants, or revenue |
| 6 | **No Verifiable Output** | Building/developing without papers, patents, or products |
| 7 | **No Customers / Revenue** | Fundraising without traction |
| 8 | **Exaggerated Credentials** | Claims degrees or affiliations without verification |
| 9 | **Logo Wall Syndrome** | Many partner logos but no deep collaboration |
| 10 | **No External Validation** | Only self-published content, zero third-party coverage |

---

## Output Files

| File | Location | Format |
|---|---|---|
| **Terminal report** | stdout | Colored text |
| **JSON report** | `output/YYYYMMDD_HHMMSS_name.json` | Machine-readable |
| **Obsidian note** | `~/Documents/Obsidian Vault/research/YYYYMMDD-larp-name.md` | Markdown (if vault exists) |

---

## Examples

```bash
# Analyze a real CTO
python larp-meter.py --text "CTO at OpenAI. MSc Mechanical Engineering, Tufts. Published ML papers."

# Analyze a suspicious profile
python larp-meter.py --text "Global Visionary Disruptor. TEDx speaker. MoU with MIT. Seeking partners."

# Interactive check
python larp-meter.py --interactive

# Web search (may be unreliable)
python larp-meter.py "Elon Musk"
```

---

## Architecture

```
larp-meter/
├── larp-meter.py          # Main CLI tool
├── output/                # Audit JSON reports
├── cache/                 # Web search cache
├── larp-meter.md          # This manual
└── README → larp-meter.md
```

---

## Limitations

- **Web search is blocked on cloud/VPS IPs** — Google, Bing, and DDG serve CAPTCHAs. Use `--text` mode instead.
- **Text analysis requires the right keywords to be present** — it's regex-based, not semantic. Results improve with longer, more detailed text.
- **Not a replacement for human due diligence** — flags indicate probabilities, not certainties. Use as a triage tool, not a verdict.

---

## License

MIT. Free to use, modify, and share.
