"""
Tests for individual agents.

Real network calls (OpenRouter, Tavily) are replaced with deterministic
test doubles via the `patched_llm` / `patched_search` fixtures in
conftest.py — this is normal test isolation, not the application's mock
mode (which has been removed; see app/llm_client.py and
app/tools/search_tool.py, which now raise LLMNotConfiguredError /
SearchNotConfiguredError instead of returning synthetic data).
"""
from __future__ import annotations

import pytest

from app.agents.analyst import AnalystAgent
from app.agents.critic import CriticAgent
from app.agents.research import ResearchAgent
from app.agents.supervisor import SupervisorAgent
from app.agents.writer import WriterAgent
from app.exceptions import LLMNotConfiguredError, ReportGenerationError, SearchNotConfiguredError
from app.llm_client import LLMClient
from app.models import Evidence
from app.schemas import AnalysisResult, CriticVerdict, ResearchQuestion


@pytest.mark.asyncio
async def test_supervisor_produces_topic_specific_plan(db_session, patched_llm):
    agent = SupervisorAgent()
    plan = await agent.plan(db_session, "test-run", "Should we adopt Kubernetes for our platform?")
    assert plan.objective
    assert len(plan.research_questions) >= 3
    assert all(q.id and q.question for q in plan.research_questions)
    assert "kubernetes" in plan.objective.lower() or any(
        "kubernetes" in q.question.lower() for q in plan.research_questions
    )


@pytest.mark.asyncio
async def test_supervisor_analyze_request_does_not_flag_clear_objective(db_session, patched_llm):
    agent = SupervisorAgent()
    analysis = await agent.analyze_request(db_session, "test-run", "Should we adopt Kubernetes for our platform?")
    assert analysis.needs_clarification is False
    assert analysis.interpreted_objective


@pytest.mark.asyncio
async def test_supervisor_analyze_request_flags_ambiguous_objective(db_session, monkeypatch):
    import json as _json

    from app.llm_client import LLMClient as _LLMClient

    async def ambiguous_response(self, system_prompt, user_prompt, *, json_mode=False):
        return _json.dumps(
            {
                "needs_clarification": True,
                "clarification_question": "Which domain of healthcare do you mean?",
                "interpreted_objective": "",
            }
        )

    monkeypatch.setattr(_LLMClient, "complete", ambiguous_response)

    agent = SupervisorAgent()
    analysis = await agent.analyze_request(db_session, "test-run", "AI in healthcare")
    assert analysis.needs_clarification is True
    assert analysis.clarification_question


@pytest.mark.asyncio
async def test_research_agent_uses_search_tool_per_question(db_session, patched_search):
    agent = ResearchAgent()
    questions = [
        ResearchQuestion(id="q1", question="What are Kubernetes scaling benefits?"),
        ResearchQuestion(id="q2", question="What alternatives exist?"),
    ]
    evidence = await agent.research_all(db_session, "test-run", questions)
    assert len(evidence) == 4  # 2 questions x 2 fake results each
    assert {e.question_id for e in evidence} == {"q1", "q2"}


@pytest.mark.asyncio
async def test_analyst_synthesizes_from_provided_evidence(db_session, patched_llm):
    agent = AnalystAgent()
    evidence = [
        Evidence(
            run_id="test-run",
            source_title="Kubernetes at Scale",
            source_url="https://real-example-domain.test/a",
            snippet="Kubernetes reduces manual scaling toil for large fleets.",
        )
    ]
    result = await agent.analyze(db_session, "test-run", evidence)
    assert isinstance(result, AnalysisResult)
    assert result.key_insights


@pytest.mark.asyncio
async def test_critic_approves_well_supported_analysis(db_session, patched_llm):
    agent = CriticAgent()
    analysis = AnalysisResult(key_insights=["Well supported insight"], unsupported_claim_warnings=[])
    feedback = await agent.review(db_session, "test-run", analysis, revision_count=0, max_revisions=2)
    assert feedback.verdict == CriticVerdict.APPROVED


@pytest.mark.asyncio
async def test_critic_reports_revision_target_and_gap_questions(db_session, monkeypatch):
    from app.llm_client import LLMClient as _LLMClient
    from app.schemas import RevisionTarget

    async def research_gap_response(self, system_prompt, user_prompt, *, json_mode=False):
        return (
            '{"verdict": "REVISION_REQUIRED", "issues": ["thin evidence"], '
            '"justification": "need more data", "revision_target": "research", '
            '"additional_research_questions": ["A gap-filling query"]}'
        )

    monkeypatch.setattr(_LLMClient, "complete", research_gap_response)

    agent = CriticAgent()
    analysis = AnalysisResult(key_insights=["ok"], unsupported_claim_warnings=["thin evidence"])
    feedback = await agent.review(db_session, "test-run", analysis, revision_count=0, max_revisions=2)

    assert feedback.verdict == CriticVerdict.REVISION_REQUIRED
    assert feedback.revision_target == RevisionTarget.RESEARCH
    assert feedback.additional_research_questions == ["A gap-filling query"]


@pytest.mark.asyncio
async def test_critic_never_exceeds_max_revisions(db_session, monkeypatch):
    """Even if the LLM would request another revision, the hard cap wins."""
    from app.llm_client import LLMClient as _LLMClient

    async def always_revise(self, system_prompt, user_prompt, *, json_mode=False):
        return '{"verdict": "REVISION_REQUIRED", "issues": ["still weak"], "justification": "not enough"}'

    monkeypatch.setattr(_LLMClient, "complete", always_revise)

    agent = CriticAgent()
    analysis = AnalysisResult(key_insights=["ok"], unsupported_claim_warnings=["thin evidence"])
    feedback = await agent.review(db_session, "test-run", analysis, revision_count=2, max_revisions=2)
    assert feedback.verdict == CriticVerdict.APPROVED  # cap forces approval regardless


@pytest.mark.asyncio
async def test_writer_produces_topic_adaptive_report_not_fixed_template(db_session, patched_llm):
    """
    Regression test for the "generic report" bug: the Writer must not emit
    a hardcoded Executive Summary/Methodology/Comparison/Risks template —
    it must use the LLM's adaptive body plus a deterministic References
    section built from real evidence.
    """
    supervisor = SupervisorAgent()
    plan = await supervisor.plan(db_session, "test-run", "Should we adopt Kubernetes for our platform?")
    analysis = AnalysisResult(key_insights=["Insight A"], trade_offs=["Trade-off A"])
    evidence = [
        Evidence(
            run_id="test-run",
            source_title="Kubernetes Docs",
            source_url="https://real-example-domain.test/k8s",
            snippet="Official Kubernetes scaling documentation.",
        )
    ]
    writer = WriterAgent()
    report = await writer.write(db_session, "test-run", plan, analysis, evidence)

    for old_section in ["## Methodology", "## Risks", "## Recommendation"]:
        assert old_section not in report.markdown

    assert "real-example-domain.test/k8s" in report.markdown
    assert "## References" in report.markdown
    assert report.title


@pytest.mark.asyncio
async def test_llm_client_raises_when_not_configured(monkeypatch):
    """No mock fallback: missing key must raise, never return synthetic text."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "openrouter_api_key", "", raising=False)
    client = LLMClient()
    with pytest.raises(LLMNotConfiguredError):
        await client.complete("system", "user", json_mode=True)


@pytest.mark.asyncio
async def test_search_tool_raises_when_not_configured(monkeypatch):
    """No mock fallback: missing Tavily key must raise, never return example.com results."""
    from app.config import get_settings
    from app.tools.search_tool import web_search

    settings = get_settings()
    monkeypatch.setattr(settings, "tavily_api_key", "", raising=False)
    with pytest.raises(SearchNotConfiguredError):
        await web_search("some query")


def test_parse_json_raises_instead_of_falling_back():
    """Malformed model output is a real failure, not a trigger for canned data."""
    with pytest.raises(ReportGenerationError):
        LLMClient.parse_json("not valid json at all")
