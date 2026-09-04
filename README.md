# JustPick

Streaming decision fatigue solver. Give it your services and your constraints — genres, how much
time you have, a rating floor if you want one — and it returns **one** movie. Not a grid of forty.

Don't like it? Say why, and it picks a different one.

**React + TypeScript · FastAPI · PostgreSQL · TMDb**

---

## Design

The decision logic lives in `backend/app/engine/` as pure functions: plain dataclasses in, a
plain dataclass out, no database and no network. Hard constraints eliminate candidates, a
weighted score ranks the survivors, and the pick is drawn from the top band using a seed derived
from the session, so the same inputs always produce the same answer while different users don't
all get handed the same movie.

Everything else — HTTP, TMDb, persistence — stays outside that boundary.
`backend/tests/test_layering.py` parses the imports under `app/` and fails the build if a layer
crosses a line it shouldn't.

---

## Running it

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

http://localhost:8000/api/v1/health · http://localhost:8000/docs

Checks:

```bash
cd backend && ruff check . && pytest -q
```

### Database

Any PostgreSQL 16 instance works. With Docker:

```bash
docker compose up
```

Otherwise point `DATABASE_URL` at a local or hosted Postgres and run:

```bash
cd backend && alembic upgrade head
```

`alembic.ini` carries no connection string — `alembic/env.py` reads `DATABASE_URL` from the
environment, so the same migrations run everywhere and no credentials are committed.

---

## Layout

```
backend/
  app/
    api/            routers, request/response schemas
    engine/         decision logic — pure, no I/O
    tmdb/           TMDb HTTP client
    db/             SQLAlchemy models, session management
    repositories/   data access
    services/       orchestration: fetch → filter → decide
  alembic/          migrations
  tests/
frontend/           React + TypeScript
```

---

## Configuration

Environment only — see [backend/.env.example](backend/.env.example). `.env` is gitignored.

| Variable | |
|---|---|
| `DATABASE_URL` | async SQLAlchemy URL, e.g. `postgresql+asyncpg://user:pass@host/db` |
| `TMDB_API_TOKEN` | v4 Read Access Token from [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) |
| `CORS_ORIGINS` | comma-separated allowed origins |
| `APP_ENV` | `local` / `production` |

---

## Attribution

This product uses the TMDB API but is not endorsed or certified by TMDB. Streaming availability
data is provided by JustWatch via TMDB.
