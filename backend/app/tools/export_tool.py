"""Markdown export and citation validation tools for the Writer/Critic agents."""
from __future__ import annotations

import re

from app.models import Evidence


def export_markdown(report_markdown: str) -> bytes:
    """Return report markdown encoded as downloadable bytes."""
    return report_markdown.encode("utf-8")


def validate_citations(report_markdown: str, evidence: list[Evidence]) -> list[str]:
    """
    Very lightweight citation validator: flags markdown links in the report
    whose URL does not match any known evidence source URL.
    """
    known_urls = {e.source_url for e in evidence}
    linked_urls = re.findall(r"\]\((https?://[^\s)]+)\)", report_markdown)

    warnings: list[str] = []
    for url in linked_urls:
        if url not in known_urls:
            warnings.append(f"Referenced URL not found in stored evidence: {url}")
    return warnings
