#!/usr/bin/env python3
"""Deterministic Killgate gate evaluator.

Input: JSON file with optional `research` object and `direct_validation_records` list.
Output: JSON containing research verdict (if supplied) and final gate verdict.
Uses only Python standard library.
"""
from __future__ import annotations
import argparse, json, re, sys, unicodedata
from pathlib import Path

DEFAULTS = {
    "research": {"min_direct_sources": 3, "min_domains": 2},
    "human": {"min_conversations": 8, "min_strong_pain_ratio": 0.30,
              "min_price_positive": 4, "min_paid": 2, "max_before_reassessment": 20},
}

BAD_REFS = {"cash","paid","yes","none","n/a","na","receipt","payment","done"}

def buyer_key(v: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", v or "").strip()).casefold()

def concrete_price(v: str) -> bool:
    text = re.sub(r"\s+", " ", str(v or "").strip().lower().replace(",", ""))
    if not text: return False
    number = r"(\d+(?:\.\d{1,2})?)"
    patterns = [rf"(?:[$€£¥]\s*){number}", rf"{number}\s*(?:usd|eur|gbp|cad|aud|dollars?|euros?|pounds?|bucks?)\b",
                rf"{number}\s*(?:/\s*|per\s+)(?:day|week|month|mo|year|yr)s?\b", rf"{number}\s*(?:daily|weekly|monthly|annually|yearly)\b"]
    for pat in patterns:
        for m in re.finditer(pat, text, re.I):
            try:
                if float(m.group(1)) > 0: return True
            except Exception: pass
    try:
        return bool(re.fullmatch(r"\d+(?:\.\d{1,2})?", text)) and float(text) > 0
    except ValueError:
        return False

def meaningful_ref(v: str) -> bool:
    s = re.sub(r"\s+", " ", str(v or "").strip())
    return len(s) >= 5 and s.casefold() not in BAD_REFS

def qualified(r: dict) -> bool:
    if r.get("voided_at"): return False
    return all(str(r.get(k) or "").strip() for k in ["buyer_identifier","buyer_role","qualification_basis","recent_real_example","current_workaround"])

def is_price_positive(r: dict) -> bool:
    return bool(r.get("price_positive") and concrete_price(r.get("pilot_price_tested","")) and str(r.get("price_response") or "").strip())

def is_paid(r: dict) -> bool:
    try: amt = float(r.get("payment_amount"))
    except (TypeError,ValueError): amt = 0
    return r.get("payment_status") == "paid" and amt > 0 and meaningful_ref(r.get("payment_reference",""))

def research_gate(research: dict) -> dict:
    blockers=[]; passed=[]
    direct=int(research.get("direct_source_count",0) or 0)
    domains=int(research.get("independent_domain_count",0) or 0)
    coverage=research.get("coverage",{}) or {}
    support=int(research.get("source_backed_support_count",0) or 0)
    disconfirm=int(research.get("disconfirming_count",0) or 0)
    fatal=bool(research.get("fatal_constraint_unresolved",False))
    tests=[
      (direct>=3, f"DIRECT public sources {direct}/3"),
      (domains>=2, f"Independent domains/groups {domains}/2"),
      (bool(coverage.get("pain")), "Problem/pain coverage"),
      (bool(coverage.get("alternatives")), "Workaround/alternative coverage"),
      (bool(coverage.get("budget")), "Budget/pricing/spend coverage"),
      (bool(research.get("disconfirming_search_performed")), "Disconfirming search performed"),
      (support>=2, f"Source-backed supporting claims {support}/2"),
      (disconfirm>=2, f"Disconfirming/constraint findings {disconfirm}/2"),
      (not fatal, "No unresolved fatal constraint"),
    ]
    for ok,label in tests: (passed if ok else blockers).append(label)
    if blockers:
        verdict="RESEARCH_FAIL"
        # If source sufficiency is there but framing/economic coverage is the issue, call PIVOT.
        source_core = direct>=3 and domains>=2 and bool(coverage.get("pain")) and bool(coverage.get("alternatives"))
        if source_core and (not coverage.get("budget") or fatal): verdict="RESEARCH_PIVOT"
    else: verdict="RESEARCH_PASS"
    return {"recommendation":verdict,"passed":passed,"blockers":blockers}

def final_gate(data: dict, research_pass: bool) -> dict:
    records=data.get("direct_validation_records",[]) or []
    groups={}
    for r in records:
        if qualified(r): groups.setdefault(buyer_key(r.get("buyer_identifier","")),[]).append(r)
    groups={k:v for k,v in groups.items() if k}
    latest=[v[-1] for v in groups.values()]
    conversations=len(groups)
    strong=sum(1 for r in latest if r.get("pain_strength")=="strong")
    ratio=strong/conversations if conversations else 0.0
    pricepos=sum(1 for r in latest if is_price_positive(r))
    paid=sum(1 for g in groups.values() if any(is_paid(r) for r in g))
    unverified_price=sum(1 for r in latest if r.get("price_positive") and not is_price_positive(r))
    unverified_paid=sum(1 for g in groups.values() if not any(is_paid(r) for r in g) and any(r.get("payment_status")=="paid" for r in g))
    history=[r for g in groups.values() for r in g]
    contradictions=bool(history) and all(str(r.get("objection_or_no_reason") or "").strip() for r in history)
    contract_matches=bool(data.get("contract_matches_hypothesis",True))
    h=DEFAULTS["human"]
    passed=[]; blockers=[]
    checks=[
      (contract_matches,"Locked contract matches active hypothesis"),
      (research_pass,"Research Qualification Gate passed"),
      (conversations>=h["min_conversations"],f"Qualified buyers {conversations}/{h['min_conversations']}"),
      (ratio>=h["min_strong_pain_ratio"],f"Strong pain {ratio:.0%}/{h['min_strong_pain_ratio']:.0%}"),
      (pricepos>=h["min_price_positive"] or paid>=h["min_paid"],f"Price signal {pricepos} price-positive / {paid} paid"),
      (paid>=h["min_paid"],f"Verified paid pilots {paid}/{h['min_paid']}"),
      (contradictions,"Contradictions/no-priority reviewed for every qualified interaction"),
    ]
    for ok,label in checks: (passed if ok else blockers).append(label)
    all_go=all(ok for ok,_ in checks)
    ceiling=conversations>=h["max_before_reassessment"]
    if all_go: verdict="GO"
    elif not contract_matches or conversations<h["min_conversations"] or not research_pass: verdict="CONTINUE_VALIDATION"
    elif ratio<h["min_strong_pain_ratio"] and paid>=h["min_paid"]: verdict="PIVOT"
    elif ratio<h["min_strong_pain_ratio"]: verdict="KILL"
    elif ceiling and paid<h["min_paid"]: verdict="PIVOT"
    elif pricepos<h["min_price_positive"] and paid<h["min_paid"]: verdict="PIVOT"
    else: verdict="CONTINUE_VALIDATION"
    if unverified_price: blockers.append(f"{unverified_price} price-positive record(s) excluded: no concrete price and/or recorded reaction")
    if unverified_paid: blockers.append(f"{unverified_paid} paid record(s) excluded: missing positive amount and/or meaningful reference")
    return {"recommendation":verdict,"metrics":{"qualified_buyers":conversations,"strong_pain_count":strong,"strong_pain_ratio":round(ratio,4),"price_positive_count":pricepos,"paid_pilot_count":paid,"reassessment_ceiling_reached":ceiling,"contradictions_reviewed":contradictions,"contract_matches":contract_matches},"passed":passed,"blockers":blockers}

def evaluate(data: dict) -> dict:
    r = research_gate(data["research"]) if isinstance(data.get("research"),dict) else None
    research_pass = (r and r["recommendation"]=="RESEARCH_PASS") or bool(data.get("research_pass",False))
    f = final_gate(data, bool(research_pass))
    return {"research_gate":r,"final_gate":f}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("json_file")
    args=ap.parse_args()
    data=json.loads(Path(args.json_file).read_text(encoding="utf-8"))
    print(json.dumps(evaluate(data),indent=2))
if __name__=="__main__": main()
