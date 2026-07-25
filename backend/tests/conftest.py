"""
Shared test fixtures.

Important distinction from the old test suite: these fixtures are ordinary
pytest test doubles (monkeypatching the LLM/search calls so tests run
offline and deterministically) — they are NOT the application's own
"mock mode", which has been removed entirely from app/ code. The app
itself always calls real OpenRouter/Tavily and fails loudly if those
aren't configured; only the *tests* substitute canned responses, which is
standard practice for isolating unit tests from network calls.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import WorkflowRun
from app.schemas import EvidenceItem


@pytest.fixture()
def db_session_factory():
    """
    Return a sessionmaker bound to a fresh in-memory SQLite DB.

    Uses StaticPool (a single shared connection) rather than the default
    pooling behavior, because LangGraph runs synchronous conditional-edge
    functions (e.g. route_after_critic) in a background executor thread.
    Without StaticPool, SQLite's default per-thread connection pool for
    `:memory:` URLs would hand that thread a completely separate, empty
    in-memory database, causing spurious "no such table" errors — a real
    gotcha worth knowing about, not a logic bug in the graph itself.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def db_session(db_session_factory):
    """A single DB session with a seeded WorkflowRun row (id='test-run')."""
    session = db_session_factory()
    session.add(WorkflowRun(id="test-run", objective="Test objective"))
    session.commit()
    yield session
    session.close()


def _llm_side_effect(system_prompt: str, user_prompt: str, *, json_mode: bool = False) -> str:
    """Route canned responses based on which agent's system prompt is calling."""
    if "request-analysis" in system_prompt:
        # Always judge the request clear enough to proceed in tests, unless
        # a test explicitly overrides this fixture's side_effect.
        return json.dumps(
            {
                "needs_clarification": False,
                "clarification_question": "",
                "interpreted_objective": "Should we adopt Kubernetes for our platform?",
            }
        )
    if "Supervisor Agent" in system_prompt:
        return json.dumps(
            {
                "objective": "Should we adopt Kubernetes for our platform?",
                "research_questions": [
                    {"id": "q1", "question": "What operational benefits does Kubernetes provide at our scale?", "rationale": "core benefit case"},
                    {"id": "q2", "question": "What are the operational costs and complexity of running Kubernetes?", "rationale": "cost case"},
                    {"id": "q3", "question": "What alternatives to Kubernetes exist for container orchestration?", "rationale": "alternatives"},
                ],
                "notes": "test plan",
            }
        )
    if "Analyst Agent" in system_prompt:
        return json.dumps(
            {
                "key_insights": ["Kubernetes reduces manual scaling effort based on the collected evidence."],
                "comparison_table": [],
                "trade_offs": ["Operational complexity increases with a Kubernetes migration."],
                "unsupported_claim_warnings": [],
            }
        )
    if "Critic Agent" in system_prompt:
        return json.dumps(
            {
                "verdict": "APPROVED",
                "issues": [],
                "justification": "Well supported by evidence.",
                "revision_target": "analyst",
                "additional_research_questions": [],
            }
        )
    if "Report Writer Agent" in system_prompt:
        return (
            "# Should We Adopt Kubernetes?\n\n"
            "## Introduction\nThis report evaluates Kubernetes adoption based on collected evidence [1][2].\n\n"
            "## Analysis\nKubernetes offers scaling benefits but adds operational complexity [1].\n\n"
            "## Conclusion\nProceed with a phased rollout.\n"
        )
    raise AssertionError(f"Unexpected system prompt in test: {system_prompt[:80]!r}")


@pytest.fixture()
def patched_llm(monkeypatch):
    """Replace real OpenRouter calls with a deterministic canned-response router."""
    from app.llm_client import LLMClient

    mock_complete = AsyncMock(side_effect=_llm_side_effect)
    monkeypatch.setattr(LLMClient, "complete", mock_complete)
    return mock_complete


@pytest.fixture()
def patched_search(monkeypatch):
    """Replace the real Tavily call (used by the Research agent) with fixed evidence."""

    async def _fake_web_search(query: str, question_id: str | None = None, max_results: int = 4):
        return [
            EvidenceItem(
                source_title=f"Test Source on {query[:30]}",
                source_url=f"https://real-example-domain.test/source-{question_id}",
                snippet=f"Findings relevant to: {query}",
                question_id=question_id,
            )
            for _ in range(2)
        ]

    monkeypatch.setattr("app.agents.research.web_search", _fake_web_search)
    return _fake_web_search


@pytest.fixture(autouse=True)
def configured_settings(monkeypatch):
    """
    Ensure settings report as fully configured during tests, regardless of
    the environment's actual .env — the patched_llm/patched_search fixtures
    handle not making real network calls.
    """
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "tavily_api_key", "test-key", raising=False)
    return settings
