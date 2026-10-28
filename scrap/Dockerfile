FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml ./
COPY scrap ./scrap
COPY migrations ./migrations

RUN useradd --system --uid 10003 --home-dir /app --shell /sbin/nologin scrap \
    && mkdir -p /var/lib/gpstracer/scrap \
    && chown -R scrap:scrap /var/lib/gpstracer /app \
    && chmod 700 /var/lib/gpstracer/scrap

USER scrap

EXPOSE 8085

CMD ["uvicorn", "scrap.api.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8085", "--no-access-log"]