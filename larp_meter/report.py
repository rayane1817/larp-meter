"""Renderers: terminal, Markdown (Obsidian), and a self-contained HTML report."""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from . import TRIGGERED, PASSED, UNKNOWN
from .extract import VERIFIED, MISMATCH, NOT_FOUND, UNCHECKABLE, UNCHECKED

LEVEL_ICON = {"GREEN": "🟢", "YELLOW": "🟡", "ORANGE": "🟠", "RED": "🔴",
              "INSUFFICIENT DATA": "⚪"}
CLAIM_ICON = {VERIFIED: "✔", MISMATCH: "✗", NOT_FOUND: "✗", UNCHECKABLE: "…",
              UNCHECKED: "·"}


def score_text(report, suffix="/100"):
    """The score, or an explicit n/a when coverage was too low to grade."""
    if report.get("larp_score") is None:
        return "n/a"
    return f"{report['larp_score']}{suffix}"


def caveats(report):
    """Things a human must know before acting on this report."""
    out = []
    signals = report.get("signals") or {}

    if signals.get("ambiguous_identity"):
        out.append(f"{signals['ambiguous_identity']} different people share this name in the "
                   f"scholarly record — confirm this report is about the right person.")

    shared = signals.get("shared_name_evidence") or {}
    if shared:
        out.append("This name is shared by more than one person — the search returned "
                   + ", ".join(sorted(shared))
                   + ". A name is not an identifier: material about a different individual may "
                     "have been read as the subject's. Re-run against a specific profile with "
                     "--text before relying on any of this.")

    discarded = report.get("sources_discarded") or []
    if discarded:
        out.append(f"{len(discarded)} search result(s) were set aside as not clearly about the "
                   f"subject and were not scored.")

    failed = report.get("providers_failed") or []
    if failed:
        out.append(f"No data from: {', '.join(failed)}. Absent sources lower coverage; they are "
                   f"not evidence against the subject.")

    checkable = [c for c in report.get("claims", [])
                 if c.get("subtype") in ("doi", "orcid", "github", "arxiv", "nct", "patent")]
    if checkable and not report.get("verified"):
        out.append(f"{len(checkable)} identifier(s) could be checked against a public registry "
                   f"but were not — re-run with --verify.")

    # The most important thing a reader can misunderstand. Nothing in text mode
    # establishes that a claim is TRUE — only that the profile is internally
    # consistent and specific. A fabricated bio that asserts the right things
    # passes, and does so easily.
    if (report.get("level") in ("GREEN", "YELLOW") and not report.get("verified")
            and not (report.get("signals") or {}).get("wikipedia_about_subject")):
        out.append("Nothing here was checked against an outside source: the passing flags rest on "
                   "the subject's own account of themselves. A well-written fabrication passes "
                   "this easily — treat a clean result as 'no internal contradictions found', "
                   "not as corroboration.")

    if report.get("evidence_coverage_pct", 100) < 50:
        out.append(f"Only {report.get('evidence_coverage_pct')}% of the flag weight could be "
                   f"decided; treat the score as provisional.")

    if report.get("specificity_index", 99) < 2 and report.get("word_count", 0) >= 40:
        out.append("The material is short on verifiable detail (dates, figures, identifiers), "
                   "which limits what any tool can conclude.")
    return out


def _supports_color():
    return sys.stdout.isatty() and not sys.platform.startswith("emscripten")


class _C:
    def __init__(self, on):
        self.red = "\033[91m" if on else ""
        self.yellow = "\033[93m" if on else ""
        self.green = "\033[92m" if on else ""
        self.grey = "\033[90m" if on else ""
        self.bold = "\033[1m" if on else ""
        self.reset = "\033[0m" if on else ""


def level_color(c, level):
    return {"GREEN": c.green, "YELLOW": c.yellow, "ORANGE": c.yellow,
            "RED": c.red, "INSUFFICIENT DATA": c.grey}.get(level, "")


def _bar(pct, width=24):
    if pct is None:
        return "—"
    filled = round(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def render_terminal(report, show_claims=True):
    c = _C(_supports_color())
    out = []
    lvl = report["level"]
    out.append("")
    out.append(f"  {'─' * 62}")
    out.append(f"  {LEVEL_ICON.get(lvl, '⚪')} {level_color(c, lvl)}{c.bold}{lvl}{c.reset}"
               f"   LARP score {score_text(report)}"
               f"   ·  evidence coverage {report['evidence_coverage_pct']}%"
               f"   ·  {'verified' if report['verified'] else 'unverified'}")
    out.append(f"  {'─' * 62}")
    out.append(f"  {report['summary']}")
    spec = report["specificity_index"]
    out.append(f"  Specificity: {spec} verifiable details per 100 words "
               f"({'low — vague' if spec < 2 else 'reasonable'})")
    out.append("")

    if report["categories"]:
        out.append(f"  {c.bold}Risk by dimension{c.reset}")
        for cat, v in report["categories"].items():
            s = v["score"]
            col = c.red if s is not None and s >= 65 else c.yellow if s is not None and s >= 35 else c.green
            out.append(f"    {cat:<14} {col}{_bar(s)}{c.reset} {s if s is not None else '—'!s:>4}"
                       f"  {c.grey}({v['flags_decided']} flags){c.reset}")
        out.append("")

    buckets = {TRIGGERED: [], PASSED: [], UNKNOWN: []}
    for f in report["flags"]:
        buckets[f["status"]].append(f)

    if buckets[TRIGGERED]:
        out.append(f"  {c.red}{c.bold}TRIGGERED ({len(buckets[TRIGGERED])}){c.reset}")
        for f in buckets[TRIGGERED]:
            out.append(f"  [{f['id']:>2}] {c.bold}{f['name']}{c.reset}  "
                       f"{c.grey}weight {f['weight']} · {f['category']}{c.reset}")
            out.append(f"       {f['description']}")
            for e in f["evidence"][:3]:
                out.append(f"       {c.grey}→ {e}{c.reset}")
        out.append("")
    if buckets[PASSED]:
        out.append(f"  {c.green}PASSED ({len(buckets[PASSED])}){c.reset}")
        for f in buckets[PASSED]:
            out.append(f"  [{f['id']:>2}] {f['name']} — {f['description']}")
        out.append("")
    if buckets[UNKNOWN]:
        out.append(f"  {c.grey}UNDECIDABLE ({len(buckets[UNKNOWN])}) — excluded from the score, "
                   f"not counted as passed{c.reset}")
        for f in buckets[UNKNOWN]:
            out.append(f"  {c.grey}[{f['id']:>2}] {f['name']} — {f['description']}{c.reset}")
        out.append("")

    checked = [cl for cl in report["claims"] if cl["status"] != UNCHECKED]
    if show_claims and checked:
        out.append(f"  {c.bold}Claim ledger{c.reset}  {c.grey}(registry lookups){c.reset}")
        for cl in checked[:14]:
            col = (c.green if cl["status"] == VERIFIED else
                   c.red if cl["status"] in (MISMATCH, NOT_FOUND) else c.grey)
            out.append(f"    {col}{CLAIM_ICON.get(cl['status'], '·')}{c.reset} "
                       f"{cl['subtype']:<12} {cl['value'][:38]:<38} {col}{cl['status']}{c.reset}")
            if cl["detail"]:
                out.append(f"      {c.grey}{cl['detail'][:90]}{c.reset}")
        out.append("")

    if report["sources"]:
        out.append(f"  {c.grey}Sources consulted: {len(report['sources'])}{c.reset}")
        for u in report["sources"][:5]:
            out.append(f"  {c.grey}  • {u[:88]}{c.reset}")
        out.append("")

    notes = caveats(report)
    if notes:
        out.append(f"  {c.yellow}Read this before acting{c.reset}")
        for n in notes:
            out.append(f"    • {n}")
        out.append("")

    out.append(f"  {c.grey}Triage output, not a verdict. Every flag is a lead to verify by hand "
               f"before you act on it.{c.reset}")
    return "\n".join(out)


def render_markdown(report):
    lines = [
        "---",
        f"created: {report['timestamp']}",
        "source: larp-meter",
        "tags: [larp, osint, research]",
        f"larp_score: {report['larp_score'] if report.get('larp_score') is not None else 'null'}",
        f"level: {report['level']}",
        "status: final",
        "---",
        "",
        f"# LARP Audit: {report['target']}",
        "",
        f"**Level:** {report['level']}  ",
        f"**LARP score:** {score_text(report)}  ",
        f"**Evidence coverage:** {report['evidence_coverage_pct']}%  ",
        f"**Specificity index:** {report['specificity_index']}  ",
        f"**Registry verification:** {'yes' if report['verified'] else 'no'}  ",
        f"**Summary:** {report['summary']}",
        "",
    ]
    if report["categories"]:
        lines += ["## Risk by dimension", "", "| Dimension | Score | Flags decided |", "|---|---|---|"]
        for cat, v in report["categories"].items():
            lines.append(f"| {cat} | {v['score'] if v['score'] is not None else '—'} | {v['flags_decided']} |")
        lines.append("")

    for status, heading in ((TRIGGERED, "## 🔴 Triggered"), (PASSED, "## ✅ Passed"),
                            (UNKNOWN, "## ❔ Undecidable")):
        flags = [f for f in report["flags"] if f["status"] == status]
        if not flags:
            continue
        lines += [heading, ""]
        for f in flags:
            lines.append(f"- **[{f['id']}] {f['name']}** *(weight {f['weight']}, {f['category']})* — {f['description']}")
            for e in f["evidence"][:3]:
                lines.append(f"    - {e}")
        lines.append("")

    checked = [c for c in report["claims"] if c["status"] != UNCHECKED]
    if checked:
        lines += ["## Claim ledger", "", "| Type | Claim | Status | Detail |", "|---|---|---|---|"]
        for c in checked:
            detail = (c["detail"] or "").replace("|", "\\|")
            lines.append(f"| {c['subtype']} | {c['value'][:50]} | {c['status']} | {detail[:80]} |")
        lines.append("")

    notes = caveats(report)
    if notes:
        lines += ["## Read this before acting", ""] + [f"- {n}" for n in notes] + [""]

    if report["sources"]:
        lines += ["## Sources", ""] + [f"- {u}" for u in report["sources"][:20]] + [""]
    lines.append(f"*Generated by LARP Meter v{report['version']} on "
                 f"{datetime.now().strftime('%Y-%m-%d %H:%M')}. Triage output, not a verdict.*")
    return "\n".join(lines)


HTML_CSS = """
:root{--bg:#fff;--fg:#16181d;--muted:#6b7280;--card:#f7f8fa;--line:#e5e7eb;
--red:#c0392b;--amber:#b7791f;--green:#217a4b;--accent:#4b5563}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--fg:#e8eaed;--muted:#9aa1ab;
--card:#171a21;--line:#252a33;--red:#ff6b5e;--amber:#e0a44a;--green:#57c98a;--accent:#9aa1ab}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:820px;margin:0 auto;padding:40px 20px 80px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:16px;margin:32px 0 12px;
text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.sub{color:var(--muted);margin-bottom:28px;font-size:14px}
.hero{border:1px solid var(--line);border-radius:12px;padding:24px;background:var(--card);
display:flex;gap:24px;align-items:center;flex-wrap:wrap}
.score{font-size:46px;font-weight:700;line-height:1}
.level{font-size:13px;font-weight:700;letter-spacing:.1em;text-transform:uppercase}
.meta{color:var(--muted);font-size:13px}
.RED,.MISMATCH,.NOT_FOUND{color:var(--red)}.ORANGE,.YELLOW{color:var(--amber)}
.GREEN,.VERIFIED{color:var(--green)}.INSUFFICIENT{color:var(--muted)}
.dim{display:grid;grid-template-columns:130px 1fr 44px;gap:10px;align-items:center;margin:6px 0;font-size:13px}
.track{height:8px;background:var(--line);border-radius:99px;overflow:hidden}
.fill{height:100%;border-radius:99px}
.flag{border:1px solid var(--line);border-left-width:4px;border-radius:8px;padding:14px 16px;margin:10px 0;background:var(--card)}
.flag.t{border-left-color:var(--red)}.flag.p{border-left-color:var(--green)}.flag.u{border-left-color:var(--line)}
.flag h3{margin:0 0 6px;font-size:15px}.flag p{margin:0;color:var(--fg)}
.tag{font-size:11px;color:var(--muted);font-weight:400;margin-left:8px}
.ev{margin:8px 0 0;padding-left:18px;color:var(--muted);font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em}
.scroll{overflow-x:auto}
code{background:var(--card);padding:1px 5px;border-radius:4px;font-size:12px}
footer{margin-top:48px;padding-top:20px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}
a{color:inherit}
.caveats{border:1px solid var(--amber);border-radius:8px;padding:4px 18px 14px;margin-top:28px}
.caveats h2{color:var(--amber);margin-bottom:8px}
.caveats ul{margin:0;padding-left:18px;font-size:14px}
.caveats li{margin:4px 0}
"""


def _esc(s):
    # The single quote matters: every attribute in render_html is single-quoted,
    # so without it a crafted bio could close the attribute and inject a live
    # event handler into the document used to judge that person.
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#x27;"))


def _safe_href(url):
    """http/https only. Escaping alone does not close a javascript: sink."""
    try:
        scheme = urlsplit(str(url)).scheme.lower()
    except ValueError:
        return None
    return str(url) if scheme in ("http", "https") else None


def render_html(report):
    lvl = report["level"]
    lvl_cls = "INSUFFICIENT" if lvl.startswith("INSUF") else lvl
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width,initial-scale=1'>",
             f"<title>LARP Audit — {_esc(report['target'])}</title>",
             f"<style>{HTML_CSS}</style></head><body><div class='wrap'>"]
    parts.append(f"<h1>LARP Audit — {_esc(report['target'])}</h1>")
    parts.append(f"<div class='sub'>{_esc(report['timestamp'])} · mode: {_esc(report['mode'])} · "
                 f"{'registry-verified' if report['verified'] else 'no registry verification'} · "
                 f"{report['word_count']} words analysed</div>")

    parts.append("<div class='hero'>")
    parts.append(f"<div><div class='score {lvl_cls}'>{score_text(report, '')}</div>"
                 f"<div class='meta'>LARP score /100</div></div>")
    parts.append(f"<div style='flex:1;min-width:240px'><div class='level {lvl_cls}'>{_esc(lvl)}</div>"
                 f"<div style='margin:6px 0'>{_esc(report['summary'])}</div>"
                 f"<div class='meta'>Evidence coverage {report['evidence_coverage_pct']}% · "
                 f"specificity {report['specificity_index']} details/100 words</div></div>")
    parts.append("</div>")

    notes = caveats(report)
    if notes:
        parts.append("<div class='caveats'><h2>Read this before acting</h2><ul>"
                     + "".join(f"<li>{_esc(n)}</li>" for n in notes) + "</ul></div>")

    if report["categories"]:
        parts.append("<h2>Risk by dimension</h2>")
        for cat, v in report["categories"].items():
            s = v["score"] or 0
            col = "var(--red)" if s >= 65 else "var(--amber)" if s >= 35 else "var(--green)"
            parts.append(f"<div class='dim'><span>{_esc(cat)}</span>"
                         f"<span class='track'><span class='fill' style='width:{s}%;background:{col}'></span></span>"
                         f"<span>{v['score'] if v['score'] is not None else '—'}</span></div>")

    for status, label, cls in ((TRIGGERED, "Triggered", "t"), (PASSED, "Passed", "p"),
                               (UNKNOWN, "Undecidable — excluded from score", "u")):
        flags = [f for f in report["flags"] if f["status"] == status]
        if not flags:
            continue
        parts.append(f"<h2>{label} ({len(flags)})</h2>")
        for f in flags:
            parts.append(f"<div class='flag {cls}'><h3>[{f['id']}] {_esc(f['name'])}"
                         f"<span class='tag'>weight {f['weight']} · {_esc(f['category'])}</span></h3>"
                         f"<p>{_esc(f['description'])}</p>")
            if f["evidence"]:
                parts.append("<ul class='ev'>" +
                             "".join(f"<li>{_esc(e)}</li>" for e in f["evidence"][:4]) + "</ul>")
            parts.append("</div>")

    checked = [c for c in report["claims"] if c["status"] != UNCHECKED]
    if checked:
        parts.append("<h2>Claim ledger</h2><div class='scroll'><table>"
                     "<tr><th>Type</th><th>Claim</th><th>Status</th><th>Registry result</th></tr>")
        for c in checked:
            parts.append(f"<tr><td>{_esc(c['subtype'])}</td><td><code>{_esc(c['value'][:60])}</code></td>"
                         f"<td class='{_esc(c['status'])}'>{_esc(c['status'])}</td>"
                         f"<td>{_esc(c['detail'])}</td></tr>")
        parts.append("</table></div>")

    if report["sources"]:
        parts.append("<h2>Sources consulted</h2><ul class='ev'>")
        for u in report["sources"][:25]:
            safe = _safe_href(u)
            if safe:
                parts.append(f"<li><a href='{_esc(safe)}' rel='noreferrer noopener'>"
                             f"{_esc(u[:100])}</a></li>")
            else:
                parts.append(f"<li>{_esc(u[:100])}</li>")
        parts.append("</ul>")

    parts.append("<footer>Generated by LARP Meter v" + _esc(report["version"]) +
                 ". This is a triage instrument: flags are leads to verify by hand, "
                 "not conclusions about a person. Do not publish these outputs as accusations."
                 "</footer></div></body></html>")
    return "".join(parts)


def save_all(report, output_dir, vault_path=None, html_path=None, md_path=None,
             write_json=True, unique_suffix=""):
    """Write the requested artifacts. Returns the paths written.

    `write_json` is the --no-save switch: it suppresses the automatic report in
    output/, but an explicitly requested --html/--md is always honoured.
    `unique_suffix` keeps batch runs from overwriting each other when several
    subjects share a slug within the same second.
    """
    written = []
    output_dir = Path(output_dir)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", report["target"].lower()).strip("-")[:40] or "audit"
    stem = f"{ts}_{slug}" + (f"_{unique_suffix}" if unique_suffix else "")

    if write_json:
        output_dir.mkdir(parents=True, exist_ok=True)
        jp = output_dir / f"{stem}.json"
        jp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        written.append(jp)

    if html_path:
        hp = Path(html_path)
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text(render_html(report), encoding="utf-8")
        written.append(hp)
    if md_path:
        mp = Path(md_path)
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(render_markdown(report), encoding="utf-8")
        written.append(mp)

    if vault_path:
        research = Path(vault_path) / "research"
        if research.is_dir():
            vp = research / f"{ts[:8]}-larp-{slug}{'-' + unique_suffix if unique_suffix else ''}.md"
            vp.write_text(render_markdown(report), encoding="utf-8")
            written.append(vp)
    return written
