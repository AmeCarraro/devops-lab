# Build from the repository root: docker build -f bench/Dockerfile .
# Two stages. The first one downloads public models and pictures and turns them into
# the files the benchmark needs; it is large (PyTorch) and never leaves the build.
# The second one is what runs in the sandbox: the ONNX runtime, the files, one script.
# Each step is its own layer, so changing a script only repeats the steps after it.
FROM python:3.12-slim AS zoo
WORKDIR /build
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.5.1 torchvision==0.20.1
RUN pip install --no-cache-dir onnx==1.17.0 onnxruntime==1.20.1 pillow==11.0.0

COPY bench/dataset.py .
RUN python dataset.py out calibration

# the weights, apart from the export: a change to the scripts does not download them again
COPY bench/zoo.json .
RUN python -c "import json, torchvision; [torchvision.models.get_model(n, weights=w) for n, w in json.load(open('zoo.json'))['models'].items()]"

COPY bench/bench.py bench/export.py ./
RUN python export.py zoo.json out calibration


FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN pip install --no-cache-dir onnxruntime==1.20.1 pillow==11.0.0
WORKDIR /opt/bench
COPY --from=zoo /build/out/ ./
COPY bench/bench.py .
USER 1000
ENTRYPOINT ["python", "bench.py"]
