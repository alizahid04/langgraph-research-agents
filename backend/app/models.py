"""ORM models for the platform's persistence layer."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class WorkflowRun(Base):
    """A single end-to-end execution of the multi-agent workflow."""

    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    objective: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="queued")  # queued/running/awaiting_clarification/completed/failed
    current_stage: Mapped[str] = mapped_column(String, default="supervisor")
    revision_count: Mapped[int] = mapped_column(Integer, default=0)
    clarification_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    clarification_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    clarification_rounds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    tasks: Mapped[list["Task"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    reports: Mapped[list["Report"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    logs: Mapped[list["ExecutionLog"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Task(Base):
    """A discrete research task assigned to an agent."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"))
    agent: Mapped[str] = mapped_column(String)
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending/running/completed/failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    run: Mapped["WorkflowRun"] = relationship(back_populates="tasks")


class Evidence(Base):
    """A single piece of evidence gathered by a research agent."""

    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"))
    task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_title: Mapped[str] = mapped_column(String)
    source_url: Mapped[str] = mapped_column(String)
    snippet: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    run: Mapped["WorkflowRun"] = relationship(back_populates="evidence")


class Report(Base):
    """The final (or intermediate, per revision) markdown report."""

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    content_markdown: Mapped[str] = mapped_column(Text)
    critic_verdict: Mapped[str] = mapped_column(String, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    run: Mapped["WorkflowRun"] = relationship(back_populates="reports")


class ExecutionLog(Base):
    """Structured execution trace event for observability / the timeline UI."""

    __tablename__ = "execution_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"))
    agent: Mapped[str] = mapped_column(String)
    event: Mapped[str] = mapped_column(String)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    run: Mapped["WorkflowRun"] = relationship(back_populates="logs")
