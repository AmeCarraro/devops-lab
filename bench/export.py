"""Build step of the bench image: the models of the zoo, as ONNX files in two precisions.

fp32 is the model as it was trained. int8 is the same model after static quantization:
weights and activations become 8-bit integers, with ranges measured on the calibration pictures.
The width and height of the input stay free, so one file serves every input size.
"""
import json
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
import torchvision
from onnxruntime.quantization import CalibrationDataReader, QuantFormat, QuantType, quantize_static
from onnxruntime.quantization.shape_inference import quant_pre_process
from PIL import Image

from bench import preprocess


class Pictures(CalibrationDataReader):
    """Feeds the calibration pictures to the quantizer, one at a time."""

    def __init__(self, folder: Path):
        self.files = iter(sorted(folder.glob("*.jpg")))

    def get_next(self):
        file = next(self.files, None)
        return {"image": preprocess(Image.open(file), 224)} if file else None


def export(name: str, weights: str, target: Path) -> list[str]:
    """Writes <name>-fp32.onnx and returns the names of the 1000 classes."""
    model = torchvision.models.get_model(name, weights=weights).eval()
    torch.onnx.export(
        model,
        torch.zeros(1, 3, 224, 224),
        str(target),
        input_names=["image"],
        output_names=["logits"],
        dynamic_axes={"image": {2: "height", 3: "width"}},
        opset_version=17,
    )
    return torchvision.models.get_model_weights(name)[weights].meta["categories"]


def quantize(source: Path, target: Path, calibration: Path) -> None:
    prepared = source.with_suffix(".prepared.onnx")
    try:
        # folds what can be folded and writes the shapes down: the quantizer does a better job on the result
        quant_pre_process(str(source), str(prepared))
    except Exception as exc:
        print(f"  no pre-processing for {source.name}: {exc}")
        prepared = source
    quantize_static(
        str(prepared),
        str(target),
        Pictures(calibration),
        quant_format=QuantFormat.QDQ,
        # one range per output channel of a convolution instead of one per layer:
        # without it the small models lose most of their accuracy
        per_channel=True,
        activation_type=QuantType.QUInt8,
        weight_type=QuantType.QInt8,
    )
    if prepared != source:
        prepared.unlink()


def accuracy(model: Path, images: Path, labels: list[int]) -> float:
    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    right = 0
    for file, label in zip(sorted(images.glob("*.jpg")), labels):
        logits = session.run(None, {"image": preprocess(Image.open(file), 224)})[0]
        right += int(np.argmax(logits)) == label
    return 100 * right / len(labels)


def main(zoo: Path, out: Path, calibration: Path) -> None:
    models = out / "models"
    models.mkdir(parents=True, exist_ok=True)
    labels = json.loads((out / "data" / "labels.json").read_text())
    classes: list[str] = []
    table = {}
    for name, weights in json.loads(zoo.read_text())["models"].items():
        fp32, int8 = models / f"{name}-fp32.onnx", models / f"{name}-int8.onnx"
        classes = export(name, weights, fp32)
        quantize(fp32, int8, calibration)
        table[name] = {
            file.stem.split("-")[-1]: {
                "megabytes": round(file.stat().st_size / 1e6, 1),
                "accuracy_224": accuracy(file, out / "data" / "images", labels),
            }
            for file in (fp32, int8)
        }
        print(name, table[name], flush=True)
    (models / "built.json").write_text(json.dumps(table, indent=2))
    # the page shows what the model answered, also when it is wrong: it needs every name
    samples = out / "public" / "samples.json"
    samples.write_text(json.dumps({**json.loads(samples.read_text()), "classes": classes}))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
