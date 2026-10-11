"""Runs one pipeline on the evaluation pictures and prints what it measured.

This is the program that runs inside the sandbox. It knows nothing about limits:
the pod it runs in is the device, and Kubernetes gives it the CPU and the memory
of that device. A pipeline is decode -> resize -> model, one picture at a time.

Usage: python bench.py '{"model": "mobilenet_v2", "precision": "int8", "input_size": 160, "threads": 1}'
Output: lines "PROGRESS done/total" while it works, then one line "RESULT {json}".
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
# the statistics of ImageNet, which every model of the zoo was trained with
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
WARMUP = 3


def preprocess(image, size: int) -> np.ndarray:
    """A picture as the model wants it: size x size, normalized, channels first, in a batch of one."""
    if image.size != (size, size):
        image = image.resize((size, size))
    pixels = (np.asarray(image.convert("RGB"), dtype=np.float32) / 255 - MEAN) / STD
    return np.ascontiguousarray(pixels.transpose(2, 0, 1)[None])


def summarize(predictions: list[int], labels: list[int], latencies: list[float], seconds: float) -> dict:
    """The numbers of a run. `latencies` are the seconds of the model alone, `seconds` those of everything."""
    right = sum(predicted == label for predicted, label in zip(predictions, labels))
    return {
        "fps": round(len(predictions) / seconds, 1),
        "accuracy": round(100 * right / len(labels), 1),
        "latency_ms": round(float(np.percentile(latencies, 50)) * 1000, 1),
        "latency_p95_ms": round(float(np.percentile(latencies, 95)) * 1000, 1),
        "images": len(predictions),
        "predictions": predictions,
    }


def held_memory_mb() -> int:
    """Megabytes this process holds and the system cannot take back: what must fit in the device.

    Files that are merely mapped, like the libraries, are left out: under pressure the
    system drops them and reads them again, so they are not what gets a pipeline killed.
    """
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("RssAnon:"):
            return round(int(line.split()[1]) / 1024)
    return 0


def run(config: dict) -> dict:
    # imported here: the functions above are used at build time and in the tests, without the runtime
    import onnxruntime as ort
    from PIL import Image

    model = HERE / "models" / f"{config['model']}-{config['precision']}.onnx"
    options = ort.SessionOptions()
    options.intra_op_num_threads = config["threads"]
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])

    files = sorted((HERE / "data" / "images").glob("*.jpg"))
    labels = json.loads((HERE / "data" / "labels.json").read_text())
    size = config["input_size"]
    for file in files[:WARMUP]:
        session.run(None, {"image": preprocess(Image.open(file), size)})

    predictions, latencies = [], []
    memory = held_memory_mb()
    started = time.perf_counter()
    for number, file in enumerate(files, start=1):
        pixels = preprocess(Image.open(file), size)
        before = time.perf_counter()
        logits = session.run(None, {"image": pixels})[0]
        latencies.append(time.perf_counter() - before)
        predictions.append(int(np.argmax(logits)))
        if number % 10 == 0:
            memory = max(memory, held_memory_mb())
            print(f"PROGRESS {number}/{len(files)}", flush=True)
    seconds = time.perf_counter() - started

    return {
        **summarize(predictions, labels, latencies, seconds),
        "memory_mb": memory,
        "model_mb": round(model.stat().st_size / 1e6, 1),
    }


if __name__ == "__main__":
    print("RESULT " + json.dumps(run(json.loads(sys.argv[1]))), flush=True)
