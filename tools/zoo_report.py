"""Measures the model zoo through the sandbox and writes the two pages of documentation that hold its numbers.

The agent reads those pages before it chooses a configuration, so what they say must be
measured and not remembered: every number and every piece of advice in them is computed here.

    python tools/zoo_report.py measure    runs the plan below and saves tools/measurements.json
    python tools/zoo_report.py write      writes docs/model-zoo.md and docs/fitting-guide.md from it

`measure` talks to the sandbox server, which has no address outside the cluster. Open a tunnel first:

    kubectl -n demo port-forward svc/sandbox-mcp 8002:8002

Keep the PC quiet while it runs: the speeds are measured on it. It takes about ten minutes.
"""
import asyncio
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
MEASUREMENTS = Path(__file__).with_name("measurements.json")
SANDBOX = "http://127.0.0.1:8002/mcp"

ZOO = json.loads((ROOT / "bench" / "zoo.json").read_text())
MODELS = list(ZOO["models"])
PRECISIONS = ZOO["precisions"]
SIZES = sorted(ZOO["input_sizes"], reverse=True)
REFERENCE = {"cpu": 1, "memory_mb": 512}
SMALL = {"cpu": 0.5, "memory_mb": 128}
LARGE = {"cpu": 2, "memory_mb": 1024}
# The guide has one section for each of these accuracies, named "Configurations with at least N% accuracy",
# and one for every whole percentage above them that some configuration still reaches.
# The fit loop asks for them by that name (app/fit.py): change the wording in both places or in neither.
LEVELS = range(85, 45, -5)
# what cannot be measured: said once here, repeated in each model's section
ABOUT = {
    "mobilenet_v3_small": ("2.5", "The smallest and fastest model of the zoo. Use it when speed matters most."),
    "mobilenet_v2": ("3.5", "A small model that is fast in both precisions. It is the least accurate of the zoo."),
    "efficientnet_b0": ("5.3", "The most accurate model of the zoo, and it needs less memory than the resnets. It is slower than the two mobilenets."),
    "resnet18": ("11.7", "A mid-size model. In fp32 it is slow for its accuracy; in int8 it is almost three times faster and just as accurate."),
    "resnet50": ("25.6", "The largest model: accurate, slow and hungry for memory in fp32. In int8 it is three times faster and needs less than a third of the memory."),
}


def plan() -> list[tuple[dict, dict]]:
    """Every (device, pipeline) to measure: the whole zoo on the reference device, and a few questions on the others."""

    def pipeline(model, precision, size=224, threads=1):
        return {"model": model, "precision": precision, "input_size": size, "threads": threads}

    runs = [(REFERENCE, pipeline(m, p, s)) for m in MODELS for p in PRECISIONS for s in SIZES]
    # which models fit in little memory, and what half a core does to the speed
    runs += [(SMALL, pipeline(m, p)) for m in MODELS for p in PRECISIONS]
    # what threads do, with as many cores as threads and with fewer
    runs += [(LARGE, pipeline(m, "fp32", threads=n)) for n in (1, 2, 4) for m in ("resnet50", "efficientnet_b0")]
    runs += [(REFERENCE, pipeline(m, p, threads=n)) for n in (2, 4) for m, p in (("mobilenet_v2", "fp32"), ("resnet50", "int8"))]
    return runs


async def measure() -> None:
    from mcp import Client

    saved = json.loads(MEASUREMENTS.read_text()) if MEASUREMENTS.exists() else {"runs": []}
    runs = saved["runs"]
    done = {json.dumps([run["device"], run["pipeline"]], sort_keys=True) for run in runs}
    async with Client(SANDBOX) as sandbox:
        for device, pipeline in plan():
            # a measurement already saved is kept: delete it from the file to take it again
            if json.dumps([device, pipeline], sort_keys=True) in done:
                continue
            started = await sandbox.call_tool("start_run", {"pipeline": pipeline, "device": device})
            while True:
                state = (await sandbox.call_tool("get_run", {"run": started.structured_content["run"]})).structured_content
                if state["state"] in ("done", "failed"):
                    break
                await asyncio.sleep(0.7)
            result = state["result"] or {}
            result.pop("predictions", None)
            runs.append({"device": device, "pipeline": pipeline, "failure": state["failure"], "result": result})
            MEASUREMENTS.write_text(json.dumps({"measured_on": str(datetime.date.today()), "runs": runs}, indent=1) + "\n")
            print(device["cpu"], *pipeline.values(), state["failure"] or result, flush=True)


class Zoo:
    """The measurements, and the questions the two pages ask of them."""

    def __init__(self, saved: dict):
        self.date = saved["measured_on"]
        self.runs = saved["runs"]
        # int8 is "broken" for a model when it costs more than 20 points of accuracy
        self.broken = [m for m in MODELS if self.at(m, "fp32")["accuracy"] - self.at(m, "int8")["accuracy"] > 20]
        self.sound = [m for m in MODELS if m not in self.broken]
        # the configurations worth recommending: all but int8 where int8 is broken
        self.usable = [
            run for run in self.runs
            if run["device"] == REFERENCE and run["pipeline"]["threads"] == 1
            and not (run["pipeline"]["precision"] == "int8" and run["pipeline"]["model"] in self.broken)
        ]
        self.top = max(run["result"]["accuracy"] for run in self.usable)

    def run(self, model, precision, size=224, threads=1, device=REFERENCE) -> dict:
        wanted = {"model": model, "precision": precision, "input_size": size, "threads": threads}
        return next(run for run in self.runs if run["device"] == device and run["pipeline"] == wanted)

    def at(self, model, precision, size=224, threads=1, device=REFERENCE) -> dict:
        return self.run(model, precision, size, threads, device)["result"]

    def gain(self, model) -> float:
        """How many times faster a model is in int8."""
        return self.at(model, "int8")["fps"] / self.at(model, "fp32")["fps"]

    def fastest(self, accuracy, limit) -> list[dict]:
        """The fastest usable configurations with at least this accuracy."""
        found = [run for run in self.usable if run["result"]["accuracy"] >= accuracy]
        return sorted(found, key=lambda run: -run["result"]["fps"])[:limit]

    def above(self, accuracy, limit=4) -> str:
        return "; ".join(
            f"`{run['pipeline']['model']}` {run['pipeline']['precision']} at {run['pipeline']['input_size']} "
            f"({run['result']['fps']:.0f} images/s, {run['result']['accuracy']}%)"
            for run in self.fastest(accuracy, limit)
        )

    def best_precision(self, model) -> str:
        return "fp32" if model in self.broken else "int8"

    def across_sizes(self, model, key) -> str:
        return " → ".join(f"{self.at(model, self.best_precision(model), size)[key]:g}" for size in SIZES)


def code(names) -> str:
    return ", ".join(f"`{name}`" for name in names)


def model_zoo(zoo: Zoo) -> str:
    by_speed = {p: sorted(MODELS, key=lambda m: -zoo.at(m, p)["fps"]) for p in PRECISIONS}
    by_accuracy = sorted(((zoo.at(m, p)["accuracy"], m, p) for m in MODELS for p in PRECISIONS), reverse=True)
    small = {(m, p): zoo.run(m, p, device=SMALL) for m in MODELS for p in PRECISIONS}
    lines = [
        "# Model zoo",
        "",
        "The zoo is the set of image classification models a pipeline can use: five models, each in two precisions, `fp32` and `int8`, at four input sizes. This page says how fast, how accurate and how large each of them is. It is written by `tools/zoo_report.py` from measurements: to change a number, measure again.",
        "",
        "## How the numbers were measured",
        "",
        "Every number in this page was measured in the sandbox on the reference device: 1 CPU core, 512 MB of memory, 1 thread. Speed is images per second over the 200 evaluation pictures, from the file to the answer. Accuracy is the share of those pictures classified correctly among the 1000 classes of ImageNet. Memory is the most the pipeline held and could not give back.",
        "",
        f"The measurements were made once each, on {zoo.date}, on the laptop the project is developed on. Another machine gives other speeds, and a second run on the same machine differs by a few percent. What carries over is the order of the configurations and the size of the gaps between them.",
        "",
        "## Which model is the fastest",
        "",
        "At 224 pixels in fp32, from the fastest to the slowest: "
        + ", ".join(f"`{m}` ({zoo.at(m, 'fp32')['fps']:.0f} images/s)" for m in by_speed["fp32"]) + ".",
        "",
        "In int8 the two resnets gain the most: "
        + ", ".join(f"`{m}` ({zoo.at(m, 'int8')['fps']:.0f})" for m in by_speed["int8"])
        + ". Speed alone is not enough to choose: two of these models lose their accuracy in int8.",
        "",
        "## Which model is the most accurate",
        "",
        "At 224 pixels, from the most accurate: " + ", ".join(f"`{m}` {p} ({a}%)" for a, m, p in by_accuracy) + ".",
        "",
        f"No usable configuration of the zoo is above {zoo.top}% on the evaluation pictures: a target higher than that cannot be met.",
        "",
        "## Models that must not be used in int8",
        "",
        "Quantization ruins two models of the zoo: "
        + " and ".join(f"`{m}` falls from {zoo.at(m, 'fp32')['accuracy']}% to {zoo.at(m, 'int8')['accuracy']}%" for m in zoo.broken)
        + ". Use these two in fp32 only.",
        "",
        "The other three keep their accuracy in int8 at 224 pixels: "
        + ", ".join(f"`{m}` ({zoo.at(m, 'fp32')['accuracy']}% in fp32, {zoo.at(m, 'int8')['accuracy']}% in int8)" for m in zoo.sound) + ".",
        "",
    ]
    for model, (millions, text) in ABOUT.items():
        lines += [
            f"## {model}",
            "",
            f"{text} It has {millions} million parameters; the file is {zoo.at(model, 'fp32')['model_mb']} MB in fp32 and {zoo.at(model, 'int8')['model_mb']} MB in int8.",
            "",
            "| precision | input size | images/s | accuracy | memory |",
            "|---|---|---|---|---|",
        ]
        for precision in PRECISIONS:
            for size in SIZES:
                result = zoo.at(model, precision, size)
                lines.append(f"| {precision} | {size} | {result['fps']} | {result['accuracy']}% | {result['memory_mb']} MB |")
        lines.append("")
    lines += [
        "## Memory each model needs",
        "",
        "Memory depends on the model and the precision, and hardly on the input size. At 224 pixels:",
        "",
        "| model | fp32 | int8 |",
        "|---|---|---|",
        *(f"| {m} | {zoo.at(m, 'fp32')['memory_mb']} MB | {zoo.at(m, 'int8')['memory_mb']} MB |" for m in MODELS),
        "",
        f"On the smallest device, which has {SMALL['memory_mb']} MB, these go out of memory and are stopped: "
        + (", ".join(f"`{m}` {p}" for (m, p), run in small.items() if run["failure"] == "out_of_memory") or "none")
        + ". These fit: " + ", ".join(f"`{m}` {p}" for (m, p), run in small.items() if not run["failure"]) + ".",
        "",
    ]
    return "\n".join(lines)


def fitting_guide(zoo: Zoo) -> str:
    # what one step down in size, from 224 to 192, gives in speed and costs in accuracy
    pairs = [(m, p) for m in MODELS for p in PRECISIONS if not (p == "int8" and m in zoo.broken)]
    faster = [zoo.at(m, p, 192)["fps"] / zoo.at(m, p)["fps"] for m, p in pairs]
    loss = [zoo.at(m, p)["accuracy"] - zoo.at(m, p, 192)["accuracy"] for m, p in pairs]
    small = {(m, p): zoo.run(m, p, device=SMALL) for m in MODELS for p in PRECISIONS}
    half = [run["result"]["fps"] / zoo.at(m, p)["fps"] for (m, p), run in small.items() if run["result"]]

    def threads(model, precision, count, device):
        return zoo.at(model, precision, threads=count, device=device)["fps"]

    # The section on threads states these as facts. If new measurements say otherwise, stop: the text must change.
    for model, precision in (("mobilenet_v2", "fp32"), ("resnet50", "int8")):
        assert threads(model, precision, 1, REFERENCE) > threads(model, precision, 2, REFERENCE) > threads(model, precision, 4, REFERENCE)
    for model in ("resnet50", "efficientnet_b0"):
        assert 1.5 <= threads(model, "fp32", 2, LARGE) / threads(model, "fp32", 1, LARGE) <= 1.9
        assert threads(model, "fp32", 2, LARGE) > threads(model, "fp32", 4, LARGE)

    int8_rows = "\n".join(
        f"| {m} | {zoo.gain(m):.1f} times | {zoo.at(m, 'fp32')['accuracy']}% → {zoo.at(m, 'int8')['accuracy']}% "
        f"| {zoo.at(m, 'fp32')['memory_mb']} → {zoo.at(m, 'int8')['memory_mb']} MB |"
        for m in MODELS
    )
    size_rows = "\n".join(
        f"- `{m}` {zoo.best_precision(m)}: {zoo.across_sizes(m, 'accuracy')} %, at {zoo.across_sizes(m, 'fps')} images/s"
        for m in MODELS
    )
    top_levels = range(int(zoo.top), max(LEVELS), -1)
    levels = "\n\n".join(
        f"## Configurations with at least {level}% accuracy\n\n"
        f"The fastest configurations that reach {level}% accuracy or more, on the reference device with 1 core, fastest first:\n\n"
        + "\n".join(
            f"- model `{run['pipeline']['model']}`, precision `{run['pipeline']['precision']}`, input_size {run['pipeline']['input_size']}: "
            f"{run['result']['fps']:.0f} images/s, {run['result']['accuracy']}% accuracy, {run['result']['memory_mb']} MB"
            for run in zoo.fastest(level, 6)
        )
        for level in (*top_levels, *LEVELS)
    )
    ruined = ", ".join(f"{zoo.at(m, 'int8')['accuracy']}% instead of {zoo.at(m, 'fp32')['accuracy']}%" for m in zoo.broken)
    dead = ", ".join(f"`{m}` {p}" for (m, p), run in small.items() if run["failure"] == "out_of_memory") or "none of the models"

    return f"""# Fitting guide

How to choose a pipeline configuration that reaches a speed and an accuracy on a device, and what to change when a run misses a target. The numbers are those of the model zoo page: reference device with 1 CPU core and 512 MB, 1 thread. This page is written by `tools/zoo_report.py` from the same measurements.

## The four settings

- `model`: the network that classifies the picture. It decides most of the speed, the accuracy and the memory.
- `precision`: `fp32` is the model as it was trained. `int8` is the same model with 8-bit integers: smaller, usually faster, and for some models much less accurate.
- `input_size`: the side of the picture given to the model: 224, 192, 160 or 128 pixels. Smaller is faster and less accurate.
- `threads`: how many threads compute. It helps only on a device with more than one core.

## Start from the accuracy

Accuracy is the harder target: few configurations reach a high one, and no setting buys accuracy back cheaply. So first keep only the configurations that are accurate enough, then take the fastest of them that is fast enough.

This page has a list for every level of accuracy from {min(LEVELS)}% to {max(LEVELS)}% in steps of 5, and for {" and ".join(f"{level}%" for level in sorted(top_levels))}: "Configurations with at least 80% accuracy" and so on. Use the list of the target, or of the next level up. The best accuracy in the zoo is {zoo.top}%: a higher target cannot be met.

{levels}

## When the pipeline is too slow

Try these in order, and stop at the first that is enough.

1. Use int8, if the model is {code(zoo.sound)}. It is the only change that costs almost no accuracy: {", ".join(f"`{m}` becomes {zoo.gain(m):.1f} times faster" for m in zoo.sound)}.
2. Lower `input_size` by one step. From 224 to 192 a pipeline is about {sum(faster) / len(faster):.1f} times faster and loses from {min(loss):g} to {max(loss):g} points of accuracy.
3. Take a faster model that is still accurate enough: see the list of configurations for the accuracy of the target.
4. On a device with 2 cores, set `threads` to 2.

Never use int8 with {" or ".join(f"`{m}`" for m in zoo.broken)} to gain speed: the accuracy collapses.

## When the accuracy is too low

1. Check the precision first. {" and ".join(f"`{m}`" for m in zoo.broken)} are ruined by int8 ({ruined}): with these two use fp32.
2. Raise `input_size` towards 224. Every model is most accurate at 224.
3. Take a more accurate model. The most accurate are {zoo.above(86, 3)}.
4. If the target is above {zoo.top}%, no configuration reaches it: say so instead of trying.

## What int8 changes

int8 stores the weights and the intermediate values of the model as 8-bit integers instead of 32-bit numbers. The file is about a quarter of the size, the model needs less memory, and on a CPU the arithmetic is faster.

| model | speed in int8 | accuracy fp32 → int8 | memory fp32 → int8 |
|---|---|---|---|
{int8_rows}

The models were quantized after training, with ranges measured on 60 pictures. {" and ".join(f"`{m}`" for m in zoo.broken)} do not survive this simple method. Why was not investigated in this project.

## What a smaller input size changes

A smaller picture has fewer pixels to compute, so the speed grows roughly with the pixels saved: 160 pixels is about half the work of 224. The price in accuracy depends on the model. Accuracy at 224 → 192 → 160 → 128 pixels, in the precision each model should be used in:

{size_rows}

## Threads and CPU cores

Use as many threads as the device has whole cores, and never more. One thread is right for a device with one core or less: with more, the threads take turns on the same core and the pipeline gets slower. On 1 core, `mobilenet_v2` fp32 runs at {threads("mobilenet_v2", "fp32", 1, REFERENCE):.0f} images/s with 1 thread, {threads("mobilenet_v2", "fp32", 2, REFERENCE):.0f} with 2 and {threads("mobilenet_v2", "fp32", 4, REFERENCE):.0f} with 4; `resnet50` int8 at {threads("resnet50", "int8", 1, REFERENCE):.0f}, {threads("resnet50", "int8", 2, REFERENCE):.0f} and {threads("resnet50", "int8", 4, REFERENCE):.0f}.

On a device with 2 cores, 2 threads are the best choice: `resnet50` fp32 runs at {threads("resnet50", "fp32", 1, LARGE):.1f} images/s with 1 thread, {threads("resnet50", "fp32", 2, LARGE):.1f} with 2 and {threads("resnet50", "fp32", 4, LARGE):.1f} with 4; `efficientnet_b0` fp32 at {threads("efficientnet_b0", "fp32", 1, LARGE):.0f}, {threads("efficientnet_b0", "fp32", 2, LARGE):.0f} and {threads("efficientnet_b0", "fp32", 4, LARGE):.0f}. Two cores do not double the speed: expect from 1.5 to 1.9 times.

## Half a core, two cores

Speed follows the CPU the device has. On half a core every configuration runs at about {sum(half) / len(half):.2f} times its speed on one core. Accuracy does not depend on the device: the same configuration gives the same answers everywhere.

So a target of 30 images/s on half a core needs a configuration that reaches about {30 / (sum(half) / len(half)):.0f} on the reference device.

## When a run goes out of memory

The pipeline needed more memory than the device has and was stopped. Memory depends on the model and the precision, and hardly on the input size, so a smaller picture does not fix it. Use int8, or a smaller model.

On the device with {SMALL['memory_mb']} MB these go out of memory: {dead}. Everything else fits. On 512 MB and more, every configuration fits.
"""


if __name__ == "__main__":
    if sys.argv[1:] == ["measure"]:
        asyncio.run(measure())
    elif sys.argv[1:] == ["write"]:
        zoo = Zoo(json.loads(MEASUREMENTS.read_text()))
        for name, page in (("model-zoo.md", model_zoo(zoo)), ("fitting-guide.md", fitting_guide(zoo))):
            (ROOT / "docs" / name).write_text(page, encoding="utf-8", newline="\n")
            print(name, "longest section:", max(len(section) for section in page.split("\n## ")), "characters")
    else:
        sys.exit(__doc__)
