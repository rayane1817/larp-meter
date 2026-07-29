"""Weighted, coverage-aware scoring.

The score is a ratio over *decided* flags only. Flags the evidence cannot
settle are excluded from both numerator and denominator, and instead lower the
coverage figure — so a thin profile produces "I don't know", not "looks clean".
"""

from . import TRIGGERED, PASSED
from .flags import REGISTRY, FLAG_BY_ID, TOTAL_WEIGHT

LEVELS = [
    (20, "GREEN", "Claims and verifiable substance broadly align."),
    (40, "YELLOW", "Some image-versus-substance gap. Verify the specifics before engaging."),
    (65, "ORANGE", "Significant concerns across weighted flags. Deep due diligence required."),
    (101, "RED", "Strong LARP pattern: claims are structurally unsupported by any verifiable evidence."),
]

MIN_COVERAGE = 0.35


def score(results):
    trig_w = sum(FLAG_BY_ID[i]["weight"] for i, r in results.items() if r.status == TRIGGERED)
    pass_w = sum(FLAG_BY_ID[i]["weight"] for i, r in results.items() if r.status == PASSED)
    decided_w = trig_w + pass_w
    coverage = decided_w / TOTAL_WEIGHT if TOTAL_WEIGHT else 0.0
    larp = round(100 * trig_w / decided_w) if decided_w else 0

    scored = coverage >= MIN_COVERAGE
    decided_flags = sum(1 for r in results.values() if r.status in (TRIGGERED, PASSED))
    if not scored:
        level = "INSUFFICIENT DATA"
        # Say what was actually missing, and note the one thing a reader can do
        # with this verdict: a profile that is genuinely this content-free is
        # itself worth remarking on, though it is not evidence of anything.
        summary = (f"Only {decided_flags} of {len(REGISTRY)} flags could be decided, which is too "
                   f"little to score responsibly. Supply the full profile text, or run web mode "
                   f"with --verify. If this already IS the subject's complete public presentation, "
                   f"its thinness is worth noting — but thinness is not evidence of deception.")
    else:
        level, summary = next((lv, s) for cut, lv, s in LEVELS if larp < cut)
        level, summary = _apply_floors(results, level, summary)

    return {
        # `scored` gates the number: a report can reach 100 on a single decided
        # flag, and a consumer filtering on larp_score alone would read that as
        # maximum risk rather than "not enough evidence to say anything".
        "score": larp if scored else None,
        "raw_score": larp,
        "scored": scored,
        "coverage": round(coverage * 100),
        "level": level,
        "summary": summary,
        "categories": category_scores(results),
        "decided": sum(1 for r in results.values() if r.status in (TRIGGERED, PASSED)),
        "triggered": sum(1 for r in results.values() if r.status == TRIGGERED),
        "total_flags": len(REGISTRY),
    }


_SEVERITY_ORDER = ["GREEN", "YELLOW", "ORANGE", "RED"]


def _apply_floors(results, level, summary):
    """Stop a categorically strong signal being averaged away.

    Most flags read self-presentation: they pass on the subject's own word. A
    public registry contradicting a claim is different in kind, and without a
    floor a fabricated profile could absorb one contradiction under a pile of
    unverified assertions and still come out GREEN. Observed doing exactly
    that: a wholly invented bio citing a nonexistent repository and a patent
    belonging to someone else scored GREEN 18/100.
    """
    floored = [FLAG_BY_ID[i] for i, r in results.items()
               if r.status == TRIGGERED and FLAG_BY_ID[i].get("floor")]
    if not floored:
        return level, summary

    strongest = max(floored, key=lambda f: _SEVERITY_ORDER.index(f["floor"]))
    if _SEVERITY_ORDER.index(strongest["floor"]) <= _SEVERITY_ORDER.index(level):
        return level, summary

    return strongest["floor"], (
        f"Held at {strongest['floor']} by '{strongest['name']}': a public registry contradicts a "
        f"specific claim. That is evidence about the world rather than about how the profile is "
        f"written, so the rest of the profile reading well does not offset it.")


def category_scores(results):
    """Per-dimension breakdown — one number hides where the problem actually is."""
    buckets = {}
    for spec in REGISTRY:
        r = results.get(spec["id"])
        if r is None or r.status not in (TRIGGERED, PASSED):
            continue
        b = buckets.setdefault(spec["category"], {"trig": 0.0, "dec": 0.0, "flags": 0})
        b["dec"] += spec["weight"]
        b["flags"] += 1
        if r.status == TRIGGERED:
            b["trig"] += spec["weight"]
    return {cat: {"score": round(100 * v["trig"] / v["dec"]) if v["dec"] else None,
                  "flags_decided": v["flags"]}
            for cat, v in sorted(buckets.items())}
