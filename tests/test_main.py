from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_reports_version(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "abc1234")
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["version"] == "abc1234"
