# Build from the repository root: docker build -f mcp-server/Dockerfile .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /srv

COPY mcp-server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp-server/*.py ./
# The corpus is part of the image: new docs = new image = new deploy
COPY docs/ docs/

USER 1000
EXPOSE 8001
CMD ["python", "server.py"]
