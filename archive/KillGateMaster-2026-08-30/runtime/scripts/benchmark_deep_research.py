#!/usr/bin/env python3
"""Run a deterministic, provider-free Deep Research contract benchmark."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.deep_research import (
    ResearchRunStatus,
    ResearchSourceRecord,
    ResearchSourceState,
)
from app.models.evidence_graph import EvidenceLink, EvidenceRelation
from app.services.deep_research import initialize_research_run
from app.services.evidence_graph import build_evidence_matrix
from app.services.research_planner import build_research_plan
from app.services.research_report import build_deep_research_report

_CASES = (
    {
        "name": "narrow-problem",
        "hypothesis": "Independent restaurants need earlier staffing warnings to reduce costly gaps.",
        "recommendation": "RESEARCH_PIVOT",
        "sources": ("https://example.com/pain", "https://example.org/alternative"),
    },
    {
        "name": "technical-uncertainty",
        "hypothesis": "Collision shops will pay $249/month if pre-teardown inputs predict hidden supplement omissions.",
        "recommendation": "FEASIBILITY_REQUIRED",
        "sources": ("https://example.net/constraint", "https://example.edu/pricing"),
    },
    {
        "name": "incumbent-bundle-contradiction",
        "hypothesis": "Independent retailers will pay separately for a feature already bundled by their POS provider.",
        "recommendation": "RESEARCH_PIVOT",
        "sources": ("https://example.com/incumbent", "https://example.org/customer-complaint"),
    },
    {
        "name": "pricing-unknown",
        "hypothesis": "Small clinics will pay for a workflow where public pricing is not available.",
        "recommendation": "RESEARCH_PIVOT",
        "sources": ("https://example.net/contact-sales", "https://example.edu/workaround"),
    },
    {
        "name": "customer-voice-shortfall",
        "hypothesis": "A narrow buyer community has enough public demand to justify direct validation.",
        "recommendation": "RESEARCH_PIVOT",
        "sources": ("https://example.com/community", "https://example.org/alternative"),
    },
)


def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    run = initialize_research_run(
        venture_id=f"benchmark-{case['name']}",
        venture_family_id=f"benchmark-family-{case['name']}",
        validation_contract={"version": "benchmark", "status": "locked"},
        hypothesis=case["hypothesis"],
        run_id=f"benchmark-{case['name']}",
    )
    build_research_plan(run, hypothesis=case["hypothesis"])
    run.sources = [
        ResearchSourceRecord(
            source_id=f"s{index}",
            url=url,
            title=f"Fixture source {index}",
            source_family=url.split("/")[2],
            relevance="direct",
            source_state=ResearchSourceState.QUALIFIED,
        )
        for index, url in enumerate(case["sources"], start=1)
    ]
    links = [
        EvidenceLink(
            claim_id=run.plan.claims[0].claim_id,
            source_id=source.source_id,
            relation=EvidenceRelation.SUPPORTS,
            source_family=source.source_family,
            direct=True,
        )
        for source in run.sources
    ]
    run.status = ResearchRunStatus.COMPLETED
    run.result = {"recommendation": case["recommendation"], "plain_summary": "fixture benchmark"}
    matrix = build_evidence_matrix(run.plan.claims, links)
    report = build_deep_research_report(run, evidence_matrix=matrix)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    source_ids = set(report.source_ids)
    linked_ids = {
        source_id
        for row in report.evidence_matrix.values()
        for source_id in row.get("supporting_source_ids", [])
    }
    return {
        "name": case["name"],
        "elapsed_ms": elapsed_ms,
        "verdict": report.verdict.value,
        "cost_usd": run.cost.estimated_cost_usd,
        "citation_integrity": linked_ids <= source_ids and bool(source_ids),
        "source_count": len(source_ids),
        "qualified_source_count": len(report.qualified_source_ids),
        "unknown_claim_count": len(report.unknowns),
    }


def run_benchmark() -> dict[str, Any]:
    cases = [_run_case(case) for case in _CASES]
    return {
        "benchmark": "deep-research-contract-v1",
        "provider_calls": 0,
        "generated_at": datetime.now(UTC).isoformat(),
        "cases": cases,
        "aggregate": {
            "case_count": len(cases),
            "max_elapsed_ms": max(case["elapsed_ms"] for case in cases),
            "total_cost_usd": round(sum(case["cost_usd"] for case in cases), 8),
            "citation_integrity": all(case["citation_integrity"] for case in cases),
            "qualified_source_count": sum(case["qualified_source_count"] for case in cases),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    args = parser.parse_args()
    payload = json.dumps(run_benchmark(), indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
