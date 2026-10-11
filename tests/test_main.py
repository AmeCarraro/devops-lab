import json

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_info_reports_version_and_model(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "abc1234")
    response = client.get("/api/info")
    assert response.status_code == 200
    assert response.json()["version"] == "abc1234"
    assert response.json()["model"] == main.CHAT_MODEL


def preflight(origin):
    """What a browser engine sends before a POST from a page on another address."""
    return client.options(
        "/api/ask/stream",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_the_desktop_app_may_call_the_api():
    response = preflight("http://tauri.localhost")
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"


def test_a_page_on_another_site_may_not_call_the_api():
    response = preflight("https://example.com")
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_ask_returns_the_summary(monkeypatch):
    async def fake_ask(question):
        return {"answer": f"You asked: {question}", "sources": []}

    monkeypatch.setattr(main, "ask", fake_ask)

    response = client.post("/api/ask", json={"question": "Why?"})

    assert response.json() == {"answer": "You asked: Why?", "sources": []}


def test_ask_answers_502_when_a_dependency_fails(monkeypatch):
    async def broken_ask(question):
        raise ConnectionError("ollama is down")

    monkeypatch.setattr(main, "ask", broken_ask)

    response = client.post("/api/ask", json={"question": "Why?"})

    assert response.status_code == 502
    assert response.json()["detail"] == "ConnectionError: ollama is down"


def stream(monkeypatch, research):
    monkeypatch.setattr(main, "research", research)
    response = client.post("/api/ask/stream", json={"question": "Why?"})
    assert response.headers["content-type"] == "application/x-ndjson"
    return [json.loads(line) for line in response.text.splitlines()]


def test_stream_sends_one_json_line_per_event(monkeypatch):
    async def research(question):
        yield {"type": "step", "tool": "search_docs", "arguments": {"query": question}}
        yield {"type": "answer", "text": "Because."}
        yield {"type": "done", "answer": "Because."}

    events = stream(monkeypatch, research)

    assert [event["type"] for event in events] == ["step", "answer", "done"]
    assert events[0]["arguments"] == {"query": "Why?"}


def test_stream_ends_with_an_error_event_when_a_dependency_fails(monkeypatch):
    async def research(question):
        yield {"type": "step", "tool": "search_docs", "arguments": {}}
        raise ConnectionError("ollama is down")

    events = stream(monkeypatch, research)

    assert events[-1] == {"type": "error", "message": "ConnectionError: ollama is down"}


TASK = {"device": {"cpu": 1, "memory_mb": 512}, "targets": {"min_fps": 30, "min_accuracy": 85}}


def test_fit_streams_the_events_of_the_search(monkeypatch):
    async def fake_fit(device, targets):
        yield {"type": "attempt", "n": 1, "device": device}
        yield {"type": "done", "outcome": "fits", "targets": targets}

    monkeypatch.setattr(main, "fit", fake_fit)

    response = client.post("/api/fit/stream", json=TASK)

    events = [json.loads(line) for line in response.text.splitlines()]
    assert response.headers["content-type"] == "application/x-ndjson"
    assert events[0] == {"type": "attempt", "n": 1, "device": {"cpu": 1.0, "memory_mb": 512}}
    assert events[1]["targets"] == {"min_fps": 30.0, "min_accuracy": 85.0}


def test_fit_refuses_a_device_bigger_than_the_sandbox_allows():
    task = {**TASK, "device": {"cpu": 64, "memory_mb": 512}}

    assert client.post("/api/fit/stream", json=task).status_code == 422


def test_fit_reports_a_failure_as_the_last_event(monkeypatch):
    async def broken_fit(device, targets):
        yield {"type": "attempt", "n": 1}
        raise ConnectionError("sandbox down")

    monkeypatch.setattr(main, "fit", broken_fit)

    events = [json.loads(line) for line in client.post("/api/fit/stream", json=TASK).text.splitlines()]

    assert events[-1] == {"type": "error", "message": "ConnectionError: sandbox down"}


def test_zoo_answers_502_when_the_sandbox_is_unreachable(monkeypatch):
    async def broken_zoo():
        raise ConnectionError("sandbox down")

    monkeypatch.setattr(main, "zoo", broken_zoo)

    assert client.get("/api/zoo").status_code == 502
