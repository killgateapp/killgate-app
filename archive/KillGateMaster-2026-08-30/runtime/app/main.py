"""
Killgate Runtime – Customer Mode first
A stranger should be able to use this without knowing founder jargon.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from app.models.state import (
    DirectValidationRecord,
    Phase,
    SystemState,
    ValidationDecision,
)
from app.services.audit_trail import (
    append_decision,
    append_direct_evidence,
    append_research_evidence,
)
from app.services.state_store import (
    list_ventures,
    load_state,
    new_venture_id,
    save_state,
)
from app.services.validation_contract import ensure_validation_contract
from app.services.validation_gate import evaluate_validation_gate, go_is_allowed

app = typer.Typer(
    help="Killgate – Test whether an idea is worth building before you waste months on it.",
    add_completion=False,
)
console = Console()


def plain(text: str):
    """Print in simple language."""
    console.print(text)


def explain_phase(phase: Phase) -> str:
    mapping = {
        Phase.VALIDATION: "Checking whether this idea is actually worth building",
        Phase.BUILD: "Building the first version",
        Phase.DISTRIBUTE: "Finding the first real users",
        Phase.SCALE: "Growing what already works",
        Phase.KILL: "This idea has been stopped",
    }
    return mapping.get(phase, str(phase.value))


def explain_decision(decision: ValidationDecision | None) -> str:
    if decision is None:
        return "No final decision yet"
    mapping = {
        ValidationDecision.GO: "Good to proceed",
        ValidationDecision.CONTINUE_VALIDATION: "Needs more evidence before deciding",
        ValidationDecision.KILL: "Stopped – evidence does not support building this",
        ValidationDecision.PIVOT: "The original idea should change direction",
    }
    return mapping.get(decision, decision.value)


@app.command()
def version():
    """Show version."""
    plain("Killgate Runtime v1.2.0 (Single-User Play Store Architecture)")
    plain("This software helps you test an idea before you spend months building it.")


@app.command()
def new(idea: str = typer.Argument(..., help="Describe your idea in plain English")):
    """
    Start testing a new idea.
    Just describe it in normal language.
    """
    idea = idea.strip()
    if len(idea) < 10:
        plain("Please describe the idea in a full sentence.")
        plain("Example: \"I want to build an AI tool that helps small auto shops answer missed calls.\"")
        raise typer.Exit(1)

    venture_id = new_venture_id()
    state = SystemState(
        current_day=1,
        phase=Phase.VALIDATION,
        hypothesis=idea,
        research_pass=False,
        validation_decision=None,
    )
    ensure_validation_contract(state)
    save_state(venture_id, state)

    console.print(Panel.fit(
        f"[bold]New idea saved[/bold]\n\n"
        f"Reference: {venture_id}\n\n"
        f"Your idea:\n\"{idea}\"\n\n"
        f"What happens next:\n"
        f"The system will start by checking public evidence to see whether\n"
        f"this problem is real and whether people already pay to solve it.\n\n"
        f"Run this command to continue:\n"
        f"[cyan]python -m app.main run {venture_id}[/cyan]",
        title="Killgate"
    ))


@app.command()
def status(venture_id: str = typer.Argument(None, help="Idea reference (leave blank to list all)")):
    """See where an idea stands right now."""
    if venture_id is None:
        ventures = list_ventures()
        if not ventures:
            plain("You haven't started any ideas yet.")
            plain("Start one with:")
            plain("  python -m app.main new \"Your idea in plain English\"")
            return

        plain("Your ideas:\n")
        for vid in ventures:
            st = load_state(vid)
            if st:
                decision = explain_decision(st.validation_decision)
                plain(f"  {vid}")
                plain(f"    {st.hypothesis[:70]}{'...' if len(st.hypothesis) > 70 else ''}")
                plain(f"    Status: {explain_phase(st.phase)} | {decision}")
                plain("")
        return

    state = load_state(venture_id)
    if not state:
        plain(f"Could not find idea {venture_id}.")
        plain("Run 'python -m app.main status' to see your ideas.")
        raise typer.Exit(1)

    decision_text = explain_decision(state.validation_decision)

    content = (
        f"**Idea:** {state.hypothesis}\n\n"
        f"**Current stage:** {explain_phase(state.phase)}\n"
        f"**Decision so far:** {decision_text}\n"
        f"**Day in process:** {state.current_day}\n"
    )

    if state.phase == Phase.KILL:
        content += (
            "\nThis idea has been **stopped**.\n"
            "The evidence did not support spending more time on it.\n"
        )
    elif state.validation_decision is None and not state.research_pass:
        content += (
            "\n**What you should do next:**\n"
            f"Run: `python -m app.main run {venture_id}`\n"
            "The system will begin checking public evidence for this idea.\n"
        )
    elif state.research_pass and state.validation_decision is None:
        content += (
            "\n**What you should do next:**\n"
            "The system needs real conversations with potential customers.\n"
            "It will tell you the exact questions to ask.\n"
        )

    console.print(Panel(Markdown(content), title=f"Idea {venture_id}"))


@app.command()
def run(venture_id: str = typer.Argument(..., help="Idea reference")):
    """
    Advance the idea one step.
    The system will do what it can automatically and tell you if it needs anything from you.
    """
    state = load_state(venture_id)
    if not state:
        plain(f"Could not find idea {venture_id}.")
        raise typer.Exit(1)

    if state.phase == Phase.KILL or state.validation_decision == ValidationDecision.KILL:
        plain("This idea has already been stopped.")
        plain("The system will not continue working on it.")
        plain("You can start a different idea with the 'new' command.")
        return

    plain(f"Working on: {state.hypothesis[:80]}{'...' if len(state.hypothesis) > 80 else ''}")
    plain("")

    # Early autonomous behavior with clear customer language
    if state.phase == Phase.VALIDATION and not state.research_pass:
        plain("Stage: Checking public evidence for this idea...")
        plain("")

        from app.services.research import run_research_pass
        result = run_research_pass(state)
        append_research_evidence(state, result)

        plain(result.plain_language)
        plain("")

        if result.supporting_evidence:
            plain("Supporting signals linked to directly relevant public sources:")
            for item in result.supporting_evidence:
                plain(f"  • {item}")
            plain("")

        if result.disconfirming_evidence:
            plain("Strongest reasons for caution:")
            for d in result.disconfirming_evidence:
                plain(f"  • {d}")
            plain("")

        if result.decision_rule_triggers:
            plain("Locked decision rules triggered:")
            for k in result.decision_rule_triggers:
                plain(f"  • {k}")
            plain("")

        plain(f"System recommendation: {result.recommendation}")
        plain(f"Confidence: {result.confidence:.0%}")
        if result.used_web_search:
            plain(
                f"(Live search: {result.search_hit_count} results — "
                f"{result.direct_source_count} DIRECT, {result.indirect_source_count} indirect, "
                f"{result.irrelevant_source_count} irrelevant; "
                f"{result.independent_domain_count} DIRECT-source domains.)"
            )
            plain("Only directly relevant public sources can influence a research PASS; this is not Level-3 direct-buyer evidence.")
        elif result.used_llm:
            plain("(Language model used, but no live evidence cleared the relevance gate.)")
        else:
            plain("(No live evidence was retrieved; the relevance gate cannot pass.)")
        if result.evidence_items:
            plain("Directly relevant public evidence sources:")
            for item in result.evidence_items[:5]:
                if item.url:
                    plain(f"  • {item.url}")
        if result.evaluator_notes:
            plain(f"Evaluator note: {result.evaluator_notes}")
        plain("")

        # Enforce the gate
        if result.recommendation == "RESEARCH_FAIL":
            plain("Research did not clear the qualification gate.")
            plain("Insufficient web evidence blocks progression but is not, by itself, proof that demand is absent.")
            plain("Review the triggered rules before deciding whether to sharpen, pivot, or stop the idea.")
        elif result.recommendation == "RESEARCH_PASS":
            state.research_pass = True
            plain("Research stage passed. Next step is real conversations with potential customers.")
            plain("The system will eventually generate the exact questions for you.")
        elif result.recommendation == "FEASIBILITY_REQUIRED":
            plain("Feasibility gate required. Do NOT start ordinary willingness-to-pay interviews yet.")
            if result.feasibility_test:
                plain(f"Capability to test: {result.feasibility_test.get('capability', 'load-bearing capability')}")
                plain("Run the pre-registered capability test against later ground truth and its locked pass/fail thresholds first.")
            plain("A pass unlocks direct buyer validation on the unchanged hypothesis; a failure does not automatically mean KILL.")
        else:
            plain("The idea needs to be clearer before it can be properly tested.")

        state.current_day += 1

    elif state.research_pass and state.validation_decision is None:
        from app.services.reality_check import generate_reality_check_plan
        plan = generate_reality_check_plan(state)

        plain(plan.intro)
        plain("")
        plain("Questions to ask real people:")
        for i, q in enumerate(plan.questions, 1):
            plain(f"  {i}. {q['question']}")
            plain(f"     (Why: {q['why']})")
            plain("")
        plain(plan.plain_instructions)
        plain("")
        plain("Record each real buyer conversation with the record command (or use the web app).")
        plain("GO remains locked until the hard evidence gates are satisfied and explicitly approved.")
    elif state.validation_decision is None:
        plain("The system is waiting for stronger evidence before making a decision.")
        plain("In particular it needs to know whether real people will pay.")

    state.last_updated = datetime.now(UTC)
    save_state(venture_id, state)

    plain("")
    plain(f"Progress saved (Day {state.current_day}).")
    plain(f"Check status anytime with:  python -m app.main status {venture_id}")


@app.command()
def record(
    venture_id: str,
    buyer_identifier: str = typer.Option(..., help="Unique buyer/company label used to prevent duplicate counting"),
    buyer_role: str = typer.Option(..., help="Role of the qualified buyer"),
    qualification_basis: str = typer.Option(..., help="Why this person is a qualified buyer or purchase influencer"),
    recent_example: str = typer.Option(..., help="Recent real example of the problem"),
    workaround: str = typer.Option(..., help="What they actually do today"),
    pain: str = typer.Option(..., help="none | weak | moderate | strong"),
    price_response: str = typer.Option(..., help="Exact reaction to the pilot price/offer"),
    objection: str = typer.Option(..., help="Objection, why not now, or 'none stated'"),
    quote_text: str = typer.Option(..., "--quote", help="Most important exact customer quote"),
    pilot_price: str = typer.Option("", help="Price actually offered"),
    price_positive: bool = typer.Option(False, help="Whether the buyer accepted the price positively"),
    payment_status: str = typer.Option("not_asked", help="not_asked | declined | committed | paid"),
    payment_amount: float = typer.Option(0.0, min=0.0, help="Amount actually received"),
    payment_reference: str = typer.Option("", help="Receipt/invoice/payment reference required for a paid pilot to count"),
):
    """Record one real buyer conversation and re-score the hard gates."""
    state = load_state(venture_id)
    if not state:
        plain(f"Could not find idea {venture_id}.")
        raise typer.Exit(1)
    if not state.research_pass:
        plain("Direct evidence entry is locked until the Research Qualification Gate passes.")
        raise typer.Exit(1)

    pain_clean = pain.strip().lower()
    if pain_clean not in {"none", "weak", "moderate", "strong"}:
        plain("--pain must be: none, weak, moderate, or strong")
        raise typer.Exit(1)
    payment_clean = payment_status.strip().lower()
    if payment_clean not in {"not_asked", "declined", "committed", "paid"}:
        plain("--payment-status must be: not_asked, declined, committed, or paid")
        raise typer.Exit(1)

    clean_identifier = buyer_identifier.strip()
    existing_ids = {record.buyer_identifier.strip().casefold() for record in state.direct_validation_records if record.buyer_identifier.strip()}
    if not clean_identifier or clean_identifier.casefold() in existing_ids:
        plain("That buyer label is blank or already recorded. Duplicate buyers do not count toward the hard gate.")
        raise typer.Exit(1)

    record = DirectValidationRecord(
        record_id=f"C-{uuid.uuid4().hex[:10].upper()}",
        buyer_identifier=clean_identifier,
        buyer_role=buyer_role.strip(),
        qualification_basis=qualification_basis.strip(),
        recent_real_example=recent_example.strip(),
        current_workaround=workaround.strip(),
        pain_strength=pain_clean,
        pilot_price_tested=pilot_price.strip(),
        price_response=price_response.strip(),
        price_positive=price_positive,
        payment_status=payment_clean,
        payment_amount=payment_amount if payment_amount > 0 else None,
        payment_reference=payment_reference.strip(),
        objection_or_no_reason=objection.strip(),
        exact_quote=quote_text.strip(),
    )
    state.direct_validation_records.append(record)
    append_direct_evidence(state, record)
    gate = evaluate_validation_gate(state)
    state.metrics["hard_gate_recommendation"] = gate.recommendation.value
    state.metrics["hard_gate_blockers"] = gate.blockers
    state.last_updated = datetime.now(UTC)
    save_state(venture_id, state)

    plain(f"Evidence saved. Current recommendation: {gate.recommendation.value.upper()}")
    for blocker in gate.blockers:
        plain(f"  • {blocker}")


@app.command()
def approve(
    venture_id: str,
    decision: str = typer.Argument(..., help="GO | KILL | PIVOT | CONTINUE_VALIDATION"),
):
    """
    Record your final judgment on an idea.
    Use this only when you have real evidence.
    """
    state = load_state(venture_id)
    if not state:
        plain(f"Could not find idea {venture_id}.")
        raise typer.Exit(1)

    decision_clean = decision.strip().lower().replace(" ", "_")
    try:
        dec = ValidationDecision(decision_clean)
    except ValueError:
        plain("Please use one of these decisions:")
        plain("  GO")
        plain("  KILL")
        plain("  PIVOT")
        plain("  CONTINUE_VALIDATION")
        raise typer.Exit(1) from None

    if dec == ValidationDecision.GO and not go_is_allowed(state):
        gate = evaluate_validation_gate(state)
        plain("GO BLOCKED by the locked Validation Contract.")
        for blocker in gate.blockers:
            plain(f"  • {blocker}")
        raise typer.Exit(1)

    gate = evaluate_validation_gate(state)
    state.validation_decision = dec
    append_decision(state, dec, gate, rationale="Accepted from the CLI approval command.")
    if dec == ValidationDecision.KILL:
        state.phase = Phase.KILL
        plain("Decision recorded: This idea has been stopped.")
        plain("The system will not continue building it.")
    elif dec == ValidationDecision.GO:
        state.phase = Phase.BUILD
        plain("Decision recorded: GO. The locked hard gates passed.")
    else:
        plain(f"Decision recorded: {dec.value}")

    state.last_updated = datetime.now(UTC)
    save_state(venture_id, state)


@app.command()
def dev_status(venture_id: str):
    """Developer view – raw state (not for normal users)."""
    state = load_state(venture_id)
    if not state:
        plain("Venture not found.")
        raise typer.Exit(1)
    console.print(state.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
