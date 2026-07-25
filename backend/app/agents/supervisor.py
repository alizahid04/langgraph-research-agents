"""
Supervisor Agent.

Responsibilities: understand the objective (asking for clarification if it's
genuinely too ambiguous to research), then produce a dynamic research plan.
Tool permissions: PLANNING ONLY — this agent must never call the search tool
or perform research itself.

This agent now runs in two explicit steps, matching the "Request Analysis"
and "Research Plan" stages of the architecture diagram:

  1. analyze_request() — decides whether the objective is clear enough to
     plan against, or needs a clarifying question sent back to the user.
  2. plan() — produces the actual research plan, incorporating the user's
     clarification answer if one was given.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.schemas import RequestAnalysis, ResearchPlan, ResearchQuestion

ANALYSIS_SYSTEM_PROMPT = """You are the Supervisor Agent's request-analysis
step. Decide whether the user's objective is clear enough to plan real
research questions against, or whether it is genuinely too ambiguous to
proceed without a clarifying question.

Only ask for clarification for GENUINE ambiguity that would make the
research plan meaningfully different depending on the answer — for example,
"AI in healthcare" could mean diagnostics, hospital operations, drug
discovery, or patient privacy, and a good plan needs to know which. Do NOT
ask for clarification just because a topic is broad but has an obvious
default interpretation, or because you'd merely prefer more detail — err
towards proceeding.

Return ONLY a JSON object of this exact shape:
{"needs_clarification": bool, "clarification_question": str, "interpreted_objective": str}

If needs_clarification is false, clarification_question can be an empty
string, and interpreted_objective should restate the objective as you
understood it.
"""

PLAN_SYSTEM_PROMPT = """You are the Supervisor Agent in a multi-agent research system.
Your ONLY job is to break the user's objective into 3-6 precise, non-overlapping
research questions that, once answered with real evidence, give enough material
to write a genuinely useful, topic-specific report (not a generic template).

Tailor the questions to what this specific topic actually needs. For example:
- A technical/survey topic ("transformer architectures from BERT to GPT-5")
  needs questions about historical development, key architectural innovations,
  benchmarks, and known limitations/open problems — NOT generic "pros vs cons".
- A decision topic ("should we adopt microservices") needs questions about
  trade-offs, costs, risks, and alternatives.

You never search the web or produce findings yourself — you only plan.
Return ONLY a JSON object of this exact shape, with no extra commentary:
{"objective": str, "research_questions": [{"id": str, "question": str, "rationale": str}], "notes": str}
"""


class SupervisorAgent(BaseAgent):
    name = "supervisor"
    allowed_tools = ()  # planning only, no tools

    async def analyze_request(
        self, db: Session, run_id: str, user_request: str, clarification_answer: str | None = None
    ) -> RequestAnalysis:
        """
        Decide whether the objective needs clarification before planning.

        If `clarification_answer` is provided, it means the user has already
        answered a previous clarifying question this run — the caller is
        responsible for capping clarification rounds (see workflow.py); this
        method itself always makes a fresh judgement call.
        """
        self.log_event(db, run_id, "started", "Analyzing request for ambiguity")

        user_prompt = f"User objective: {user_request}"
        if clarification_answer:
            user_prompt += f"\n\nThe user already clarified: {clarification_answer}"

        raw = await self.llm.complete(ANALYSIS_SYSTEM_PROMPT, user_prompt, json_mode=True)
        data = self.llm.parse_json(raw)

        analysis = RequestAnalysis(
            needs_clarification=bool(data.get("needs_clarification", False)),
            clarification_question=data.get("clarification_question", ""),
            interpreted_objective=data.get("interpreted_objective", user_request),
        )

        if analysis.needs_clarification:
            self.log_event(db, run_id, "clarification_needed", analysis.clarification_question)
        else:
            self.log_event(db, run_id, "request_clear", analysis.interpreted_objective)
        return analysis

    async def plan(self, db: Session, run_id: str, user_request: str) -> ResearchPlan:
        self.log_event(db, run_id, "planning_started", "Drafting research plan")

        raw = await self.llm.complete(
            PLAN_SYSTEM_PROMPT,
            f"User objective: {user_request}",
            json_mode=True,
        )
        data = self.llm.parse_json(raw)

        questions = [ResearchQuestion(**q) for q in data.get("research_questions", [])]
        plan = ResearchPlan(
            objective=data.get("objective", user_request),
            research_questions=questions,
            notes=data.get("notes", ""),
        )

        self.log_event(
            db, run_id, "plan_ready", f"{len(plan.research_questions)} research questions created"
        )
        return plan
