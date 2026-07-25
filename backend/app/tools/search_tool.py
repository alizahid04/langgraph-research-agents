"""Web search tool. Calls Tavily directly — no synthetic fallback."""
from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.exceptions import SearchNotConfiguredError
from app.schemas import EvidenceItem

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"


async def web_search(query: str, question_id: str | None = None, max_results: int = 4) -> list[EvidenceItem]:
    """
    Search the web for `query` and return citation-preserving evidence items.

    Raises:
        SearchNotConfiguredError: if TAVILY_API_KEY is not set. There is no
        fallback to synthetic/example.com results.
    """
    settings = get_settings()
    if not settings.tavily_configured:
        raise SearchNotConfiguredError()

    payload = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "advanced",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(TAVILY_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()

    items: list[EvidenceItem] = []
    for r in data.get("results", [])[:max_results]:
        items.append(
            EvidenceItem(
                source_title=r.get("title", "Untitled source"),
                source_url=r.get("url", ""),
                snippet=(r.get("content", "") or "")[:1200],
                question_id=question_id,
            )
        )
    return items
