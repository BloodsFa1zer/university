# Build context: ./services (so the shared package `common` is available).
FROM python:3.13.18-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY worker/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY common /tmp/common
RUN pip install /tmp/common && rm -rf /tmp/common

COPY worker/bank_worker ./bank_worker

RUN useradd --system --uid 10001 --no-create-home app
USER app

# Exec form: python is PID 1 and receives SIGTERM from `docker compose stop`.
CMD ["python", "-m", "bank_worker.main"]
