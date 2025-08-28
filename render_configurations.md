## Render Configuration Guide

This document outlines the recommended Render setup for running the service with dual databases (SQLite + Postgres) and Redis cache on the free tier.

### Services Overview
- Web Service: FastAPI app
  - Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Postgres: Managed Render Postgres (use internal connection URL)
- Redis: Managed Render Redis (use internal connection URL)

### Environment Variables (Render → Environment)
- `YOUTUBE_API_KEY`: Your YouTube API key (secret)
- `SQLITE_DATABASE_URL`: `sqlite:///app.db` (default)
- `POSTGRES_DATABASE_URL`: Internal Postgres URL (e.g., `postgresql://USER:PASSWORD@HOST:PORT/DBNAME`)
- `DATABASE_URL` (optional): Backward-compat. If set to a Postgres URL, it is used as Postgres.
- `DB_READ_PREFERENCE`: `postgres` (default) or `sqlite`
- `REDIS_URL`: Internal Redis URL (e.g., `redis://default:PASSWORD@HOST:PORT` or `redis://HOST:PORT` if no auth)
- `REDIS_TTL_SECONDS`: `3600` (default)

### Database Plan and Behavior
- SQLite: Always enabled and used as a secondary durability store.
- Postgres: Primary operational database when configured.
- Writes: Write-through to all configured DBs (SQLite and Postgres). Failures on one DB are logged and do not block commits to the other.
- Reads: Use the DB specified by `DB_READ_PREFERENCE` (default `postgres` if available, else `sqlite`).
- Schema management: `init_db()` creates tables on startup on all configured DBs (no Alembic migrations yet).

### Connection Guidance (Render Free Tier)
- Use internal connection strings from Render to avoid egress and reduce latency.
- Keep pool sizes modest (SQLAlchemy defaults are fine).
- Expect cold starts; the app will initialize DB tables on first request if needed.

### Health and Monitoring
- Health endpoint: `GET /health`
- Logging at INFO level; DB write-through errors are logged with context.

### Security Notes
- Do not commit secrets; set them in Render Environment.
- If your Redis instance enforces auth, prefer `redis://default:PASS@HOST:PORT` format.

### Example Values (do not commit to repo)
- `POSTGRES_DATABASE_URL=postgresql://tune_trace_db_user:NHgWGfhyqDLbqK270dx1XKY1U9lBdawh@dpg-d2o7g3euk2gs73ajefv0-a/tune_trace_db`
- `REDIS_URL=redis://red-d2b2cpemcj7s73e47s40:6379`


