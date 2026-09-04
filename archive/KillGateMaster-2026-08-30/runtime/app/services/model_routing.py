"""Application-owned model routing for bounded Deep Research stages."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class ResearchModelStage(str, Enum):
    PLANNER = "planner"
    EXTRACTOR = "extractor"
    CONTRADICTION = "contradiction"
    SYNTHESIS = "synthesis"
    CRITIC = "critic"


SUPPORTED_MODELS = frozenset({"gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"})
_DEFAULTS = {
    ResearchModelStage.PLANNER: "gpt-5.6-luna",
    ResearchModelStage.EXTRACTOR: "gpt-5.6-luna",
    ResearchModelStage.CONTRADICTION: "gpt-5.6-luna",
    ResearchModelStage.SYNTHESIS: "gpt-5.6-terra",
    ResearchModelStage.CRITIC: "gpt-5.6-luna",
}


@dataclass(frozen=True)
class ModelRoute:
    """Resolved stage models and the explicit tool ceiling for one run."""

    planner: str
    extractor: str
    contradiction: str
    synthesis: str
    critic: str
    max_tool_calls: int

    def for_stage(self, stage: ResearchModelStage | str) -> str:
        return getattr(self, ResearchModelStage(stage).value)


def _allow_sol() -> bool:
    return os.getenv("DEEP_RESEARCH_ALLOW_SOL", "0").strip() == "1"


def model_for_stage(stage: ResearchModelStage | str) -> str:
    """Resolve one model while keeping Sol opt-in and never implicit."""
    resolved_stage = ResearchModelStage(stage)
    env_name = f"DEEP_RESEARCH_{resolved_stage.value.upper()}_MODEL"
    model = os.getenv(env_name, _DEFAULTS[resolved_stage]).strip() or _DEFAULTS[resolved_stage]
    if model not in SUPPORTED_MODELS:
        raise ValueError(f"{env_name} must name a supported GPT-5.6 model")
    if model == "gpt-5.6-sol" and not _allow_sol():
        raise ValueError("gpt-5.6-sol is disabled unless DEEP_RESEARCH_ALLOW_SOL=1")
    return model


def max_tool_calls() -> int:
    raw = os.getenv("DEEP_RESEARCH_MAX_TOOL_CALLS", "8").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("DEEP_RESEARCH_MAX_TOOL_CALLS must be an integer") from exc
    if not 1 <= value <= 50:
        raise ValueError("DEEP_RESEARCH_MAX_TOOL_CALLS must be between 1 and 50")
    return value


def resolve_model_route() -> ModelRoute:
    return ModelRoute(
        planner=model_for_stage(ResearchModelStage.PLANNER),
        extractor=model_for_stage(ResearchModelStage.EXTRACTOR),
        contradiction=model_for_stage(ResearchModelStage.CONTRADICTION),
        synthesis=model_for_stage(ResearchModelStage.SYNTHESIS),
        critic=model_for_stage(ResearchModelStage.CRITIC),
        max_tool_calls=max_tool_calls(),
    )


def validate_model_routing() -> list[str]:
    """Return readiness blockers without exposing any secret configuration."""
    try:
        resolve_model_route()
    except ValueError as exc:
        return [str(exc)]
    return []
