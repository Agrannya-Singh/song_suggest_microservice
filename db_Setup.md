## Database and Cache Setup

This service now supports concurrent SQLite and Postgres databases, plus Redis caching, while maintaining backward compatibility.

### Overview
- Writes: Write-through to all configured databases (SQLite always; Postgres when configured).
- Reads: Prefer the database defined by `DB_READ_PREFERENCE` (defaults to `postgres` if available, otherwise falls back to `sqlite`).
- Cache: Two-tier cache for suggestions
  - Tier 1: Redis (`REDIS_URL`) with TTL
  - Tier 2: In-process TTL cache as fallback

### Environment Variables
- SQLITE_DATABASE_URL: SQLite connection string (default `sqlite:///app.db`).
- POSTGRES_DATABASE_URL: Postgres internal connection URL (Render Postgres).
- DATABASE_URL: Backward-compatible. If set to a Postgres URL, used as `POSTGRES_DATABASE_URL`.
- DB_READ_PREFERENCE: `postgres` (default) or `sqlite`.
- REDIS_URL: Render Redis internal URL.
- REDIS_TTL_SECONDS: Cache TTL in seconds (default `3600`).

### SQLAlchemy Engine Initialization
Defined in `db.py`:
- Separate engines and session factories for SQLite and Postgres.
- `init_db()` creates tables on all configured engines.
- `get_read_session()` returns a session to the preferred DB.
- `get_write_sessions()` returns sessions for all configured DBs for write-through.

### Data Model
Models are defined once and created on each configured DB:
- `User`
- `UserLikedSong`
- `QueryCache`
- `VideoFeature`

### Read/Write Strategy
- Writes: `_persist_user_likes_write_through()` in `main.py` iterates over `get_write_sessions()`; each DB is a separate transaction. Failures on one DB are logged and do not block others.
- Reads: `_load_user_likes()` uses `get_read_session()`.

### Redis Cache
- If `REDIS_URL` is set, `combine_suggestions()` checks Redis first, then local cache.
- On cache miss, results are stored in both caches using `REDIS_TTL_SECONDS` for Redis.
- If Redis is unreachable, logic falls back to local cache without failing requests.

### Render Free Tier Notes
- Use internal Postgres and Redis URLs for low-latency, no-egress access.
- Expect cold starts; Redis may be evicted on free tier—local cache ensures continuity.
- Keep connection counts modest; SQLAlchemy defaults are acceptable for free tier.

### Migration / Bootstrapping
- No Alembic migrations are required at this time. `init_db()` creates missing tables on startup across both DBs.
- Ensure both DB URLs are configured before first boot if you want both populated from day one.

### Operational Guidance
- Prefer `postgres` for reads once configured for better concurrency and scaling.
- Monitor Postgres/Redis metrics on Render. If repeated write-through errors are logged, verify credentials and network access.


