"""
Critic Agent.

Responsibilities: detect weak reasoning, unsupported claims, missing
evidence, contradictions, logical issues. Returns APPROVED or
REVISION_REQUIRED — and when requesting a revision, decides WHICH upstream
agent should redo its work: Research (if the real problem is insufficient
evidence) or Analyst (if the evidence is adequate but its synthesis is
weak). Tool permissions: ANALYSIS ACCESS ONLY (no tools).
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.schemas import AnalysisResult, CriticFeedback, CriticVerdict, RevisionTarget

SYSTEM_PROMPT = """You are the Critic Agent. Review the analysis below for weak
reasoning, unsupported claims, missing evidence, and contradictions.

If you find real problems, decide the ROOT CAUSE:
- If the evidence itself is too thin, missing key facts, or doesn't cover
  something the analysis needed to address — the fix is to gather MORE
  evidence. Set "revision_target": "research" and list 1-3 specific
  additional search queries in "additional_research_questions" that would
  fill the gap.
- If the evidence is adequate but the analysis drew weak conclusions,
  missed obvious insights, or reasoned poorly from what it had — the fix is
  to re-analyze the SAME evidence. Set "revision_target": "analyst" and
  leave "additional_research_questions" empty.

Return ONLY a JSON object of this exact shape:
{
  "verdict": "APPROVED" | "REVISION_REQUIRED",
  "issues": [str, ...],
  "justification": str,
  "revision_target": "research" | "analyst",
  "additional_research_questions": [str, ...]
}

Be strict but fair — approve if the analysis is reasonably well supported
by its evidence-derived insights. Flag REVISION_REQUIRED only for concrete,
specific problems, not stylistic preferences. If verdict is APPROVED,
revision_target can be "analyst" (ignored) and additional_research_questions
should be empty.
"""


class CriticAgent(BaseAgent):
    name = "critic"
    allowed_tools = ()  # analysis access only, no tools

    async def review(
        self, db: Session, run_id: str, analysis: AnalysisResult, revision_count: int, max_revisions: int
    ) -> CriticFeedback:
        self.log_event(db, run_id, "started", f"Reviewing analysis (revision {revision_count})")

        analysis_text = json.dumps(analysis.model_dump(), indent=2)

        raw = await self.llm.complete(
            SYSTEM_PROMPT,
            f"Analysis:\n{analysis_text}\n\nRevision count so far: {revision_count}/{max_revisions}",
            json_mode=True,
        )
        data = self.llm.parse_json(raw)

        verdict = CriticVerdict(data.get("verdict", "APPROVED"))

        # Hard cap: never request another revision once max_revisions is hit.
        # This is a real safety limit (guarantees graph termination), not a
        # mock shortcut — the Critic's actual judgement above is unaffected.
        if revision_count >= max_revisions:
            verdict = CriticVerdict.APPROVED

        feedback = CriticFeedback(
            verdict=verdict,
            issues=data.get("issues", []),
            justification=data.get("justification", ""),
            revision_target=RevisionTarget(data.get("revision_target", "analyst")),
            additional_research_questions=data.get("additional_research_questions", []),
        )
        self.log_event(
            db,
            run_id,
            "verdict",
            f"{feedback.verdict.value}"
            + (f" (revise: {feedback.revision_target.value})" if verdict == CriticVerdict.REVISION_REQUIRED else ""),
        )
        return feedback
