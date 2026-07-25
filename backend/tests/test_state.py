"""Tests for the shared WorkflowState and schema contracts."""
from __future__ import annotations

from app.graph.state import WorkflowState
from app.schemas import (
    AnalysisResult,
    CriticFeedback,
    CriticVerdict,
    ResearchPlan,
    ResearchQuestion,
)


def test_workflow_state_accepts_expected_fields():
    state: WorkflowState = {
        "run_id": "run-1",
        "user_request": "Should we migrate to microservices?",
        "objective": "Should we migrate to microservices?",
        "clarifications": [],
        "plan": None,
        "evidence": [],
        "analysis": None,
        "critic_feedback": None,
        "final_report": None,
        "revision_count": 0,
        "max_revisions": 2,
        "status": "queued",
        "current_stage": "supervisor",
        "errors": [],
        "timestamps": {},
    }
    assert state["run_id"] == "run-1"
    assert state["revision_count"] == 0


def test_research_plan_schema_roundtrip():
    plan = ResearchPlan(
        objective="Evaluate cloud providers",
        research_questions=[
            ResearchQuestion(id="q1", question="What are the pricing models?", rationale="cost comparison"),
        ],
    )
    dumped = plan.model_dump()
    rebuilt = ResearchPlan(**dumped)
    assert rebuilt.objective == plan.objective
    assert rebuilt.research_questions[0].id == "q1"


def test_critic_feedback_verdict_enum():
    feedback = CriticFeedback(verdict=CriticVerdict.APPROVED, issues=[], justification="ok")
    assert feedback.verdict == "APPROVED"


def test_analysis_result_defaults():
    result = AnalysisResult(key_insights=["insight one"])
    assert result.comparison_table == []
    assert result.trade_offs == []
    assert result.unsupported_claim_warnings == []
