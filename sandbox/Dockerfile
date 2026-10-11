# Build from the repository root: docker build -f sandbox/Dockerfile .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /srv

COPY sandbox/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# zoo.json is shared with the bench image: one list of what a pipeline can be made of
COPY sandbox/*.py bench/zoo.json ./

USER 1000
EXPOSE 8002
CMD ["python", "sandbox_server.py"]
