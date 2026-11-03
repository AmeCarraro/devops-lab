"""The metrics Prometheus reads: HTTP by route, LLM calls, research runs."""
import asyncio

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

import main
import metrics

client = TestClient(main.app)


def value(name, **labels):
    """Current value of one series; a series nobody has touched yet is 0."""
    return REGISTRY.get_sample_value(name, labels) or 0


def test_metrics_are_served_as_prometheus_text():
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in response.text


def test_requests_are_counted_by_route_and_status():
    before = value("http_requests_total", method="GET", route="/healthz", status="200")

    client.get("/healthz")

    assert value("http_requests_total", method="GET", route="/healthz", status="200") == before + 1
    assert value("http_request_duration_seconds_count", method="GET", route="/healthz") > 0


def test_unknown_paths_share_one_label():
    # every probe of a scanner would otherwise become a new series
    before = value("http_requests_total", method="GET", route="unmatched", status="404")

    client.get("/wp-login.php")
    client.get("/.env")

    assert value("http_requests_total", method="GET", route="unmatched", status="404") == before + 2


def test_a_failing_dependency_is_counted_as_a_502(monkeypatch):
    async def broken_ask(question):
        raise ConnectionError("ollama is down")

    monkeypatch.setattr(main, "ask", broken_ask)
    before = value("http_requests_total", method="POST", route="/api/ask", status="502")

    client.post("/api/ask", json={"question": "Why?"})

    assert value("http_requests_total", method="POST", route="/api/ask", status="502") == before + 1


def test_known_series_exist_before_the_first_event():
    # otherwise rate() would lose the first event of each of them
    assert REGISTRY.get_sample_value("agent_runs_total", {"finished_by": "max_steps"}) is not None
    metrics.prepare("some-model")
    assert REGISTRY.get_sample_value(
        "llm_requests_total", {"model": "some-model", "mode": "stream", "outcome": "error"}
    ) == 0


def test_an_llm_call_counts_its_tokens():
    before = value("llm_tokens_total", model="m", mode="tools", kind="prompt")

    metrics.llm_done("m", "tools", 1.5, {"prompt_eval_count": 1200, "eval_count": 40})

    assert value("llm_tokens_total", model="m", mode="tools", kind="prompt") == before + 1200
    assert value("llm_tokens_total", model="m", mode="tools", kind="completion") >= 40
    assert value("llm_requests_total", model="m", mode="tools", outcome="ok") >= 1


async def fake_run(steps, finished_by="finish", fail=False):
    for step in steps:
        yield {"type": "step", **step}
    if fail:
        raise ConnectionError("ollama is down")
    yield {"type": "sources", "sources": []}
    yield {"type": "done", "answer": "...", "steps": steps, "finished_by": finished_by, "seconds": 1.0}


def consume(events, stop_after=None):
    async def go():
        seen = 0
        async for _ in events:
            seen += 1
            if seen == stop_after:
                # what a closed connection does to the stream
                await events.aclose()
                return

    asyncio.run(go())


def test_a_completed_run_records_how_it_ended_and_what_it_found():
    steps = [
        {"tool": "search_docs", "arguments": {"query": "a"}, "new_excerpts": 2},
        {"tool": "search_docs", "arguments": {"query": "b"}, "new_excerpts": 0},
        {"tool": "search_docs", "arguments": {"query": "b"}, "refused": "repeated"},
        {"tool": "finish", "arguments": {"missing": ""}},
    ]
    runs = value("agent_runs_total", finished_by="finish")
    excerpts = value("agent_run_excerpts_sum")
    found = value("agent_tool_calls_total", tool="search_docs", result="new_excerpts")
    empty = value("agent_tool_calls_total", tool="search_docs", result="nothing_new")
    refused = value("agent_tool_calls_total", tool="search_docs", result="refused_repeated")

    consume(metrics.observe_run(fake_run(steps)))

    assert value("agent_runs_total", finished_by="finish") == runs + 1
    assert value("agent_run_excerpts_sum") == excerpts + 2
    assert value("agent_tool_calls_total", tool="search_docs", result="new_excerpts") == found + 1
    assert value("agent_tool_calls_total", tool="search_docs", result="nothing_new") == empty + 1
    assert value("agent_tool_calls_total", tool="search_docs", result="refused_repeated") == refused + 1


def test_a_run_that_found_nothing_lands_in_the_zero_bucket():
    zero = value("agent_run_excerpts_bucket", le="0.0")

    consume(metrics.observe_run(fake_run([{"tool": "search_docs", "arguments": {}, "new_excerpts": 0}])))

    assert value("agent_run_excerpts_bucket", le="0.0") == zero + 1


def test_a_run_stopped_by_the_client_is_cancelled_not_failed():
    cancelled = value("agent_runs_total", finished_by="cancelled")
    failed = value("agent_runs_total", finished_by="error")

    consume(metrics.observe_run(fake_run([{"tool": "search_docs", "arguments": {}, "new_excerpts": 1}])), stop_after=1)

    assert value("agent_runs_total", finished_by="cancelled") == cancelled + 1
    assert value("agent_runs_total", finished_by="error") == failed


def test_a_run_that_breaks_is_an_error():
    failed = value("agent_runs_total", finished_by="error")

    try:
        consume(metrics.observe_run(fake_run([], fail=True)))
    except ConnectionError:
        pass

    assert value("agent_runs_total", finished_by="error") == failed + 1
