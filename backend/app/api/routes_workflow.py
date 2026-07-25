"""API routes for creating and inspecting workflow runs."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal, get_db
from app.graph.workflow import build_workflow
from app.models import Evidence, Report, Task, WorkflowRun
from app.schemas import (
    ClarificationAnswer,
    CreateWorkflowRequest,
    DashboardStats,
    EvidenceOut,
    LogOut,
    ReportOut,
    TaskOut,
    WorkflowDetail,
    WorkflowSummary,
)
from app.tools.export_tool import export_markdown

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workflows", tags=["workflows"])

_workflow_app = build_workflow(SessionLocal)


def _build_initial_state(run_id: str, objective: str, clarifications: list[str], clarification_rounds: int) -> dict:
    settings = get_settings()
    return {
        "run_id": run_id,
        "user_request": objective,
        "objective": objective,
        "clarifications": clarifications,
        "needs_clarification": False,
        "clarification_question": None,
        "clarification_rounds": clarification_rounds,
        "max_clarification_rounds": 1,
        "plan": None,
        "evidence": [],
        "analysis": None,
        "critic_feedback": None,
        "final_report": None,
        "pending_research_questions": None,
        "revision_count": 0,
        "max_revisions": settings.max_revisions,
        "status": "running",
        "current_stage": "supervisor",
        "errors": [],
        "timestamps": {"started": datetime.now(timezone.utc)},
    }


async def _run_workflow_background(initial_state: dict) -> None:
    """Executed as a background task so the create-workflow call returns instantly."""
    run_id = initial_state["run_id"]
    try:
        await _workflow_app.ainvoke(initial_state)
    except Exception as exc:  # noqa: BLE001 - surface all failures to the run record
        logger.exception("Workflow %s failed", run_id)
        db = SessionLocal()
        try:
            run = db.get(WorkflowRun, run_id)
            if run:
                run.status = "failed"
                run.error = str(exc)
                db.commit()
        finally:
            db.close()


@router.post("", response_model=WorkflowSummary, status_code=201)
async def create_workflow(
    payload: CreateWorkflowRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> WorkflowRun:
    """
    Create a new workflow run and kick off execution in the background.

    Fails fast with a clear 400 if required API keys are missing, instead of
    creating a run that will only fail silently later — there is no mock
    mode to quietly fall back to.
    """
    settings = get_settings()
    missing = []
    if not settings.openrouter_configured:
        missing.append("OPENROUTER_API_KEY")
    if not settings.tavily_configured:
        missing.append("TAVILY_API_KEY")
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot start a research run: missing required configuration "
                f"({', '.join(missing)}). Add real values to your .env file — "
                f"this platform does not run on synthetic/mock data."
            ),
        )

    run = WorkflowRun(objective=payload.objective, status="queued", current_stage="supervisor")
    db.add(run)
    db.commit()
    db.refresh(run)

    initial_state = _build_initial_state(run.id, payload.objective, clarifications=[], clarification_rounds=0)
    background_tasks.add_task(_run_workflow_background, initial_state)
    return run


@router.post("/{run_id}/clarify", response_model=WorkflowSummary)
async def submit_clarification(
    run_id: str,
    payload: ClarificationAnswer,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> WorkflowRun:
    """
    Answer the Supervisor's clarifying question and resume a paused run.

    Only valid while the run's status is "awaiting_clarification". Resumes
    as a fresh graph invocation with the answer folded in — capped at one
    clarification round total, so the Supervisor will proceed with the plan
    regardless of its own judgement on the second pass.
    """
    run = db.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if run.status != "awaiting_clarification":
        raise HTTPException(
            status_code=409,
            detail=f"Run is not awaiting clarification (current status: {run.status})",
        )

    run.clarification_answer = payload.answer
    run.status = "running"
    db.commit()
    db.refresh(run)

    initial_state = _build_initial_state(
        run.id,
        run.objective,
        clarifications=[payload.answer],
        clarification_rounds=run.clarification_rounds,
    )
    background_tasks.add_task(_run_workflow_background, initial_state)
    return run


@router.get("", response_model=list[WorkflowSummary])
def list_workflows(db: Session = Depends(get_db)) -> list[WorkflowRun]:
    return db.query(WorkflowRun).order_by(WorkflowRun.created_at.desc()).all()


@router.get("/stats", response_model=DashboardStats)
def get_stats(db: Session = Depends(get_db)) -> DashboardStats:
    total = db.query(func.count(WorkflowRun.id)).scalar() or 0
    running = db.query(func.count(WorkflowRun.id)).filter(WorkflowRun.status == "running").scalar() or 0
    completed = db.query(func.count(WorkflowRun.id)).filter(WorkflowRun.status == "completed").scalar() or 0
    failed = db.query(func.count(WorkflowRun.id)).filter(WorkflowRun.status == "failed").scalar() or 0
    evidence_count = db.query(func.count(Evidence.id)).scalar() or 0
    reports_count = db.query(func.count(Report.id)).scalar() or 0
    running_tasks = db.query(func.count(Task.id)).filter(Task.status == "running").scalar() or 0

    finished = completed + failed
    success_rate = (completed / finished * 100.0) if finished else 100.0

    durations = []
    for run in db.query(WorkflowRun).filter(WorkflowRun.completed_at.isnot(None)).all():
        durations.append((run.completed_at - run.created_at).total_seconds())
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    return DashboardStats(
        total_workflows=total,
        active_agents=5 if running else 0,
        running_tasks=running_tasks,
        evidence_count=evidence_count,
        reports_generated=reports_count,
        success_rate=round(success_rate, 1),
        avg_workflow_seconds=round(avg_duration, 1),
    )


@router.get("/{run_id}", response_model=WorkflowDetail)
def get_workflow(run_id: str, db: Session = Depends(get_db)) -> WorkflowDetail:
    run = db.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    return WorkflowDetail(
        run=WorkflowSummary.model_validate(run),
        tasks=[TaskOut.model_validate(t) for t in run.tasks],
        evidence=[EvidenceOut.model_validate(e) for e in run.evidence],
        reports=[ReportOut.model_validate(r) for r in run.reports],
        logs=[LogOut.model_validate(l) for l in run.logs],
    )


@router.get("/{run_id}/report/download")
def download_report(run_id: str, db: Session = Depends(get_db)) -> Response:
    run = db.get(WorkflowRun, run_id)
    if not run or not run.reports:
        raise HTTPException(status_code=404, detail="No report available for this run")

    latest_report = max(run.reports, key=lambda r: r.version)
    content = export_markdown(latest_report.content_markdown)
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename=report_{run_id}.md"},
    )
