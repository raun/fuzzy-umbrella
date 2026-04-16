# Feature: FastAPI Backend + React Frontend Setup

## Summary

Establish a full-stack web application scaffold within this repository: a FastAPI backend serving a JSON REST API, and a React (Vite) single-page frontend that consumes it. Both services run in Docker (separate containers orchestrated by docker-compose), alongside a PostgreSQL database for persistent storage. The backend uses SQLAlchemy (async) for ORM/migrations and asyncpg as the async driver. Development includes hot-reload for the backend; the frontend container serves the production build via `vite preview`. This is a greenfield scaffold — it provides the structural skeleton (project layout, wiring, one representative domain) so subsequent features can extend it.

---

## Scope

**IN**
- FastAPI application under `src/api/` with:
  - A health-check endpoint
  - A representative CRUD resource: `items` (id, name, description, created_at)
  - CORS middleware configured for the React dev server
  - Pydantic v2 models for all request/response schemas
  - Uvicorn as the ASGI server
  - Async SQLAlchemy session dependency injected into routes
- PostgreSQL service added to docker-compose
- SQLAlchemy async ORM layer (`src/api/database.py`, `src/api/db_models.py`) replacing the in-memory store
- Alembic for database migrations (`alembic/` directory, initial migration for `items` table)
- React application (Vite + TypeScript) under `frontend/` with:
  - A minimal UI that fetches and displays the `items` list from the API
  - A form to create a new item
  - Vite dev-server proxy so frontend code calls `/api/...` without hardcoded ports
- Docker setup:
  - Updated `Dockerfile` (renamed to `Dockerfile.backend`) for the FastAPI service
  - New `Dockerfile.frontend` for building/serving the React app via `vite preview`
  - Updated `docker-compose.yml` with `backend`, `frontend`, and `postgres` services
- `pyproject.toml` updated with backend Python dependencies (including asyncpg, SQLAlchemy, alembic)
- `frontend/package.json` listing frontend dependencies with major version pins
- `.env.example` committed to the repo as a bootstrap template
- Unit tests for all API endpoints (pytest + httpx `AsyncClient`), using SQLite via SQLAlchemy for isolation
- Integration tests pointing at a dedicated `appdb_test` Postgres database
- Frontend component smoke tests (Vitest + Testing Library)
- `scripts/run.sh` updated to target the `backend` service (replacing `app`)
- `CLAUDE.md` updated to reflect the `backend` service rename, the `alembic upgrade head` setup step, and the PYTHONPATH change from `/workspace/src` to `/workspace`

**OUT**
- Authentication / authorization (no JWT, no sessions)
- CI/CD pipeline configuration
- Production TLS / reverse-proxy (nginx) configuration
- State management libraries (Redux, Zustand, etc.)
- End-to-end browser tests (Playwright / Cypress)

---

## Acceptance Criteria

- [ ] `docker compose up` starts `backend`, `frontend`, and `postgres` services without errors
- [ ] `GET /health` returns `{"status": "ok"}` with HTTP 200
- [ ] `GET /api/items` returns a JSON array (empty on first startup after migration)
- [ ] `POST /api/items` with a valid body creates an item and returns it with HTTP 201
- [ ] `GET /api/items/{id}` returns the item or HTTP 404 if not found
- [ ] `DELETE /api/items/{id}` removes the item and returns HTTP 204 or 404
- [ ] Items survive a `docker compose restart backend` (data is in Postgres, not in-memory)
- [ ] The React app renders the items list fetched from the backend
- [ ] The React app's create-item form posts to the backend and refreshes the list
- [ ] All backend unit tests pass: `./scripts/run.sh pytest tests/unit/`
- [ ] All backend integration tests pass: `./scripts/run.sh pytest tests/integration/`
- [ ] All frontend tests pass: `./scripts/run.sh npm --prefix frontend run test`
- [ ] `ruff check src/` passes with zero errors
- [ ] `pyright src/` passes with zero errors
- [ ] `alembic upgrade head` runs cleanly against the `postgres` service

---

## Design

### Directory Layout (after implementation)

```
fuzzy-umbrella/
├── src/
│   └── api/
│       ├── __init__.py
│       ├── main.py            ← FastAPI app factory + middleware (no create_all)
│       ├── routers/
│       │   ├── __init__.py
│       │   ├── health.py      ← /health endpoint
│       │   └── items.py       ← /api/items CRUD endpoints
│       ├── models.py          ← Pydantic request/response schemas
│       ├── db_models.py       ← SQLAlchemy ORM table definitions
│       └── database.py        ← engine, session factory, get_db dependency
├── alembic/
│   ├── env.py                 ← custom wiring; prefers ini sqlalchemy.url, falls back to DATABASE_URL env var
│   ├── script.py.mako
│   └── versions/
│       └── 0001_create_items_table.py
├── alembic.ini
├── tests/
│   ├── unit/
│   │   ├── conftest.py        ← SQLite async engine + per-test session fixture
│   │   ├── test_health.py
│   │   └── test_items.py
│   └── integration/
│       ├── conftest.py        ← real Postgres URL from env; session-scoped event loop; session fixture
│       └── test_items_pg.py   ← full CRUD round-trip against Postgres
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts         ← proxy /api → http://backend:8000 (dev only)
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── components/
│       │   ├── ItemList.tsx
│       │   └── CreateItemForm.tsx
│       └── api/
│           └── items.ts       ← fetch wrappers using VITE_API_BASE_URL prefix
├── .env.example               ← committed bootstrap template (no secrets)
├── Dockerfile.backend
├── Dockerfile.frontend
├── docker-compose.yml
├── pyproject.toml
├── CLAUDE.md                  ← updated: backend service name, alembic step, PYTHONPATH change
└── scripts/
    └── run.sh                 ← updated: targets `backend` service
```

### New Files

| File | Responsibility |
|---|---|
| `src/api/main.py` | Creates the FastAPI `app`, registers routers, configures CORS. Does NOT call `create_all`. Requires `alembic upgrade head` to be run before starting the server. |
| `src/api/routers/health.py` | `GET /health` |
| `src/api/routers/items.py` | CRUD routes; receives `AsyncSession` via `Depends(get_db)` |
| `src/api/models.py` | `ItemCreate`, `ItemResponse` Pydantic v2 models |
| `src/api/db_models.py` | SQLAlchemy `Item` ORM model (mapped to `items` table) |
| `src/api/database.py` | `async_engine`, `AsyncSessionLocal`, `get_db` async generator |
| `alembic/` | Alembic scaffold + initial migration creating `items` table |
| `alembic.ini` | Alembic config; `script_location = alembic`; `sqlalchemy.url` left blank (overridden by `env.py` at runtime) |
| `tests/unit/conftest.py` | In-memory SQLite async engine; overrides `get_db` dependency per test |
| `tests/integration/conftest.py` | Reads `TEST_DATABASE_URL` from env; session-scoped event loop fixture; runs `alembic upgrade head` / `downgrade base` |
| `frontend/vite.config.ts` | Vite config + `/api` proxy (applies to `vite dev` only; not active in `vite preview`) |
| `frontend/src/App.tsx` | Root component |
| `frontend/src/components/ItemList.tsx` | Fetches + renders items |
| `frontend/src/components/CreateItemForm.tsx` | Controlled form for item creation |
| `frontend/src/api/items.ts` | `fetchItems()`, `createItem(body)`, `deleteItem(id)` — all calls prefixed with `import.meta.env.VITE_API_BASE_URL` |
| `Dockerfile.backend` | Python 3.12 slim; installs both runtime and dev dependencies (pytest, ruff, pyright, aiosqlite, pytest-asyncio, httpx) so `./scripts/run.sh pytest` works |
| `Dockerfile.frontend` | Node 20 alpine; `npm run build` then `CMD ["npx", "vite", "preview", "--host", "0.0.0.0", "--port", "5173"]` |
| `frontend/src/__tests__/App.test.tsx` | React component smoke tests |
| `.env.example` | Committed template listing every required variable with placeholder values (see Environment Variables section) |

### Modified Files

| File | What changes |
|---|---|
| `docker-compose.yml` | Add `backend`, `frontend`, and `postgres` services; remove legacy `app` service. **PYTHONPATH changes from `/workspace/src` to `/workspace`** so that `alembic/env.py` and integration tests can use `from src.api.db_models import Base` import paths. The existing value was `/workspace/src` (making `import api` work); the new value `/workspace` makes `import src.api` work, which is required by Alembic's env.py and the test suite. |
| `Dockerfile` | Renamed to `Dockerfile.backend` |
| `pyproject.toml` | Add runtime and dev Python dependencies; add `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` |
| `scripts/run.sh` | Change `COMPOSE_SERVICE` (or equivalent target) from `app` to `backend` |
| `CLAUDE.md` | Update `docker compose up -d --build app` to `docker compose up -d --build backend`; add one-time setup step: run `./scripts/run.sh alembic upgrade head` before starting the server for the first time; **note that PYTHONPATH changes from `/workspace/src` to `/workspace`** for the backend service |

---

## Data Structures

### Pydantic Models (`src/api/models.py`)

```
ItemCreate
  name: str               (1–200 chars)
  description: str | None (0–2000 chars, default None — nullable)

ItemResponse
  model_config = ConfigDict(from_attributes=True)
  # Required so FastAPI can serialize SQLAlchemy ORM objects directly.
  # Without this, calling ItemResponse.model_validate(orm_obj) raises
  # ValidationError at runtime because Pydantic cannot read ORM attributes.

  id: str                 (UUID4 string, e.g. "550e8400-e29b-41d4-a716-446655440000")
  name: str
  description: str | None (nullable; None when not provided at creation)
  created_at: str         (ISO-8601 datetime string)
```

### SQLAlchemy ORM Model (`src/api/db_models.py`)

```
class Item(Base):
  __tablename__ = "items"

  id:           Mapped[str]            String(36), primary key
                                       Python-side: default=lambda: str(uuid.uuid4())
                                       (NOT a server_default — UUID generated in Python
                                        so SQLite unit tests work without a UUID extension)
                                       Migration server_default: sa.text("gen_random_uuid()")
                                       (Postgres-native; applied in the Alembic migration only,
                                        not on the ORM Column, so that SQLite tests still work)
  name:         Mapped[str]            VARCHAR(200), not null
                                       No UNIQUE constraint — duplicate names are allowed
  description:  Mapped[str | None]     TEXT, nullable (no server_default — column accepts NULL)
                                       ORM default: None (Python side)
  created_at:   Mapped[datetime]       server_default=func.now(), not null
                                       Migration server_default: sa.func.now()
```

UUID column type: `String(36)` in SQLAlchemy mapped column definition. The Alembic migration emits `VARCHAR(36)` for Postgres, which is compatible. SQLite also stores it as TEXT, enabling in-memory unit tests without any native UUID type.

### Alembic Migration Column Defaults (`alembic/versions/0001_create_items_table.py`)

The migration file must specify the following server defaults so Postgres generates values without requiring the application to supply them:

| Column | ORM Python default | Migration `server_default` | Rationale |
|---|---|---|---|
| `id` | `default=lambda: str(uuid.uuid4())` | `server_default=sa.text("gen_random_uuid()")` | Postgres-native UUID generation. The Python default is kept on the ORM so SQLite unit tests (which lack `gen_random_uuid()`) still generate IDs without a server round-trip. |
| `created_at` | — | `server_default=sa.func.now()` | Postgres fills the timestamp automatically. Matches the ORM `server_default=func.now()`. |
| `description` | `None` (Python) | No `server_default` — column is `nullable=True` | Nullable column; no default value is stored in the schema. The application passes `None` when the field is not provided. |

The migration `op.create_table` call should look like:

```python
op.create_table(
    "items",
    sa.Column("id",          sa.String(36),  primary_key=True,
              server_default=sa.text("gen_random_uuid()")),
    sa.Column("name",        sa.String(200), nullable=False),
    sa.Column("description", sa.Text(),      nullable=True),
    sa.Column("created_at",  sa.DateTime(),  nullable=False,
              server_default=sa.func.now()),
)
```

### Database Layer (`src/api/database.py`)

```
DATABASE_URL: str   read from os.environ["DATABASE_URL"]; raises RuntimeError at
                    import time with a clear message if the variable is missing

async_engine        = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal   = async_sessionmaker(async_engine, expire_on_commit=False)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a per-request async session."""
```

---

## Alembic `env.py` Wiring

The default `alembic/env.py` reads `sqlalchemy.url` from `alembic.ini`. This project leaves that field blank. The URL is resolved with the following precedence:

1. **`config.get_main_option("sqlalchemy.url")`** — non-blank value wins. This allows the integration test conftest to call `cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)` before invoking `command.upgrade`, so migrations target `appdb_test` and not the production database.
2. **`os.environ["DATABASE_URL"]`** — fallback used by CLI invocations (`alembic upgrade head` in the terminal) where `alembic.ini`'s `sqlalchemy.url` is blank.

The implementer must write `alembic/env.py` as follows (pseudocode — exact imports may vary):

```python
import os
import asyncio
from logging.config import fileConfig
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context

config = context.config

# Load the Alembic logging config from alembic.ini
if config.config_file_name:
    fileConfig(config.config_file_name)

# Import your ORM Base so Alembic can see all mapped tables
from src.api.db_models import Base  # noqa: E402
target_metadata = Base.metadata

# URL precedence: ini option first (allows programmatic override from conftest),
# then environment variable (used by CLI invocations where ini value is blank).
DATABASE_URL = config.get_main_option("sqlalchemy.url") or os.environ["DATABASE_URL"]


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no live DB connection)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async engine."""
    connectable = create_async_engine(DATABASE_URL)
    async with connectable.connect() as connection:
        await connection.run_sync(
            lambda sync_conn: context.configure(
                connection=sync_conn,
                target_metadata=target_metadata,
            )
        )
        await connection.run_sync(
            lambda sync_conn: context.run_migrations()
        )
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

Key points:
- `config.get_main_option("sqlalchemy.url") or os.environ["DATABASE_URL"]` — the ini value (which may be set programmatically by the conftest) takes priority; falls back to the environment variable for CLI use.
- This prevents the integration conftest's `cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)` call from being silently ignored, which would cause migrations to run against the production `appdb` database.
- The async engine is created inside `env.py`, not imported from `database.py`, to keep the migration runner decoupled from the application's session pool.
- `asyncio.run(run_migrations_online())` is correct when Alembic is invoked from the CLI (`alembic upgrade head` in a terminal), where no event loop is running. However, **when the integration test conftest calls `command.upgrade(cfg, "head")` from inside an async pytest fixture, an event loop is already active — calling `asyncio.run()` at that point raises `RuntimeError: This event loop is already running`.** The integration conftest pseudocode below resolves this by running `command.upgrade` in a `ThreadPoolExecutor` thread (where no event loop is active), so `asyncio.run()` in `env.py` is safe in all contexts.

---

## Environment Variables

| Variable | Required | Example value | Notes |
|---|---|---|---|
| `DATABASE_URL` | Yes | `postgresql+asyncpg://app:secret@postgres:5432/appdb` | Used by app and Alembic CLI |
| `POSTGRES_USER` | Yes (compose) | `app` | Passed to the `postgres` service |
| `POSTGRES_PASSWORD` | Yes (compose) | `secret` | Passed to the `postgres` service |
| `POSTGRES_DB` | Yes (compose) | `appdb` | Passed to the `postgres` service |
| `TEST_DATABASE_URL` | Integration tests only | `postgresql+asyncpg://app:secret@localhost:5432/appdb_test` | Used by `tests/integration/conftest.py` |
| `VITE_API_BASE_URL` | Frontend build | `http://localhost:8000` (container); `` (empty, for local dev with Vite proxy) | Baked into the JS bundle at `npm run build` time. Empty string causes `items.ts` to use relative `/api/...` paths (correct when Vite proxy is active). Set to `http://localhost:8000` in the frontend docker-compose service env block so the built bundle reaches the backend. |

### `.env.example` (exact contents to commit)

```dotenv
# Copy this file to .env and fill in real values.
# .env is gitignored; .env.example is committed.

DATABASE_URL=postgresql+asyncpg://app:secret@postgres:5432/appdb
POSTGRES_USER=app
POSTGRES_PASSWORD=secret
POSTGRES_DB=appdb
TEST_DATABASE_URL=postgresql+asyncpg://app:secret@localhost:5432/appdb_test
VITE_API_BASE_URL=http://localhost:8000
```

All variables should be set in a `.env` file at the repo root (already in `.gitignore`). `.env.example` is committed and contains only placeholder values — no real secrets.

---

## Frontend API Base URL

`frontend/src/api/items.ts` must prefix every fetch call with `import.meta.env.VITE_API_BASE_URL`. Vite bakes this value into the bundle at build time.

```typescript
// frontend/src/api/items.ts
const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function fetchItems(): Promise<ItemResponse[]> {
    const res = await fetch(`${BASE}/api/items`);
    // ...
}
async function createItem(body: ItemCreate): Promise<ItemResponse> {
    const res = await fetch(`${BASE}/api/items`, { method: "POST", ... });
    // ...
}
async function deleteItem(id: string): Promise<void> {
    await fetch(`${BASE}/api/items/${id}`, { method: "DELETE" });
}
```

Behavior by context:

| Context | `VITE_API_BASE_URL` value | Effective URL |
|---|---|---|
| `npm run dev` (host, Vite proxy active) | `` (empty / unset) | `/api/items` — proxied by Vite to `http://backend:8000` |
| `vite preview` (Docker container) | `http://localhost:8000` | `http://localhost:8000/api/items` — direct call to backend |

The `frontend` docker-compose service must include `VITE_API_BASE_URL=http://localhost:8000` in its `environment` block (or source it from `.env`) so it is available at build time inside the container.

---

## Integration Test Database Provisioning

`TEST_DATABASE_URL` points to a **separate** database named `appdb_test` on the same Postgres instance. This database is NOT created automatically by the `postgres` service (which only creates `POSTGRES_DB`).

The integration test `conftest.py` must:

1. Provide a **session-scoped `event_loop` fixture** so that the async session-scoped `setup_test_db` fixture can access the event loop without a `ScopeMismatch` error (required by `pytest-asyncio>=0.23`).
2. Create `appdb_test` programmatically before running any migrations.
3. Call `command.upgrade(cfg, "head")` after `cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)` — this override is read by `env.py` (see Alembic env.py Wiring above) so migrations target `appdb_test`, not the production `appdb`.

```python
# tests/integration/conftest.py  (pseudocode)
import asyncio
import os

import asyncpg
import pytest
from alembic import command
from alembic.config import Config

TEST_DATABASE_URL = os.environ["TEST_DATABASE_URL"]
# Derive a plain DSN for asyncpg (strip the SQLAlchemy driver prefix)
PG_DSN = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


# Required: session-scoped event loop so that async session-scoped fixtures
# do not raise ScopeMismatch with pytest-asyncio >= 0.23.
@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop for all integration tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_test_db():
    # Connect to the maintenance 'postgres' database to create appdb_test
    conn = await asyncpg.connect(
        dsn=PG_DSN.rsplit("/", 1)[0] + "/postgres"
    )
    try:
        await conn.execute(
            "CREATE DATABASE appdb_test"
            " TEMPLATE template0"
            " ENCODING 'UTF8'"
            " LC_COLLATE 'en_US.UTF-8'"
            " LC_CTYPE 'en_US.UTF-8'"
        )
    except asyncpg.DuplicateDatabaseError:
        pass  # Already exists from a prior aborted run; proceed
    finally:
        await conn.close()

    # Run migrations against appdb_test.
    # cfg.set_main_option overrides sqlalchemy.url, which env.py reads first
    # (before falling back to os.environ["DATABASE_URL"]), ensuring migrations
    # do NOT run against the production appdb.
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)

    # IMPORTANT: command.upgrade/downgrade must NOT be called directly from this
    # async fixture. env.py ends with asyncio.run(run_migrations_online()), which
    # raises RuntimeError("This event loop is already running") when an event loop
    # is active (as it is inside every async pytest fixture). Fix: run the blocking
    # Alembic command in a ThreadPoolExecutor thread, where no event loop is active,
    # so asyncio.run() in env.py succeeds normally.
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: command.upgrade(cfg, "head"))

    yield

    # Teardown: roll back migrations, then drop database
    await loop.run_in_executor(None, lambda: command.downgrade(cfg, "base"))
    conn = await asyncpg.connect(
        dsn=PG_DSN.rsplit("/", 1)[0] + "/postgres"
    )
    await conn.execute("DROP DATABASE IF EXISTS appdb_test")
    await conn.close()
```

Notes:
- The session-scoped `event_loop` fixture is the standard workaround for pytest-asyncio >= 0.23 when session-scoped async fixtures are needed. Pin `pytest-asyncio>=0.23.7` (which introduced `loop_scope` as an alternative) in dev dependencies.
- `asyncpg.DuplicateDatabaseError` is caught and ignored if `appdb_test` already exists from a prior aborted run.
- Running integration tests locally requires either the compose `postgres` service to be running (`docker compose up -d postgres`) or a local Postgres instance with credentials matching `TEST_DATABASE_URL`.

---

## API Contract

### `GET /health`
- Response 200: `{"status": "ok"}`

### `GET /api/items`
- Response 200: `ItemResponse[]`

### `POST /api/items`
- Request body: `ItemCreate` (JSON)
- Response 201: `ItemResponse`
- Response 422: Pydantic validation error (missing `name`, `name` too long, etc.)
- Note: `name` is NOT unique — duplicate names are allowed; no 409 is returned.

### `GET /api/items/{id}`
- Response 200: `ItemResponse`
- Response 404: `{"detail": "Item not found"}`

### `DELETE /api/items/{id}`
- Response 204: (no body)
- Response 404: `{"detail": "Item not found"}`

---

## CORS & Proxy Configuration

### Backend CORS (FastAPI middleware)
Allow origins: `http://localhost:5173` only. The internal Docker hostname `http://frontend:5173` is NOT needed — the browser always connects via the host-mapped port, not via Docker's internal network. Including unnecessary origins increases attack surface.

### Frontend Vite Proxy (`vite.config.ts`)
```
server.proxy["/api"] -> target: "http://backend:8000", changeOrigin: true
```
This proxy is active only when running `npm run dev` (Vite dev server). It is NOT active in `vite preview`. In the Docker container, the frontend is served via `vite preview` and the browser makes API calls to `${VITE_API_BASE_URL}/api/...` which resolves to `http://localhost:8000/api/...`. For local development outside Docker, `npm run dev` uses the Vite proxy (VITE_API_BASE_URL is empty / unset, so paths are relative and proxied).

---

## Docker Compose Services

### `postgres` service
- Image: `postgres:16-alpine`
- Environment: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` (sourced from `.env`)
- Port mapping: `5432:5432` (host-exposed for local tooling and integration tests)
- Volume: `postgres_data:/var/lib/postgresql/data` (named volume for persistence)
- Healthcheck: `pg_isready -U ${POSTGRES_USER}`

### `backend` service
- Build context: `.`, dockerfile: `Dockerfile.backend`
- Port mapping: `8000:8000`
- Command: `uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload`
- Volume: `.:/workspace`
- Environment: `PYTHONPATH=/workspace` (changed from `/workspace/src`; required so `alembic/env.py` and the test suite can use `from src.api.db_models import Base`), `DATABASE_URL` (sourced from `.env`)
- Depends on: `postgres` (with `service_healthy` condition)
- Note: The `backend` container also serves as the test/lint runner. `Dockerfile.backend` installs all dev dependencies so `./scripts/run.sh pytest tests/unit/` executes via `docker compose exec backend pytest tests/unit/`.

### `frontend` service
- Build context: `./frontend`, dockerfile: `../Dockerfile.frontend`
- Port mapping: `5173:5173`
- Build args (docker-compose `build.args` block): `VITE_API_BASE_URL: http://localhost:8000`
  - Vite bakes `VITE_*` variables at `npm run build` time (inside `RUN npm run build` in `Dockerfile.frontend`). Docker-compose `environment` is runtime-only and is NOT visible during the build layer. The value must be passed as a build argument so the `Dockerfile.frontend` can expose it as an `ENV` before the build step runs (see `Dockerfile.frontend` spec below).
  - docker-compose frontend service example snippet:
    ```yaml
    build:
      context: ./frontend
      dockerfile: ../Dockerfile.frontend
      args:
        VITE_API_BASE_URL: http://localhost:8000
    environment:
      - VITE_API_BASE_URL=http://localhost:8000
    ```
- Environment: `VITE_API_BASE_URL=http://localhost:8000` — also set at runtime for any tooling that reads it after container start (not used by the static bundle itself)
- Command: `vite preview --host 0.0.0.0 --port 5173` (production build; no HMR, no proxy)
- Depends on: `backend`
- Note: `npm run dev` is for **local development outside Docker only**. Inside the container, `vite preview` always serves the pre-built static files. Developers who want HMR run `npm run dev` on their host machine directly, not via compose.

### `Dockerfile.frontend` required build-arg pattern

`Dockerfile.frontend` must declare and propagate `VITE_API_BASE_URL` as both an `ARG` and `ENV` **before** the `RUN npm run build` step, so Vite can read it during the build:

```dockerfile
# ... (FROM, WORKDIR, COPY, npm ci) ...

ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build

CMD ["npx", "vite", "preview", "--host", "0.0.0.0", "--port", "5173"]
```

Without `ARG`/`ENV` before `RUN npm run build`, `import.meta.env.VITE_API_BASE_URL` is `undefined` in the production bundle, and all API calls fail with relative paths like `/api/items` that `vite preview` does not proxy.

The legacy `app` (sleep-infinity) service is removed.

---

## One-Time Setup Steps

After cloning the repo and before running `docker compose up`:

1. Copy `.env.example` to `.env` and fill in real values (or keep the placeholders for local dev).
2. `docker compose up -d postgres` — start only the Postgres service and wait for it to pass its healthcheck.
3. `docker compose run --rm backend alembic upgrade head` — creates the `items` table. **Must complete before the backend starts handling any requests.** (Since `main.py` does not call `create_all`, any request before migration crashes with "relation does not exist".)
4. `docker compose up -d backend` — start the backend (Postgres is already healthy; no race condition).
5. `docker compose up -d frontend` — start the frontend service.
6. For integration tests: ensure `TEST_DATABASE_URL` is set; `appdb_test` does not need to exist ahead of time — the conftest creates and destroys it automatically.

---

## Frontend `package.json` Scripts

The `scripts` block in `frontend/package.json` must define the following commands exactly:

```json
{
  "scripts": {
    "dev":     "vite --host 0.0.0.0",
    "build":   "vite build",
    "preview": "vite preview --host 0.0.0.0 --port 5173",
    "test":    "vitest run"
  }
}
```

| Script | Resolved command | When used |
|---|---|---|
| `npm run dev` | `vite --host 0.0.0.0` | Local development outside Docker; enables HMR and the `/api` proxy |
| `npm run build` | `vite build` | Called by `Dockerfile.frontend` to produce the static bundle |
| `npm run preview` | `vite preview --host 0.0.0.0 --port 5173` | Container entry point; serves the built bundle |
| `npm run test` | `vitest run` | Single-pass test run for CI and `./scripts/run.sh npm --prefix frontend run test` |

`vitest run` (not `vitest`) is required for single-pass CI execution; `vitest` alone runs in watch mode and never exits.

---

## Key Functions / Interfaces

```python
# src/api/main.py
def create_app() -> FastAPI:
    """Construct and return the configured FastAPI application instance.
    Does not call Base.metadata.create_all. Schema must exist via alembic upgrade head."""

# src/api/database.py
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a per-request async SQLAlchemy session."""

# src/api/routers/items.py  (signatures; session injected via Depends)
async def list_items(db: AsyncSession = Depends(get_db)) -> list[ItemResponse]: ...
async def get_item(item_id: str, db: AsyncSession = Depends(get_db)) -> ItemResponse: ...
async def create_item(body: ItemCreate, db: AsyncSession = Depends(get_db)) -> ItemResponse: ...
async def delete_item(item_id: str, db: AsyncSession = Depends(get_db)) -> Response: ...
```

```typescript
// frontend/src/api/items.ts
const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function fetchItems(): Promise<ItemResponse[]>
async function createItem(body: ItemCreate): Promise<ItemResponse>
async function deleteItem(id: string): Promise<void>
// All paths constructed as `${BASE}/api/...`
```

---

## Edge Cases & Error Handling

| Case | Handling |
|---|---|
| `POST /api/items` with missing `name` | FastAPI returns 422 automatically via Pydantic |
| `POST /api/items` with duplicate `name` | Allowed — names are NOT unique; creates a second item normally |
| `GET /api/items/{id}` with unknown UUID | Router raises `HTTPException(404)` |
| `DELETE /api/items/{id}` with unknown UUID | Router raises `HTTPException(404)` |
| Frontend fetch fails (network / 5xx) | Component shows an inline error message; does not crash |
| `name` exceeds 200 chars | Pydantic `max_length` validator rejects at 422 |
| Postgres not yet ready at backend startup | `depends_on: postgres: condition: service_healthy` ensures Postgres is ready before backend starts |
| `DATABASE_URL` missing from env | `database.py` raises `RuntimeError` at import time with a clear message |
| Alembic migration not yet run | Backend will fail on first DB query with a "relation does not exist" error; the setup steps make clear that `alembic upgrade head` is required before starting. `create_all` is NOT called in `main.py`. |
| `appdb_test` already exists from prior aborted integration test run | Integration conftest catches `asyncpg.DuplicateDatabaseError` and proceeds without recreating the database |
| Session-scoped async fixture with `asyncio_mode = "auto"` | Integration conftest provides an explicit session-scoped `event_loop` fixture to prevent `ScopeMismatch` from pytest-asyncio >= 0.23 |
| `vite preview` making relative `/api/...` calls (no proxy) | `VITE_API_BASE_URL` is set in the frontend docker-compose service env block; `items.ts` prefixes all calls with this variable, producing absolute URLs that reach the backend |

---

## Test Plan

### Backend Unit Tests (`tests/unit/`)

Strategy: override the `get_db` FastAPI dependency with a fixture that provides an async SQLite session (`:memory:`). No Postgres required. SQLAlchemy creates the schema in the in-memory database at fixture setup (using `Base.metadata.create_all`), and rolls back / drops tables after each test function to ensure isolation.

- `conftest.py`
  - `async_sqlite_engine` fixture: creates an in-memory SQLite engine with `aiosqlite`
  - `db_session` fixture: creates tables via `Base.metadata.create_all`, yields a session, rolls back / drops tables after test
  - `client` fixture: creates `httpx.AsyncClient` with `app.dependency_overrides[get_db]` pointing to the SQLite session

- `test_health.py`
  - `GET /health` returns 200 and `{"status": "ok"}`

- `test_items.py`
  - `GET /api/items` on empty DB returns `[]`
  - `POST /api/items` with valid body returns 201 and a persisted item (id is a valid UUID4 string)
  - `POST /api/items` with missing `name` returns 422
  - `POST /api/items` twice with the same `name` returns 201 both times (no uniqueness constraint)
  - `GET /api/items/{id}` for existing item returns 200
  - `GET /api/items/{id}` for unknown id returns 404
  - `DELETE /api/items/{id}` for existing item returns 204
  - `DELETE /api/items/{id}` for unknown id returns 404
  - Full CRUD round-trip: create → list → get → delete → list

### Backend Integration Tests (`tests/integration/`)

Strategy: use a real Postgres instance (`appdb_test` database on the compose `postgres` service). `TEST_DATABASE_URL` must be set. The session-scoped conftest provides an explicit `event_loop` fixture, creates `appdb_test` programmatically, runs `alembic upgrade head` (targeting `appdb_test` via `cfg.set_main_option`), yields, then runs `alembic downgrade base` and drops the database.

- `test_items_pg.py`
  - Full CRUD round-trip against real Postgres
  - Verify `created_at` is a valid datetime returned by the server
  - Verify data persists across multiple requests within the same test session

### Frontend Tests (`frontend/src/__tests__/`)

- `App.test.tsx`
  - Renders without crashing (smoke test)
  - Displays "No items" when API returns empty array (mock fetch)
  - Renders item names when API returns populated array (mock fetch)
  - Submitting the create form calls `createItem` and triggers a list refresh (mock)

Tests use Vitest + `@testing-library/react`. Fetch is mocked via `vi.mock`.

---

## Dependencies

### Python (added to `pyproject.toml`)

Runtime dependencies:

| Package | Justification |
|---|---|
| `fastapi>=0.111` | Core web framework |
| `uvicorn[standard]>=0.29` | ASGI server with websocket support |
| `pydantic>=2.7` | Schema validation; FastAPI v0.111 requires Pydantic v2 |
| `sqlalchemy[asyncio]>=2.0` | Async ORM; `asyncio` extra includes `greenlet` |
| `asyncpg>=0.29` | High-performance async Postgres driver for SQLAlchemy |
| `alembic>=1.13` | Database migration management |

Dev-only dependencies (in `[tool.uv.dev-dependencies]` or `[project.optional-dependencies] dev`):

| Package | Justification |
|---|---|
| `httpx>=0.27` | Async HTTP client for tests (`httpx.AsyncClient`) |
| `pytest>=8.0` | Test runner |
| `pytest-asyncio>=0.23.7` | Async test support; 0.23.7 is the minimum for `loop_scope` fixture parameter (used by the session-scoped event loop pattern) |
| `aiosqlite>=0.20` | SQLite async driver for unit test isolation — dev only, not needed at runtime |
| `ruff>=0.4` | Linter |
| `pyright>=1.1` | Type checker |

`pyproject.toml` must include:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

This makes every async test function run automatically without requiring `@pytest.mark.asyncio` on each one. Without this, `pytest-asyncio>=0.23` in strict mode silently skips or errors on async tests.

### Node (added to `frontend/package.json`)

All packages must be pinned to the listed major version in `package.json`.

| Package | Version | Justification |
|---|---|---|
| `react` | `^18.0.0` | UI framework (v18 required for concurrent features; v19 has breaking test renderer changes) |
| `react-dom` | `^18.0.0` | DOM renderer; must match `react` major |
| `typescript` | `^5.0.0` | Type safety |
| `vite` | `^5.0.0` | Dev server + bundler |
| `@vitejs/plugin-react` | `^4.0.0` | React fast refresh |
| `vitest` | `^2.0.0` | Unit test runner (v2 config API differs from v1) |
| `@testing-library/react` | `^16.0.0` | Component test utilities (v16 requires React 18+) |
| `@testing-library/jest-dom` | `^6.0.0` | Custom matchers |
| `@types/react` | `^18.0.0` | TypeScript type declarations |
| `@types/react-dom` | `^18.0.0` | TypeScript type declarations |

---

## Open Questions

None. All issues from the plan-reviewer (including all prior and new critical/important gaps) have been resolved in this revision:

1. Session-scoped async fixture event loop mismatch — resolved: explicit session-scoped `event_loop` fixture added to integration conftest pseudocode; `pytest-asyncio>=0.23.7` pinned in dev dependencies.
2. env.py / conftest URL precedence bug — resolved: `env.py` now reads `config.get_main_option("sqlalchemy.url") or os.environ["DATABASE_URL"]`; conftest continues to call `cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)` and this value is now actually honored, preventing silent migration against the production DB.
3. Frontend API base URL undefined for `vite preview` — resolved: `VITE_API_BASE_URL` added to environment variables table, `.env.example`, and frontend docker-compose service env block; `items.ts` prefixes all calls with `import.meta.env.VITE_API_BASE_URL`.
4. Setup order: backend starts before schema exists — resolved: one-time setup steps now bring up postgres first, run migrations via `docker compose run --rm backend alembic upgrade head`, then start backend, then frontend.
5. PYTHONPATH inconsistency — resolved: docker-compose.yml and CLAUDE.md Modified Files entries explicitly note the change from `/workspace/src` to `/workspace` and explain why.
6. Frontend `package.json` scripts not specified — resolved: `scripts` block fully specified (`dev`, `build`, `preview`, `test`) with exact commands and rationale.
7. `asyncio.run()` inside a running event loop (new) — resolved: integration conftest now wraps `command.upgrade(cfg, "head")` and `command.downgrade(cfg, "base")` in `await loop.run_in_executor(None, lambda: command.upgrade(cfg, "head"))` (getting the loop first with `asyncio.get_event_loop()`). `env.py` itself is unchanged — `asyncio.run()` at the module level remains correct for the CLI path; the executor ensures the fixture calls it from a thread where no loop is active.
8. `VITE_API_BASE_URL` not available at Docker build time (new) — resolved: `Dockerfile.frontend` now requires `ARG VITE_API_BASE_URL` / `ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}` before `RUN npm run build`. docker-compose frontend service spec includes a `build.args.VITE_API_BASE_URL` block alongside the existing `environment` block.
9. `ItemResponse` missing `model_config` (new) — resolved: `model_config = ConfigDict(from_attributes=True)` added to `ItemResponse` in the Pydantic models section with an explanation of why it is required for ORM object serialization.
10. Alembic migration column defaults unspecified (new) — resolved: new "Alembic Migration Column Defaults" subsection added specifying `id` uses `server_default=sa.text("gen_random_uuid()")`, `created_at` uses `server_default=sa.func.now()`, and `description` has no server_default (nullable). The `description` field is updated to `str | None = None` in both the ORM model and Pydantic schemas.
