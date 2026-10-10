"""Integration tests for FastAPI endpoints."""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "execution_mode" in data


def test_demo_inquiries_endpoint():
    response = client.get("/api/v1/agent/demo-inquiries")
    assert response.status_code == 200
    samples = response.json()
    assert isinstance(samples, list)
    assert len(samples) >= 6


def test_evaluate_endpoint_complete_inquiry():
    payload = {
        "inquiry_id": "api_test_complete_01",
        "contractor_message": "Need a 20-ton excavator for 4 days starting 2026-11-12 at 1200 East 7th St, Austin TX. Budget is $8,000. Dry hire.",
        "contractor_id": "CON-101",
    }
    response = client.post("/api/v1/agent/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["inquiry_id"] == "api_test_complete_01"
    assert data["decision"] == "AUTO_QUOTE"
    assert data["qualification_score"] > 80.0
    assert data["estimated_quote"] is not None
    assert data["confidence_score"] > 0.60
    assert data["execution_mode"] in ["SIMULATED", "LLM"]


def test_evaluate_endpoint_missing_inquiry():
    payload = {
        "inquiry_id": "api_test_missing_02",
        "contractor_message": "Looking to rent an excavator in Buda, TX. What are your rates?",
        "contractor_id": "CON-102",
    }
    response = client.post("/api/v1/agent/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "REQUEST_INFO"
    assert data["follow_up_message"] is not None
    assert len(data["missing_information"]) > 0


def test_get_inquiry_details_and_history():
    # Evaluate an inquiry first
    payload = {
        "inquiry_id": "api_test_history_03",
        "contractor_message": "Need a 20-ton excavator for 4 days starting 2026-11-12 in Austin TX.",
    }
    client.post("/api/v1/agent/evaluate", json=payload)

    # Fetch list
    hist_resp = client.get("/api/v1/agent/inquiries")
    assert hist_resp.status_code == 200
    records = hist_resp.json()
    assert any(r["inquiry_id"] == "api_test_history_03" for r in records)

    # Fetch individual detail
    detail_resp = client.get("/api/v1/agent/inquiries/api_test_history_03")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["inquiry_id"] == "api_test_history_03"
    assert "response" in detail


def test_get_nonexistent_inquiry_returns_404():
    response = client.get("/api/v1/agent/inquiries/nonexistent_id_99999")
    assert response.status_code == 404


def test_update_and_get_api_key_settings():
    # Test setting Google Gemini API key
    payload = {
        "api_key": "AIzaSyTestKeyForEvaluation12345",
        "provider": "gemini",
        "model": "gemini-1.5-flash",
    }
    resp = client.post("/api/v1/agent/settings/api-key", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["execution_mode"] == "LLM"
    assert data["llm_provider"] == "gemini"
    assert data["has_key"] is True

    # Test status endpoint returns masked key and active LLM configuration
    status_resp = client.get("/api/v1/agent/settings/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["execution_mode"] == "LLM"
    assert status_data["llm_provider"] == "gemini"
    assert status_data["has_key"] is True
    assert "AIza" in status_data["masked_key"]

    # Reset settings for isolated subsequent tests
    client.post("/api/v1/agent/settings/api-key", json={"api_key": "", "provider": "openai", "model": "gpt-4o-mini"})


