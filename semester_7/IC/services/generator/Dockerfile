# Build context: ./services (so the shared package `common` is available).
FROM python:3.13.18-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY generator/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY common /tmp/common
RUN pip install /tmp/common && rm -rf /tmp/common

COPY generator/bank_generator ./bank_generator

RUN useradd --system --uid 10001 --no-create-home app
USER app

EXPOSE 8000
CMD ["python", "-m", "bank_generator.main"]
