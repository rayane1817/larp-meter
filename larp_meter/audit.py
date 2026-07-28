"""Audit orchestration: text/corpus in, structured report out.

One pipeline serves every mode (text, file, web, batch) so the methodology
cannot drift between them — that duplication was a real bug source in v1/v2.
"""

from datetime import datetime
from pathlib import Path

from . import __version__, TRIGGERED, PASSED, UNKNOWN
from . import extract as ex
from .flags import AuditContext, FLAG_BY_ID, REGISTRY, evaluate
from .matching import load_banks
from .scoring import score
from .verify import Verifier, summarize


def run_audit(target, text, mode="text", source_urls=None, subject_name=None,
              verify=False, cache_dir=None, banks=None, progress=None, signals=None):
    """Full pipeline. Returns a JSON-serializable report dict."""
    source_urls = source_urls or []
    signals = signals or {}
    claims = ex.extract_claims(text)

    verifier = None
    if verify:
        verifier = Verifier(Path(cache_dir or ".") / "verify",
                            subject_name=subject_name or target)
        verifier.verify_all(claims, progress=progress)

    ctx = AuditContext(
        text=text,
        claims=claims,
        source_urls=source_urls,
        subject_name=subject_name or target,
        banks=banks or load_banks(),
        verified=bool(verify),
        signals=signals,
    )
    results = evaluate(ctx)
    verdict = score(results)

    return {
        "version": __version__,
        "schema": 3,
        "target": target,
        "mode": mode,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "verified": bool(verify),
        "level": verdict["level"],
        "larp_score": verdict["score"],
        "evidence_coverage_pct": verdict["coverage"],
        "specificity_index": ex.specificity_index(text),
        "summary": verdict["summary"],
        "categories": verdict["categories"],
        "word_count": len(text.split()),
        "flags": [
            {
                "id": spec["id"],
                "name": spec["name"],
                "weight": spec["weight"],
                "category": spec["category"],
                "question": spec["question"],
                "status": results[spec["id"]].status,
                "description": results[spec["id"]].description,
                "evidence": results[spec["id"]].evidence,
            }
            for spec in sorted(REGISTRY, key=lambda s: s["id"])
        ],
        "claims": [c.to_dict() for c in claims],
        "claim_status_counts": summarize(claims),
        "signals": signals,
        "sources": source_urls,
        "verifier_stats": (
            {"api_calls": verifier.calls, "network_failures": verifier.network_failures}
            if verifier else None),
    }


def counts(report):
    out = {TRIGGERED: 0, PASSED: 0, UNKNOWN: 0}
    for f in report["flags"]:
        out[f["status"]] = out.get(f["status"], 0) + 1
    return out
