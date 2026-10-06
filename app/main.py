import logging
import os
import socket

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent import ask

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="devops-lab")


class Question(BaseModel):
    question: str


@app.get("/")
def root():
    # version = commit SHA baked in by the pipeline, pod = which replica answered
    return {
        "message": "Ciao da Kubernetes!",
        "version": os.getenv("APP_VERSION", "dev"),
        "pod": socket.gethostname(),
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/ask")
async def ask_docs(body: Question):
    """Answer a question about the documentation, with the sources used."""
    try:
        return await ask(body.question)
    except Exception as exc:
        # the LLM or the MCP server is unreachable or failed: a dependency problem, not a client error
        logger.exception("ask failed")
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}")
