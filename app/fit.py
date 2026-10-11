"""Fits a vision pipeline to a device: the LLM chooses configurations, the sandbox measures them.

It is the loop of the documentation search with one more tool, run_pipeline, which
runs a configuration on the device and comes back with its numbers. The device is a
pod whose limits are the CPU and the memory of the device (see sandbox/).

Two things are not left to the model, because a small one gets them wrong.
It never declares success: a configuration fits when its measurements say so, and
the result is put in words by this code, from the numbers. And it is not trusted to
find the right page by itself: the agent looks up the documentation for the task
before the first run, and for the target that was missed after every run.
"""
import asyncio
import json
import math
import os
import re
import time

import anyio
from mcp import Client

import agent
from agent import CHAT_MODEL, MCP_URL, STEP_TOKENS, Notes, _call_key, _excerpts, _run_tool, _text

SANDBOX_URL = os.getenv("SANDBOX_URL", "http://127.0.0.1:8002/mcp")
MAX_RUNS = 8
# reading the documentation costs steps too, so that a model cannot read forever instead of trying
MAX_STEPS = 16
POLL_SECONDS = 0.7
# longer than any run can last: after this the sandbox itself is considered stuck
PATIENCE_SECONDS = 200

FIT = (
    "You are an engineer who fits an image classification pipeline onto a small device. "
    "The device has {cpu:g} CPU and {memory_mb} MB of memory. "
    "The pipeline must classify at least {min_fps:g} images per second with at least {min_accuracy:g}% accuracy. "
    "You choose a configuration and test it with run_pipeline, which runs it on the device and measures it. "
    "Choose from what the documentation says: the parts that matter for this task are given to you, "
    "and you can read more with search_docs. "
    "After every run you are told which target was missed: change the configuration to fix exactly that. "
    f"You have {MAX_RUNS} runs. Call one tool at a time, and never run the same configuration twice."
)
TASK = "Find a configuration that meets both targets on this device."
FROM_DOCS = "From the documentation:"

RUN_DESCRIPTION = (
    "Run one configuration of the pipeline on the device and measure it on 200 pictures: "
    "speed in images per second, accuracy, memory."
)
REASON = "One short sentence: why you expect this configuration to meet the targets."

NO_CALL = "Do not write text. Call run_pipeline with the next configuration to test."
REPEATED_RUN = "You already ran this configuration. Already run: {run}. Choose a configuration that is not in this list."
REPEATED_SEARCH = "You already made this search. Choose a configuration and test it with run_pipeline."
# a model that is turned down this many times in a row is going round in circles: more steps would not help
MAX_REFUSALS = 3
STUCK = "The search stopped early: the model kept asking for things it had already done."

# What the agent asks the documentation when a run misses, by what went wrong
ADVICE = {
    "slow": "the pipeline is too slow: what to change",
    "inaccurate": "the accuracy is too low: what to change",
    "out_of_memory": "which models go out of memory on a device with little memory",
}


def _function(tool) -> dict:
    """An MCP tool as the LLM wants it."""
    return {
        "type": "function",
        "function": {"name": tool.name, "description": tool.description or "", "parameters": tool.input_schema},
    }


def _run_function(start_run) -> dict:
    """run_pipeline as the model sees it: the choices of a pipeline, as the sandbox publishes them, and a reason.

    The device is not among the arguments: it is part of the task, not something the model may change.
    """
    schema = start_run.input_schema
    pipeline = schema["properties"]["pipeline"]
    if "$ref" in pipeline:
        pipeline = schema["$defs"][pipeline["$ref"].rsplit("/", 1)[-1]]
    return {
        "type": "function",
        "function": {
            "name": "run_pipeline",
            "description": RUN_DESCRIPTION,
            "parameters": {
                "type": "object",
                # the reason comes first: writing it down before the choice makes a small model think
                "properties": {"reason": {"type": "string", "description": REASON}, **pipeline["properties"]},
                "required": ["reason", *pipeline.get("required", [])],
            },
        },
    }


def _problems(text: str) -> str:
    """The reasons inside a validation error of the sandbox, without the noise around them."""
    found = re.findall(r"^(?:\w+\.)?(\w+)\n\s+(?:Value error, )?(.+?) \[type=", text, flags=re.MULTILINE)
    return "; ".join(f"{field}: {reason}" for field, reason in found) or text


def _name(pipeline: dict) -> str:
    threads = pipeline.get("threads", 1)
    return (
        f"{pipeline.get('model')}, {pipeline.get('precision')}, {pipeline.get('input_size')} px, "
        f"{threads} thread{'' if threads == 1 else 's'}"
    )


def _by_meaning(query: str) -> tuple[str, dict, str]:
    """A lookup by meaning that keeps the best section, whatever its title."""
    return "search_docs", {"query": query, "k": 1}, ""


def _first_reads(device: dict, targets: dict) -> list[list[tuple[str, dict, str]]]:
    """What the agent reads before the first run: what this task, on this device, depends on.

    Each entry is a list of lookups to try in order, until one finds something. A lookup is
    a tool, its arguments, and what the title of a section must contain to be kept.
    """
    # The fitting guide has lists of the fastest configurations by accuracy, each under a heading with
    # the number in it: for some exact percentages, and for every 5 points. A number is found by name,
    # not by meaning; and a search by name answers with the nearest names when the exact one does not
    # exist, so the number is checked. The target itself is tried first, then the next multiple of 5.
    exact = math.ceil(targets["min_accuracy"])
    levels = dict.fromkeys(f"{level}%" for level in (exact, math.ceil(exact / 5) * 5))
    reads = [[
        *(("search_by_name", {"name": f"configurations with at least {level} accuracy"}, level) for level in levels),
        _by_meaning("which model is the most accurate"),
    ]]
    if device["cpu"] < 1:
        reads.append([_by_meaning("speed on half a core compared to one core")])
    if device["cpu"] >= 2:
        reads.append([_by_meaning("how many threads on a device with 2 cores")])
    if device["memory_mb"] < 256:
        reads.append([_by_meaning(ADVICE["out_of_memory"])])
    return reads


def _verdict(result: dict, targets: dict) -> dict:
    """Which targets a measurement meets. Memory is not here: a run that did not fit never gets to measure."""
    fps = result["fps"] >= targets["min_fps"]
    accuracy = result["accuracy"] >= targets["min_accuracy"]
    return {"fits": fps and accuracy, "fps": fps, "accuracy": accuracy}


def _missed(attempt: dict) -> str:
    """What went wrong in an attempt, as a key of ADVICE; empty when nothing did."""
    if attempt["failure"] == "out_of_memory":
        return "out_of_memory"
    if attempt["failure"] == "timeout":
        return "slow"
    if attempt["failure"] or not attempt["verdict"] or attempt["verdict"]["fits"]:
        return ""
    # accuracy first: it is the target that is harder to get back
    return "slow" if attempt["verdict"]["accuracy"] else "inaccurate"


def _report(attempt: dict, targets: dict, device: dict) -> str:
    """The result of a run as the model reads it: the numbers against the targets, and how far off they are."""
    head = f"Run {attempt['n']} ({_name(attempt['pipeline'])})"
    if attempt["failure"] == "out_of_memory":
        return f"{head}: FAILED, out of memory. The device has only {device['memory_mb']} MB."
    if attempt["failure"] == "timeout":
        return f"{head}: FAILED, it was far too slow to finish."
    if attempt["failure"]:
        return f"{head}: FAILED. {attempt['message']}"

    result, verdict = attempt["result"], attempt["verdict"]
    lines = [
        f"{head}:",
        f"- speed {result['fps']} images/s, target {targets['min_fps']:g}: {'OK' if verdict['fps'] else 'TOO SLOW'}",
        f"- accuracy {result['accuracy']}%, target {targets['min_accuracy']:g}%: {'OK' if verdict['accuracy'] else 'TOO LOW'}",
        f"- memory {result['memory_mb']} of {device['memory_mb']} MB",
    ]
    slower = targets["min_fps"] / result["fps"]
    points = targets["min_accuracy"] - result["accuracy"]
    if verdict["fits"]:
        lines.append("Both targets are met.")
    elif not verdict["fps"] and not verdict["accuracy"]:
        lines.append(f"Both targets are missed: it must be {slower:.1f} times faster and {points:.1f} points more accurate.")
    elif not verdict["fps"]:
        lines.append(
            f"The accuracy is fine. It must be {slower:.2f} times faster: "
            "choose a faster configuration from the documentation that is still accurate enough."
        )
    else:
        lines.append(
            f"The speed is fine, {1 / slower:.1f} times the target. It must be {points:.1f} points more accurate: "
            "choose a more accurate configuration from the documentation that is still fast enough."
        )
    return "\n".join(lines)


def _pick(attempts: list[dict], targets: dict) -> tuple[str, int | None]:
    """How the search ended and which attempt to keep."""
    fitting = [attempt for attempt in attempts if attempt["verdict"] and attempt["verdict"]["fits"]]
    if fitting:
        return "fits", fitting[-1]["n"]
    measured = [attempt for attempt in attempts if attempt["result"]]
    if not measured:
        return "none", None

    def shortfall(attempt: dict) -> float:
        # how far the worse of the two numbers is from its target, as a fraction of the target
        result = attempt["result"]
        return max(1 - result["fps"] / targets["min_fps"], 1 - result["accuracy"] / targets["min_accuracy"])

    return "closest", min(measured, key=shortfall)["n"]


def _others(attempts: list[dict]) -> str:
    """How the attempts in the list went, counted: "2 were not accurate enough, 1 ran out of memory"."""
    kinds = {"inaccurate": "not accurate enough", "slow": "too slow", "both": "too slow and not accurate enough"}
    counts: dict[str, int] = {}
    for attempt in attempts:
        if attempt["failure"]:
            kind = "ran out of memory" if attempt["failure"] == "out_of_memory" else "failed"
        elif not attempt["verdict"]["fps"] and not attempt["verdict"]["accuracy"]:
            kind = kinds["both"]
        else:
            kind = kinds.get(_missed(attempt), "within the targets")
        counts[kind] = counts.get(kind, 0) + 1
    # "ran out of memory" and "failed" are verbs already; the others need "was" or "were"
    return ", ".join(
        f"{count} {kind}" if kind in ("ran out of memory", "failed") else f"{count} {'was' if count == 1 else 'were'} {kind}"
        for kind, count in counts.items()
    )


def _note(attempts: list[dict], outcome: str, best: int | None, device: dict, targets: dict, stuck=False) -> str:
    """The result in words. Written here from the measurements: a model would get a number wrong sooner or later."""
    note = _result_in_words(attempts, outcome, best, device, targets)
    return f"{note} {STUCK}" if stuck else note


def _result_in_words(attempts: list[dict], outcome: str, best: int | None, device: dict, targets: dict) -> str:
    if outcome == "none":
        return f"Nothing could be measured: {_others(attempts)}." if attempts else "The model did not start any run."

    kept = next(attempt for attempt in attempts if attempt["n"] == best)
    pipeline, result = kept["pipeline"], kept["result"]
    threads = f"{pipeline['threads']} thread{'' if pipeline['threads'] == 1 else 's'}"
    config = f"{pipeline['model']} in {pipeline['precision']} at {pipeline['input_size']} pixels with {threads}"
    numbers = (
        f"{result['fps']} images per second against a target of {targets['min_fps']:g}, "
        f"and {result['accuracy']}% accuracy against a target of {targets['min_accuracy']:g}%"
    )
    rest = [attempt for attempt in attempts if attempt["n"] != best]
    if outcome == "fits":
        memory = f"It holds {result['memory_mb']} of the {device['memory_mb']} MB of the device."
        tail = f"Of the other attempts, {_others(rest)}." if rest else "It was the first configuration tried."
        return f"Use {config}. It measured {numbers}. {memory} {tail}"
    gap = {"slow": "accurate enough but too slow", "inaccurate": "fast enough but not accurate enough"}.get(
        _missed(kept), "short of both targets"
    )
    tail = f" Of the other attempts, {_others(rest)}." if rest else ""
    return (
        f"No configuration met both targets in {len(attempts)} attempts. The closest was {config}: "
        f"{numbers}. It is {gap}.{tail}"
    )


async def _read(docs: Client, tool: str, arguments: dict, wanted: str, notes: Notes) -> tuple[str, int]:
    """A lookup of the agent: the sections found whose title contains `wanted`, as the model reads them."""
    try:
        result = await docs.call_tool(tool, arguments)
    except Exception:
        return "", 0
    hits = [hit for hit in (result.structured_content or {}).get("hits", []) if wanted in hit["title"]]
    return _excerpts({"hits": hits}, notes) if hits else ("", 0)


async def _watch(sandbox: Client, run: str):
    """Follows a run in the sandbox: yields its state every time it changes, until it is over."""
    last = None
    give_up = time.monotonic() + PATIENCE_SECONDS
    while True:
        result = await sandbox.call_tool("get_run", {"run": run})
        if result.is_error:
            state = {"state": "failed", "failure": "error", "message": _text(result)}
        else:
            state = {key: value for key, value in result.structured_content.items() if key != "run"}
        if state != last:
            last = state
            yield state
        if state["state"] in ("done", "failed"):
            return
        if time.monotonic() > give_up:
            await sandbox.call_tool("cancel_run", {"run": run})
            yield {**state, "state": "failed", "failure": "timeout", "message": "The sandbox did not answer in time."}
            return
        await asyncio.sleep(POLL_SECONDS)


async def _cancel(sandbox_server, run: str) -> None:
    """Stops a run that nobody is waiting for any more.

    It is called while this request is being cancelled, when its own connection to the
    sandbox is already going away: so it opens a new one, shielded from the cancellation.
    If it fails, the run still ends by itself at the deadline of its Job.
    """
    with anyio.CancelScope(shield=True), anyio.move_on_after(5):
        try:
            async with Client(sandbox_server) as sandbox:
                await sandbox.call_tool("cancel_run", {"run": run})
        except Exception:
            pass


async def fit(device: dict, targets: dict, docs_server=MCP_URL, sandbox_server=SANDBOX_URL):
    """The whole search as a stream of events, so that a client can show progress and stop it.

    In order: a "step" for every look at the documentation, by the agent or by the model,
    an "attempt" every time the state of a run changes, then "result" and a final "done".
    """
    started = time.perf_counter()
    notes = Notes()
    attempts: list[dict] = []
    made: set[str] = set()
    steps = 0
    refusals = 0

    async with Client(docs_server) as docs, Client(sandbox_server) as sandbox:

        async def look_up(tool: str, arguments: dict, wanted: str) -> tuple[str, dict]:
            """One look at the documentation made by the agent. What it found is returned only if it is new."""
            content, added = await _read(docs, tool, arguments, wanted, notes)
            shown = {key: value for key, value in arguments.items() if key != "k"}
            event = {"type": "step", "tool": tool, "arguments": shown, "new_excerpts": added, "by": "agent"}
            return (content if added else ""), event

        start_run = next(tool for tool in (await sandbox.list_tools()).tools if tool.name == "start_run")
        tools = [_function(tool) for tool in (await docs.list_tools()).tools] + [_run_function(start_run)]
        system = FIT.format(**device, **targets)
        if docs.instructions:
            system += f"\n\nAbout the documentation tools: {docs.instructions}"

        # the pages this task depends on, before the model chooses anything
        read = []
        for lookups in _first_reads(device, targets):
            for lookup in lookups:
                content, event = await look_up(*lookup)
                yield event
                if content:
                    read.append(content)
                    break
        task = "\n\n".join([TASK, FROM_DOCS, *read]) if read else TASK
        messages = [{"role": "system", "content": system}, {"role": "user", "content": task}]

        while len(attempts) < MAX_RUNS and steps < MAX_STEPS and refusals < MAX_REFUSALS:
            steps += 1
            # counted before the step and cleared by whatever the step achieves
            refusals += 1
            already_run = REPEATED_RUN.format(run="; ".join(_name(attempt["pipeline"]) for attempt in attempts))
            message = await agent.chat(messages, tools, STEP_TOKENS)
            calls = message.get("tool_calls") or []
            messages.append(message)
            if not calls:
                # here text is not an answer: only a measurement can end the search
                messages.append({"role": "user", "content": NO_CALL})
                yield {"type": "step", "tool": "", "arguments": {}, "refused": "no_call"}
                continue
            # one tool per step: the model must read a result before it decides the next move
            message["tool_calls"] = calls[:1]
            name = calls[0]["function"]["name"]
            arguments = calls[0]["function"].get("arguments") or {}

            if name != "run_pipeline":
                step = {"tool": name, "arguments": arguments}
                if _call_key(name, arguments) in made:
                    content = REPEATED_SEARCH
                    step["refused"] = "repeated"
                else:
                    made.add(_call_key(name, arguments))
                    content, step["new_excerpts"] = await _run_tool(docs, name, arguments, notes)
                    refusals = 0
                messages.append({"role": "tool", "tool_name": name, "content": content})
                yield {"type": "step", **step}
                continue

            pipeline = {key: value for key, value in arguments.items() if key != "reason"}
            step = {"tool": name, "arguments": pipeline}
            if json.dumps({"threads": 1, **pipeline}, sort_keys=True, default=str) in made:
                messages.append({"role": "tool", "tool_name": name, "content": already_run})
                yield {"type": "step", **step, "refused": "repeated"}
                continue
            started_run = await sandbox.call_tool("start_run", {"pipeline": pipeline, "device": device})
            if started_run.is_error:
                # a model the zoo does not have, a size that does not exist: the sandbox says what is valid
                problem = _problems(_text(started_run))
                messages.append({"role": "tool", "tool_name": name, "content": f"Invalid configuration. {problem}"})
                yield {"type": "step", **step, "refused": "invalid", "message": problem}
                continue
            run = started_run.structured_content["run"]
            # as the sandbox understood it, with the defaults filled in
            pipeline = started_run.structured_content["pipeline"]
            key = json.dumps(pipeline, sort_keys=True)
            if key in made:
                # the same configuration written in another way, "160" for 160: seen only now
                await sandbox.call_tool("cancel_run", {"run": run})
                messages.append({"role": "tool", "tool_name": name, "content": already_run})
                yield {"type": "step", **step, "refused": "repeated"}
                continue
            made.add(key)
            # also as the model wrote it, so that the same words are turned down without asking the sandbox
            made.add(json.dumps({"threads": 1, **{k: v for k, v in arguments.items() if k != "reason"}}, sort_keys=True, default=str))
            refusals = 0

            attempt = {
                "n": len(attempts) + 1,
                "pipeline": pipeline,
                "reason": str(arguments.get("reason") or "").strip(),
                "state": "queued",
                "done": 0,
                "total": 0,
                "result": None,
                "failure": "",
                "message": "",
                "verdict": None,
            }
            attempts.append(attempt)
            try:
                async for state in _watch(sandbox, run):
                    attempt.update(state)
                    if attempt["result"]:
                        attempt["verdict"] = _verdict(attempt["result"], targets)
                    yield {"type": "attempt", **attempt}
            except BaseException:
                # the client stopped listening, or something broke: do not leave the run behind
                await _cancel(sandbox_server, run)
                raise
            if attempt["verdict"] and attempt["verdict"]["fits"]:
                break

            # the page of the documentation on what went wrong travels with the result
            content = _report(attempt, targets, device)
            if _missed(attempt):
                advice, event = await look_up(*_by_meaning(ADVICE[_missed(attempt)]))
                if advice:
                    content += f"\n\n{FROM_DOCS}\n\n{advice}"
                yield event
            messages.append({"role": "tool", "tool_name": name, "content": content})

    outcome, best = _pick(attempts, targets)
    note = _note(attempts, outcome, best, device, targets, stuck=refusals >= MAX_REFUSALS)
    yield {"type": "result", "outcome": outcome, "best": best, "note": note}
    yield {
        "type": "done",
        "outcome": outcome,
        "best": best,
        "attempts": attempts,
        "note": note,
        "steps": steps,
        "model": CHAT_MODEL,
        "seconds": round(time.perf_counter() - started, 2),
    }


async def zoo(sandbox_server=SANDBOX_URL) -> dict:
    """What a pipeline can be made of, as the sandbox lists it."""
    async with Client(sandbox_server) as sandbox:
        return (await sandbox.call_tool("zoo", {})).structured_content
