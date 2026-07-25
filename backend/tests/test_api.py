"""Tests for the create-workflow API endpoint's pre-flight configuration check."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_create_workflow_rejects_when_keys_missing(monkeypatch):
    """
    Fixes: previously, a missing API key silently triggered mock mode and
    the run would "succeed" with synthetic data. Now it must fail fast with
    a clear 400 and never create a run that will only fail later.
    """
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "openrouter_api_key", "", raising=False)
    monkeypatch.setattr(settings, "tavily_api_key", "", raising=False)

    client = TestClient(app)
    resp = client.post("/api/workflows", json={"objective": "Should we adopt Kubernetes?"})

    assert resp.status_code == 400
    body = resp.json()
    assert "OPENROUTER_API_KEY" in body["detail"]
    assert "TAVILY_API_KEY" in body["detail"]


def test_health_check_reports_real_configuration_state(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "openrouter_api_key", "", raising=False)
    monkeypatch.setattr(settings, "tavily_api_key", "some-key", raising=False)

    client = TestClient(app)
    resp = client.get("/api/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["openrouter_configured"] is False
    assert data["tavily_configured"] is True
