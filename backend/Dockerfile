FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
# Included so the provider and genre tables can be refreshed from a one-off shell.
COPY scripts ./scripts

RUN pip install --upgrade pip && pip install .

EXPOSE 8000

# Migrations run at boot rather than in a separate release step, because Render's free
# tier has no pre-deploy hook. Fine for a single instance; with several, this would need
# to move to a one-off job so they do not race.
#
# $PORT is injected by the host; 8000 locally.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
