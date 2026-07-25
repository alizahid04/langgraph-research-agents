"""
End-to-end tests for the compiled LangGraph workflow.

Uses the patched_llm / patched_search test doubles from conftest.py so the
test runs offline and deterministically. The graph logic itself (routing,
revision loop, clarification pause, state shape) is real and unmodified.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.graph.workflow import build_workflow
from app.models import WorkflowRun


def _initial_state(run_id: str, objective: str, **overrides) -> dict:
    base = {
        "run_id": run_id,
        "user_request": objective,
        "objective": objective,
        "clarifications": [],
        "needs_clarification": False,
        "clarification_question": None,
        "clarification_rounds": 0,
        "max_clarification_rounds": 1,
        "plan": None,
        "evidence": [],
        "analysis": None,
        "critic_feedback": None,
        "final_report": None,
        "pending_research_questions": None,
        "revision_count": 0,
        "max_revisions": 2,
        "status": "running",
        "current_stage": "supervisor",
        "errors": [],
        "timestamps": {},
    }
    base.update(overrides)
    return base


@pytest.fixture()
def session_factory(db_session_factory):
    # Seed a WorkflowRun row since the graph nodes update an existing run.
    seed = db_session_factory()
    seed.add(WorkflowRun(id="e2e-run", objective="Should we adopt Kubernetes for our platform?", status="queued"))
    seed.commit()
    seed.close()
    return db_session_factory


@pytest.mark.asyncio
async def test_full_workflow_completes_and_produces_adaptive_report(
    session_factory, patched_llm, patched_search
):
    app = build_workflow(session_factory)
    initial_state = _initial_state("e2e-run", "Should we adopt Kubernetes for our platform?")

    final_state = await app.ainvoke(initial_state)

    assert final_state["status"] == "completed"
    assert final_state["final_report"] is not None
    assert final_state["revision_count"] <= final_state["max_revisions"]

    report_markdown = final_state["final_report"].markdown
    assert "## Methodology" not in report_markdown
    assert "## References" in report_markdown

    db = session_factory()
    run = db.get(WorkflowRun, "e2e-run")
    assert run.status == "completed"
    assert len(run.reports) >= 1
    assert len(run.evidence) > 0
    assert len(run.logs) > 0
    db.close()


@pytest.mark.asyncio
async def test_workflow_fails_cleanly_when_llm_not_configured(session_factory, monkeypatch):
    """
    With no LLM configured and no patched_llm double, the run must end by
    raising a clear, real error — never completing with synthetic data.
    """
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "openrouter_api_key", "", raising=False)

    app = build_workflow(session_factory)
    initial_state = _initial_state("e2e-run", "Should we adopt Kubernetes for our platform?")

    with pytest.raises(Exception) as exc_info:
        await app.ainvoke(initial_state)

    assert "OPENROUTER_API_KEY" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ambiguous_request_pauses_for_clarification(session_factory, monkeypatch, patched_search):
    """
    A genuinely ambiguous objective must pause the run at
    'awaiting_clarification' rather than guessing and proceeding silently.
    """
    from app.llm_client import LLMClient

    async def always_ambiguous(self, system_prompt, user_prompt, *, json_mode=False):
        if "request-analysis" in system_prompt:
            return json.dumps(
                {
                    "needs_clarification": True,
                    "clarification_question": "Do you mean diagnostics, hospital operations, or drug discovery?",
                    "interpreted_objective": "",
                }
            )
        raise AssertionError("Should not reach planning/analyst/critic/writer while paused")

    monkeypatch.setattr(LLMClient, "complete", always_ambiguous)

    app = build_workflow(session_factory)
    initial_state = _initial_state("e2e-run", "AI in healthcare")

    final_state = await app.ainvoke(initial_state)

    assert final_state["status"] == "awaiting_clarification"
    assert final_state["clarification_question"]
    assert final_state["plan"] is None  # never reached planning

    db = session_factory()
    run = db.get(WorkflowRun, "e2e-run")
    assert run.status == "awaiting_clarification"
    assert run.clarification_question
    db.close()


@pytest.mark.asyncio
async def test_clarification_round_is_capped_at_one(session_factory, monkeypatch, patched_search):
    """
    If the Supervisor would ask for clarification AGAIN on the resumed run,
    the hard cap must force it to proceed anyway rather than pausing forever.
    """
    from app.llm_client import LLMClient

    async def always_ambiguous_but_plan_if_asked(self, system_prompt, user_prompt, *, json_mode=False):
        if "request-analysis" in system_prompt:
            return json.dumps(
                {"needs_clarification": True, "clarification_question": "Still ambiguous?", "interpreted_objective": ""}
            )
        if "Supervisor Agent" in system_prompt:
            return json.dumps(
                {
                    "objective": "AI in healthcare",
                    "research_questions": [
                        {"id": "q1", "question": "What are current AI diagnostic tools?", "rationale": "core"},
                        {"id": "q2", "question": "What are the regulatory hurdles for AI in healthcare?", "rationale": "risk"},
                        {"id": "q3", "question": "What is the adoption rate of AI in hospitals?", "rationale": "adoption"},
                    ],
                    "notes": "",
                }
            )
        if "Analyst Agent" in system_prompt:
            return json.dumps({"key_insights": ["insight"], "comparison_table": [], "trade_offs": [], "unsupported_claim_warnings": []})
        if "Critic Agent" in system_prompt:
            return json.dumps({"verdict": "APPROVED", "issues": [], "justification": "fine", "revision_target": "analyst", "additional_research_questions": []})
        if "Report Writer Agent" in system_prompt:
            return "# AI in Healthcare\n\n## Overview\nSome content [1].\n"
        raise AssertionError(f"unexpected prompt: {system_prompt[:60]}")

    monkeypatch.setattr(LLMClient, "complete", always_ambiguous_but_plan_if_asked)

    app = build_workflow(session_factory)
    # Simulate the resumed run: clarification_rounds already at the cap (1).
    initial_state = _initial_state(
        "e2e-run", "AI in healthcare", clarifications=["I mean diagnostics"], clarification_rounds=1
    )

    final_state = await app.ainvoke(initial_state)

    # Despite the Supervisor still wanting clarification, the cap forces progress.
    assert final_state["status"] == "completed"
    assert final_state["plan"] is not None


@pytest.mark.asyncio
async def test_critic_revision_routes_to_research_for_evidence_gaps(session_factory, patched_search, monkeypatch):
    """
    When the Critic's root cause is insufficient evidence, the graph must
    route back to Research (with gap-filling questions), not Analyst.
    """
    from app.llm_client import LLMClient

    call_state = {"critic_calls": 0}

    async def side_effect(self, system_prompt, user_prompt, *, json_mode=False):
        if "request-analysis" in system_prompt:
            return json.dumps({"needs_clarification": False, "clarification_question": "", "interpreted_objective": "Test objective"})
        if "Supervisor Agent" in system_prompt:
            return json.dumps(
                {
                    "objective": "Test objective",
                    "research_questions": [{"id": "q1", "question": "Initial question", "rationale": "r"}],
                    "notes": "",
                }
            )
        if "Analyst Agent" in system_prompt:
            return json.dumps({"key_insights": ["insight"], "comparison_table": [], "trade_offs": [], "unsupported_claim_warnings": ["thin evidence"]})
        if "Critic Agent" in system_prompt:
            call_state["critic_calls"] += 1
            if call_state["critic_calls"] == 1:
                return json.dumps(
                    {
                        "verdict": "REVISION_REQUIRED",
                        "issues": ["insufficient evidence"],
                        "justification": "need more data",
                        "revision_target": "research",
                        "additional_research_questions": ["A gap-filling query"],
                    }
                )
            return json.dumps({"verdict": "APPROVED", "issues": [], "justification": "fine", "revision_target": "analyst", "additional_research_questions": []})
        if "Report Writer Agent" in system_prompt:
            return "# Test Report\n\n## Body\nContent [1][2].\n"
        raise AssertionError(f"unexpected prompt: {system_prompt[:60]}")

    monkeypatch.setattr(LLMClient, "complete", side_effect)

    app = build_workflow(session_factory)
    initial_state = _initial_state("e2e-run", "Test objective")

    final_state = await app.ainvoke(initial_state)

    assert final_state["status"] == "completed"
    assert final_state["revision_count"] == 1
    # 2 questions total means the gap-filling research question also ran
    # (1 initial question + 1 gap question, 2 fake results each = 4 evidence items).
    assert len(final_state["evidence"]) == 4
