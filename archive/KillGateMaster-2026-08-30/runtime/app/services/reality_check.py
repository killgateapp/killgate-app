"""
Human Reality Check service.
After a RESEARCH_PASS, this generates the exact questions a human should ask
and later processes the answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models.state import SystemState


@dataclass
class RealityCheckPlan:
    intro: str
    questions: list[dict[str, str]] = field(default_factory=list)  # question + why it matters
    plain_instructions: str = ""


def _proposed_price(state: SystemState) -> str:
    """Use the founder's stated price for the offer, without treating it as evidence."""
    for key in ("pilot", "monthly", "price", "amount"):
        value = state.pricing.get(key) if isinstance(state.pricing, dict) else None
        if value not in (None, ""):
            return str(value)

    match = re.search(
        r"\$\s*\d+(?:\.\d{1,2})?(?:\s*(?:-|–|to)\s*\$?\s*\d+(?:\.\d{1,2})?)?"
        r"(?:\s*(?:(?:per|/)\s*(?:month|mo|year|yr)|monthly|annually))?",
        state.hypothesis,
        re.IGNORECASE,
    )
    if match:
        return re.sub(r"\s+", " ", match.group(0)).strip()
    return "the exact price you state before the conversation"


def generate_reality_check_plan(state: SystemState) -> RealityCheckPlan:
    """
    Produce a short, focused set of questions that only a human can answer.
    Follows the spirit of HUMAN_REALITY_CHECK_PROTOCOL.md.
    """
    proposed_price = _proposed_price(state)

    questions = [
        {
            "question": "Think about the last time this problem actually happened to you (or your customers). What exactly happened?",
            "why": "We need a real recent example, not a hypothetical."
        },
        {
            "question": "What did you (or they) do about it? How much time or money did that cost?",
            "why": "Shows the current workaround and whether the pain has real consequences."
        },
        {
            "question": "Have you ever paid for a tool or service to help with this specific problem? If yes, what was it and why?",
            "why": "Direct signal of existing willingness to pay."
        },
        {
            "question": (
                f"We are offering a short paid pilot at {proposed_price}. "
                "Are you ready to begin now? If yes, complete the payment or deposit; "
                "if no, what prevents you?"
            ),
            "why": "Only a completed payment or verifiable deposit is economic evidence. A verbal yes is not."
        },
        {
            "question": "Who actually controls the budget for something like this?",
            "why": "Identifies whether the person talking can buy."
        },
    ]

    intro = (
        "The research stage found enough signal to continue.\n\n"
        "Now we need real answers from potential customers. "
        "Please have short conversations (or message people) using the questions below. "
        "Record their exact words — that is the most valuable part."
    )

    instructions = (
        "How to do this:\n"
        "1. Find 8–12 qualified people who match the customer you have in mind; expand only if the evidence stays ambiguous.\n"
        "2. Ask the questions (you can adapt the wording slightly).\n"
        "3. Write down their actual answers.\n"
        "4. Make the same concrete paid-pilot offer to qualified buyers.\n"
        "5. Record each conversation and any payment/deposit in Killgate so the locked gates can be re-scored.\n\n"
        "Do not count 'I would pay' as payment. GO still requires at least two actual pilot payments.\n"
        "Do not start building yet."
    )

    return RealityCheckPlan(
        intro=intro,
        questions=questions,
        plain_instructions=instructions,
    )


def summarize_answers_for_decision(answers_text: str) -> str:
    """
    Very lightweight summary helper.
    In a fuller version this would also update evidence records and re-score gates.
    """
    text = answers_text.lower()
    signals = []
    if any(w in text for w in ["paid", "paying", "subscribe", "pilot", "buy", "purchase"]):
        signals.append("Some mention of payment or willingness to pay appeared.")
    if any(w in text for w in ["no", "not really", "wouldn’t", "would not", "already have"]):
        signals.append("There are signs of resistance or existing alternatives.")
    if not signals:
        signals.append("No clear strong payment signal was detected in the notes you provided.")

    return " | ".join(signals)
