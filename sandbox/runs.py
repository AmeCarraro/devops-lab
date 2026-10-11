"""A run of a pipeline as Kubernetes sees it: the Job that is created, and how to read its state.

Nothing here talks to the cluster: these are plain functions from data to data.
"""
import json
import re

from pipeline import Device, Measurement, Pipeline, Run

# long enough for the slowest model on the smallest device, short enough to stop a run that hangs
DEADLINE_SECONDS = 150
# a finished run stays readable for a while, then Kubernetes removes it by itself
KEEP_SECONDS = 300
NOT_PULLED = {"ErrImagePull", "ImagePullBackOff", "ErrImageNeverPull", "InvalidImageName"}
DEVICE_NOTE = "devops-lab/device"


def job_manifest(name: str, image: str, pipeline: Pipeline, device: Device) -> dict:
    """The Job that runs one pipeline. Its limits are the device; the rest keeps the run inside."""
    # request = limit: the pod gets exactly this much, never more and never less
    resources = {"cpu": f"{round(device.cpu * 1000)}m", "memory": f"{device.memory_mb}Mi"}
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name,
            "labels": {"app": "pipeline-run"},
            # The device, as it was asked for. It cannot be read back from the limits:
            # Kubernetes rewrites them in its own way, "1000m" becomes "1" and "1024Mi" becomes "1Gi"
            "annotations": {DEVICE_NOTE: device.model_dump_json()},
        },
        "spec": {
            # one try: a pipeline that fails is a result, not something to retry
            "backoffLimit": 0,
            "activeDeadlineSeconds": DEADLINE_SECONDS,
            "ttlSecondsAfterFinished": KEEP_SECONDS,
            "template": {
                "metadata": {"labels": {"app": "pipeline-run"}},
                "spec": {
                    "restartPolicy": "Never",
                    # the run has no reason to talk to Kubernetes: it gets no credentials for it
                    "automountServiceAccountToken": False,
                    "enableServiceLinks": False,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 1000,
                        "runAsGroup": 1000,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "bench",
                            "image": image,
                            "imagePullPolicy": "IfNotPresent",
                            # a list, not a command line: nothing in the configuration is read by a shell
                            "args": [pipeline.model_dump_json()],
                            "resources": {"requests": resources, "limits": resources},
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                        }
                    ],
                },
            },
        },
    }


def _progress(log: str) -> tuple[int, int]:
    found = re.findall(r"^PROGRESS (\d+)/(\d+)", log, flags=re.MULTILINE)
    return (int(found[-1][0]), int(found[-1][1])) if found else (0, 0)


def _container(pod: dict) -> dict:
    """The state of the only container of the pod: {"waiting": ...}, {"running": ...} or {"terminated": ...}."""
    statuses = pod.get("status", {}).get("containerStatuses") or [{}]
    return statuses[0].get("state") or {}


def read_run(name: str, job: dict, pod: dict | None, log: str) -> Run:
    """What a run is doing, from the Job, its pod and the last lines the pod printed."""
    done, total = _progress(log)
    device = Device.model_validate_json(job["metadata"]["annotations"][DEVICE_NOTE])
    failed = next((c for c in job.get("status", {}).get("conditions") or [] if c["type"] == "Failed"), None)
    if failed and failed.get("reason") == "DeadlineExceeded":
        return Run(run=name, state="failed", done=done, total=total, failure="timeout",
                   message=f"The pipeline did not finish in {DEADLINE_SECONDS} seconds.")
    if pod is None:
        # the Job exists and its pod does not yet: no room in the quota of the sandbox, for example
        return Run(run=name, state="queued")

    phase = pod.get("status", {}).get("phase")
    state = _container(pod)
    if phase == "Pending":
        reason = state.get("waiting", {}).get("reason", "")
        if reason in NOT_PULLED:
            return Run(run=name, state="failed", failure="error", message=f"The bench image is not on the node ({reason}).")
        return Run(run=name, state="starting")
    if phase == "Running":
        return Run(run=name, state="running", done=done, total=total)
    if phase == "Succeeded":
        result = re.search(r"^RESULT (.+)$", log, flags=re.MULTILINE)
        if result:
            measurement = Measurement(**json.loads(result.group(1)))
            return Run(run=name, state="done", done=measurement.images, total=measurement.images, result=measurement)
        return Run(run=name, state="failed", failure="error", message="The pipeline ended without a result.")

    terminated = state.get("terminated", {})
    if terminated.get("reason") == "OOMKilled" or terminated.get("exitCode") == 137:
        return Run(run=name, state="failed", done=done, total=total, failure="out_of_memory",
                   message=f"The pipeline needed more than the {device.memory_mb} MB of the device and was stopped.")
    # a crash: the last lines it printed are the best explanation there is
    tail = "\n".join(line for line in log.splitlines()[-4:] if not line.startswith("PROGRESS"))
    return Run(run=name, state="failed", done=done, total=total, failure="error", message=tail or "The pipeline crashed.")
