from __future__ import annotations

import pytest

from app.services.model_routing import (
    ResearchModelStage,
    model_for_stage,
    resolve_model_route,
    validate_model_routing,
)


def test_default_route_uses_luna_for_bounded_stages_and_terra_for_synthesis(monkeypatch):
    for name in (
        "DEEP_RESEARCH_PLANNER_MODEL",
        "DEEP_RESEARCH_EXTRACTOR_MODEL",
        "DEEP_RESEARCH_CONTRADICTION_MODEL",
        "DEEP_RESEARCH_SYNTHESIS_MODEL",
        "DEEP_RESEARCH_CRITIC_MODEL",
        "DEEP_RESEARCH_MAX_TOOL_CALLS",
        "DEEP_RESEARCH_ALLOW_SOL",
    ):
        monkeypatch.delenv(name, raising=False)
    route = resolve_model_route()
    assert route.for_stage(ResearchModelStage.PLANNER) == "gpt-5.6-luna"
    assert route.for_stage("extractor") == "gpt-5.6-luna"
    assert route.synthesis == "gpt-5.6-terra"
    assert route.max_tool_calls == 8


def test_sol_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("DEEP_RESEARCH_SYNTHESIS_MODEL", "gpt-5.6-sol")
    monkeypatch.delenv("DEEP_RESEARCH_ALLOW_SOL", raising=False)
    with pytest.raises(ValueError, match="disabled"):
        model_for_stage(ResearchModelStage.SYNTHESIS)
    assert validate_model_routing()

    monkeypatch.setenv("DEEP_RESEARCH_ALLOW_SOL", "1")
    assert model_for_stage(ResearchModelStage.SYNTHESIS) == "gpt-5.6-sol"


def test_invalid_tool_ceiling_is_a_readiness_error(monkeypatch):
    monkeypatch.setenv("DEEP_RESEARCH_MAX_TOOL_CALLS", "0")
    assert any("MAX_TOOL_CALLS" in message for message in validate_model_routing())
