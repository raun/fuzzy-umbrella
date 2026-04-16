# Feature: Sentry Integration

## Summary

Add Sentry error and performance monitoring to both the FastAPI backend and the React
frontend. The backend uses `sentry-sdk[fastapi]` (initialized before the app is created),
captures unhandled exceptions and performance traces, and filters out the `/health`
endpoint from transaction data. The frontend uses `@sentry/react`, wraps the root
component in a Sentry `ErrorBoundary`, and reports JavaScript errors with performance
tracing via `BrowserTracing`. DSNs and environment names are injected via environment
variables so no secrets are hard-coded in source.

---

## Scope

**IN**
- Backend: `sentry_sdk.init()` in `src/api/main.py`, before `create_app()` is called
- Backend: traces_sample_rate, environment tagging, `/health` transaction filter
- Backend: helper functions extracted to `src/api/sentry_utils.py` (no database import)
- Frontend: `@sentry/react` init in `frontend/src/main.tsx`
- Frontend: `Sentry.ErrorBoundary` wrapping `<App />`
- Frontend: `BrowserTracing` integration (no React Router — the app uses no router)
- Frontend: session replay excluded (not needed at this stage)
- New env vars documented in `.env.example`
- `Dockerfile.frontend`: new `ARG`/`ENV` pair for `VITE_SENTRY_DSN` and
  `VITE_SENTRY_ENVIRONMENT`, following the same pattern as `VITE_API_BASE_URL`
- `docker-compose.yml`: pass `SENTRY_DSN` and `SENTRY_ENVIRONMENT` to the `backend`
  service; add `VITE_SENTRY_DSN` and `VITE_SENTRY_ENVIRONMENT` build args to the
  `frontend` service
- Unit tests: mock `sentry_sdk.init`, verify call args and `/health` filter behaviour
- Frontend tests: `ErrorBoundary` renders fallback UI when a child throws

**OUT**
- Session replay (`@sentry/replay`) — deferred until product need is confirmed
- Custom performance instrumentation beyond the automatic FastAPI / BrowserTracing spans
- Sentry alert / notification rule configuration (done in the Sentry UI)
- Source map upload in CI (deferred; requires CI pipeline feature)
- React Router instrumentation (`reactRouterV6Instrumentation`) — the app has no router

---

## Acceptance Criteria

- [ ] Backend `sentry_sdk.init()` is called with the DSN read from `SENTRY_DSN`; when
      `SENTRY_DSN` is unset or empty the call is skipped and the app starts normally
- [ ] Backend `traces_sample_rate` defaults to `1.0` in development, configurable via
      `SENTRY_TRACES_SAMPLE_RATE` env var (float, 0–1)
- [ ] `SENTRY_ENVIRONMENT` is forwarded to Sentry as the `environment` tag
- [ ] Requests to `/health` do not appear as Sentry transactions (filtered via
      `traces_sampler`)
- [ ] When `SENTRY_TRACES_SAMPLE_RATE` is set to a non-numeric value, `_traces_sampler`
      logs a warning and returns `1.0` instead of raising
- [ ] Unhandled exceptions in API routes are captured and sent to Sentry
- [ ] Frontend `Sentry.init()` is called with DSN from `VITE_SENTRY_DSN`; when the var
      is empty the SDK is not initialized (enforced by an explicit `if (dsn)` guard)
- [ ] `Sentry.ErrorBoundary` wraps `<App />`; throwing inside `<App />` renders the
      fallback UI (not a blank page)
- [ ] `BrowserTracing` integration is registered, producing page-load transactions
- [ ] `VITE_SENTRY_ENVIRONMENT` is forwarded as the `environment` tag in the frontend SDK
- [ ] All new env vars are documented in `.env.example` with placeholder values
- [ ] `Dockerfile.frontend` builds successfully with the new ARG/ENV lines
- [ ] `docker compose up` passes `SENTRY_*` vars to backend and `VITE_SENTRY_*` build
      args to frontend without error
- [ ] New backend unit tests pass: `./scripts/run.sh pytest tests/unit/test_sentry.py`
- [ ] New frontend tests pass: `./scripts/run.sh npm --prefix frontend run test`

---

## Design

### New Files

- `src/api/sentry_utils.py` — contains `_init_sentry()` and `_traces_sampler()`; has
  **no import of `src.api.database`** so it can be imported in tests without a
  `DATABASE_URL` set
- `tests/unit/test_sentry.py` — unit tests for `sentry_sdk.init` call and health-filter
  logic; imports from `src.api.sentry_utils` directly
- `frontend/src/components/__tests__/ErrorBoundary.test.tsx` — Vitest test for the
  `ErrorBoundary` fallback

### Modified Files

- `src/api/main.py` — import `_init_sentry` from `src.api.sentry_utils`; call it at
  module level before `create_app()`
- `pyproject.toml` — add `sentry-sdk[fastapi]>=2.0,<3` to `[project.dependencies]`
- `frontend/src/main.tsx` — import and call `Sentry.init()` with explicit DSN guard;
  wrap render tree in `Sentry.ErrorBoundary`
- `frontend/package.json` — add `@sentry/react ^8.0.0` to `dependencies`
- `.env.example` — add four new vars with placeholder values
- `Dockerfile.frontend` — add two `ARG`/`ENV` pairs for Sentry vars before `npm run build`
- `docker-compose.yml` — backend `environment` block gets `SENTRY_DSN` and
  `SENTRY_ENVIRONMENT`; frontend `build.args` gets `VITE_SENTRY_DSN` and
  `VITE_SENTRY_ENVIRONMENT`

### Data Structures

No new persistent models. The only structured data is the Sentry SDK configuration
objects, which are inline dicts passed to `sentry_sdk.init()` and `Sentry.init()`.

### Key Functions / Interfaces

**`src/api/sentry_utils.py`**

```python
def _traces_sampler(sampling_context: dict) -> float:
    """Return 0 for /health transactions; otherwise use the configured rate.

    Reads SENTRY_TRACES_SAMPLE_RATE on each call. Falls back to 1.0 and logs
    a warning if the value is not a valid float.
    """
    ...

def _init_sentry() -> None:
    """Read SENTRY_DSN from env and initialize the Sentry SDK.

    No-ops when SENTRY_DSN is empty so local dev without a Sentry project works.
    Called from src.api.main at module load time, before create_app().
    """
    ...
```

`_init_sentry()` calls:

```python
sentry_sdk.init(
    dsn=dsn,                          # from SENTRY_DSN env var
    environment=os.getenv("SENTRY_ENVIRONMENT", "development"),
    traces_sampler=_traces_sampler,
    integrations=[StarletteIntegration(), FastApiIntegration()],
    send_default_pii=False,
)
```

`StarletteIntegration` and `FastApiIntegration` are imported from
`sentry_sdk.integrations.starlette` and `sentry_sdk.integrations.fastapi` respectively.
The `sentry-sdk[fastapi]` extra installs both.

**`frontend/src/main.tsx`**

```ts
const dsn = import.meta.env.VITE_SENTRY_DSN;
if (dsn) {
  Sentry.init({
    dsn,
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT ?? "development",
    integrations: [Sentry.browserTracingIntegration()],
    tracesSampleRate: 1.0,
  });
}
```

The explicit `if (dsn)` guard makes the no-DSN-no-init contract visible in source,
matching the backend's early-return pattern in `_init_sentry()`.

Render tree — `<StrictMode>` is preserved; the final nesting is:

```tsx
<Sentry.ErrorBoundary fallback={<p>An unexpected error occurred.</p>}>
  <StrictMode>
    <App />
  </StrictMode>
</Sentry.ErrorBoundary>
```

### Edge Cases & Error Handling

| Case | Handling |
|---|---|
| `SENTRY_DSN` not set in backend | `_init_sentry()` returns early; app starts normally |
| `VITE_SENTRY_DSN` not set at build time | `dsn` is falsy; `if (dsn)` guard prevents `Sentry.init()` from being called |
| `/health` polling in production | `_traces_sampler` returns `0.0` for that path, suppressing transaction noise |
| SDK init throws (bad DSN format) | Let it propagate on startup so misconfiguration is caught early |
| Child component throws in browser | `Sentry.ErrorBoundary` catches it, reports to Sentry, renders fallback `<p>` |
| `SENTRY_TRACES_SAMPLE_RATE` not a valid float | `_traces_sampler` catches `ValueError`, logs a warning, and returns `1.0` |

### `_traces_sampler` Logic

```python
def _traces_sampler(sampling_context: dict) -> float:
    asgi_scope = sampling_context.get("asgi_scope", {})
    path = asgi_scope.get("path", "")
    if path == "/health":
        return 0.0
    try:
        rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "1.0"))
    except ValueError:
        logger.warning(
            "SENTRY_TRACES_SAMPLE_RATE is not a valid float; defaulting to 1.0"
        )
        rate = 1.0
    return max(0.0, min(1.0, rate))
```

The key `asgi_scope["path"]` is set by `SentryAsgiMiddleware` in
`sentry_sdk/integrations/asgi.py` and is stable across the pinned range
`sentry-sdk[fastapi]>=2.0,<3`. The pin in `pyproject.toml` keeps this contract stable.

---

## Test Plan

### Backend Unit Tests (`tests/unit/test_sentry.py`)

**Import strategy:** `test_sentry.py` imports from `src.api.sentry_utils`, NOT from
`src.api.main`. Because `sentry_utils.py` has no import of `src.api.database`, importing
it does not trigger the `DATABASE_URL` check. No env-var pre-seeding is required for
these tests.

- **`test_sentry_init_called_with_dsn`**: patch `sentry_sdk.init`, set `SENTRY_DSN` env
  var, call `_init_sentry()`, assert `sentry_sdk.init` was called once with `dsn=<value>`
  and the correct `environment`
- **`test_sentry_init_skipped_when_no_dsn`**: unset `SENTRY_DSN`, call `_init_sentry()`,
  assert `sentry_sdk.init` was NOT called
- **`test_traces_sampler_filters_health`**: call `_traces_sampler` with a sampling context
  where `asgi_scope["path"]` is `"/health"`; assert return value is `0.0`
- **`test_traces_sampler_passes_other_paths`**: call `_traces_sampler` with path
  `"/api/items"`; assert return value equals the configured sample rate
- **`test_traces_sampler_invalid_rate_falls_back`**: set `SENTRY_TRACES_SAMPLE_RATE` to
  `"not-a-float"`, call `_traces_sampler` with a non-health path, assert return value is
  `1.0` and that a warning was logged

### Frontend Tests (`frontend/src/components/__tests__/ErrorBoundary.test.tsx`)

**Mock strategy:** Mock the entire `@sentry/react` module at the top of the test file:

```ts
vi.mock('@sentry/react', () => ({
  init: vi.fn(),
  ErrorBoundary: ({ children, fallback }: { children: React.ReactNode; fallback: React.ReactNode }) =>
    // simplified passthrough that renders fallback on thrown error via React test utils
    ...
}));
```

This neutralises `Sentry.init()` entirely (no network calls, no DSN requirement) and
keeps the test hermetic regardless of `VITE_SENTRY_DSN`. Do not rely on an empty DSN env
var as the sole guard — mock the module explicitly.

- **`renders fallback when child throws`**: render a component that throws synchronously
  inside `Sentry.ErrorBoundary`; assert the fallback text is visible and no uncaught error
  escapes

Use Vitest + Testing Library, same pattern as existing component tests.

---

## Dependencies

### Backend

| Package | Justification |
|---|---|
| `sentry-sdk[fastapi]>=2.0,<3` | Installs the core SDK plus `StarletteIntegration` and `FastApiIntegration` extras for ASGI/FastAPI automatic instrumentation. Upper bound `<3` pins the `asgi_scope["path"]` key contract documented in sentry-sdk 2.x source (`sentry_sdk/integrations/asgi.py`). |

Add to `[project.dependencies]` in `pyproject.toml`.

### Frontend

| Package | Justification |
|---|---|
| `@sentry/react ^8.0.0` | Official Sentry SDK for React. v8 is required — v7 uses the deprecated `BrowserTracing` class; v8 renames it to `browserTracingIntegration()` which is the API used throughout this brief. Bundles `ErrorBoundary` and React component tracing; no separate `@sentry/browser` needed. |

Add to `dependencies` (not `devDependencies`) in `frontend/package.json`; the SDK is
part of the production bundle.

---

## Configuration Reference

### New env vars

| Variable | Where used | Example value |
|---|---|---|
| `SENTRY_DSN` | Backend runtime | `https://abc123@o0.ingest.sentry.io/0` |
| `SENTRY_ENVIRONMENT` | Backend runtime | `development` / `staging` / `production` |
| `SENTRY_TRACES_SAMPLE_RATE` | Backend runtime (optional) | `1.0` |
| `VITE_SENTRY_DSN` | Frontend build-time | `https://xyz789@o0.ingest.sentry.io/1` |
| `VITE_SENTRY_ENVIRONMENT` | Frontend build-time | `development` |

All five must be added to `.env.example` with placeholder values and a comment noting
that empty values disable Sentry.

### `.env.example` additions

```dotenv
# Sentry — leave blank to disable error reporting
SENTRY_DSN=
SENTRY_ENVIRONMENT=development
SENTRY_TRACES_SAMPLE_RATE=1.0
VITE_SENTRY_DSN=
VITE_SENTRY_ENVIRONMENT=development
```

### `Dockerfile.frontend` additions

Insert after the existing `ARG VITE_API_BASE_URL` / `ENV VITE_API_BASE_URL` block:

```dockerfile
ARG VITE_SENTRY_DSN
ENV VITE_SENTRY_DSN=${VITE_SENTRY_DSN}

ARG VITE_SENTRY_ENVIRONMENT
ENV VITE_SENTRY_ENVIRONMENT=${VITE_SENTRY_ENVIRONMENT}
```

### `docker-compose.yml` additions

Backend `environment` block:

```yaml
- SENTRY_DSN=${SENTRY_DSN}
- SENTRY_ENVIRONMENT=${SENTRY_ENVIRONMENT}
```

Frontend `build.args` block:

```yaml
VITE_SENTRY_DSN: ${VITE_SENTRY_DSN}
VITE_SENTRY_ENVIRONMENT: ${VITE_SENTRY_ENVIRONMENT}
```

**Note on `VITE_SENTRY_*` placement:** These vars appear only in `build.args`, not in the
runtime `environment` block. This is intentional: Vite bakes `import.meta.env.*` values
into the static bundle at build time. Adding them to the runtime `environment` block would
have no effect on the already-compiled bundle. This differs from `VITE_API_BASE_URL`, which
also appears in the runtime `environment` block for `vite preview` compatibility; that
pattern is inconsistent with how Vite actually works for production images and should not
be replicated here.

---

## Open Questions

1. **Traces sample rate in production** — `1.0` is fine for low-traffic dev but will
   generate cost at scale. The `SENTRY_TRACES_SAMPLE_RATE` env var lets ops tune this
   without a code change; agree on a sensible production default (e.g. `0.2`) before
   go-live.
2. **PII policy** — `send_default_pii=False` is set on the backend. If request headers
   or user-identifying fields are needed in Sentry traces later, this will need an
   explicit opt-in decision.
3. **Session replay** — excluded from this brief. If the product team wants replay, add
   `@sentry/replay` and `replaySampleRate` in a follow-up.
4. **Source maps** — the frontend build produces minified JS. Without source map upload
   to Sentry, stack traces in the dashboard will be minified. A CI job to run
   `sentry-cli sourcemaps upload` should be added once a CI pipeline exists.
