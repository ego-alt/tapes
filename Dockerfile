# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# ffmpeg: required by yt-dlp audio extraction.
# libchromaprint-tools: provides `fpcalc` for AcoustID acoustic-fingerprint dedup.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libchromaprint-tools \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-dev --no-install-project

COPY . /app/
RUN uv sync --frozen --no-dev

ENV FLASK_ENV=production
ENV FLASK_APP=app:create_app

EXPOSE 5003

# Tables are created in create_app(); no migration step in Stage 1/2.
CMD ["sh", "-c", "exec uv run gunicorn 'app:create_app()' -c gunicorn.conf.py"]
