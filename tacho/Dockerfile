# ---------------------------------------------------------------------------
# GPS_Tracer tachograph service
#
# One image, two entrypoints: the API (uvicorn) and the worker (python -m
# tacho.worker). Sharing the image guarantees the parser that runs in the worker is
# byte-for-byte the one the API was tested against, which would not be true if the
# two were built separately.
#
# Runs as a non-root user because it reads attacker-supplied files. The parser is
# pure Python and never executes uploaded content, but defence in depth is cheap
# here: a driver card download is untrusted input by definition.
# ---------------------------------------------------------------------------
FROM python:3.12-slim

# Deterministic, quiet, and no .pyc litter in a read-only layer.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first: this layer is cached until requirements.txt changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml ./
COPY tacho ./tacho
COPY migrations ./migrations

# Storage lives on a mounted volume, never in the image. Created as root and then
# handed to the runtime user so the mount has the right owner on first boot.
RUN useradd --system --uid 10002 --home-dir /app --shell /sbin/nologin tacho \
    && mkdir -p /var/lib/gpstracer/tacho \
    && chown -R tacho:tacho /var/lib/gpstracer /app \
    && chmod 700 /var/lib/gpstracer/tacho

USER tacho

# 8084 is the API. It is published to loopback only by docker-compose; nothing here
# is intended to be reachable from the internet.
EXPOSE 8084

# The API is the default entrypoint. The worker overrides the command in compose.
CMD ["uvicorn", "tacho.api.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8084", "--no-access-log"]
