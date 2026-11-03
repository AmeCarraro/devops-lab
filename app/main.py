import json
import logging
import os
import socket

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from agent import CHAT_MODEL, ask, research
from fit import fit, zoo
from metrics import HTTPMetrics

logger = logging.getLogger("uvicorn.error")

# Everything a client uses lives under /api, so that one address can serve
# the web page at / and this service next to it
app = FastAPI(title="devops-lab", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
api = APIRouter(prefix="/api")

# Counts and times every request. Added before CORS, so CORS wraps it: the preflights
# that CORS answers by itself never reach the metrics
app.add_middleware(HTTPMetrics)

# The page of the desktop app is not served from this address, so the browser engine
# inside it asks for permission before calling the API. These are the origins Tauri uses;
# a page on any other site is still refused.
DESKTOP_ORIGINS = "http://tauri.localhost,https://tauri.localhost,tauri://localhost"
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", DESKTOP_ORIGINS).split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class Question(BaseModel):
    question: str


class Device(BaseModel):
    cpu: float = Field(gt=0, le=4)
    memory_mb: int = Field(ge=64, le=2048)


class Targets(BaseModel):
    min_fps: float = Field(gt=0, le=10000)
    min_accuracy: float = Field(ge=0, le=100)


class FitTask(BaseModel):
    device: Device
    targets: Targets


def stream(events, what: str) -> StreamingResponse:
    """A run as a stream of JSON lines, one per event. Closing the connection stops the run."""
    async def lines():
        try:
            async for event in events:
                yield json.dumps(event) + "\n"
        except Exception as exc:
            # the status code is already sent: the failure travels as the last event
            logger.exception("%s failed", what)
            yield json.dumps({"type": "error", "message": f"{type(exc).__name__}: {exc}"}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache"})


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    # Read by Prometheus from inside the cluster. Outside /api, so the ingress does not route it
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@api.get("/info")
def info():
    # version = commit SHA baked in by the pipeline, pod = which replica answered
    return {"version": os.getenv("APP_VERSION", "dev"), "pod": socket.gethostname(), "model": CHAT_MODEL}


@api.post("/ask")
async def ask_docs(body: Question):
    """Answer a question about the documentation, with the sources used."""
    try:
        return await ask(body.question)
    except Exception as exc:
        # the LLM or the MCP server is unreachable or failed: a dependency problem, not a client error
        logger.exception("ask failed")
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}")


@api.post("/ask/stream")
async def ask_docs_stream(body: Question):
    """The same as /ask, as a stream of JSON lines: every step as it happens, then the answer as it is written.

    Closing the connection stops the run.
    """
    return stream(research(body.question), "ask")


@api.get("/zoo")
async def pipeline_zoo():
    """What a pipeline can be made of: models, precisions, input sizes, threads."""
    try:
        return await zoo()
    except Exception as exc:
        logger.exception("zoo failed")
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}")


@api.post("/fit/stream")
async def fit_stream(body: FitTask):
    """Search for a pipeline configuration that meets the targets on a device, as a stream of JSON lines.

    Every run in the sandbox is reported while it happens. Closing the connection stops
    the search and cancels the run in progress.
    """
    return stream(fit(body.device.model_dump(), body.targets.model_dump()), "fit")


app.include_router(api)
