"""What the sandbox accepts and what it returns, as types.

The choices of a pipeline come from bench/zoo.json, the same file the bench image is
built from, so the sandbox can never accept a model that the image does not hold.
"""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

HERE = Path(__file__).parent
# next to the code in the image, in bench/ in the repository
ZOO = json.loads(next(p for p in (HERE / "zoo.json", HERE.parent / "bench" / "zoo.json") if p.exists()).read_text())
MODELS = list(ZOO["models"])


def _one_of(value, choices: list, what: str):
    if value not in choices:
        raise ValueError(f"{value!r} is not a valid {what}: choose one of {', '.join(map(str, choices))}")
    return value


class Pipeline(BaseModel):
    """One configuration of the vision pipeline."""

    model: str = Field(
        description="The network that classifies the picture. Smaller ones are faster and less accurate.",
        json_schema_extra={"enum": MODELS},
    )
    precision: str = Field(
        description="fp32 is the model as trained. int8 is quantized: smaller and usually faster, sometimes less accurate.",
        json_schema_extra={"enum": ZOO["precisions"]},
    )
    input_size: int = Field(
        description="Side of the picture given to the model, in pixels. Smaller is faster and less accurate.",
        json_schema_extra={"enum": ZOO["input_sizes"]},
    )
    threads: int = Field(
        default=1,
        ge=1,
        le=ZOO["max_threads"],
        description="Threads the model computes with. More than the CPU cores of the device does not help.",
    )

    @field_validator("model")
    @classmethod
    def known_model(cls, value):
        return _one_of(value, MODELS, "model")

    @field_validator("precision")
    @classmethod
    def known_precision(cls, value):
        return _one_of(value, ZOO["precisions"], "precision")

    @field_validator("input_size")
    @classmethod
    def known_size(cls, value):
        return _one_of(value, ZOO["input_sizes"], "input_size")


class Device(BaseModel):
    """The device the pipeline must fit in. It becomes the limits of the pod that runs it."""

    cpu: float = Field(gt=0, le=4, description="CPU cores, also a fraction: 0.5 is half a core")
    memory_mb: int = Field(ge=64, le=2048, description="Memory in megabytes")


class Measurement(BaseModel):
    fps: float = Field(description="Pictures per second, from the file to the answer")
    accuracy: float = Field(description="Percentage of pictures classified correctly")
    latency_ms: float = Field(description="Median time of the model alone on one picture")
    latency_p95_ms: float
    memory_mb: int = Field(description="The most memory the pipeline held and could not give back")
    model_mb: float = Field(description="Size of the model file")
    images: int
    predictions: list[int] = Field(description="The class answered for every picture, in order")


class Started(BaseModel):
    run: str = Field(description="Identifier of the run: pass it to get_run")
    pipeline: Pipeline = Field(description="The configuration that is running, with the defaults filled in")


class Run(BaseModel):
    run: str
    state: Literal["queued", "starting", "running", "done", "failed"]
    done: int = Field(default=0, description="Pictures measured so far")
    total: int = 0
    result: Measurement | None = None
    failure: Literal["", "out_of_memory", "timeout", "error"] = ""
    message: str = Field(default="", description="What went wrong, in words")


class Zoo(BaseModel):
    models: list[str]
    precisions: list[str]
    input_sizes: list[int]
    max_threads: int
