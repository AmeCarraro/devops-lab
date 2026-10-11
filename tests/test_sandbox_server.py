"""The sandbox server through MCP, with a fake Kubernetes behind it."""
import asyncio

from mcp import Client

import sandbox_server

PIPELINE = {"model": "resnet50", "precision": "fp32", "input_size": 224}
DEVICE = {"cpu": 1, "memory_mb": 256}


class FakeKube:
    """Remembers the Jobs it is given, and answers with the pod that the test prepared."""

    def __init__(self):
        self.jobs = {}
        self.pod = None
        self.text = ""

    async def create_job(self, manifest):
        self.jobs[manifest["metadata"]["name"]] = manifest

    async def job(self, name):
        return self.jobs.get(name)

    async def pod_of(self, job):
        return self.pod

    async def log(self, pod):
        return self.text

    async def delete_job(self, name):
        self.jobs.pop(name, None)


def call(monkeypatch, *steps, kube=None):
    """Calls the tools one after the other on one connection. A step is (tool, arguments) or a function of the results so far."""
    kube = kube or FakeKube()
    monkeypatch.setattr(sandbox_server, "kube", kube)

    async def run():
        results = []
        async with Client(sandbox_server.mcp) as client:
            for step in steps:
                tool, arguments = step(results) if callable(step) else step
                results.append(await client.call_tool(tool, arguments))
        return results

    return asyncio.run(run()), kube


def test_start_run_creates_a_job_with_the_limits_of_the_device(monkeypatch):
    (started,), kube = call(monkeypatch, ("start_run", {"pipeline": PIPELINE, "device": DEVICE}))

    run = started.structured_content["run"]
    limits = kube.jobs[run]["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]
    assert limits == {"cpu": "1000m", "memory": "256Mi"}
    # the configuration comes back complete: the threads were not given
    assert started.structured_content["pipeline"] == {**PIPELINE, "threads": 1}


def test_an_invalid_pipeline_starts_nothing(monkeypatch):
    (started,), kube = call(monkeypatch, ("start_run", {"pipeline": {**PIPELINE, "model": "vgg16"}, "device": DEVICE}))

    assert started.is_error
    assert "'vgg16' is not a valid model" in started.content[0].text
    assert kube.jobs == {}


def test_get_run_reads_the_state_from_kubernetes(monkeypatch):
    kube = FakeKube()
    kube.pod = {
        "metadata": {"name": "pod-1"},
        "status": {"phase": "Failed", "containerStatuses": [{"state": {"terminated": {"reason": "OOMKilled"}}}]},
    }

    (_, state), _ = call(
        monkeypatch,
        ("start_run", {"pipeline": PIPELINE, "device": DEVICE}),
        lambda results: ("get_run", {"run": results[0].structured_content["run"]}),
        kube=kube,
    )

    assert state.structured_content["failure"] == "out_of_memory"
    # the device is read back from the Job, so the message names the memory this run was given
    assert "256 MB" in state.structured_content["message"]


def test_a_run_that_does_not_exist_is_an_error(monkeypatch):
    (state,), _ = call(monkeypatch, ("get_run", {"run": "run-0123abcd"}))

    assert state.is_error
    assert "No run is called run-0123abcd" in state.content[0].text


def test_an_identifier_that_is_not_a_run_is_refused(monkeypatch):
    # the identifier becomes part of the address of a call to Kubernetes: only the shape start_run produces is accepted
    (state,), _ = call(monkeypatch, ("get_run", {"run": "../../secrets"}))

    assert state.is_error


def test_cancel_run_removes_the_job(monkeypatch):
    _, kube = call(
        monkeypatch,
        ("start_run", {"pipeline": PIPELINE, "device": DEVICE}),
        lambda results: ("cancel_run", {"run": results[0].structured_content["run"]}),
    )

    assert kube.jobs == {}


def test_zoo_lists_the_choices(monkeypatch):
    (zoo,), _ = call(monkeypatch, ("zoo", {}))

    assert "mobilenet_v2" in zoo.structured_content["models"]
    assert zoo.structured_content["precisions"] == ["fp32", "int8"]
