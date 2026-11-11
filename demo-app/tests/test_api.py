from fastapi.testclient import TestClient

from app.main import app

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
