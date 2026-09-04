"""Deterministic claim coverage and source-family corroboration."""

from __future__ import annotations

from collections import defaultdict

from app.models.deep_research import ResearchClaim
from app.models.evidence_graph import EvidenceLink, EvidenceRelation


def build_evidence_matrix(
    claims: list[ResearchClaim], links: list[EvidenceLink]
) -> dict[str, dict[str, object]]:
    """Build coverage without treating repeated URLs or vendors as corroboration."""
    known = {claim.claim_id for claim in claims}
    matrix: dict[str, dict[str, object]] = {
        claim.claim_id: {
            "supporting_source_ids": [],
            "challenging_source_ids": [],
            "supporting_families": [],
            "challenging_families": [],
            "corroborated": False,
            "gap": True,
        }
        for claim in claims
    }
    for link in links:
        if link.claim_id not in known:
            continue
        row = matrix[link.claim_id]
        relation_key = "supporting" if link.relation is EvidenceRelation.SUPPORTS else "challenging"
        source_key = f"{relation_key}_source_ids"
        family_key = f"{relation_key}_families"
        if link.source_id not in row[source_key]:
            row[source_key].append(link.source_id)
        if link.source_family and link.source_family not in row[family_key]:
            row[family_key].append(link.source_family)
    for row in matrix.values():
        row["corroborated"] = len(row["supporting_families"]) >= 2
        row["gap"] = not row["supporting_source_ids"]
    return matrix


def unresolved_claim_ids(claims: list[ResearchClaim], links: list[EvidenceLink]) -> list[str]:
    matrix = build_evidence_matrix(claims, links)
    return [claim_id for claim_id, row in matrix.items() if row["gap"]]


def source_family_counts(links: list[EvidenceLink]) -> dict[str, int]:
    """Count distinct claim/source-family pairs for audit display."""
    pairs = defaultdict(set)
    for link in links:
        if link.source_family:
            pairs[link.claim_id].add(link.source_family)
    return {claim_id: len(families) for claim_id, families in sorted(pairs.items())}


def contradiction_summary(
    claims: list[ResearchClaim], links: list[EvidenceLink]
) -> list[dict[str, object]]:
    """Return claims with competing evidence for explicit falsification review."""
    matrix = build_evidence_matrix(claims, links)
    return [
        {
            "claim_id": claim_id,
            "supporting_source_ids": row["supporting_source_ids"],
            "challenging_source_ids": row["challenging_source_ids"],
            "material": next(claim.load_bearing for claim in claims if claim.claim_id == claim_id),
        }
        for claim_id, row in matrix.items()
        if row["supporting_source_ids"] and row["challenging_source_ids"]
    ]
