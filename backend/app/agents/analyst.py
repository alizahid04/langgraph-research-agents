"""
Analyst Agent.

Responsibilities: compare findings, identify trade-offs, build comparison
tables (only when the topic actually has comparable options), generate
insights. Must never invent unsupported facts. Tool permissions: EVIDENCE
ACCESS ONLY (read-only, no search).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.models import Evidence
from app.schemas import AnalysisResult, ComparisonRow

SYSTEM_PROMPT = """You are the Analyst Agent. Using ONLY the evidence provided
below (never invent facts not present in the evidence), produce a synthesis.

Return ONLY a JSON object of this exact shape:
{
  "key_insights": [str, ...],
  "comparison_table": [{"dimension": str, "values": {label: value}}],
  "trade_offs": [str, ...],
  "unsupported_claim_warnings": [str, ...]
}

Important:
- "comparison_table" should ONLY be populated if the topic genuinely involves
  comparable options (e.g. competing tools, models, or approaches). For a
  purely explanatory/survey topic with no distinct options to compare,
  return an empty list [] rather than inventing a false comparison.
- "key_insights" should be substantive and specific to the evidence — reference
  concrete facts, numbers, or claims found in the evidence, not vague filler.
- If the evidence is thin or contradictory, say so explicitly in
  "unsupported_claim_warnings" instead of papering over the gap.
"""


class AnalystAgent(BaseAgent):
    name = "analyst"
    allowed_tools = ("evidence_retrieve",)

    async def analyze(self, db: Session, run_id: str, evidence: list[Evidence]) -> AnalysisResult:
        self.log_event(db, run_id, "started", f"Analyzing {len(evidence)} evidence items")

        if not evidence:
            self.log_event(db, run_id, "warning", "No evidence available to analyze")

        evidence_text = "\n\n".join(
            f"[{i + 1}] Source: {e.source_title} ({e.source_url})\n{e.snippet}"
            for i, e in enumerate(evidence)
        ) or "No evidence was collected."

        raw = await self.llm.complete(
            SYSTEM_PROMPT,
            f"Evidence:\n{evidence_text}",
            json_mode=True,
        )
        data = self.llm.parse_json(raw)

        result = AnalysisResult(
            key_insights=data.get("key_insights", []),
            comparison_table=[ComparisonRow(**row) for row in data.get("comparison_table", [])],
            trade_offs=data.get("trade_offs", []),
            unsupported_claim_warnings=data.get("unsupported_claim_warnings", []),
        )
        self.log_event(db, run_id, "completed", f"{len(result.key_insights)} insights generated")
        return result
