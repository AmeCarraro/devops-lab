"""The sandbox without a cluster: the Job it would create, and how it reads what Kubernetes answers."""
import json

import pytest
from pydantic import ValidationError

from pipeline import Device, Pipeline
from runs import DEADLINE_SECONDS, job_manifest, read_run

PIPELINE = Pipeline(model="mobilenet_v2", precision="int8", input_size=160)
DEVICE = Device(cpu=0.5, memory_mb=256)
RESULT = {
    "fps": 31.4, "accuracy": 84.0, "latency_ms": 28.1, "latency_p95_ms": 35.0,
    "memory_mb": 96, "model_mb": 3.9, "images": 200, "predictions": [0, 217],
}


def pod(phase, **state):
    return {"metadata": {"name": "run-1-abc"}, "status": {"phase": phase, "containerStatuses": [{"state": state}]}}


def read(pod=None, log="", status=None):
    job = job_manifest("run-1", "bench:1", PIPELINE, DEVICE)
    # Kubernetes hands the limits back in its own notation; nothing may depend on reading them
    job["spec"]["template"]["spec"]["containers"][0]["resources"] = {"limits": {"cpu": "2", "memory": "1Gi"}}
    return read_run("run-1", {**job, "status": status or {}}, pod, log)


def test_the_limits_of_the_pod_are_the_device():
    container = job_manifest("run-1", "bench:1", PIPELINE, DEVICE)["spec"]["template"]["spec"]["containers"][0]

    assert container["resources"]["limits"] == {"cpu": "500m", "memory": "256Mi"}
    # the same as requests: the pod is given exactly the device, not "up to" it
    assert container["resources"]["requests"] == container["resources"]["limits"]
    assert json.loads(container["args"][0]) == {
        "model": "mobilenet_v2", "precision": "int8", "input_size": 160, "threads": 1,
    }


def test_a_run_is_locked_down_and_cannot_last_forever():
    spec = job_manifest("run-1", "bench:1", PIPELINE, DEVICE)["spec"]
    pod_spec = spec["template"]["spec"]
    security = pod_spec["containers"][0]["securityContext"]

    assert spec["activeDeadlineSeconds"] == DEADLINE_SECONDS
    assert spec["backoffLimit"] == 0
    assert pod_spec["automountServiceAccountToken"] is False
    assert pod_spec["securityContext"]["runAsNonRoot"] is True
    assert security == {
        "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]},
    }


def test_a_job_without_a_pod_is_waiting_in_line():
    assert read().state == "queued"


def test_a_pod_that_is_being_created_is_starting():
    assert read(pod=pod("Pending", waiting={"reason": "ContainerCreating"})).state == "starting"


def test_a_missing_image_is_a_failure_and_not_an_endless_wait():
    run = read(pod=pod("Pending", waiting={"reason": "ImagePullBackOff"}))

    assert (run.state, run.failure) == ("failed", "error")
    assert "ImagePullBackOff" in run.message


def test_progress_is_the_last_line_the_pipeline_printed():
    run = read(pod=pod("Running", running={}), log="PROGRESS 10/200\nPROGRESS 20/200\n")

    assert (run.state, run.done, run.total) == ("running", 20, 200)


def test_a_finished_run_carries_what_it_measured():
    run = read(pod=pod("Succeeded", terminated={"exitCode": 0}), log=f"PROGRESS 200/200\nRESULT {json.dumps(RESULT)}\n")

    assert run.state == "done"
    assert (run.result.fps, run.result.accuracy, run.result.memory_mb) == (31.4, 84.0, 96)
    assert (run.done, run.total) == (200, 200)


def test_a_run_that_ends_without_a_result_failed():
    assert read(pod=pod("Succeeded", terminated={"exitCode": 0}), log="PROGRESS 200/200\n").failure == "error"


def test_a_pipeline_too_big_for_the_device_is_out_of_memory():
    run = read(pod=pod("Failed", terminated={"reason": "OOMKilled", "exitCode": 137}), log="PROGRESS 10/200\n")

    assert (run.state, run.failure, run.done) == ("failed", "out_of_memory", 10)
    assert "256 MB" in run.message


def test_a_run_past_its_deadline_timed_out():
    status = {"conditions": [{"type": "Failed", "reason": "DeadlineExceeded"}]}

    # Kubernetes removes the pod of a Job that is past its deadline: there may be none to look at
    assert read(status=status).failure == "timeout"


def test_a_crash_reports_the_last_lines_of_the_log():
    run = read(pod=pod("Failed", terminated={"reason": "Error", "exitCode": 1}), log="PROGRESS 10/200\nTraceback\nKeyError: 'x'\n")

    assert run.failure == "error"
    assert run.message == "Traceback\nKeyError: 'x'"


def test_an_unknown_model_is_refused_with_the_valid_choices():
    with pytest.raises(ValidationError) as error:
        Pipeline(model="resnet101", precision="fp32", input_size=224)

    assert "'resnet101' is not a valid model: choose one of mobilenet_v3_small, mobilenet_v2" in str(error.value)


def test_sizes_and_threads_outside_the_zoo_are_refused():
    with pytest.raises(ValidationError):
        Pipeline(model="resnet18", precision="fp32", input_size=200)
    with pytest.raises(ValidationError):
        Pipeline(model="resnet18", precision="fp32", input_size=224, threads=64)
