import json
import logging
import os
import socket

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent import CHAT_MODEL, ask, research

logger = logging.getLogger("uvicorn.error")

# Everything a client uses lives under /api, so that one address can serve
# the web page at / and this service next to it
app = FastAPI(title="devops-lab", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
api = APIRouter(prefix="/api")

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


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}


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
    async def lines():
        try:
            async for event in research(body.question):
                yield json.dumps(event) + "\n"
        except Exception as exc:
            # the status code is already sent: the failure travels as the last event
            logger.exception("ask failed")
            yield json.dumps({"type": "error", "message": f"{type(exc).__name__}: {exc}"}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache"})


app.include_router(api)
