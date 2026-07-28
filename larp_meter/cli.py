"""Command-line interface."""

import argparse
import csv
import json
import re
import os
import sys
from pathlib import Path

from . import __version__, TRIGGERED, PASSED, UNKNOWN
from .audit import run_audit
from .flags import REGISTRY, TOTAL_WEIGHT
from .matching import load_banks
from .report import (render_terminal, render_html, render_markdown, save_all,
                     score_text, LEVEL_ICON)
from .scoring import LEVELS, MIN_COVERAGE
from .search import gather

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(os.environ.get("LARP_OUTPUT", BASE_DIR / "output"))
CACHE_DIR = Path(os.environ.get("LARP_CACHE", BASE_DIR / "cache"))
VAULT_PATH = os.environ.get("OBSIDIAN_VAULT_PATH", str(Path.home() / "Documents" / "Obsidian Vault"))


def _fix_console():
    """Windows consoles default to cp1252 and cannot print the report glyphs."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _emit(report, args):
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_terminal(report))
    written = save_all(report, OUTPUT_DIR, vault_path=None if args.no_save else VAULT_PATH,
                       html_path=args.html, md_path=args.md,
                       write_json=not args.no_save)
    if not args.json:
        for p in written:
            print(f"  saved: {p}")


def _progress(args):
    if args.json or args.quiet:
        return None

    def report_progress(*a):
        if len(a) == 1:
            print(f"  · {a[0]}", flush=True)
        else:
            i, total, claim = a
            print(f"  · verifying {i}/{total}: {claim.subtype} {claim.value[:48]}", flush=True)
    return report_progress


def cmd_text(args, target, text):
    # `target` is a UI label — "pasted-text", "stdin", a filename. Passing it
    # as the subject's name made every genuine artifact a MISMATCH, because
    # "pasted-text" tokenizes to a real-looking name that matches nothing.
    if args.verify and not args.name and not args.quiet:
        print("  note: --verify without --name checks that artifacts exist, but cannot check "
              "whether they belong to the subject. Pass --name for attribution.")
    report = run_audit(target, text, mode="text", subject_name=args.name,
                       verify=args.verify, cache_dir=CACHE_DIR, progress=_progress(args))
    _emit(report, args)
    return report


def cmd_web(args, target):
    if not args.json and not args.quiet:
        print(f"\n  LARP METER v{__version__} — web audit of {target}")
    bundle = gather(target, CACHE_DIR, deep=args.deep, progress=_progress(args),
                    refresh=args.refresh)
    if not args.json and not args.quiet:
        if bundle.providers_ok:
            print(f"  sources answering: {', '.join(bundle.providers_ok)}"
                  + (f"  (no data from: {', '.join(bundle.providers_failed)})"
                     if bundle.providers_failed else ""))
        else:
            print("\n  ⚠ No source returned anything. Public APIs may be unreachable from this "
                  "network. Fall back to --text with a pasted bio.")
    report = run_audit(target, bundle.corpus, mode="web", source_urls=bundle.used_urls,
                       subject_name=args.name or target, verify=args.verify,
                       cache_dir=CACHE_DIR, progress=_progress(args),
                       signals=bundle.signals)
    report["providers_ok"] = bundle.providers_ok
    report["providers_failed"] = bundle.providers_failed
    report["sources_discarded"] = [f.url for f in bundle.discarded if f.url]
    if not args.json and not args.quiet:
        if bundle.discarded:
            print(f"  {len(bundle.discarded)} result(s) set aside as not clearly about "
                  f"{target} — they were NOT scored.")
        if bundle.signals.get("ambiguous_identity"):
            print(f"  ⚠ {bundle.signals['ambiguous_identity']} different people share this name "
                  f"in the scholarly record. Confirm you are looking at the right one.")
    _emit(report, args)
    return report


def cmd_batch(args):
    """Audit many subjects. Input: .jsonl of {name,text?} or one name/TSV pair per line."""
    path = Path(args.batch)
    entries = []
    if path.suffix == ".jsonl":
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                obj = json.loads(line)
                entries.append((obj.get("name") or obj.get("target", "unknown"), obj.get("text")))
    else:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            name, _, text = line.partition("\t")
            entries.append((name.strip(), text.strip() or None))

    rows = []
    for i, (name, text) in enumerate(entries, 1):
        print(f"\n[{i}/{len(entries)}] {name}")
        if text:
            report = run_audit(name, text, mode="batch-text", subject_name=name,
                               verify=args.verify, cache_dir=CACHE_DIR)
        else:
            bundle = gather(name, CACHE_DIR, deep=args.deep, refresh=args.refresh)
            report = run_audit(name, bundle.corpus, mode="batch-web", source_urls=bundle.urls,
                               subject_name=name, verify=args.verify, cache_dir=CACHE_DIR,
                               signals=bundle.signals)
        stem = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")[:40] or "audit"
        save_all(report, OUTPUT_DIR, vault_path=None,
                 html_path=(Path(args.html).parent / f"{i:03d}-{stem}.html") if args.html else None,
                 md_path=(Path(args.md).parent / f"{i:03d}-{stem}.md") if args.md else None,
                 write_json=not args.no_save, unique_suffix=f"{i:03d}")
        triggered = sum(1 for f in report["flags"] if f["status"] == TRIGGERED)
        print(f"      {LEVEL_ICON.get(report['level'], '⚪')} {report['level']} · "
              f"score {score_text(report, '')} · coverage {report['evidence_coverage_pct']}% · "
              f"{triggered} flags")
        rows.append({
            "target": name, "level": report["level"], "larp_score": report["larp_score"],
            "coverage_pct": report["evidence_coverage_pct"],
            "specificity": report["specificity_index"], "triggered_flags": triggered,
            "timestamp": report["timestamp"],
        })

    out_csv = Path(args.csv) if args.csv else OUTPUT_DIR / "batch-summary.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["target"])
        w.writeheader()
        w.writerows(rows)
    print(f"\n  summary CSV: {out_csv}")


def cmd_interactive(args):
    print(f"\n  LARP METER v{__version__} — guided assessment")
    print("  Answer from what the profile CLAIMS and what you can independently VERIFY.\n")

    def ask(q):
        print(f"  {q}")
        return input("  > ").strip()

    def yn(q):
        a = ask(q + "  (y / n / u for unknown)").lower()
        return PASSED if a.startswith("y") else TRIGGERED if a.startswith("n") else UNKNOWN

    from .flags import FlagResult
    from .scoring import score
    results = {}
    results[1] = FlagResult(yn("[1] Does their education match the domain they claim expertise in?"))
    results[2] = FlagResult(yn("[2] Does their work history include real roles in that domain?"))
    partners = ask("[3] Claimed partners (comma-separated, blank if none):")
    owned = ask("    Organizations they founded or lead (comma-separated):")
    p = {x.strip().casefold() for x in partners.split(",") if x.strip()}
    o = {x.strip().casefold() for x in owned.split(",") if x.strip()}
    both = p & o
    results[3] = FlagResult(TRIGGERED if both else (PASSED if p else UNKNOWN),
                            f"Own organization presented as partner: {', '.join(both)}" if both else
                            "Partners are independent of the subject's own organizations." if p else
                            "No partners named.")
    results[4] = FlagResult(yn("[4] Is the language concrete rather than hype?"))
    results[5] = FlagResult(yn("[5] Are partnerships backed by contracts or grants (not just MoU/NDA)?"))
    results[6] = FlagResult(yn("[6] Any verifiable output — papers, patents, code, shipped product?"))
    if ask("[7] Are they fundraising? (y/n)").lower().startswith("y"):
        results[7] = FlagResult(yn("    Do they show customers, revenue or usage?"))
    else:
        results[7] = FlagResult(UNKNOWN, "Not fundraising.")
    results[8] = FlagResult(yn("[8] Are claimed degrees tied to a named institution?"))
    results[9] = FlagResult(yn("[9] Evidence of deep collaboration with the listed partners?"))
    results[10] = FlagResult(yn("[10] Any independent press or third-party coverage?"))
    results[11] = FlagResult(yn("[11] Did every identifier you checked (DOI, patent, repo) check out?"))
    results[12] = FlagResult(yn("[12] Do the claimed dates and durations add up?"))

    verdict = score(results)
    report = {
        "version": __version__, "schema": 3, "target": "interactive assessment",
        "mode": "interactive", "timestamp": "", "verified": False,
        "level": verdict["level"], "larp_score": verdict["score"],
        "raw_score": verdict["raw_score"], "scored": verdict["scored"],
        "evidence_coverage_pct": verdict["coverage"], "specificity_index": 0.0,
        "summary": verdict["summary"], "categories": verdict["categories"],
        "word_count": 0,
        "flags": [{"id": s["id"], "name": s["name"], "weight": s["weight"],
                   "category": s["category"], "question": s["question"],
                   "status": results[s["id"]].status,
                   "description": results[s["id"]].description or s["question"],
                   "evidence": results[s["id"]].evidence}
                  for s in sorted(REGISTRY, key=lambda x: x["id"])],
        "claims": [], "claim_status_counts": {}, "sources": [], "verifier_stats": None,
    }
    print(render_terminal(report, show_claims=False))


def cmd_list(args):
    files = sorted(OUTPUT_DIR.glob("*.json"), reverse=True) if OUTPUT_DIR.is_dir() else []
    if not files:
        print('No audits yet. Try:  python larp-meter.py --text "<paste a bio>"')
        return
    print(f"\n  {'':2} {'TARGET':<28} {'LEVEL':<18} {'SCORE':>5} {'COV':>5} {'DATE':>11}")
    print(f"  {'─' * 74}")
    for f in files[:20]:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        print(f"  {LEVEL_ICON.get(d.get('level'), '⚪')} {str(d.get('target'))[:28]:<28} "
              f"{str(d.get('level')):<18} "
              f"{('n/a' if d.get('larp_score') is None else d.get('larp_score')):>5} "
              f"{str(d.get('evidence_coverage_pct', '—')):>4}% {str(d.get('timestamp'))[:10]:>11}")
    print()


def cmd_explain(args):
    print(f"""
  LARP METER v{__version__} — methodology

  SCORING
    LARP score = 100 x (weight of TRIGGERED flags) / (weight of DECIDED flags)
    coverage   = (weight of decided flags) / (total weight {TOTAL_WEIGHT})

    A flag the evidence cannot settle is UNKNOWN. It is excluded from the score
    entirely, and lowers coverage instead — absence of evidence is never scored
    as innocence. Below {int(MIN_COVERAGE * 100)}% coverage the tool refuses to grade at all
    and returns INSUFFICIENT DATA.

  THRESHOLDS""")
    prev = 0
    for cut, level, summary in LEVELS:
        print(f"    {LEVEL_ICON.get(level, ' ')} {level:<8} {prev:>3}–{min(cut - 1, 100):<3}  {summary}")
        prev = cut
    print("\n  FLAGS")
    for s in sorted(REGISTRY, key=lambda x: -x["weight"]):
        print(f"    [{s['id']:>2}] {s['name']:<32} w={s['weight']:<4} {s['category']:<14} {s['question']}")
    print(f"""
  VERIFICATION (--verify)
    Identifiers found in the text are checked against public registries:
      DOI          -> Crossref            ORCID        -> orcid.org
      arXiv ID     -> arXiv API           GitHub repo  -> GitHub API
      NCT number   -> ClinicalTrials.gov  Patent       -> Google Patents
      Institution  -> ROR (Research Organization Registry)

    Existence is not attribution: with --name, an artifact that exists but does
    not list the subject returns MISMATCH, which is weighted more heavily than a
    missing artifact. A network failure returns UNCHECKABLE and is never treated
    as evidence against the subject.

  LIMITS
    Keyword and pattern heuristics, not semantics. Sarcasm, negation and
    non-English text will fool it. Use the output as a list of things to check
    by hand, never as a conclusion about a person.
""")


def cmd_selftest(args):
    import unittest
    loader = unittest.TestLoader()
    suite = loader.discover(str(BASE_DIR / "tests"), pattern="test_*.py", top_level_dir=str(BASE_DIR))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def build_parser():
    p = argparse.ArgumentParser(
        prog="larp-meter",
        description=f"LARP Meter v{__version__} — audit public professional claims against "
                    f"verifiable evidence. Triage instrument for due diligence.",
        epilog="Run --explain to print the full scoring methodology.")
    p.add_argument("target", nargs="?", help="Name to audit via web search (or 'list')")
    src = p.add_argument_group("input")
    src.add_argument("--text", "-t", help="Analyze pasted bio/pitch/About text")
    src.add_argument("--file", "-f", help="Analyze text from a file")
    src.add_argument("--stdin", action="store_true", help="Analyze text piped on stdin")
    src.add_argument("--batch", help="Audit many subjects (.jsonl or name<TAB>text lines)")
    beh = p.add_argument_group("behaviour")
    beh.add_argument("--verify", action="store_true",
                     help="Check identifiers against public registries (network)")
    beh.add_argument("--deep", action="store_true",
                     help="Web mode: also fetch and read the top result pages")
    beh.add_argument("--refresh", action="store_true",
                     help="Ignore cached search results and re-query the sources")
    beh.add_argument("--name", help="Subject's real name, for attribution checks during --verify")
    beh.add_argument("--interactive", "-i", action="store_true", help="Guided 12-question assessment")
    out = p.add_argument_group("output")
    out.add_argument("--json", action="store_true", help="Print the report as JSON")
    out.add_argument("--html", help="Also write a self-contained HTML report to this path")
    out.add_argument("--md", help="Also write a Markdown report to this path")
    out.add_argument("--csv", help="Batch mode: path for the summary CSV")
    out.add_argument("--no-save", action="store_true", help="Do not write report files")
    out.add_argument("--quiet", "-q", action="store_true", help="Suppress progress output")
    misc = p.add_argument_group("other")
    misc.add_argument("--list", action="store_true", help="List recent audits")
    misc.add_argument("--explain", action="store_true", help="Print the scoring methodology")
    misc.add_argument("--selftest", action="store_true", help="Run the test suite")
    misc.add_argument("--version", action="version", version=f"larp-meter {__version__}")
    return p


def main(argv=None):
    _fix_console()
    args = build_parser().parse_args(argv)

    if args.selftest:
        return cmd_selftest(args)
    if args.explain:
        return cmd_explain(args)
    if args.list or args.target in ("list", "ls"):
        return cmd_list(args)
    if args.interactive:
        return cmd_interactive(args)
    if args.batch:
        return cmd_batch(args)
    if args.stdin:
        return cmd_text(args, args.target or "stdin", sys.stdin.read()) and None
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
        cmd_text(args, args.target or Path(args.file).stem, text)
        return
    if args.text:
        cmd_text(args, args.target or "pasted-text", args.text)
        return
    if args.target:
        cmd_web(args, args.target)
        return
    build_parser().print_help()
