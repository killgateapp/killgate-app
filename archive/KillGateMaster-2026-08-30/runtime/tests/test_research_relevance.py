import json
import logging
import sys
from types import SimpleNamespace

import pytest

from app.models.state import SystemState
from app.services.live_search import (
    SearchHit,
    _canonical_url,
    _concept_terms,
    _make_queries,
    classify_search_hits,
    source_domain,
)
from app.services.reality_check import generate_reality_check_plan
from app.services.research import (
    DEFAULT_OPENAI_MODEL,
    _call_llm_with_hits,
    _evaluate_packet,
    _heuristic_with_hits,
    _structured_llm_to_result,
    enforce_deep_observed_evidence_gate,
)

QUEUECUE = (
    "I want to build QueueCue, a mobile app showing live restaurant wait times. "
    "Diners report how long they waited, and restaurants can update their own wait times. "
    "Users pay $4.99 per month. I would acquire customers through TikTok and restaurant table cards. "
    "None of the assumptions have been validated."
)


def _hit(title, url, snippet, theme="general"):
    return SearchHit(title=title, url=url, snippet=snippet, query="test query", query_theme=theme)


def test_queries_use_problem_context_not_founder_pricing_or_promotion():
    terms = _concept_terms(QUEUECUE)
    queries = " ".join(_make_queries(QUEUECUE)).lower()

    assert "restaurant" in terms
    assert "wait" in terms
    assert "queuecue" not in terms
    assert "4.99" not in queries
    assert "tiktok" not in queries
    assert "none of the assumptions" not in queries


def test_dictionary_social_and_wikipedia_results_are_irrelevant():
    hits = [
        _hit(
            "WANT Definition & Meaning - Merriam-Webster",
            "https://www.merriam-webster.com/dictionary/want",
            "The meaning of WANT is to be needy or destitute.",
        ),
        _hit(
            "WANT | English meaning - Cambridge Dictionary",
            "https://dictionary.cambridge.org/dictionary/english/want",
            "to wish for a particular thing",
        ),
        _hit(
            "Instagram (@instagram) • Instagram photos and videos",
            "https://www.instagram.com/instagram/",
            "See Instagram photos and videos.",
        ),
        _hit(
            "I - Wikipedia",
            "https://en.wikipedia.org/wiki/I",
            "I is the ninth letter in the Latin alphabet.",
        ),
    ]

    classified = classify_search_hits(QUEUECUE, hits)

    assert all(hit.relevance == "irrelevant" for hit in classified)


def test_queuecue_junk_packet_cannot_pass():
    hits = classify_search_hits(
        QUEUECUE,
        [
            _hit(
                "WANT Definition & Meaning - Merriam-Webster",
                "https://www.merriam-webster.com/dictionary/want",
                "The meaning of WANT is to desire.",
            ),
            _hit(
                "WANT | English meaning - Cambridge Dictionary",
                "https://dictionary.cambridge.org/dictionary/english/want",
                "A definition of want.",
            ),
            _hit(
                "I - Wikipedia",
                "https://en.wikipedia.org/wiki/I",
                "I is a letter.",
            ),
        ],
    )

    result = _heuristic_with_hits(SystemState(hypothesis=QUEUECUE), hits)

    assert result.recommendation == "RESEARCH_FAIL"
    assert result.direct_source_count == 0
    assert result.irrelevant_source_count == 3
    assert result.supporting_evidence == []


def test_founder_claims_alone_never_create_demand_evidence():
    state = SystemState(
        hypothesis=(
            "This is unquestionably a billion-dollar opportunity. "
            "Assume 80% of contractors will pay $99 per month."
        )
    )

    result = _heuristic_with_hits(state, [])

    assert result.recommendation == "RESEARCH_FAIL"
    assert result.direct_source_count == 0


def test_unverified_search_snippets_cannot_clear_research_gate():
    idea = (
        "I want to build LeadLatch for independent plumbers, electricians, HVAC contractors, "
        "and mobile mechanics. When an owner misses a call, LeadLatch texts the caller and books the job."
    )
    hits = classify_search_hits(
        idea,
        [
            _hit(
                "Independent plumbers are frustrated by missed calls",
                "https://tradeforum.example/plumbers-missed-calls",
                "Plumbers describe lost jobs and complaints when a missed call goes unanswered.",
                "pain",
            ),
            _hit(
                "Plumbers and HVAC contractors use missed-call booking apps",
                "https://fieldservice.example/missed-call-alternatives",
                "Contractors currently use an app, answering service, or manual callback workflow.",
                "alternatives",
            ),
            _hit(
                "Pricing for missed-call text-back used by HVAC contractors",
                "https://pricing.example/hvac-text-back",
                "HVAC contractors pay $49 per month for missed-call text and booking service.",
                "budget",
            ),
        ],
    )

    result = _heuristic_with_hits(SystemState(hypothesis=idea), hits)

    assert result.recommendation == "RESEARCH_PIVOT"
    assert result.direct_source_count == 3
    assert result.independent_domain_count == 3
    assert result.evidence_coverage["pain"] is True
    assert result.evidence_coverage["alternatives"] is True
    assert result.evidence_coverage["budget"] is True
    assert result.cited_support_count >= 2


def test_model_pass_without_hosted_web_source_ledger_is_rejected():
    idea = "Independent plumbers lose booked jobs when they miss customer calls."
    hits = classify_search_hits(
        idea,
        [
            _hit("Plumbers lose jobs from missed calls", "https://one.example/pain", "Plumbers report lost jobs and frustrating missed calls."),
            _hit("Plumbers use answering services", "https://two.example/alternative", "Plumbers currently use answering services and manual callbacks."),
            _hit("Plumber callback software pricing", "https://three.example/budget", "Plumbers pay $49 per month for callback software."),
        ],
    )
    payload = {
        "plain_summary": "Pass",
        "supporting_evidence": [
            {"claim": "Pain", "direct_source_number": 1},
            {"claim": "Alternative", "direct_source_number": 2},
        ],
        "disconfirming_evidence": [
            {"claim": "Competition", "direct_source_number": 2},
            {"claim": "No buyer interviews", "direct_source_number": None},
        ],
        "decision_rule_triggers": [],
        "recommendation": "RESEARCH_PASS",
        "confidence": 0.7,
        "why_recommendation": "Claimed pass",
    }
    state = SystemState(hypothesis=idea)

    result = _evaluate_packet(
        _structured_llm_to_result(payload, state, hits, json.dumps(payload), verified_urls=set()),
        state,
    )

    assert result.recommendation == "RESEARCH_FAIL"
    assert result.direct_source_count == 0
    assert result.cited_support_count == 0


def test_reality_check_uses_submitted_price_and_requires_real_payment():
    plan = generate_reality_check_plan(SystemState(hypothesis=QUEUECUE))
    payment_question = plan.questions[3]

    assert "$4.99 per month" in payment_question["question"]
    assert "$29" not in payment_question["question"]
    assert "complete the payment or deposit" in payment_question["question"]
    assert "A verbal yes is not" in payment_question["why"]
    assert "two actual pilot payments" in plan.plain_instructions


def test_openai_research_uses_responses_structured_output_and_server_attached_citations(monkeypatch):
    idea = (
        "I want to build LeadLatch for independent plumbers and HVAC contractors. "
        "When an owner misses a call, LeadLatch texts the caller and books the job."
    )
    hits = [
        SearchHit(
            title="Plumbers lose jobs to missed calls",
            url="https://pain.example/missed-calls",
            snippet="Independent plumbers describe frustrating missed calls and lost jobs.",
            query="pain",
            query_theme="pain",
            relevance="direct",
        ),
        SearchHit(
            title="Contractors use answering and booking services",
            url="https://alternatives.example/answering",
            snippet="HVAC contractors currently use answering services, apps, and manual callbacks.",
            query="alternatives",
            query_theme="alternatives",
            relevance="direct",
        ),
        SearchHit(
            title="Missed-call service pricing",
            url="https://pricing.example/text-back",
            snippet="Contractors pay $49 per month for missed-call text-back service.",
            query="budget",
            query_theme="budget",
            relevance="direct",
        ),
    ]
    payload = {
        "plain_summary": "The public evidence clears the research-only relevance gate.",
        "supporting_evidence": [
            {"claim": "Missed calls cause lost work.", "direct_source_number": 1},
            {"claim": "Existing services prove an alternative workflow exists.", "direct_source_number": 2},
            {"claim": "This citation number is invalid and must be dropped.", "direct_source_number": 99},
        ],
        "disconfirming_evidence": [
            {"claim": "Existing answering services already compete for this job.", "direct_source_number": 2},
            {"claim": "Public evidence cannot prove individual willingness to pay.", "direct_source_number": None},
        ],
        "mechanism_scoreboard": [
            {
                "mechanism": "Missed-call text-back and booking workflow",
                "role": "CORE",
                "action": "KEEP",
                "load_bearing": False,
                "changes_commercial_hypothesis": False,
                "rationale": "Existing alternatives show the workflow is technically ordinary; buyer demand still needs direct validation.",
                "direct_source_number": 2,
            }
        ],
        "feasibility_test": None,
        "decision_rule_triggers": [],
        "recommendation": "RESEARCH_PASS",
        "confidence": 0.82,
        "why_recommendation": "The hard public-research requirements are present, but direct buyer validation still comes next.",
    }
    seen = {}

    class FakeResponses:
        def create(self, **kwargs):
            seen.update(kwargs)
            usage = SimpleNamespace(
                input_tokens=6000,
                output_tokens=900,
                total_tokens=6900,
                input_tokens_details=SimpleNamespace(cached_tokens=1000),
                output_tokens_details=SimpleNamespace(reasoning_tokens=300),
            )
            sources = [SimpleNamespace(url=hit.url) for hit in hits]
            web_call = SimpleNamespace(
                type="web_search_call",
                action=SimpleNamespace(sources=sources),
            )
            return SimpleNamespace(
                output_text=json.dumps(payload),
                output=[web_call],
                model="gpt-5.6-luna",
                usage=usage,
            )

    class FakeOpenAI:
        def __init__(self, api_key):
            seen["api_key"] = api_key
            self.responses = FakeResponses()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)

    result = _call_llm_with_hits(SystemState(hypothesis=idea), hits)

    assert result is not None
    assert seen["model"] == DEFAULT_OPENAI_MODEL
    assert seen["store"] is False
    assert seen["tools"] == [{"type": "web_search"}]
    assert seen["tool_choice"] == "required"
    assert seen["include"] == ["web_search_call.action.sources"]
    assert seen["text"]["format"]["type"] == "json_schema"
    assert seen["text"]["format"]["strict"] is True
    assert seen["reasoning"]["effort"] == "low"
    assert result.used_llm is True
    assert result.recommendation == "RESEARCH_PASS"
    assert result.confidence == 0.70  # deterministic evaluator caps a research PASS
    assert len(result.supporting_evidence) == 2
    assert "https://pain.example/missed-calls" in result.supporting_evidence[0]
    assert "https://alternatives.example/answering" in result.supporting_evidence[1]
    assert all("99" not in claim for claim in result.supporting_evidence)
    assert result.cited_support_count == 2
    assert result.llm_model == "gpt-5.6-luna"
    assert result.llm_input_tokens == 6000
    assert result.llm_cached_input_tokens == 1000
    assert result.llm_output_tokens == 900
    assert result.llm_reasoning_tokens == 300
    assert result.llm_total_tokens == 6900


def test_deep_research_provider_uses_routed_synthesis_and_tool_ceiling(monkeypatch):
    hit = _hit("Restaurant wait problem", "https://pain.example/wait", "Restaurants report long waits and lost bookings.")
    hit.relevance = "direct"
    payload = {
        "recommendation": "RESEARCH_PIVOT",
        "confidence": 0.4,
        "plain_summary": "bounded",
        "why_recommendation": "The public evidence is incomplete.",
        "supporting_evidence": [],
        "disconfirming_evidence": [],
        "decision_rule_triggers": [],
        "evidence_items": [],
        "mechanism_scoreboard": [],
        "feasibility_test": None,
    }
    seen = {}

    class FakeResponses:
        def create(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(
                output_text=json.dumps(payload),
                output=[],
                model="gpt-5.6-terra",
                usage=SimpleNamespace(input_tokens=10, output_tokens=10, total_tokens=20),
            )

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DEEP_RESEARCH_ENABLED", "1")
    monkeypatch.setenv("DEEP_RESEARCH_MAX_TOOL_CALLS", "3")
    monkeypatch.delenv("DEEP_RESEARCH_SYNTHESIS_MODEL", raising=False)

    result = _call_llm_with_hits(SystemState(hypothesis=QUEUECUE), [hit])
    assert result is not None
    assert seen["model"] == "gpt-5.6-terra"
    assert seen["max_tool_calls"] == 3


def test_deep_scorecard_blocks_pass_when_observed_voice_thresholds_are_missing():
    from app.services.research import ResearchResult

    result = ResearchResult(
        summary="candidate",
        recommendation="RESEARCH_PASS",
        confidence=0.9,
        observed_user_evidence_count=29,
        independent_observed_voice_count=14,
        observed_community_count=2,
    )
    enforce_deep_observed_evidence_gate(result)
    assert result.recommendation == "RESEARCH_PIVOT"
    assert result.confidence == 0.70
    assert "30" in result.evaluator_notes
    assert "15" in result.evaluator_notes
    assert "3" in result.evaluator_notes



def test_load_bearing_core_test_blocks_research_pass_until_feasibility():
    idea = "Collision shops pay $249/month if pre-teardown inputs can predict costly hidden supplement omissions."
    hits = [
        SearchHit(title="Supplement delays hurt cycle time", url="https://pain.example/supplements", snippet="Collision shops report costly supplement delays and production problems.", query="pain", query_theme="pain", relevance="direct"),
        SearchHit(title="Estimators use review tools", url="https://tools.example/review", snippet="Collision estimators use software tools and manual review as current alternatives.", query="alternatives", query_theme="alternatives", relevance="direct"),
        SearchHit(title="Collision estimating software pricing", url="https://pricing.example/collision", snippet="Collision shops pay $249 per month for estimating and review software.", query="budget", query_theme="budget", relevance="direct"),
    ]
    payload = {
        "plain_summary": "Pain and spend are real, but the differentiated prediction capability is unproven.",
        "supporting_evidence": [
            {"claim": "Supplement delays create operational pain.", "direct_source_number": 1},
            {"claim": "Shops already use review tools and spend on estimating software.", "direct_source_number": 2},
        ],
        "disconfirming_evidence": [
            {"claim": "Current inputs may not contain enough signal for hidden damage.", "direct_source_number": None},
            {"claim": "Commodity review tools already cover obvious missed operations.", "direct_source_number": 2},
        ],
        "mechanism_scoreboard": [
            {
                "mechanism": "Predict hidden supplement-causing omissions before teardown",
                "role": "CORE",
                "action": "TEST",
                "load_bearing": True,
                "changes_commercial_hypothesis": True,
                "rationale": "The $249 WTP sentence depends on this prediction creating earlier action.",
                "direct_source_number": None,
            },
            {
                "mechanism": "Prioritized estimator review packet",
                "role": "SUPPORTING",
                "action": "KEEP",
                "load_bearing": False,
                "changes_commercial_hypothesis": False,
                "rationale": "This is a delivery format, not the hard capability.",
                "direct_source_number": 2,
            },
        ],
        "feasibility_test": {
            "capability": "Pre-teardown omission prediction",
            "why_load_bearing": "If pre-teardown artifacts cannot predict costly omissions, the delay-prevention value proposition collapses.",
            "decision_time_inputs": ["initial estimate", "photos", "VIN", "labor ops", "parts list"],
            "later_ground_truth": "post-teardown supplement and final repair record",
            "metrics": ["true captures of costly omissions", "false positives", "action-changing flags"],
            "baselines": ["human estimator review", "cheap missed-ops tool"],
            "pass_thresholds": ["capture at least 50% of costly supplement events", "false-positive rate <= 25%", "at least 30% of correct flags would change a pre-teardown action"],
            "fail_thresholds": ["capture below 30%", "false-positive rate above 50%"],
        },
        "decision_rule_triggers": [],
        "recommendation": "RESEARCH_PASS",
        "confidence": 0.82,
        "why_recommendation": "The model tried to pass, but the feasibility gate should override it.",
    }
    verified = {hit.url for hit in hits}
    result = _evaluate_packet(
        _structured_llm_to_result(payload, SystemState(hypothesis=idea), hits, json.dumps(payload), verified_urls=verified),
        SystemState(hypothesis=idea),
    )
    assert result.recommendation == "FEASIBILITY_REQUIRED"
    assert result.confidence == 0.70
    assert result.feasibility_test is not None
    assert any(row["load_bearing"] for row in result.mechanism_scoreboard)
    assert "PASS blocked" in result.evaluator_notes


def test_feasibility_required_without_preregistered_thresholds_is_rejected():
    state = SystemState(hypothesis="A technically uncertain prediction product for a real paid workflow")
    result = __import__("app.services.research", fromlist=["ResearchResult"]).ResearchResult(
        summary="x",
        recommendation="FEASIBILITY_REQUIRED",
        confidence=0.8,
        used_web_search=True,
        search_hit_count=3,
        direct_source_count=3,
        independent_domain_count=2,
        evidence_coverage={"pain": True, "alternatives": True, "budget": True},
        cited_support_count=2,
        supporting_evidence=["a", "b"],
        disconfirming_evidence=["x", "y"],
        mechanism_scoreboard=[{
            "mechanism": "Hard prediction",
            "role": "CORE",
            "action": "TEST",
            "load_bearing": True,
            "changes_commercial_hypothesis": True,
            "rationale": "required",
            "source_url": "",
        }],
        feasibility_test={"capability": "Hard prediction", "decision_time_inputs": ["input"]},
    )
    evaluated = _evaluate_packet(result, state)
    assert evaluated.recommendation == "RESEARCH_PIVOT"
    assert "FEASIBILITY_REQUIRED rejected" in evaluated.evaluator_notes


def test_evidence_urls_accept_only_http_https_and_strip_tracking():
    assert _canonical_url("javascript://evil.example/%0Aalert(1)") == ""
    assert _canonical_url("data:text/html,boom") == ""
    assert _canonical_url("https://user:pass@example.com/private") == ""
    assert _canonical_url("https://Example.com/path/?utm_source=x&keep=1#frag") == "https://example.com/path?keep=1"


def test_source_independence_collapses_subdomains_to_registrable_domain():
    assert source_domain("https://blog.example.com/a") == "example.com"
    assert source_domain("https://shop.example.com/b") == "example.com"
    assert source_domain("https://news.example.co.uk/a") == "example.co.uk"


def test_required_openai_never_silently_falls_back(monkeypatch):
    from app.services import research

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("OPENAI_REQUIRED", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    hits = [
        _hit("Restaurant wait problem", "https://a.example/pain", "Restaurants struggle with long wait problems and delays."),
        _hit("Restaurant wait software", "https://b.example/tool", "Restaurants currently use waitlist software and booking tools."),
        _hit("Restaurant waitlist pricing", "https://c.example/price", "Restaurant waitlist software pricing is $99 per month."),
    ]
    hits = classify_search_hits(QUEUECUE, hits)

    with pytest.raises(research.ResearchUnavailable):
        research._call_llm_with_hits(SystemState(hypothesis=QUEUECUE), hits)


def test_openai_provider_error_does_not_log_sensitive_exception_text(monkeypatch, caplog):
    from app.services import research

    sentinel = "synthetic-provider-detail-should-not-reach-logs"

    class BrokenResponses:
        @staticmethod
        def create(**kwargs):
            raise RuntimeError(sentinel)

    class BrokenClient:
        responses = BrokenResponses()

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("OPENAI_REQUIRED", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(
        sys.modules,
        "openai",
        SimpleNamespace(OpenAI=lambda **kwargs: BrokenClient()),
    )
    caplog.set_level(logging.WARNING, logger=research.__name__)
    hits = classify_search_hits(
        QUEUECUE,
        [
            _hit(
                "Restaurant wait problem",
                "https://a.example/pain",
                "Restaurants struggle with long wait problems and delays.",
            ),
        ],
    )

    assert research._call_llm_with_hits(SystemState(hypothesis=QUEUECUE), hits) is None
    assert "OpenAI research request failed (RuntimeError)." in caplog.text
    assert sentinel not in caplog.text


def test_live_search_total_provider_failure_is_operational_not_negative_evidence(monkeypatch):
    from app.services.research import ResearchUnavailable, run_research_pass

    class BrokenDDGS:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def text(self, *args, **kwargs):
            raise RuntimeError("provider down")

    import types
    fake_module = types.SimpleNamespace(DDGS=BrokenDDGS)
    monkeypatch.setitem(sys.modules, "ddgs", fake_module)
    with pytest.raises(ResearchUnavailable):
        run_research_pass(SystemState(hypothesis=QUEUECUE))
