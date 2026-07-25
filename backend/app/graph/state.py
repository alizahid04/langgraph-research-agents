"""Strongly typed shared state passed between nodes in the LangGraph workflow."""
from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from app.schemas import (
    AnalysisResult,
    CriticFeedback,
    EvidenceItem,
    FinalReport,
    ResearchPlan,
    ResearchQuestion,
)


class WorkflowState(TypedDict, total=False):
    """
    The single source of truth threaded through every agent node.

    Using a TypedDict (rather than passing raw chat history) enforces the
    handoff-contract discipline required by the architecture: each agent
    reads only the typed fields it needs and writes back typed results.
    """

    run_id: str
    user_request: str
    objective: str
    clarifications: list[str]

    # Clarification loop (Supervisor's "Request Analysis" step)
    needs_clarification: bool
    clarification_question: str | None
    clarification_rounds: int
    max_clarification_rounds: int

    plan: ResearchPlan | None
    evidence: list[EvidenceItem]
    analysis: AnalysisResult | None
    critic_feedback: CriticFeedback | None
    final_report: FinalReport | None

    # Set by the Critic when it routes a revision back to Research instead
    # of Analyst — these are gap-filling questions only, not the full plan.
    pending_research_questions: list[ResearchQuestion] | None

    revision_count: int
    max_revisions: int

    status: str  # queued/running/awaiting_clarification/completed/failed
    current_stage: str
    errors: list[str]
    timestamps: dict[str, datetime]
