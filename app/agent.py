"""Agentic search: the LLM runs a research loop with the tools of the MCP server.

Two phases. In the research loop the model reads what it has found so far and
decides the next move: search again with a different query, look a section up by
name, or call `finish` to leave the loop. Then it writes the answer, in a new
conversation that holds only the excerpts it collected.
The agent knows nothing about documentation search: it discovers the tools, and
how to use them, at runtime from the MCP server.
"""
import json
import os
import re
import time
from dataclasses import dataclass, field

import httpx2
from mcp import Client

import metrics

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
CHAT_MODEL = os.getenv("CHAT_MODEL", "granite4.1:3b")
metrics.prepare(CHAT_MODEL)
MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:8001/mcp")
# 6144 is the largest context that keeps a 3B model entirely inside 4 GB of video memory
NUM_CTX = int(os.getenv("NUM_CTX", "6144"))
MAX_STEPS = 6
# one query is rarely enough for a small model: it must rephrase at least once before it may leave
MIN_SEARCHES = 2
# excerpts may fill about half of the context (one token is roughly 4 characters)
EXCERPT_BUDGET = NUM_CTX * 2
# a tool call is short: a low cap stops a model that starts writing the answer inside the loop
STEP_TOKENS = 160
ANSWER_TOKENS = 512

RESEARCH = (
    "You research the technical documentation of a software project to answer a question. "
    "You cannot see the documentation: you find what you need with the tools, "
    f"one call at a time, in at most {MAX_STEPS} steps. "
    "After every result, look in the excerpts for the sentence that answers each part of the question. "
    "If a part has no such sentence, search again in a different way: other words, a more specific term, "
    "or the name of a section you have seen. Never repeat a call. "
    "When every part is answered, call finish. "
    "Do not write the answer yourself: you will be asked for it after the loop."
)

ANSWER = (
    "You answer a question about the technical documentation of a software project, "
    "using only the excerpts you are given. Cite them with their number like [1]. Be brief. "
    "Copy commands exactly, in a code block. "
    "Do not add commands, links or examples that are not in the excerpts. "
    "If the excerpts do not answer the question, or a part of it, say so instead of guessing. "
    "Reply in {language}."
)

# a small model follows "reply in Italian" far better than "reply in the language of the question"
LANGUAGE = "Which language is this text written in? Give the English name of the language.\n\n{question}"
LANGUAGE_SCHEMA = {"type": "object", "properties": {"language": {"type": "string"}}, "required": ["language"]}

# The only tool that belongs to the agent itself: it is control flow, not a capability of a server
FINISH_TOOL = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": "Leave the search loop. Call it when the excerpts answer every part of the question.",
        "parameters": {
            "type": "object",
            "properties": {
                "missing": {
                    "type": "string",
                    "description": (
                        "What the question asks that no excerpt answers yet. "
                        "Empty if the excerpts answer every part of the question."
                    ),
                },
            },
            "required": ["missing"],
        },
    },
}

TOO_EARLY = (
    f"Not yet: search at least {MIN_SEARCHES} times, with different words, "
    "to check that nothing is missing before you finish."
)
NOT_YET = "Not yet, you have steps left. Still missing: {missing}. Search for it with different words."
REPEATED = "You already made this call. Search with different words, use another tool, or call finish."
NOTHING_NEW = (
    "Nothing new: every excerpt this call matches is already above. "
    "Search with different words, or call finish."
)
CONTEXT_FULL = "The context is full: no more excerpts can be added. Call finish."


@dataclass
class Notes:
    """What the model has read so far."""
    sources: list[str] = field(default_factory=list)  # cited as [1], [2]... in this order
    excerpts: list[str] = field(default_factory=list)  # numbered, as the model reads them
    shown: set = field(default_factory=set)  # ids of the excerpts already read
    chars: int = 0


def _payload(messages: list[dict], tools: list[dict], max_tokens: int, stream: bool) -> dict:
    return {
        "model": CHAT_MODEL,
        "messages": messages,
        "tools": tools,
        "stream": stream,
        "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": max_tokens},
    }


async def chat(messages: list[dict], tools: list[dict], max_tokens: int, schema: dict | None = None) -> dict:
    """One call to the LLM. With `schema`, the reply is JSON that is guaranteed to match it."""
    payload = _payload(messages, tools, max_tokens, stream=False)
    mode = "tools"
    if schema:
        payload["format"] = schema
        mode = "structured"
    started = time.perf_counter()
    try:
        async with httpx2.AsyncClient(timeout=180) as client:
            response = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            response.raise_for_status()
            reply = response.json()
    except Exception:
        metrics.llm_failed(CHAT_MODEL, mode)
        raise
    metrics.llm_done(CHAT_MODEL, mode, time.perf_counter() - started, reply)
    return reply["message"]


async def chat_stream(messages: list[dict], max_tokens: int):
    """Like chat, without tools: yields the reply piece by piece while the model writes it."""
    payload = _payload(messages, [], max_tokens, stream=True)
    started = time.perf_counter()
    first = True
    try:
        async with httpx2.AsyncClient(timeout=180) as client:
            # leaving this block early (the caller stopped listening) closes the connection,
            # and Ollama stops generating
            async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    reply = json.loads(line) if line else {}
                    piece = reply.get("message", {}).get("content", "")
                    if piece:
                        if first:
                            # how long the user looks at an empty answer: the reading of the prompt
                            metrics.LLM_FIRST_TOKEN.labels(CHAT_MODEL).observe(time.perf_counter() - started)
                            first = False
                        yield piece
                    if reply.get("done"):
                        # the last line carries the token counts of the whole reply
                        metrics.llm_done(CHAT_MODEL, "stream", time.perf_counter() - started, reply)
    except Exception:
        metrics.llm_failed(CHAT_MODEL, "stream")
        raise


async def _language(question: str) -> str:
    """Name of the language the question is written in, e.g. "Italian"."""
    message = await chat([{"role": "user", "content": LANGUAGE.format(question=question)}], [], 20, LANGUAGE_SCHEMA)
    try:
        return json.loads(message["content"])["language"]
    except (ValueError, KeyError, TypeError):
        return "the language of the question"


def _text(result) -> str:
    return "\n".join(block.text for block in result.content if getattr(block, "text", None))


def _call_key(name: str, arguments: dict) -> str:
    """Identity of a call: the same words in another order or case are the same search."""
    normalized = {
        key: " ".join(sorted(re.findall(r"\w+", value.lower()))) if isinstance(value, str) else value
        for key, value in arguments.items()
    }
    return name + json.dumps(normalized, sort_keys=True)


def _missing(arguments: dict) -> str:
    """What the model says is still unanswered when it calls finish; empty if nothing."""
    missing = str(arguments.get("missing") or "").strip()
    return "" if missing.lower().strip(". ") in {"nothing", "none", "no", "n/a"} else missing


def _excerpts(data: dict, notes: Notes) -> tuple[str, int]:
    """Format the hits of a search for the model, leaving out what it has already read."""
    parts = []
    added = 0
    for hit in data["hits"]:
        key = hit.get("id", hit["text"])
        if key in notes.shown:
            continue
        if notes.chars + len(hit["text"]) > EXCERPT_BUDGET:
            parts.append(CONTEXT_FULL)
            break
        notes.shown.add(key)
        notes.chars += len(hit["text"])
        if hit["source"] not in notes.sources:
            notes.sources.append(hit["source"])
        # the number the model cites is the position in the "sources" list of the reply
        number = notes.sources.index(hit["source"]) + 1
        parts.append(f"[{number}] {hit['source']} ({hit['title']})\n{hit['text']}")
        notes.excerpts.append(parts[-1])
        added += 1

    if not data["hits"]:
        parts.append(data.get("note") or "No results.")
    elif not parts:
        parts.append(NOTHING_NEW)
    if data.get("sections"):
        parts.append("Sections you can open by name: " + "; ".join(data["sections"]))
    return "\n\n".join(parts), added


async def _run_tool(mcp: Client, name: str, arguments: dict, notes: Notes) -> tuple[str, int]:
    """Call one MCP tool. Returns what the model will read and how many new excerpts it contains."""
    started = time.perf_counter()
    try:
        result = await mcp.call_tool(name, arguments)
    except Exception as exc:
        metrics.TOOL_SECONDS.labels(name[:40], "error").observe(time.perf_counter() - started)
        # unknown tool, bad arguments, server down: show it to the model so it can recover
        return f"Tool error: {exc}", 0
    outcome = "error" if result.is_error else "ok"
    metrics.TOOL_SECONDS.labels(name[:40], outcome).observe(time.perf_counter() - started)
    if result.is_error:
        return f"Tool error: {_text(result)}", 0
    data = result.structured_content or {}
    if "hits" not in data:
        return _text(result), 0
    return _excerpts(data, notes)


def research(question: str, mcp_server=MCP_URL):
    """The whole run as a stream of events, so that a client can show progress and stop it.

    In order: one "step" for every tool call, "sources", the answer in "answer"
    pieces while the model writes it, and a final "done" with the summary of everything.
    Every run is also counted in the metrics, from these same events.
    """
    return metrics.observe_run(_research(question, mcp_server))


async def _research(question: str, mcp_server):
    started = time.perf_counter()
    notes = Notes()
    steps: list[dict] = []
    made: set[str] = set()
    finished_by = "max_steps"

    async with Client(mcp_server) as mcp:
        listed = await mcp.list_tools()
        tools = [
            {
                "type": "function",
                "function": {"name": t.name, "description": t.description or "", "parameters": t.input_schema},
            }
            for t in listed.tools
        ] + [FINISH_TOOL]
        system = RESEARCH + (f"\n\nAbout the tools: {mcp.instructions}" if mcp.instructions else "")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]

        for _ in range(MAX_STEPS):
            message = await chat(messages, tools, STEP_TOKENS)
            calls = message.get("tool_calls") or []
            if not calls:
                # the model started to answer instead of calling finish: same thing, it is done searching
                finished_by = "answer"
                break
            # one tool per step: the model must read a result before it decides the next move
            message["tool_calls"] = calls[:1]
            messages.append(message)
            name = calls[0]["function"]["name"]
            arguments = calls[0]["function"].get("arguments") or {}
            step = {"tool": name, "arguments": arguments}
            steps.append(step)

            if name == "finish":
                missing = _missing(arguments)
                if len(made) >= MIN_SEARCHES and not missing:
                    finished_by = "finish"
                    yield {"type": "step", **step}
                    break
                # leaving early is only for a model that is convinced it has everything:
                # one that knows something is missing goes back to search until the steps run out
                content = NOT_YET.format(missing=missing) if missing and made else TOO_EARLY
                step["refused"] = "missing" if missing and made else "too_early"
            elif _call_key(name, arguments) in made:
                # an unsure model tends to repeat itself: make it vary instead of running the call again
                content = REPEATED
                step["refused"] = "repeated"
            else:
                made.add(_call_key(name, arguments))
                content, step["new_excerpts"] = await _run_tool(mcp, name, arguments, notes)
            messages.append({"role": "tool", "tool_name": name, "content": content})
            yield {"type": "step", **step}

    yield {"type": "sources", "sources": notes.sources}

    # The answer is written in a new conversation that holds only the excerpts and the question:
    # the back and forth of the research would distract a small model
    language = await _language(question)
    found = "\n\n".join(notes.excerpts) or "(nothing was found)"
    answer = ""
    async for piece in chat_stream(
        [
            {"role": "system", "content": ANSWER.format(language=language)},
            {"role": "user", "content": f"Excerpts:\n\n{found}\n\nQuestion: {question}"},
        ],
        ANSWER_TOKENS,
    ):
        answer += piece
        yield {"type": "answer", "text": piece}

    yield {
        "type": "done",
        "answer": answer,
        "sources": notes.sources,
        "steps": steps,
        "finished_by": finished_by,
        "model": CHAT_MODEL,
        "seconds": round(time.perf_counter() - started, 2),
    }


async def ask(question: str, mcp_server=MCP_URL) -> dict:
    """Run the research to its end and return only the summary."""
    summary = {}
    async for event in research(question, mcp_server):
        if event["type"] == "done":
            summary = {key: value for key, value in event.items() if key != "type"}
    return summary
