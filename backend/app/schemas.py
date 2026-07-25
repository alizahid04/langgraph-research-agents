"""
Pydantic schemas.

These define the strict "handoff contracts" between agents (no raw chat
history is ever passed between agents — only these typed structures) as
well as the request/response models for the public API.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class WorkflowStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    COMPLETED = "completed"
    FAILED = "failed"


class CriticVerdict(str, Enum):
    APPROVED = "APPROVED"
    REVISION_REQUIRED = "REVISION_REQUIRED"


class RevisionTarget(str, Enum):
    """Which upstream agent should redo its work when the Critic requests a revision."""

    RESEARCH = "research"
    ANALYST = "analyst"


# ---------------------------------------------------------------------------
# Agent handoff contracts
# ---------------------------------------------------------------------------
class RequestAnalysis(BaseModel):
    """
    Output of the Supervisor's first step: deciding whether the objective is
    clear enough to plan against, or whether it's too ambiguous and needs a
    clarifying question sent back to the user before planning proceeds.
    """

    needs_clarification: bool
    clarification_question: str = ""
    interpreted_objective: str = ""


class ResearchQuestion(BaseModel):
    id: str
    question: str
    rationale: str = ""


class ResearchPlan(BaseModel):
    """Output of the Supervisor agent's planning step."""

    objective: str
    research_questions: list[ResearchQuestion]
    notes: str = ""


class EvidenceItem(BaseModel):
    """A single fact gathered by the Research agent, always cited."""

    source_title: str
    source_url: str
    snippet: str
    question_id: str | None = None


class ResearchFindings(BaseModel):
    """Output of the Research agent for one research question."""

    question_id: str
    evidence: list[EvidenceItem]
    missing_information: str = ""


class ComparisonRow(BaseModel):
    dimension: str
    values: dict[str, str]


class AnalysisResult(BaseModel):
    """Output of the Analyst agent."""

    key_insights: list[str]
    comparison_table: list[ComparisonRow] = Field(default_factory=list)
    trade_offs: list[str] = Field(default_factory=list)
    unsupported_claim_warnings: list[str] = Field(default_factory=list)


class CriticFeedback(BaseModel):
    """
    Output of the Critic agent.

    When verdict is REVISION_REQUIRED, `revision_target` decides which
    upstream agent redoes its work: "research" if the real problem is
    insufficient/missing evidence (in which case `additional_research_questions`
    names what gap-filling searches are needed), or "analyst" if the evidence
    is adequate but the synthesis of it was weak.
    """

    verdict: CriticVerdict
    issues: list[str] = Field(default_factory=list)
    justification: str = ""
    revision_target: RevisionTarget = RevisionTarget.ANALYST
    additional_research_questions: list[str] = Field(default_factory=list)


class FinalReport(BaseModel):
    """
    Output of the Report Writer agent.

    The report's internal structure is intentionally NOT modeled as fixed
    fields (no forced executive_summary/comparison/risks/etc.) — the Writer
    adapts section structure to the topic. `markdown` is the full adaptive
    report; `references` is the deterministic, evidence-backed source list.
    """

    title: str
    markdown: str
    references: list[str]


# ---------------------------------------------------------------------------
# API request / response models
# ---------------------------------------------------------------------------
class CreateWorkflowRequest(BaseModel):
    objective: str = Field(..., min_length=5, description="The research / decision question to solve")


class ClarificationAnswer(BaseModel):
    answer: str = Field(..., min_length=1, description="The user's answer to the Supervisor's clarifying question")


class WorkflowSummary(BaseModel):
    id: str
    objective: str
    status: WorkflowStatus
    current_stage: str
    revision_count: int
    clarification_question: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskOut(BaseModel):
    id: str
    agent: str
    question: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class EvidenceOut(BaseModel):
    id: str
    source_title: str
    source_url: str
    snippet: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReportOut(BaseModel):
    id: str
    version: int
    content_markdown: str
    critic_verdict: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LogOut(BaseModel):
    id: str
    agent: str
    event: str
    detail: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkflowDetail(BaseModel):
    run: WorkflowSummary
    tasks: list[TaskOut]
    evidence: list[EvidenceOut]
    reports: list[ReportOut]
    logs: list[LogOut]


class DashboardStats(BaseModel):
    total_workflows: int
    active_agents: int
    running_tasks: int
    evidence_count: int
    reports_generated: int
    success_rate: float
    avg_workflow_seconds: float
