from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_quote():
    response = client.get("/quote", params={"amount": 1000, "coupon": "WELCOME10"})
    assert response.status_code == 200
    assert response.json()["final_price"] == 900


def test_quote_rejects_negative_amount():
    assert client.get("/quote", params={"amount": -5}).status_code == 400


def test_health_fails_when_a_broken_release_is_simulated(monkeypatch):
    monkeypatch.setenv("FAIL_HEALTH", "true")
    assert client.get("/health").status_code == 503


def test_metrics_count_requests_by_status():
    client.get("/quote", params={"amount": 100})
    client.get("/quote", params={"amount": -1})
    body = client.get("/metrics").text
    assert 'http_requests_total{path="/quote",status="200"}' in body
    assert 'http_requests_total{path="/quote",status="400"}' in body
