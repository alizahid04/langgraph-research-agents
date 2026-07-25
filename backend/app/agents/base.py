"""Base class shared by all agents."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.llm_client import LLMClient
from app.models import ExecutionLog

logger = logging.getLogger(__name__)


class BaseAgent:
    """
    Common functionality for every agent: LLM access and execution-trace
    logging (which powers the live agent monitor / timeline in the UI).
    """

    name: str = "base_agent"
    allowed_tools: tuple[str, ...] = ()

    def __init__(self) -> None:
        self.llm = LLMClient()

    def log_event(self, db: Session, run_id: str, event: str, detail: str = "") -> None:
        """Persist a structured execution-trace event."""
        entry = ExecutionLog(run_id=run_id, agent=self.name, event=event, detail=detail)
        db.add(entry)
        db.commit()
        logger.info("[%s] %s: %s", self.name, event, detail)
