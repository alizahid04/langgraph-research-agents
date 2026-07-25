"""
LangGraph workflow definition.

Graph shape:

    START -> request_analysis -> (needs clarification?) -> [pause, END]
                    |
                    v (clear enough)
                 planning -> research -> analyst -> critic -> (approved?) -> writer -> END
                                 ^            ^          |
                                 |            |__revise__|  (revision_target picks which)
                                 |_______________________|

- The Supervisor never researches.
- The Analyst never searches.
- The Critic never edits content directly — it only approves or requests
  revision, and when requesting revision, decides whether the root cause is
  insufficient evidence (send back to Research for gap-filling searches) or
  weak synthesis of adequate evidence (send back to Analyst).
- A run can pause at "request_analysis" awaiting a clarifying answer from
  the user; POST /api/workflows/{id}/clarify resumes it as a fresh
  invocation with the answer folded into the request (capped at one round).

Each node reads/writes ONLY the typed WorkflowState fields it needs.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from app.agents.analyst import AnalystAgent
from app.agents.critic import CriticAgent
from app.agents.research import ResearchAgent
from app.agents.supervisor import SupervisorAgent
from app.agents.writer import WriterAgent
from app.graph.state import WorkflowState
from app.models import WorkflowRun
from app.schemas import CriticVerdict, ResearchQuestion, RevisionTarget
from app.tools.evidence_tool import retrieve_evidence

logger = logging.getLogger(__name__)

supervisor_agent = SupervisorAgent()
research_agent = ResearchAgent()
analyst_agent = AnalystAgent()
critic_agent = CriticAgent()
writer_agent = WriterAgent()


def _update_run(db: Session, run_id: str, **fields) -> None:
    run = db.get(WorkflowRun, run_id)
    if not run:
        return
    for key, value in fields.items():
        setattr(run, key, value)
    db.commit()


def build_workflow(db_factory):
    """
    Build the compiled LangGraph app.

    `db_factory` is a zero-arg callable returning a fresh SQLAlchemy Session,
    since LangGraph node functions are plain callables without DI support.
    """

    async def request_analysis_node(state: WorkflowState) -> WorkflowState:
        db = db_factory()
        try:
            _update_run(db, state["run_id"], current_stage="supervisor", status="running")
            clarifications = state.get("clarifications", [])
            clarification_answer = clarifications[-1] if clarifications else None

            analysis = await supervisor_agent.analyze_request(
                db, state["run_id"], state["user_request"], clarification_answer
            )
            state["needs_clarification"] = analysis.needs_clarification
            state["clarification_question"] = analysis.clarification_question or None

            rounds = state.get("clarification_rounds", 0)
            cap = state.get("max_clarification_rounds", 1)

            if analysis.needs_clarification and rounds < cap:
                # NOTE: this decision — and every state field the routing
                # function below needs — MUST be set here, inside a real
                # node. LangGraph only merges state changes returned by
                # nodes; a conditional-edge function (like
                # route_after_request_analysis) can inspect state to choose
                # a route, but any mutations IT makes are silently dropped.
                state["clarification_rounds"] = rounds + 1
                state["status"] = "awaiting_clarification"
                _update_run(
                    db,
                    state["run_id"],
                    status="awaiting_clarification",
                    clarification_question=state["clarification_question"],
                    clarification_rounds=state["clarification_rounds"],
                )
            else:
                # Either the request was clear, or we've already used up the
                # one clarification round — proceed regardless rather than
                # loop forever.
                state["objective"] = analysis.interpreted_objective or state["user_request"]
            return state
        finally:
            db.close()

    def route_after_request_analysis(state: WorkflowState) -> str:
        """Pure routing decision — reads state only, never mutates it."""
        return "pause" if state.get("status") == "awaiting_clarification" else "proceed"

    async def planning_node(state: WorkflowState) -> WorkflowState:
        db = db_factory()
        try:
            objective = state.get("objective") or state["user_request"]
            plan = await supervisor_agent.plan(db, state["run_id"], objective)
            state["plan"] = plan
            state["objective"] = plan.objective
            state["current_stage"] = "research"
            return state
        finally:
            db.close()

    async def research_node(state: WorkflowState) -> WorkflowState:
        db = db_factory()
        try:
            _update_run(db, state["run_id"], current_stage="research")
            pending = state.get("pending_research_questions")
            if pending:
                # Gap-filling pass triggered by the Critic — research only
                # the new questions, don't redo the original plan's searches.
                questions = pending
            else:
                plan = state["plan"]
                assert plan is not None
                questions = plan.research_questions

            new_evidence = await research_agent.research_all(db, state["run_id"], questions)
            state["evidence"] = state.get("evidence", []) + new_evidence
            state["pending_research_questions"] = None
            state["current_stage"] = "analyst"
            return state
        finally:
            db.close()

    async def analyst_node(state: WorkflowState) -> WorkflowState:
        db = db_factory()
        try:
            _update_run(db, state["run_id"], current_stage="analyst")
            evidence_rows = retrieve_evidence(db, state["run_id"])
            analysis = await analyst_agent.analyze(db, state["run_id"], evidence_rows)
            state["analysis"] = analysis
            state["current_stage"] = "critic"
            return state
        finally:
            db.close()

    async def critic_node(state: WorkflowState) -> WorkflowState:
        db = db_factory()
        try:
            _update_run(db, state["run_id"], current_stage="critic")
            analysis = state["analysis"]
            assert analysis is not None
            feedback = await critic_agent.review(
                db,
                state["run_id"],
                analysis,
                state.get("revision_count", 0),
                state.get("max_revisions", 2),
            )
            state["critic_feedback"] = feedback

            if feedback.verdict == CriticVerdict.REVISION_REQUIRED:
                # As above: this must happen here, inside the node, not in
                # the routing function — conditional-edge functions cannot
                # durably mutate state.
                new_count = state.get("revision_count", 0) + 1
                state["revision_count"] = new_count
                _update_run(db, state["run_id"], revision_count=new_count)

                if feedback.revision_target == RevisionTarget.RESEARCH and feedback.additional_research_questions:
                    state["pending_research_questions"] = [
                        ResearchQuestion(
                            id=f"gap-{uuid.uuid4().hex[:8]}", question=q, rationale="Critic-flagged evidence gap"
                        )
                        for q in feedback.additional_research_questions
                    ]
                else:
                    state["pending_research_questions"] = None
            return state
        finally:
            db.close()

    def route_after_critic(state: WorkflowState) -> str:
        """Pure routing decision — reads state only, never mutates it."""
        feedback = state["critic_feedback"]
        assert feedback is not None
        if feedback.verdict == CriticVerdict.REVISION_REQUIRED:
            return "revise_research" if state.get("pending_research_questions") else "revise_analyst"
        return "approved"

    async def writer_node(state: WorkflowState) -> WorkflowState:
        db = db_factory()
        try:
            _update_run(db, state["run_id"], current_stage="writer")
            plan = state["plan"]
            analysis = state["analysis"]
            assert plan is not None and analysis is not None
            evidence_rows = retrieve_evidence(db, state["run_id"])
            report = await writer_agent.write(db, state["run_id"], plan, analysis, evidence_rows)
            state["final_report"] = report
            state["status"] = "completed"
            state["current_stage"] = "completed"

            from app.models import Report

            db.add(
                Report(
                    run_id=state["run_id"],
                    version=state.get("revision_count", 0) + 1,
                    content_markdown=report.markdown,
                    critic_verdict=state["critic_feedback"].verdict.value,
                )
            )
            _update_run(
                db,
                state["run_id"],
                status="completed",
                current_stage="completed",
                completed_at=datetime.now(timezone.utc),
            )
            db.commit()
            return state
        finally:
            db.close()

    graph = StateGraph(WorkflowState)
    graph.add_node("request_analysis", request_analysis_node)
    graph.add_node("planning", planning_node)
    graph.add_node("research", research_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("critic", critic_node)
    graph.add_node("writer", writer_node)

    graph.set_entry_point("request_analysis")
    graph.add_conditional_edges(
        "request_analysis",
        route_after_request_analysis,
        {"pause": END, "proceed": "planning"},
    )
    graph.add_edge("planning", "research")
    graph.add_edge("research", "analyst")
    graph.add_edge("analyst", "critic")
    graph.add_conditional_edges(
        "critic",
        route_after_critic,
        {"revise_research": "research", "revise_analyst": "analyst", "approved": "writer"},
    )
    graph.add_edge("writer", END)

    return graph.compile()
