# The triage API image.
#
# Built ONCE per commit by the CD workflow and promoted through dev, acceptance
# and production by digest. Nothing is rebuilt between environments, so the
# image production runs is byte-for-byte the image acceptance approved.
#
# The agent manifest and prompt are baked in. GET /version reports the release
# id computed from those baked-in bytes, which is how a smoke test proves the
# right version is running.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY requirements-api.txt ./
RUN pip install -r requirements-api.txt

COPY src/ src/
COPY agent/ agent/

ARG GIT_SHA=unknown
ENV TRIAGE_GIT_SHA=${GIT_SHA}

LABEL org.opencontainers.image.source="https://github.com/vineet-builds-ai/foundry-triage-genaiops" \
      org.opencontainers.image.description="Ticket triage agent API" \
      org.opencontainers.image.revision="${GIT_SHA}"

# Run as an unprivileged user.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin triage
USER 10001

EXPOSE 8000
CMD ["uvicorn", "triage.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
