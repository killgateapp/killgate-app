"""Bounded gap-fill search planning and deterministic stopping decisions."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.deep_research import CostLedger, ResearchBudgetConfig, ResearchPlan


@dataclass(frozen=True)
class StopDecision:
    stop: bool
    reason: str
    unresolved_claim_ids: tuple[str, ...] = ()


@dataclass
class GapFillController:
    """Own search stopping policy independently of model recommendations."""

    budget: ResearchBudgetConfig
    ledger: CostLedger = field(default_factory=CostLedger)
    saturation_rounds: int = 2
    rounds: int = 0
    rounds_without_new_sources: int = 0
    _seen_sources: set[str] = field(default_factory=set)

    def reserve_search(self) -> None:
        """Reserve one search before provider work; raises at the hard boundary."""
        self.ledger.record_search_call(config=self.budget)

    def evaluate_round(
        self,
        *,
        unresolved_claim_ids: list[str],
        new_source_ids: list[str],
        elapsed_seconds: float,
    ) -> StopDecision:
        """Evaluate one completed search round using only deterministic counters."""
        self.rounds += 1
        fresh_sources = {source_id for source_id in new_source_ids if source_id and source_id not in self._seen_sources}
        self._seen_sources.update(fresh_sources)
        self.rounds_without_new_sources = 0 if fresh_sources else self.rounds_without_new_sources + 1
        unresolved = tuple(dict.fromkeys(item for item in unresolved_claim_ids if item))
        if not unresolved:
            return StopDecision(True, "coverage_complete")
        if self.ledger.hard_limit_reached or self.ledger.search_calls >= self.budget.max_search_calls:
            return StopDecision(True, "hard_search_budget", unresolved)
        if self.ledger.soft_limit_reached:
            return StopDecision(True, "soft_cost_limit", unresolved)
        if elapsed_seconds >= self.budget.max_elapsed_seconds:
            return StopDecision(True, "elapsed_time_limit", unresolved)
        if self.rounds_without_new_sources >= self.saturation_rounds:
            return StopDecision(True, "evidence_saturated", unresolved)
        return StopDecision(False, "continue_gap_fill", unresolved)


def build_gap_fill_queries(plan: ResearchPlan, unresolved_claim_ids: list[str], *, limit: int = 4) -> list[str]:
    """Generate bounded, claim-specific follow-ups from the application plan."""
    by_id = {claim.claim_id: claim for claim in plan.claims}
    queries: list[str] = []
    seen: set[str] = set()
    for claim_id in unresolved_claim_ids:
        claim = by_id.get(claim_id)
        if claim is None:
            continue
        query = f"{claim.text.strip()} independent evidence counterexample"
        normalized = " ".join(query.split()).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        queries.append(query[:300])
        if len(queries) >= limit:
            break
    return queries
