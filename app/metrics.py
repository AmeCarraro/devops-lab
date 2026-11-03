"""Prometheus metrics of the agent: what the Grafana dashboard shows and what the alerts watch.

Three layers, from the outside in:
- HTTP: requests, errors and latency of every route (the RED method: rate, errors, duration)
- LLM: every call to the model, how long it takes, how many tokens it reads and writes
- agent: every research run, how it ended, how many steps it took, how much it found

Prometheus reads GET /metrics every 15 seconds. Everything here is a counter or a
histogram: rates, error ratios and percentiles are computed by Prometheus, not by the app.
"""
import asyncio
import time
from contextlib import aclosing

from prometheus_client import Counter, Histogram

# Buckets in seconds. An HTTP request is timed until its response starts, which for a
# stream is the first byte; an LLM call or a whole run takes seconds to minutes on a CPU.
FAST_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
LLM_BUCKETS = (0.25, 0.5, 1, 2, 5, 10, 20, 40, 80, 160)
RUN_BUCKETS = (1, 2.5, 5, 10, 20, 40, 80, 160, 320, 640)

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests by route and status code", ["method", "route", "status"]
)
HTTP_SECONDS = Histogram(
    "http_request_duration_seconds", "Time until the response starts", ["method", "route"], buckets=FAST_BUCKETS
)

# mode: "tools" = a step of the research loop, "structured" = a reply forced into a JSON
# schema (the language of the question), "stream" = the answer, written piece by piece
LLM_REQUESTS = Counter("llm_requests_total", "Calls to the LLM by outcome", ["model", "mode", "outcome"])
LLM_SECONDS = Histogram(
    "llm_request_duration_seconds", "Duration of a call to the LLM", ["model", "mode"], buckets=LLM_BUCKETS
)
LLM_TOKENS = Counter(
    "llm_tokens_total", "Tokens the LLM read (prompt) and wrote (completion)", ["model", "mode", "kind"]
)
LLM_FIRST_TOKEN = Histogram(
    "llm_time_to_first_token_seconds", "Wait before the first piece of a streamed answer", ["model"],
    buckets=LLM_BUCKETS,
)

# finished_by: "finish" (the model was convinced), "answer" (it started answering inside the loop),
# "max_steps" (it ran out of steps), "error", "cancelled" (the client closed the connection)
RUNS = Counter("agent_runs_total", "Research runs by how they ended", ["finished_by"])
RUN_SECONDS = Histogram(
    "agent_run_duration_seconds", "A completed research run, from the question to the end of the answer",
    buckets=RUN_BUCKETS,
)
RUN_STEPS = Histogram("agent_run_steps", "Tool calls the model made in a completed run", buckets=(1, 2, 3, 4, 5, 6))
# the le="0" bucket counts the runs that found nothing: the answer has no excerpts to stand on
RUN_EXCERPTS = Histogram(
    "agent_run_excerpts", "Excerpts of documentation a completed run collected", buckets=(0, 1, 2, 4, 8, 16)
)
# result: "new_excerpts", "nothing_new", "finish", or "refused_<reason>" when the agent
# refused the call (repeated, too early, something still missing)
TOOL_CALLS = Counter("agent_tool_calls_total", "Tool calls the model asked for, by result", ["tool", "result"])
TOOL_SECONDS = Histogram(
    "agent_tool_call_duration_seconds", "Duration of a call to an MCP tool", ["tool", "outcome"],
    buckets=FAST_BUCKETS,
)

# A series with labels appears only when it is first used, already at 1. rate() and
# increase() need two samples, so that first event would be lost and a panel would stay
# empty until the second one. The label values known in advance start at zero instead.
for _finished_by in ("finish", "answer", "max_steps", "error", "cancelled"):
    RUNS.labels(_finished_by)


def prepare(model: str):
    """Create the series of the LLM metrics of `model` at zero, before its first call."""
    for mode in ("tools", "structured", "stream"):
        LLM_SECONDS.labels(model, mode)
        for outcome in ("ok", "error"):
            LLM_REQUESTS.labels(model, mode, outcome)
        for kind in ("prompt", "completion"):
            LLM_TOKENS.labels(model, mode, kind)
    LLM_FIRST_TOKEN.labels(model)


class HTTPMetrics:
    """ASGI middleware: counts every request and times it until its response starts.

    Written against ASGI directly rather than as a Starlette BaseHTTPMiddleware, which
    wraps the body of streaming responses and gets in the way of their cancellation.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500  # an exception that escapes the app becomes a 500 further out

        async def send_and_time(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                HTTP_SECONDS.labels(scope["method"], _route(scope)).observe(time.perf_counter() - started)
            await send(message)

        try:
            await self.app(scope, receive, send_and_time)
        finally:
            HTTP_REQUESTS.labels(scope["method"], _route(scope), str(status)).inc()


def _route(scope) -> str:
    """The route template ("/api/ask"), never the raw path: one label value per route.

    A path that matches no route would add a new series for every typo or scanner probe.
    """
    route = scope.get("route")
    return getattr(route, "path", None) or "unmatched"


def llm_done(model: str, mode: str, seconds: float, reply: dict):
    """Record a call that worked. `reply` is Ollama's last JSON object, which holds the token counts."""
    LLM_REQUESTS.labels(model, mode, "ok").inc()
    LLM_SECONDS.labels(model, mode).observe(seconds)
    LLM_TOKENS.labels(model, mode, "prompt").inc(reply.get("prompt_eval_count") or 0)
    LLM_TOKENS.labels(model, mode, "completion").inc(reply.get("eval_count") or 0)


def llm_failed(model: str, mode: str):
    LLM_REQUESTS.labels(model, mode, "error").inc()


def _tool_result(step: dict) -> str:
    if "refused" in step:
        return f"refused_{step['refused']}"
    if step["tool"] == "finish":
        return "finish"
    return "new_excerpts" if step.get("new_excerpts") else "nothing_new"


async def observe_run(events):
    """Pass the events of a research run through unchanged, recording what they say.

    The metrics come from the same events the web page shows, so the dashboard and the
    page cannot disagree about what a run did.
    """
    started = time.perf_counter()
    finished_by = None
    # aclosing: when the client goes away, the run underneath is closed at once,
    # and with it the connection to the LLM
    async with aclosing(events):
        try:
            async for event in events:
                if event["type"] == "step":
                    # the tool name comes from the model: cut it short so a wild one cannot flood the labels
                    TOOL_CALLS.labels(str(event["tool"])[:40], _tool_result(event)).inc()
                elif event["type"] == "done":
                    finished_by = event["finished_by"]
                    RUN_STEPS.observe(len(event["steps"]))
                    RUN_EXCERPTS.observe(sum(step.get("new_excerpts", 0) for step in event["steps"]))
                    RUN_SECONDS.observe(time.perf_counter() - started)
                yield event
        except (GeneratorExit, asyncio.CancelledError):
            # the client closed the connection before the end: the run was stopped, it did not fail
            finished_by = finished_by or "cancelled"
            raise
        finally:
            # no "done" event and no cancellation: the run broke on an exception
            RUNS.labels(finished_by or "error").inc()
