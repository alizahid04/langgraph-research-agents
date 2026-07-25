"""
Research Agent.

Responsibilities: search the web, retrieve evidence, preserve citations,
flag missing information. Tool permissions: SEARCH + EVIDENCE STORAGE ONLY.
"""
from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.schemas import EvidenceItem, ResearchQuestion
from app.tools.evidence_tool import store_evidence
from app.tools.search_tool import web_search


class ResearchAgent(BaseAgent):
    name = "research"
    allowed_tools = ("search", "evidence_store")

    async def research_question(
        self, db: Session, run_id: str, question: ResearchQuestion
    ) -> list[EvidenceItem]:
        self.log_event(db, run_id, "searching", question.question)
        results = await web_search(question.question, question_id=question.id)
        store_evidence(db, run_id, task_id=question.id, items=results)
        self.log_event(db, run_id, "evidence_stored", f"{len(results)} items for '{question.id}'")
        return results

    async def research_all(
        self, db: Session, run_id: str, questions: list[ResearchQuestion]
    ) -> list[EvidenceItem]:
        """Run research for all questions in parallel (parallel research stage)."""
        self.log_event(db, run_id, "started", f"Researching {len(questions)} questions in parallel")
        results_lists = await asyncio.gather(
            *(self.research_question(db, run_id, q) for q in questions)
        )
        all_evidence = [item for sublist in results_lists for item in sublist]
        self.log_event(db, run_id, "completed", f"Total evidence collected: {len(all_evidence)}")
        return all_evidence
