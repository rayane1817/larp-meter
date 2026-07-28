#!/usr/bin/env python3
"""
LARP Meter — Standalone OSINT Tool
==================================
Audits a person's LinkedIn-front vs real-achievements gap.

Usage:
    python larp-meter.py "Jan Fictief"
    python larp-meter.py "Jan Fictief" --linkedin https://ch.linkedin.com/in/jan-fictief
    python larp-meter.py --url https://be.linkedin.com/in/voorbeeldpersoon
    python larp-meter.py list

Output:
    - Terminal report
    - JSON saved to output/
    - Obsidian note saved to vault
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────
HERMES_HOME = os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))
VAULT_PATH = os.environ.get("OBSIDIAN_VAULT_PATH", str(Path.home() / "Documents" / "Obsidian Vault"))
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def fetch_url(url, timeout=15):
    """Platform-safe URL fetch. Uses requests if available, fallback to curl."""
    try:
        import requests
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, allow_redirects=True)
        return r.text
    except ImportError:
        pass
    try:
        import httpx
        r = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True)
        return r.text
    except ImportError:
        pass
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        pass
    return ""


def search_web(query, limit=5):
    """Search web — tries Bing with fallback to basic fetch.
    Note: Most search engines block automated requests from this machine."""
    import urllib.parse
    encoded = urllib.parse.quote(query)
    url = f"https://www.bing.com/search?q={encoded}"
    
    html = fetch_url(url)
    if not html or len(html) < 1000:
        return []

    # Try to find real result links (not Bing redirects)
    real_links = re.findall(r'<a[^>]+href="(https?://(?!.*bing\.com)[^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL)
    
    results = []
    seen = set()
    for url, title_text in real_links:
        if url in seen:
            continue
        seen.add(url)
        title = re.sub(r'<[^>]+>', '', title_text).strip()
        if title and url.startswith('http'):
            results.append((url, title))
            if len(results) >= limit:
                break

    return results


def run_osint(name):
    """
    Gather evidence for all 10 red flags using web search.
    Returns a dict with findings per flag.
    """
    print(f"  🔍 Searching public web for '{name}'...")
    sys.stdout.flush()

    # ── Gather all search results ──
    queries = {
        "general": [f'"{name}"', f'"{name}" biography background'],
        "tech": [f'"{name}" technology OR AI OR hardware OR engineer OR startup', f'"{name}" radiation OR space OR health-tech'],
        "partners": [f'"{name}" partner OR collaboration OR MoU OR consortium', f'"{name}" "in partnership with" OR "working with"'],
        "education": [f'"{name}" education OR university OR degree OR MSc OR PhD OR studied'],
        "press": [f'"{name}" news OR interview OR article OR speaker'],
        "linkedin": [f'site:linkedin.com/in "{name}"'],
    }

    all_results = {}
    for category, query_list in queries.items():
        combined = []
        seen = set()
        for q in query_list:
            results = search_web(q, limit=5)
            for url, snippet in results:
                if url not in seen:
                    combined.append((url, snippet))
                    seen.add(url)
        all_results[category] = combined[:8]

    # ── Build text corpus ──
    corpus_parts = []
    for cat, results in all_results.items():
        for url, snippet in results:
            corpus_parts.append(snippet)
    corpus = " ".join(corpus_parts).lower()
    all_urls = [url for cat in all_results.values() for url, _ in cat]
    all_snippets = [s for cat in all_results.values() for _, s in cat]
    combined_text = " ".join(all_snippets)

    # Also try to get LinkedIn snippet separately
    linkedin_snippets = [s for url, s in all_results.get("linkedin", [])]
    linkedin_text = " ".join(linkedin_snippets).lower()

    evidence = {}

    # ── Flag 1: Education ≠ Claimed Domain ──
    # Keywords for technical background
    tech_edu_kw = ["engineering", "computer science", "physics", "electrical", "mechanical",
                   "biomedical", "mathematics", "informatics", "robotics", "aerospace",
                   "data science", "machine learning", "ai", "artificial intelligence",
                   "msc", "bsc", "phd", "doctor", "master of science", "bachelor of science",
                   "electronics", "telecommunications", "nuclear"]
    
    # Keywords for non-technical/policy background
    nontech_edu_kw = ["public health", "policy", "governance", "advocacy", "law",
                      "political science", "european studies", "international relations",
                      "sociology", "psychology", "business administration", "mba",
                      "master of arts", "bachelor of arts", "humanities", "history",
                      "philosophy", "communication", "marketing"]

    # Keywords for tech CLAIMS (what they say they do now)
    tech_claim_kw = ["ai", "artificial intelligence", "edge-ai", "radiation", "hardware",
                     "space", "dual-use", "deep-tech", "nuclear", "rocket", "satellite",
                     "machine learning", "neural network", "semiconductor", "sensor",
                     "biometric", "genomics", "robotics", "blockchain", "quantum"]

    # Check: do they claim tech expertise but have non-tech education?
    has_tech_claim = any(kw in corpus for kw in tech_claim_kw)
    has_tech_edu = any(kw in corpus for kw in tech_edu_kw)
    has_nontech_edu = any(kw in corpus for kw in nontech_edu_kw)

    if has_tech_claim and has_nontech_edu and not has_tech_edu:
        evidence[1] = {
            "triggered": True,
            "description": f"Claims expertise in deep-tech/AI/hardware domains but educational background appears to be in non-technical fields (policy, health, advocacy). No engineering/CS degree found in public search.",
            "sources": [url for url, _ in all_results.get("education", [])[:2] if url],
        }

    # ── Flag 2: Experience ≠ Declared Title ──
    # Check if actual work history matches claimed expert role
    policy_role_kw = ["patient advocacy", "secretary general", "policy officer", "public health",
                      "governance", "board member", "independent", "consultant", "advisor"]
    tech_role_kw = ["engineer", "developer", "cto", "chief technology", "head of engineering",
                    "research scientist", "scientist", "architect", "lead developer"]

    has_tech_title = any(kw in linkedin_text for kw in ["president", "founder", "ceo", "director", "head of"])
    has_nontech_experience = any(kw in corpus for kw in policy_role_kw)
    has_tech_experience = any(kw in corpus for kw in tech_role_kw)

    if not has_tech_experience and has_nontech_experience and has_tech_title:
        evidence[2] = {
            "triggered": True,
            "description": f"Self-declared leadership title (President/Founder/CEO) in tech domain, but work history shows policy/advocacy roles without technical positions.",
            "sources": all_urls[:3],
        }

    # ── Flag 3: Self-Referential Partners ──
    # Detect pattern: person's org A partners with person's org B
    own_orgs = re.findall(r'(?:founder|created|established|runs?|manage[ds]?)\s+(?:the\s+)?(\w+(?:\s+\w+)?)', combined_text)
    self_ref_kw = ["examplealliance", "exampleco", "examplefoundation", "example digital peer"]
    own_org_matches = [kw for kw in self_ref_kw if kw in combined_text.lower()]
    
    if len(own_org_matches) >= 2:
        evidence[3] = {
            "triggered": True,
            "description": f"Multiple organizations linked to the same person ({', '.join(own_org_matches)}). Risk of self-referential validation loop where own orgs certify each other.",
            "sources": [url for url, _ in all_results.get("partners", [])[:2]],
        }

    # ── Flag 4: Buzzword Density ──
    buzzwords_list = [
        "synergy", "transformation", "paradigm", "deep-tech", "ai-driven", "space-grade",
        "dual-use", "disruption", "innovation", "meta", "quantum", "radiation-tolerant",
        "edge-ai", "cutting-edge", "next-generation", "groundbreaking", "pioneering",
        "revolutionary", "state-of-the-art", "world-class", "disruptive", "game-changing",
        "bleeding-edge", "paradigm-shift", "thought-leadership", "innovative",
        "high-tech", "space-age", "future-proof", "sustainable", "eco-friendly",
    ]
    
    # Count buzzwords in LinkedIn-specific text first, then corpus
    target_text = linkedin_text + " " + combined_text if linkedin_text else combined_text
    buzzword_count = sum(1 for bw in buzzwords_list if bw in target_text)

    if buzzword_count >= 5:
        evidence[4] = {
            "triggered": True,
            "description": f"Found {buzzword_count} buzzwords in profile/headline. High buzzword density (>5) suggests image-crafting over substance.",
            "sources": [],
        }

    # ── Flag 5: Vague Partnerships ──
    vague_kw = ["mou", "non-disclosure", "nda", "in discussion", "discussions ongoing",
                "in talks", "preliminary", "exploratory", "letter of intent", "loi",
                "memorandum of understanding", "terms sheet", "heads of terms"]

    vague_count = sum(1 for kw in vague_kw if kw in combined_text.lower())
    specific_kw = ["grant", "funding", "contract", "joint venture", "joint development",
                   "co-development", "collaboration agreement", "strategic partnership",
                   "investment", "series a", "revenue", "customer", "pilot"]

    specific_count = sum(1 for kw in specific_kw if kw in combined_text.lower())

    if vague_count > specific_count:
        evidence[5] = {
            "triggered": True,
            "description": f"Claims use vague partnership language (MoU, NDA, 'discussions ongoing') more than concrete terms (grants, contracts, revenue). Signals partnerships are preliminary or aspirational.",
            "sources": [url for url, _ in all_results.get("partners", [])[:2]],
        }

    # ── Flag 6: No Verifiable Output ──
    output_kw = ["publication", "paper", "patent", "granted patent", "filed patent",
                 "open source", "github", "product launch", "certification",
                 "fda", "ce marking", "clinical trial", "peer-reviewed",
                 "doi", "researchgate", "google scholar", "academia"]

    has_output = any(kw in combined_text.lower() for kw in output_kw)
    has_self_published = any(domain in combined_text.lower() for domain in 
                            ["medium.com", "substack.com", "linkedin.com/pulse", "wordpress.com"])

    if not has_output and has_self_published:
        evidence[6] = {
            "triggered": True,
            "description": f"No verifiable publications, patents, or products found. Only self-published content (Medium, LinkedIn, blog) detected.",
            "sources": [],
        }

    # ── Flag 7: No Customers / Revenue ──
    traction_kw = ["customer", "revenue", "client", "user", "pilot customer",
                   "enterprise", "contract signed", "paying", "subscription",
                   "commercial", "recurring revenue", "arr", "mrr"]

    has_traction = any(kw in combined_text.lower() for kw in traction_kw)
    funding_ask_kw = ["seeking investment", "funding ask", "raise", "seed round",
                      "looking for investors", "join as investor", "invest in"]

    has_funding_ask = any(kw in combined_text.lower() for kw in funding_ask_kw)

    if has_funding_ask and not has_traction:
        evidence[7] = {
            "triggered": True,
            "description": f"Publicly seeking investment but no evidence of customers, revenue, or traction found.",
            "sources": [],
        }

    # ── Flag 8: Degree Verification ──
    edu_orgs = ["master", "bachelor", "phd", "msc", "bsc", "university", "college",
                "institute", "school of"]
    has_edu_mention = any(kw in combined_text.lower() for kw in edu_orgs)
    specific_degree = re.search(r'(?:MSc|Master|PhD|Bachelor|BSc|MA|BA)\s+(?:in|of|from)?\s+([^,.;]+)', combined_text, re.I)

    if not specific_degree and not has_edu_mention:
        evidence[8] = {
            "triggered": False,  # This is common - many people don't have edu online
            "description": "",
        }
    elif not specific_degree and has_edu_mention:
        # Mention of education but no specific degree claimed = suspicious
        evidence[8] = {
            "triggered": True,
            "description": f"Mentions education/degrees but no specific qualification or institution verifiable in public search.",
            "sources": [],
        }

    # ── Flag 9: Logo Wall Syndrome ──
    logo_partner_kw = ["partner", "collaborator", "member", "affiliate", "association",
                       "alliance", "network", "consortium", "foundation", "institute",
                       "center", "lab", "university", "ngo"]

    # Count partner orgs mentioned vs actual deep collaborations
    partner_count = sum(1 for kw in logo_partner_kw if kw in combined_text.lower())
    deep_collab_kw = ["co-authored", "joint paper", "joint research", "co-developed",
                      "integration partner", "technology partner", "reseller",
                      "oem", "distributor", "system integrator"]

    deep_collab_count = sum(1 for kw in deep_collab_kw if kw in combined_text.lower())

    if partner_count >= 5 and deep_collab_count == 0:
        evidence[9] = {
            "triggered": True,
            "description": f"Lists many partner organizations ({partner_count} mentions) but no evidence of deep collaboration (joint papers, integrations, co-development). Logo-wall pattern.",
            "sources": [url for url, _ in all_results.get("partners", [])[:2]],
        }

    # ── Flag 10: No Independent Press ──
    press_urls = [url for url, _ in all_results.get("press", [])]
    # Filter out self-published and owned domains
    owned_domains = ["linkedin.com", "facebook.com", "x.com", "medium.com/@",
                     "substack.com/@", "example-co.org", "examplealliance", "exampleco",
                     "wordpress.com", "blogspot.com", "wixsite.com"]

    external_press = []
    for url in press_urls:
        is_owned = any(domain in url.lower() for domain in owned_domains)
        is_self = name.lower().replace(" ", "") in url.lower() if name else False
        if not is_owned and not is_self:
            external_press.append(url)

    if len(external_press) == 0 and len(press_urls) > 0:
        evidence[10] = {
            "triggered": True,
            "description": f"All press/mentions appear to be self-published or on owned platforms. No independent third-party coverage found.",
            "sources": press_urls[:3],
        }

    return evidence


def run_audit(name, linkedin_url=None):
    """Run a full LARP audit."""
    print(f"\n{'='*60}")
    print(f"  LARP METER AUDIT")
    print(f"  Target: {name}")
    if linkedin_url:
        print(f"  LinkedIn: {linkedin_url}")
    print(f"{'='*60}\n")

    # Phase 1: OSINT
    evidence = run_osint(name)

    # Phase 2: Evaluate flags
    RED_FLAGS = [
        {"id": 1, "name": "Education ≠ Claimed Domain", "check": "Does their educational background match the field they claim expertise in?"},
        {"id": 2, "name": "Experience ≠ Declared Title", "check": "Does their actual work history support their self-declared role/title?"},
        {"id": 3, "name": "Self-Referential Partners", "check": "Are claimed 'partners' actually their own organizations or creations?"},
        {"id": 4, "name": "Buzzword Density > 5", "check": "Does the headline/tagline contain excessive vague terminology?"},
        {"id": 5, "name": "Vague Partnerships Only", "check": "Are claimed collaborations limited to MoUs, NDAs, or 'in discussion'?"},
        {"id": 6, "name": "No Verifiable Output", "check": "Have they actually produced anything? Papers, patents, code, products?"},
        {"id": 7, "name": "No Customers / Revenue", "check": "Does the company/venture have any traction?"},
        {"id": 8, "name": "Claims Degree/Accreditation Without Proof", "check": "Is their claimed education/accreditation verifiable?"},
        {"id": 9, "name": "Logo Wall Syndrome", "check": "Do they list many partners without deep collaboration evidence?"},
        {"id": 10, "name": "No Independent Press or Coverage", "check": "Is there any third-party coverage that doesn't originate from themselves?"},
    ]

    triggered = []
    for flag in RED_FLAGS:
        result = evidence.get(flag["id"], {})
        if result.get("triggered"):
            triggered.append({
                "id": flag["id"],
                "name": flag["name"],
                "description": result.get("description", ""),
                "sources": result.get("sources", []),
            })

    # Phase 3: Calculate level
    count = len(triggered)
    if count <= 1:
        level = "GREEN"
        summary = "Likely legitimate. Claims and background align."
    elif count <= 3:
        level = "YELLOW"
        summary = "Questionable. Some gap between image and reality. Investigate before engaging."
    elif count <= 5:
        level = "ORANGE"
        summary = "Significant concerns. Self-referential partners, buzzword-heavy, unverifiable claims."
    else:
        level = "RED"
        summary = "Likely LARP. Background doesn't match claims. Partners are circular. No real output."

    # ── Terminal output ──
    colors = {"GREEN": "🟢", "YELLOW": "🟡", "ORANGE": "🟠", "RED": "🔴"}
    
    print(f"\n  {'─'*50}")
    print(f"  {colors.get(level, '⚪')} LEVEL: {level}  |  Red Flags: {count}/10")
    print(f"  {'─'*50}")
    print(f"  {summary}\n")

    if triggered:
        print(f"  🔴 TRIGGERED FLAGS:")
        for flag in triggered:
            print(f"  [{flag['id']}] {flag['name']}")
            print(f"     {flag['description']}")
            for src in flag.get("sources", [])[:2]:
                print(f"     → {src}")
            print()

    passed = [f for f in RED_FLAGS if f["id"] not in [t["id"] for t in triggered]]
    print(f"  ✅ GREEN FLAGS (passed — {len(passed)}/10):")
    for flag in passed[:5]:
        print(f"     • {flag['name']}")
    if len(passed) > 5:
        print(f"     • ... and {len(passed)-5} more")

    # ── Save report ──
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r'[^a-zA-Z0-9]', '-', name.lower())[:40].strip('-')
    
    report = {
        "target": name,
        "linkedin_url": linkedin_url,
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "red_flags_count": count,
        "summary": summary,
        "triggered_flags": [
            {"id": f["id"], "name": f["name"], "description": f["description"]}
            for f in triggered
        ],
        "passed_flags": [f["id"] for f in passed],
    }

    json_path = OUTPUT_DIR / f"{timestamp}_{slug}.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  💾 JSON report: {json_path}")

    # Obsidian save
    vault_path = Path(VAULT_PATH)
    vault_research = vault_path / "research"
    if vault_research.exists():
        md_path = vault_research / f"{timestamp[:8]}-larp-{slug}.md"
        with open(md_path, "w") as f:
            f.write(f"---\ncreated: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\nsource: larp-meter\ntags: [larp, osint, research]\nstatus: final\n---\n\n")
            f.write(f"# LARP Audit: {name}\n\n")
            f.write(f"**Level:** {level}  \n**Red Flags:** {count}/10  \n**Summary:** {summary}\n\n")
            if linkedin_url:
                f.write(f"**LinkedIn:** {linkedin_url}\n\n")
            if triggered:
                f.write(f"## 🔴 Triggered Flags\n\n")
                for flag in triggered:
                    f.write(f"### [{flag['id']}] {flag['name']}\n{flag['description']}\n\n")
                    if flag.get("sources"):
                        for src in flag["sources"][:3]:
                            f.write(f"- {src}\n")
                    f.write("\n")
            if passed:
                f.write(f"## ✅ Passed Checks\n\n")
                for flag in passed:
                    f.write(f"- **{flag['name']}**: {flag['check']}\n")
            f.write(f"\n---\n*Generated by LARP Meter on {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")
        print(f"  📝 Obsidian note: {md_path}")

    return level, triggered


def list_audits():
    files = sorted(OUTPUT_DIR.glob("*.json"), reverse=True)
    if not files:
        print("No audits found. Run: python larp-meter.py \"Person Name\"")
        return
    print(f"\n{'='*60}")
    print(f"  RECENT LARP AUDITS")
    print(f"{'='*60}\n")
    for f in files[:10]:
        try:
            with open(f) as fh:
                data = json.load(fh)
            lvl = data.get("level", "?")
            emoji = {"GREEN": "🟢", "YELLOW": "🟡", "ORANGE": "🟠", "RED": "🔴"}.get(lvl, "⚪")
            print(f"  {emoji} {data['target'][:32]:32s} | {lvl:6s} | {data['red_flags_count']}/10 | {data['timestamp'][:10]}")
        except Exception:
            pass
    print()


def run_text_audit(name, text):
    """Audit based on provided text (LinkedIn bio, claims, etc.) instead of web search."""
    print(f"\n{'='*60}")
    print(f"  LARP METER — TEXT ANALYSIS")
    print(f"  Target: {name}")
    print(f"  Text Length: {len(text)} chars")
    print(f"{'='*60}\n")
    
    text_lower = text.lower()
    evidence = {}

    # ── Flag 1: Education ≠ Domain ──
    tech_edu_kw = ["engineering", "computer science", "physics", "electrical engineering", "mechanical engineering",
                   "biomedical engineering", "mathematics", "informatics", "aerospace engineering", "data science",
                   "bachelor of science", "bachelor of engineering", "bachelor of technology",
                   "electronics", "telecommunications", "chemical engineering", "nuclear engineering"]
    nontech_edu_kw = ["public health", "policy", "governance", "advocacy", "law",
                      "political science", "sociology", "psychology", "mba", "business administration",
                      "humanities", "history", "communication", "marketing", "arts", "european studies",
                      "international relations", "philosophy"]
    tech_claim_kw = ["ai", "edge-ai", "radiation", "hardware", "space", "dual-use",
                     "deep-tech", "nuclear", "rocket", "satellite", "machine learning",
                     "neural network", "semiconductor", "quantum", "robotics"]
    
    has_tech_claim = any(kw in text_lower for kw in tech_claim_kw)
    has_tech_edu = any(kw in text_lower for kw in tech_edu_kw)
    has_nontech_edu = any(kw in text_lower for kw in nontech_edu_kw)
    
    if has_tech_claim and has_nontech_edu and not has_tech_edu:
        evidence[1] = {"triggered": True, "description": "Claims deep-tech expertise but education background is in non-technical fields.", "sources": []}
    
    # ── Flag 2: Experience ≠ Title ──
    policy_role_kw = ["secretary general", "policy", "advocacy", "independent", "consultant", "advisor"]
    tech_role_kw = ["engineer", "developer", "cto", "chief technology", "scientist", "architect"]
    has_tech_title = any(kw in text_lower for kw in ["president", "founder", "ceo", "director", "head of"])
    has_nontech_exp = any(kw in text_lower for kw in policy_role_kw)
    has_tech_exp = any(kw in text_lower for kw in tech_role_kw)
    
    if has_tech_title and has_nontech_exp and not has_tech_exp:
        evidence[2] = {"triggered": True, "description": "Self-declared tech leadership title but background is in policy/advocacy/advisory roles, not technical positions.", "sources": []}
    
    # ── Flag 3: Self-Referential Partners ──
    # Check for multiple orgs owned by the same person
    orgs_found = []
    for org in ["examplealliance", "exampleco", "examplefoundation"]:
        if org in text_lower:
            orgs_found.append(org)
    if len(orgs_found) >= 2:
        evidence[3] = {"triggered": True, "description": f"Multiple organizations found ({', '.join(orgs_found)}) owned by same person. Risk of self-referential validation loop.", "sources": []}
    
    # ── Flag 4: Buzzword Density ──
    buzzwords_list = ["synergy", "transformation", "paradigm", "deep-tech", "ai-driven", "space-grade",
                      "dual-use", "disruption", "innovation", "meta", "quantum", "radiation-tolerant",
                      "edge-ai", "cutting-edge", "next-generation", "groundbreaking", "pioneering",
                      "revolutionary", "world-class", "disruptive", "game-changing", "bleeding-edge",
                      "thought-leadership", "future-proof", "state-of-the-art"]
    buzzword_count = sum(1 for bw in buzzwords_list if bw in text_lower)
    
    if buzzword_count >= 5:
        evidence[4] = {"triggered": True, "description": f"Found {buzzword_count} buzzwords in text. High buzzword density suggests image-crafting over substance.", "sources": []}
    
    # ── Flag 5: Vague Partnerships ──
    vague_kw = ["mou", "non-disclosure", "nda", "in discussion", "discussions ongoing", "in talks",
                "preliminary", "exploratory", "memorandum of understanding"]
    specific_kw = ["grant", "funding", "contract", "joint venture", "revenue", "customer", "pilot"]
    vague_count = sum(1 for kw in vague_kw if kw in text_lower)
    specific_count = sum(1 for kw in specific_kw if kw in text_lower)
    
    if vague_count > specific_count:
        evidence[5] = {"triggered": True, "description": "Claims use vague partnership language (MoU, NDA) more than concrete terms (grants, contracts, revenue).", "sources": []}
    
    # ── Flag 6: No Output ──
    output_kw = ["publication", "paper", "patent", "open source", "github", "product launch",
                 "certification", "fda", "clinical trial", "peer-reviewed"]
    has_output = any(kw in text_lower for kw in output_kw)
    if not has_output and any(kw in text_lower for kw in ["building", "developing", "creating", "patent pending"]):
        evidence[6] = {"triggered": True, "description": "No verifiable publications, patents, or products mentioned. Claims are about 'building' or 'developing' without evidence of output.", "sources": []}
    
    # ── Flag 7: No Customers ──
    traction_kw = ["customer", "revenue", "client", "user", "paying", "commercial"]
    funding_kw = ["seeking investment", "funding ask", "raise", "seed round", "looking for investors"]
    
    has_traction = any(kw in text_lower for kw in traction_kw)
    has_funding_ask = any(kw in text_lower for kw in funding_kw)
    
    if has_funding_ask and not has_traction:
        evidence[7] = {"triggered": True, "description": "Actively seeking investment but no mention of customers or revenue.", "sources": []}
    
    # ── Flag 9: Logo Wall Syndrome ──
    # Count organization/partner mentions vs specific collaboration language
    partner_orgs = re.findall(r'(?:partner|collaborat|alliance|consortium|member of|signed with|MoU with)\s+(?:with\s+)?(\w+(?:\s+\w+)?)', text_lower)
    if len(partner_orgs) >= 3:
        evidence[9] = {"triggered": True, "description": f"Lists many partner organizations ({len(partner_orgs)} mentions) but no evidence of deep collaboration.", "sources": []}
    
    # ── Flag 10: No External Validation ──
    external_kw = ["as featured in", "as seen on", "interviewed by", "published in", "recognized by", "awarded by"]
    has_external = any(kw in text_lower for kw in external_kw)
    if not has_external and any(kw in text_lower for kw in ["vision", "mission", "goal", "aspire", "seek"]):
        evidence[10] = {"triggered": True, "description": "No external validation or third-party recognition mentioned. Only forward-looking aspirational language.", "sources": []}
    
    # ── Evaluate ──
    RED_FLAGS = [
        {"id": 1, "name": "Education ≠ Claimed Domain", "check": "Does educational background match claimed expertise?"},
        {"id": 2, "name": "Experience ≠ Declared Title", "check": "Does work history support self-declared role?"},
        {"id": 3, "name": "Self-Referential Partners", "check": "Are claimed partners own organizations?"},
        {"id": 4, "name": "Buzzword Density > 5", "check": "Does text contain excessive buzzwords?"},
        {"id": 5, "name": "Vague Partnerships Only", "check": "Are collaborations MoUs/NDAs not contracts?"},
        {"id": 6, "name": "No Verifiable Output", "check": "Any papers, patents, products mentioned?"},
        {"id": 7, "name": "No Customers / Revenue", "check": "Any traction mentioned?"},
        {"id": 8, "name": "Exaggerated Credentials", "check": "Are claimed credentials verifiable?"},
        {"id": 9, "name": "Logo Wall Syndrome", "check": "Many partners but no deep collaboration?"},
        {"id": 10, "name": "Only Self-Published Claims", "check": "Any external validation mentioned?"},
    ]
    
    triggered = []
    for flag in RED_FLAGS:
        if flag["id"] in evidence and evidence[flag["id"]].get("triggered"):
            triggered.append(evidence[flag["id"]])
    
    count = len(triggered)
    if count <= 1:
        level, summary = "GREEN", "Likely legitimate. Claims and background align."
    elif count <= 3:
        level, summary = "YELLOW", "Questionable. Some gap between image and reality."
    elif count <= 5:
        level, summary = "ORANGE", "Significant concerns. Buzzword-heavy, unverifiable claims."
    else:
        level, summary = "RED", "Likely LARP. Background doesn't match claims."
    
    colors = {"GREEN": "🟢", "YELLOW": "🟡", "ORANGE": "🟠", "RED": "🔴"}
    print(f"  {'─'*50}")
    print(f"  {colors.get(level, '⚪')} LEVEL: {level}  |  Red Flags: {count}/10")
    print(f"  {'─'*50}")
    print(f"  {summary}\n")
    trunc = "..." if len(text) > 500 else ""
    print(f"  Analyzed text:\n  \"{text[:500]}{trunc}\"\n")
    if triggered:
        for t in triggered:
            print(f"  🔴 {t.get('description', 'Flag triggered')}")
    print()


def run_interactive():
    """Interactive mode — user enters/answers claims."""
    print("\n  LARP METER — INTERACTIVE MODE")
    print("  Answer each question to assess the profile.\n")
    
    score = 0
    flags = []
    
    print("  [1/7] What is their claimed title/role?")
    title = input("  > ").strip()
    
    print("  [2/7] What is their educational background?")
    edu = input("  > ").strip()
    
    print("  [3/7] What domain/industry do they claim expertise in?")
    domain = input("  > ").strip()
    
    print("  [4/7] List any claimed partners or collaborators (comma-separated):")
    partners = [p.strip() for p in input("  > ").strip().split(",") if p.strip()]
    
    print("  [5/7] Do they mention any specific customers, revenue, or traction? (y/n)")
    has_traction = input("  > ").strip().lower() in ("y", "yes")
    
    print("  [6/7] Do they mention any publications, patents, or products? (y/n)")
    has_output = input("  > ").strip().lower() in ("y", "yes")
    
    print("  [7/7] Is there independent press or third-party coverage? (y/n)")
    has_press = input("  > ").strip().lower() in ("y", "yes")
    
    # Evaluate
    if not has_traction:
        flags.append("No customers/revenue mentioned")
    if not has_output:
        flags.append("No publications/patents/products mentioned")
    if not has_press:
        flags.append("No independent press/coverage mentioned")
    if len(partners) > 3:
        flags.append(f"Lists {len(partners)} partners — logo wall risk")
    
    print(f"\n  {'─'*50}")
    print(f"  INTERACTIVE ASSESSMENT")
    print(f"  Red Flags: {len(flags)}")
    print(f"  {'─'*50}")
    if flags:
        for f in flags:
            print(f"  🔴 {f}")
    else:
        print("  ✅ No obvious red flags found.")
    print()


def main():
    parser = argparse.ArgumentParser(description="LARP Meter — Audit LinkedIn-front vs real-achievements gap")
    parser.add_argument("name", nargs="?", help="Person name to audit")
    parser.add_argument("--linkedin", "-l", help="LinkedIn profile URL")
    parser.add_argument("--url", help="Audit from LinkedIn URL only")
    parser.add_argument("--text", "-t", help="Paste LinkedIn bio/headline/claims text to analyze")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode — enter claims one by one")
    parser.add_argument("--list", action="store_true", help="List recent audits")
    args = parser.parse_args()

    if not args.name and not args.url:
        if args.list or (len(sys.argv) > 1 and sys.argv[1] in ("list", "ls")):
            list_audits()
            return
        if args.text:
            run_text_audit("Pasted text", args.text)
            return
        if args.interactive:
            run_interactive()
            return
        parser.print_help()
        return

    name = args.name or ""
    linkedin_url = args.linkedin or args.url or ""

    if not name and args.url:
        m = re.search(r'/in/([^/]+)', args.url)
        if m:
            name = m.group(1).replace("-", " ").title()

    run_audit(name, linkedin_url)


if __name__ == "__main__":
    main()
