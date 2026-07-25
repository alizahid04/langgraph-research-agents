"""
Report Writer Agent.

Responsibilities: produce a genuinely topic-specific final report — the
section structure adapts to what the topic needs (a technical survey looks
very different from a build-vs-buy decision memo). Tool permissions:
EXPORT ONLY.

Design note (fixes the "generic report" bug): the Writer used to assemble a
hardcoded Python f-string template and never called the LLM at all, so the
report always had the same six sections no matter the topic. Now the LLM
writes the entire body from the plan + evidence + analysis, and is
explicitly told to adapt structure to the topic. To keep references honest
(no hallucinated URLs), the Writer numbers the real evidence items itself
and appends a deterministic References section built from that same list —
the LLM is instructed to cite using those exact [n] numbers rather than
inventing its own sources.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.models import Evidence
from app.schemas import AnalysisResult, FinalReport, ResearchPlan

SYSTEM_PROMPT = """You are the Report Writer Agent. Write a complete,
professional, long-form Markdown report that genuinely answers the user's
objective, using ONLY the evidence and analysis provided — never invent facts.

Adapt the report's structure to what THIS topic actually needs. Do not force
a fixed template. Choose from (and reorder/rename/omit as appropriate):
Title, Introduction, Background, Detailed Explanation, Technical Analysis,
Comparison Tables (ONLY if the topic genuinely involves comparable options —
omit entirely otherwise), Advantages, Limitations, Future Directions,
Conclusion. A technical/survey topic should read like a technical survey.
A decision/build-vs-buy topic should read like a decision memo. Do not
include a "References" section yourself — it will be appended separately.

Citations: evidence items below are numbered [1], [2], [3]... Cite claims
inline using those exact bracket numbers (e.g. "...as shown in recent
benchmarks [2][5]."). Do not invent sources or renumber them.

Start the report with a single "# Title" heading, then the adaptive body.
Return ONLY the Markdown — no commentary before or after it.
"""


class WriterAgent(BaseAgent):
    name = "writer"
    allowed_tools = ("export",)

    async def write(
        self,
        db: Session,
        run_id: str,
        plan: ResearchPlan,
        analysis: AnalysisResult,
        evidence: list[Evidence],
    ) -> FinalReport:
        self.log_event(db, run_id, "started", "Drafting adaptive final report")

        numbered_evidence = "\n\n".join(
            f"[{i + 1}] {e.source_title} ({e.source_url})\n{e.snippet}"
            for i, e in enumerate(evidence)
        ) or "No evidence was collected."

        analysis_summary = (
            f"Key insights:\n" + "\n".join(f"- {i}" for i in analysis.key_insights)
            + "\n\nTrade-offs:\n" + "\n".join(f"- {t}" for t in analysis.trade_offs)
            + "\n\nUnresolved gaps/warnings:\n" + "\n".join(f"- {w}" for w in analysis.unsupported_claim_warnings)
        )

        if analysis.comparison_table:
            headers = ["Dimension"] + sorted(
                {k for row in analysis.comparison_table for k in row.values.keys()}
            )
            table_lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
            for row in analysis.comparison_table:
                cells = [row.dimension] + [row.values.get(h, "-") for h in headers[1:]]
                table_lines.append("| " + " | ".join(cells) + " |")
            comparison_hint = (
                "\n\nThe Analyst identified this comparison table — include it if it "
                "fits the report's structure:\n" + "\n".join(table_lines)
            )
        else:
            comparison_hint = "\n\nThe Analyst found no distinct options to compare for this topic."

        user_prompt = (
            f"Research objective: {plan.objective}\n\n"
            f"Research questions investigated:\n"
            + "\n".join(f"- {q.question}" for q in plan.research_questions)
            + f"\n\nNumbered evidence:\n{numbered_evidence}"
            + f"\n\n{analysis_summary}"
            + comparison_hint
        )

        body_markdown = await self.llm.complete(SYSTEM_PROMPT, user_prompt, json_mode=False)
        body_markdown = body_markdown.strip()

        references_lines = [
            f"{i + 1}. [{e.source_title}]({e.source_url})" for i, e in enumerate(evidence)
        ]
        references_md = "\n".join(references_lines) if references_lines else "_No references available._"

        markdown = f"{body_markdown}\n\n## References\n{references_md}\n"

        title_line = next((line for line in body_markdown.splitlines() if line.strip().startswith("# ")), None)
        title = title_line.lstrip("# ").strip() if title_line else plan.objective

        report = FinalReport(
            title=title,
            markdown=markdown,
            references=[e.source_url for e in evidence],
        )
        self.log_event(db, run_id, "completed", "Final report generated")
        return report
