"""The fit loop without Ollama and without a cluster: a scripted LLM, a fake sandbox that "measures" from a table."""
import asyncio

import pytest
from mcp.server.mcpserver import MCPServer

import fit
from pipeline import Device, Pipeline, Run, Started
from test_agent import Hit, SearchResult, calls, says, script

DEVICE = {"cpu": 1.0, "memory_mb": 512}
TARGETS = {"min_fps": 30.0, "min_accuracy": 85.0}

# what each model "measures" in the fake sandbox: (images per second, accuracy)
TABLE = {"mobilenet_v2": (115.0, 75.5), "resnet18": (40.0, 81.0), "resnet50": (13.5, 86.0), "efficientnet_b0": (60.0, 87.5)}

# the fake documentation: one section per subject, found by a few words of the query
PAGES = [
    ("too slow", Hit(id=1, source="docs/guide.md#too-slow", title="Too slow", text="Use int8.")),
    ("too low", Hit(id=2, source="docs/guide.md#too-low", title="Too low", text="Use a larger input.")),
    ("out of memory", Hit(id=3, source="docs/guide.md#memory", title="Memory", text="resnet50 fp32 does not fit.")),
    ("half a core", Hit(id=4, source="docs/guide.md#half", title="Half a core", text="Half the speed.")),
    ("threads", Hit(id=5, source="docs/guide.md#threads", title="Threads", text="As many threads as cores.")),
    ("at least", Hit(id=6, source="docs/guide.md#85", title="At least 85% accuracy", text="85% or more: efficientnet_b0.")),
    ("most accurate", Hit(id=7, source="docs/zoo.md#accurate", title="Most accurate", text="The best is 87.5%.")),
]


def make_docs(queries: list | None = None) -> MCPServer:
    server = MCPServer("fake-docs", instructions="Fake instructions.")

    @server.tool()
    def search_docs(query: str, k: int = 4) -> SearchResult:
        """Search the documentation."""
        if queries is not None:
            queries.append(query)
        return SearchResult(hits=[hit for words, hit in PAGES if words in query][:k])

    @server.tool()
    def search_by_name(name: str) -> SearchResult:
        """Open a section by its name."""
        if queries is not None:
            queries.append(name)
        return SearchResult(hits=[hit for words, hit in PAGES if words in name])

    return server


class Sandbox:
    """A fake sandbox server that remembers what it was asked."""

    def __init__(self, too_big=(), never_ends=False):
        self.started: list[dict] = []
        self.cancelled: list[str] = []
        self.server = MCPServer("fake-sandbox")
        polls: dict[str, int] = {}

        @self.server.tool()
        def start_run(pipeline: Pipeline, device: Device) -> Started:
            """Start a pipeline."""
            self.started.append({"pipeline": pipeline.model_dump(), "device": device.model_dump()})
            return Started(run=f"run-{len(self.started):08x}", pipeline=pipeline)

        @self.server.tool()
        def get_run(run: str) -> Run:
            """State of a run: running at the first look, over at the second."""
            polls[run] = polls.get(run, 0) + 1
            if polls[run] == 1 or never_ends:
                return Run(run=run, state="running", done=100, total=200)
            pipeline = self.started[int(run[4:], 16) - 1]["pipeline"]
            if pipeline["model"] in too_big:
                return Run(run=run, state="failed", failure="out_of_memory", message="Too big.")
            fps, accuracy = TABLE[pipeline["model"]]
            # int8 is twice as fast in this fake world
            fps *= 2 if pipeline["precision"] == "int8" else 1
            return Run(run=run, state="done", done=200, total=200, result={
                "fps": fps, "accuracy": accuracy, "latency_ms": 1, "latency_p95_ms": 2,
                "memory_mb": 100, "model_mb": 10, "images": 200, "predictions": [],
            })

        @self.server.tool()
        def cancel_run(run: str) -> str:
            """Stop a run."""
            self.cancelled.append(run)
            return "cancelled"


def try_(model, precision="fp32", input_size=224, reason="because", **more):
    arguments = {"reason": reason, "model": model, "precision": precision, "input_size": input_size, **more}
    return calls(("run_pipeline", arguments))


def search(query):
    return calls(("search_docs", {"query": query}))


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(fit, "POLL_SECONDS", 0)


def run(sandbox=None, device=DEVICE, queries=None, targets=TARGETS):
    sandbox = sandbox or Sandbox()

    async def collect():
        return [event async for event in fit.fit(device, targets, make_docs(queries), sandbox.server)]

    return asyncio.run(collect()), sandbox


def by_model(events):
    """The steps the model made itself, without the lookups the agent makes for it."""
    return [event for event in events if event["type"] == "step" and "by" not in event]


def tool_result(seen_call):
    return seen_call["messages"][-1]["content"]


def test_the_search_ends_at_the_first_configuration_that_fits(monkeypatch):
    seen = script(monkeypatch, [try_("mobilenet_v2"), try_("efficientnet_b0")])

    events, sandbox = run()

    done = events[-1]
    assert (done["outcome"], done["best"]) == ("fits", 2)
    assert [attempt["pipeline"]["model"] for attempt in done["attempts"]] == ["mobilenet_v2", "efficientnet_b0"]
    assert done["attempts"][0]["verdict"] == {"fits": False, "fps": True, "accuracy": False}
    assert done["attempts"][1]["verdict"]["fits"] is True
    # the model was told which target it missed and by how much
    assert "accuracy 75.5%, target 85%: TOO LOW" in tool_result(seen[1])
    assert "It must be 9.5 points more accurate" in tool_result(seen[1])
    # the LLM is not called again once a configuration fits: nothing it could say would change the result
    assert len(seen) == 2
    assert [event["type"] for event in events][-2:] == ["result", "done"]


def test_the_result_is_put_in_words_from_the_measurements(monkeypatch):
    script(monkeypatch, [try_("mobilenet_v2"), try_("resnet50"), try_("efficientnet_b0")])

    events, _ = run()

    assert events[-2] == {"type": "result", "outcome": "fits", "best": 3, "note": events[-1]["note"]}
    assert events[-1]["note"] == (
        "Use efficientnet_b0 in fp32 at 224 pixels with 1 thread. "
        "It measured 60.0 images per second against a target of 30, and 87.5% accuracy against a target of 85%. "
        "It holds 100 of the 512 MB of the device. "
        "Of the other attempts, 1 was not accurate enough, 1 was too slow."
    )


def test_every_change_of_state_of_a_run_is_reported(monkeypatch):
    script(monkeypatch, [try_("efficientnet_b0", reason="accurate and light")])

    events, _ = run()

    attempts = [event for event in events if event["type"] == "attempt"]
    assert [(event["state"], event["done"]) for event in attempts] == [("running", 100), ("done", 200)]
    assert attempts[0]["verdict"] is None and attempts[1]["verdict"]["fits"] is True
    assert attempts[0]["reason"] == "accurate and light"
    assert attempts[0]["pipeline"] == {"model": "efficientnet_b0", "precision": "fp32", "input_size": 224, "threads": 1}
    assert events[-1]["note"].endswith("It was the first configuration tried.")


def test_the_model_chooses_the_pipeline_and_never_the_device(monkeypatch):
    seen = script(monkeypatch, [try_("efficientnet_b0", cpu=4, memory_mb=2048)])

    _, sandbox = run()

    offered = {tool["function"]["name"]: tool["function"]["parameters"] for tool in seen[0]["tools"]}
    assert set(offered) == {"search_docs", "search_by_name", "run_pipeline"}
    assert list(offered["run_pipeline"]["properties"]) == ["reason", "model", "precision", "input_size", "threads"]
    # the choices are the ones the sandbox publishes
    assert "mobilenet_v2" in offered["run_pipeline"]["properties"]["model"]["enum"]
    # whatever the model writes, a run gets the device of the task
    assert sandbox.started[0]["device"] == DEVICE
    assert "1 CPU and 512 MB" in seen[0]["messages"][0]["content"]


def test_the_agent_reads_the_documentation_for_the_task_before_the_model_chooses(monkeypatch):
    seen = script(monkeypatch, [try_("efficientnet_b0")])
    queries = []

    events, _ = run(queries=queries)

    # the list of configurations for the accuracy of the target, asked for by the name of its section
    assert queries == ["configurations with at least 85% accuracy"]
    assert events[0] == {
        "type": "step", "tool": "search_by_name", "arguments": {"name": queries[0]}, "new_excerpts": 1, "by": "agent",
    }
    task = seen[0]["messages"][1]["content"]
    assert task.startswith(fit.TASK) and "85% or more: efficientnet_b0." in task


def test_a_target_between_two_levels_gets_the_list_of_the_next_one_up(monkeypatch):
    script(monkeypatch, [try_("efficientnet_b0")])
    queries = []

    run(queries=queries, targets={"min_fps": 30.0, "min_accuracy": 81.0})

    # there is no list for 81%: what the search by name answers instead is dropped, and 85% is asked for
    assert queries == ["configurations with at least 81% accuracy", "configurations with at least 85% accuracy"]


def test_without_a_list_for_the_target_the_agent_asks_which_models_are_the_most_accurate(monkeypatch):
    seen = script(monkeypatch, [try_("efficientnet_b0")])
    queries = []

    events, _ = run(queries=queries, targets={"min_fps": 30.0, "min_accuracy": 87.0})

    # the search by name answers with the nearest section, the one for 85%: not what was asked for, so it is dropped
    assert queries == [
        "configurations with at least 87% accuracy",
        "configurations with at least 90% accuracy",
        "which model is the most accurate",
    ]
    assert "85% or more" not in seen[0]["messages"][1]["content"]
    assert [event["new_excerpts"] for event in events if event.get("by") == "agent"] == [0, 0, 1]
    assert "The best is 87.5%." in seen[0]["messages"][1]["content"]


def test_what_the_agent_reads_first_depends_on_the_device(monkeypatch):
    script(monkeypatch, [try_("efficientnet_b0")])
    small, large = [], []

    run(device={"cpu": 0.5, "memory_mb": 128}, queries=small)
    script(monkeypatch, [try_("efficientnet_b0")])
    run(device={"cpu": 2.0, "memory_mb": 1024}, queries=large)

    assert small[1:] == ["speed on half a core compared to one core", fit.ADVICE["out_of_memory"]]
    assert large[1:] == ["how many threads on a device with 2 cores"]


def test_after_a_miss_the_agent_looks_up_what_went_wrong(monkeypatch):
    seen = script(monkeypatch, [try_("resnet50"), try_("resnet18"), try_("efficientnet_b0")])
    queries = []

    events, _ = run(queries=queries)

    # resnet50 was too slow: the page on that travels with its result
    assert queries[1] == fit.ADVICE["slow"]
    assert tool_result(seen[1]).endswith("From the documentation:\n\n[2] docs/guide.md#too-slow (Too slow)\nUse int8.")
    # resnet18 was not accurate enough: another page
    assert queries[2] == fit.ADVICE["inaccurate"]
    assert "Use a larger input." in tool_result(seen[2])
    lookups = [event for event in events if event.get("by") == "agent"]
    assert [event["new_excerpts"] for event in lookups] == [1, 1, 1]


def test_a_page_the_model_has_already_read_is_not_given_again(monkeypatch):
    seen = script(monkeypatch, [try_("resnet50"), try_("resnet50", input_size=192), try_("efficientnet_b0")])

    events, _ = run()

    assert "Use int8." in tool_result(seen[1])
    assert "From the documentation" not in tool_result(seen[2])
    assert [event["new_excerpts"] for event in events if event.get("by") == "agent"] == [1, 1, 0]


def test_text_does_not_end_the_search(monkeypatch):
    seen = script(monkeypatch, [says("I am sure resnet50 fits."), try_("efficientnet_b0")])

    events, _ = run()

    assert by_model(events) == [{"type": "step", "tool": "", "arguments": {}, "refused": "no_call"}]
    assert tool_result(seen[1]) == fit.NO_CALL
    assert events[-1]["outcome"] == "fits"


def test_a_configuration_already_run_is_not_run_again(monkeypatch):
    seen = script(monkeypatch, [try_("mobilenet_v2"), try_("mobilenet_v2", threads=1), try_("efficientnet_b0")])

    events, sandbox = run()

    assert len(sandbox.started) == 2
    # the refusal lists what was run, so that the model has something to choose against
    assert tool_result(seen[2]) == (
        "You already ran this configuration. Already run: mobilenet_v2, fp32, 224 px, 1 thread. "
        "Choose a configuration that is not in this list."
    )
    assert [event.get("refused") for event in by_model(events)] == ["repeated"]


def test_a_model_that_goes_round_in_circles_is_stopped(monkeypatch):
    again = try_("mobilenet_v2")
    seen = script(monkeypatch, [again, again, again, again, try_("efficientnet_b0")])

    events, sandbox = run()

    # three refusals in a row end the search: the fifth reply, which would have fitted, is never asked for
    assert len(seen) == 4 and len(sandbox.started) == 1
    assert events[-1]["outcome"] == "closest"
    assert events[-1]["note"].endswith(fit.STUCK)


def test_the_same_configuration_written_in_another_way_is_cancelled(monkeypatch):
    script(monkeypatch, [try_("mobilenet_v2"), try_("mobilenet_v2", input_size="224"), try_("efficientnet_b0")])

    events, sandbox = run()

    # it was started, because only the sandbox knows that "224" is 224, and stopped at once
    assert sandbox.cancelled == ["run-00000002"]
    assert len(events[-1]["attempts"]) == 2


def test_an_invalid_configuration_comes_back_with_the_valid_choices(monkeypatch):
    seen = script(monkeypatch, [try_("resnet101"), try_("efficientnet_b0")])

    events, sandbox = run()

    refused = by_model(events)[0]
    assert refused["refused"] == "invalid"
    assert "'resnet101' is not a valid model: choose one of mobilenet_v3_small" in refused["message"]
    assert tool_result(seen[1]).startswith("Invalid configuration. model: 'resnet101' is not a valid model")
    # it was not a run: it does not count against the limit
    assert [attempt["n"] for attempt in events[-1]["attempts"]] == [1]


def test_a_pipeline_that_does_not_fit_in_memory_is_a_failed_attempt(monkeypatch):
    seen = script(monkeypatch, [try_("resnet50"), try_("efficientnet_b0")])

    events, _ = run(Sandbox(too_big={"resnet50"}))

    failed = events[-1]["attempts"][0]
    assert (failed["state"], failed["failure"], failed["verdict"]) == ("failed", "out_of_memory", None)
    assert "FAILED, out of memory. The device has only 512 MB." in tool_result(seen[1])
    assert "resnet50 fp32 does not fit." in tool_result(seen[1])
    assert events[-1]["note"].endswith("Of the other attempts, 1 ran out of memory.")


def test_when_the_runs_are_used_up_the_closest_attempt_is_kept(monkeypatch):
    monkeypatch.setattr(fit, "MAX_RUNS", 3)
    script(monkeypatch, [try_("mobilenet_v2"), try_("resnet50"), try_("resnet18")])

    events, sandbox = run()

    assert len(sandbox.started) == 3
    # resnet18 misses the accuracy by 4 points of 85; the others miss by more
    assert (events[-1]["outcome"], events[-1]["best"]) == ("closest", 3)
    assert events[-1]["note"] == (
        "No configuration met both targets in 3 attempts. The closest was resnet18 in fp32 at 224 pixels with 1 thread: "
        "40.0 images per second against a target of 30, and 81.0% accuracy against a target of 85%. "
        "It is fast enough but not accurate enough. Of the other attempts, 1 was not accurate enough, 1 was too slow."
    )


def test_the_model_can_read_more_documentation_by_itself(monkeypatch):
    seen = script(monkeypatch, [search("threads"), search("threads"), try_("efficientnet_b0")])

    events, _ = run()

    assert by_model(events) == [
        {"type": "step", "tool": "search_docs", "arguments": {"query": "threads"}, "new_excerpts": 1},
        {"type": "step", "tool": "search_docs", "arguments": {"query": "threads"}, "refused": "repeated"},
    ]
    assert "As many threads as cores." in tool_result(seen[1])
    assert events[-1]["steps"] == 3


def test_a_run_is_cancelled_when_the_client_stops_listening(monkeypatch):
    script(monkeypatch, [try_("efficientnet_b0")])
    sandbox = Sandbox(never_ends=True)

    async def stop_early():
        reported = asyncio.Event()

        async def listen():
            async for event in fit.fit(DEVICE, TARGETS, make_docs(), sandbox.server):
                if event["type"] == "attempt":
                    reported.set()

        # what the web server does when the connection closes: it cancels the task that is producing the events
        listener = asyncio.create_task(listen())
        await reported.wait()
        listener.cancel()
        with pytest.raises(asyncio.CancelledError):
            await listener

    asyncio.run(stop_early())

    assert sandbox.cancelled == ["run-00000001"]


def test_nothing_measured_is_its_own_outcome():
    failed = {"n": 1, "result": None, "verdict": None, "failure": "out_of_memory"}

    assert fit._pick([failed], TARGETS) == ("none", None)
    assert fit._note([failed], "none", None, DEVICE, TARGETS) == "Nothing could be measured: 1 ran out of memory."
    assert fit._note([], "none", None, DEVICE, TARGETS) == "The model did not start any run."


def test_validation_noise_is_reduced_to_the_reasons():
    text = (
        "Error executing tool start_run: 2 validation errors for start_runArguments\n"
        "pipeline.model\n  Value error, 'x' is not a valid model: choose one of a, b [type=value_error, input_value='x']\n"
        "    For further information visit https://errors.pydantic.dev/2.11/v/value_error\n"
        "pipeline.threads\n  Input should be less than or equal to 4 [type=less_than_equal, input_value=9]\n"
    )

    assert fit._problems(text) == (
        "model: 'x' is not a valid model: choose one of a, b; threads: Input should be less than or equal to 4"
    )
    assert fit._problems("The sandbox is down") == "The sandbox is down"
