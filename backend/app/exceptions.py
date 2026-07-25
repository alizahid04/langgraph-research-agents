"""
Custom exceptions.

These exist so that missing configuration or generation failures surface
as clear, actionable errors instead of the system silently falling back to
synthetic/mock data.
"""
from __future__ import annotations


class LLMNotConfiguredError(RuntimeError):
    """Raised when an LLM call is attempted without OPENROUTER_API_KEY configured."""

    def __init__(self) -> None:
        super().__init__(
            "OPENROUTER_API_KEY is not configured. Set it in your .env file "
            "to enable real LLM reasoning — the platform does not run on "
            "synthetic/mock responses."
        )


class SearchNotConfiguredError(RuntimeError):
    """Raised when a web search is attempted without TAVILY_API_KEY configured."""

    def __init__(self) -> None:
        super().__init__(
            "TAVILY_API_KEY is not configured. Set it in your .env file to "
            "enable real web search — the platform does not fall back to "
            "synthetic evidence."
        )


class ReportGenerationError(RuntimeError):
    """Raised when the LLM's output cannot be parsed/used and no safe fallback exists."""
