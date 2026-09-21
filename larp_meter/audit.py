"""Audit orchestration: text/corpus in, structured report out.

One pipeline serves every mode (text, file, web, batch) so the methodology
cannot drift between them — that duplication was a real bug source in v1/v2.
"""

from datetime import datetime
from pathlib import Path

from . import __version__, TRIGGERED, PASSED, UNKNOWN
from . import extract as ex
from . import reconcile
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
    reconciliations = []
    if verify:
        # Only an explicitly supplied name may drive attribution. Falling back
        # to `target` would feed a UI placeholder into the name comparison.
        verifier = Verifier(Path(cache_dir or ".") / "verify", subject_name=subject_name)
        verifier.verify_all(claims, progress=progress)
        # The reverse path: claims that imply a register entry are checked
        # even when the subject supplied no identifier at all. Same opt-in as
        # every other network call -- nothing is contacted without --verify.
        # Web modes are excluded: their corpus is search results about many
        # people, so a role claim found in it is not the subject's own account.
        if not str(mode).endswith("web"):
            reconciliations = reconcile.reconcile_text(text, subject_name or "",
                                                       Path(cache_dir or ".") / "reconcile")

    # `verify` alone only means the flag was passed -- it says nothing about
    # whether any registry was actually reached. verify_all's dispatch is
    # gated on HANDLERS, so a profile with zero checkable identifiers (a
    # fabricator's cheapest evasion) leaves every claim UNCHECKED and makes
    # zero calls; "verified" must not read the same as a run that genuinely
    # checked something, or the report's one honesty disclaimer disappears
    # for exactly the profile that needed it most.
    # A company that merely exists says nothing about the subject, so only a
    # register answer that confirms or contradicts them counts here.
    verification_effective = bool(verify) and (
        any(c.status != ex.UNCHECKED for c in claims)
        or any(r.outcome in (reconcile.CONFIRMED, reconcile.CONTRADICTED) for r in reconciliations))

    ctx = AuditContext(
        text=text,
        claims=claims,
        source_urls=source_urls,
        subject_name=subject_name or "",
        banks=banks or load_banks(),
        verified=bool(verify),
        signals=signals,
        reconciliations=reconciliations,
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
        "verification_effective": verification_effective,
        "level": verdict["level"],
        "larp_score": verdict["score"],          # None when coverage is too low to grade
        "raw_score": verdict["raw_score"],
        "scored": verdict["scored"],
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
        "reconciliations": [r.to_dict() for r in reconciliations],
        "signals": signals,
        "sources": source_urls,
        "verifier_stats": (
            {"api_calls": verifier.calls,
             "network_failures": verifier.network_failures,
             # Which claim classes no registry was asked about. Without this a
             # reader cannot tell a clean check from one that never ran.
             "skipped_subtypes": dict(sorted(verifier.skipped.items()))}
            if verifier else None),
    }


def counts(report):
    out = {TRIGGERED: 0, PASSED: 0, UNKNOWN: 0}
    for f in report["flags"]:
        out[f["status"]] = out.get(f["status"], 0) + 1
    return out
