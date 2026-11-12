# Build context: ./services (so the shared package `common` is available).
FROM python:3.13.18-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY auth/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY common /tmp/common
RUN pip install /tmp/common && rm -rf /tmp/common

COPY auth/bank_auth ./bank_auth

# /data holds the SQLite file. A new named volume copies this directory, owner
# included, so the non-root user can write there.
RUN useradd --system --uid 10001 --no-create-home app \
    && mkdir /data && chown app /data
USER app

EXPOSE 8000
CMD ["python", "-m", "bank_auth.main"]
