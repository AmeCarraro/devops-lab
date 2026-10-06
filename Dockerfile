FROM python:3.12-slim

WORKDIR /app

# Dependencies first: this layer is cached until requirements.txt changes
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

USER 1000
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
