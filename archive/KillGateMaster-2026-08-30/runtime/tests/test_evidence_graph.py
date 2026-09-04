from __future__ import annotations

from app.models.deep_research import ResearchClaim
from app.models.evidence_graph import EvidenceLink, EvidenceRelation
from app.services.evidence_graph import (
    build_evidence_matrix,
    contradiction_summary,
    unresolved_claim_ids,
)


def test_evidence_matrix_requires_independent_source_families_for_corroboration():
    claims = [ResearchClaim(claim_id="c1", text="The problem is frequent.")]
    links = [
        EvidenceLink(claim_id="c1", source_id="s1", relation=EvidenceRelation.SUPPORTS, source_family="forum-a"),
        EvidenceLink(claim_id="c1", source_id="s2", relation=EvidenceRelation.SUPPORTS, source_family="forum-a"),
        EvidenceLink(claim_id="c1", source_id="s3", relation=EvidenceRelation.CHALLENGES, source_family="vendor"),
    ]
    matrix = build_evidence_matrix(claims, links)
    assert matrix["c1"]["gap"] is False
    assert matrix["c1"]["corroborated"] is False
    assert matrix["c1"]["challenging_families"] == ["vendor"]

    links.append(
        EvidenceLink(claim_id="c1", source_id="s4", relation=EvidenceRelation.SUPPORTS, source_family="review-site")
    )
    assert build_evidence_matrix(claims, links)["c1"]["corroborated"] is True


def test_unresolved_claims_ignore_links_to_unknown_claims():
    claims = [ResearchClaim(claim_id="c1", text="Known claim.")]
    links = [EvidenceLink(claim_id="unknown", source_id="s1", relation=EvidenceRelation.SUPPORTS, source_family="x")]
    assert unresolved_claim_ids(claims, links) == ["c1"]


def test_contradiction_summary_requires_both_sides_of_the_claim():
    claims = [ResearchClaim(claim_id="c1", text="Known claim.", load_bearing=True)]
    links = [
        EvidenceLink(claim_id="c1", source_id="s1", relation=EvidenceRelation.SUPPORTS, source_family="a"),
        EvidenceLink(claim_id="c1", source_id="s2", relation=EvidenceRelation.CHALLENGES, source_family="b"),
    ]
    summary = contradiction_summary(claims, links)
    assert summary[0]["claim_id"] == "c1"
    assert summary[0]["material"] is True
