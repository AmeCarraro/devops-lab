"""MCP server "sandbox": runs a vision pipeline on a simulated device and measures it.

A run is a Kubernetes Job in a namespace of its own. The pod of the Job has the CPU
and the memory of the device as limits, no network, no credentials and nothing it can
write to. This server holds no state: the name of the Job is the identifier of the
run, and everything else is asked to Kubernetes at every call.
"""
import os
import secrets
from typing import Annotated

import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from kube import Kube
from pipeline import ZOO, Device, Pipeline, Run, Started, Zoo
from runs import job_manifest, read_run

BENCH_IMAGE = os.getenv("BENCH_IMAGE", "devops-lab-bench:local")
kube = Kube(os.getenv("SANDBOX_NAMESPACE", "sandbox"))

INSTRUCTIONS = (
    "Runs an image classification pipeline on a simulated edge device and measures it on 200 pictures. "
    "start_run returns at once with the identifier of the run; a run takes from a few seconds to two minutes. "
    "Call get_run with that identifier until its state is 'done' or 'failed'. "
    "A pipeline that needs more memory than the device has fails with 'out_of_memory'. "
    "zoo lists the valid choices for a pipeline."
)

mcp = MCPServer("sandbox", instructions=INSTRUCTIONS)

RunId = Annotated[str, Field(description="Identifier returned by start_run", pattern=r"^run-[0-9a-f]{8}$")]


@mcp.tool()
async def start_run(pipeline: Pipeline, device: Device) -> Started:
    """Start a pipeline on a device with the given CPU and memory. Returns the identifier of the run."""
    name = f"run-{secrets.token_hex(4)}"
    try:
        await kube.create_job(job_manifest(name, BENCH_IMAGE, pipeline, device))
    except httpx2.HTTPStatusError as exc:
        # Kubernetes said no, and it says why: a ToolError carries that to the caller
        raise ToolError(f"Kubernetes refused the run: {exc.response.text}") from exc
    return Started(run=name, pipeline=pipeline)


@mcp.tool()
async def get_run(run: RunId) -> Run:
    """The state of a run and, when it is done, what it measured."""
    job = await kube.job(run)
    if job is None:
        raise ToolError(f"No run is called {run}: it was cancelled, or it ended more than a few minutes ago.")
    pod = await kube.pod_of(run)
    log = await kube.log(pod["metadata"]["name"]) if pod else ""
    return read_run(run, job, pod, log)


@mcp.tool()
async def cancel_run(run: RunId) -> str:
    """Stop a run and remove it. Cancelling a run that is already gone is not an error."""
    await kube.delete_job(run)
    return "cancelled"


@mcp.tool()
def zoo() -> Zoo:
    """The valid choices for a pipeline: models, precisions, input sizes and the most threads."""
    return Zoo(
        models=list(ZOO["models"]),
        precisions=ZOO["precisions"],
        input_sizes=ZOO["input_sizes"],
        max_threads=ZOO["max_threads"],
    )


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "bench_image": BENCH_IMAGE})


if __name__ == "__main__":
    # The SDK rejects requests whose Host header is not listed (DNS rebinding protection)
    allowed_hosts = os.getenv("ALLOWED_HOSTS", "sandbox-mcp:8002,127.0.0.1:*,localhost:*").split(",")
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8002")),
        # no server-side sessions and plain JSON replies: any replica can serve any request
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=allowed_hosts),
    )
