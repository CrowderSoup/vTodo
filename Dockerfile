FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app" \
    UV_NO_DEV=1 \
    UV_NO_CACHE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev && rm -rf /root/.cache/uv

COPY . .

RUN uv run manage.py collectstatic --noinput

RUN addgroup --system app && adduser --system --ingroup app app \
    && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["sh", "-c", "uv run manage.py migrate && uv run gunicorn config.wsgi:application -b 0.0.0.0:${PORT:-8000} -w ${GUNICORN_WORKERS:-2}"]
