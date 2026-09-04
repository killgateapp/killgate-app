from __future__ import annotations

from scripts.benchmark_deep_research import run_benchmark


def test_contract_benchmark_is_provider_free_and_citation_integrity_holds():
    result = run_benchmark()
    assert result["provider_calls"] == 0
    assert result["aggregate"]["case_count"] == 5
    assert result["aggregate"]["citation_integrity"] is True
    assert result["aggregate"]["total_cost_usd"] == 0.0
    assert all(case["citation_integrity"] for case in result["cases"])
    assert result["aggregate"]["qualified_source_count"] == 10
