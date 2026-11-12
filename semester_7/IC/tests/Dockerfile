# Image for lint, unit and e2e tests. The repository is mounted at /repo at run time,
# so only the dependencies are baked in.
FROM python:3.13.18-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONUNBUFFERED=1

COPY tests/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

WORKDIR /repo
