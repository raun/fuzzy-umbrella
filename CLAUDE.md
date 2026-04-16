# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

**fuzzy-umbrella** is a multi-agent Claude Code orchestration framework. It is not an application — it is infrastructure for running specialized agents through a gated feature-development pipeline (plan → review → implement → test → review → done). Application code lives in `src/` and `tests/`, which are populated by the agents.

## Commands

All code execution must happen inside the Docker container. The container guard hook will block bare Python/pytest/ruff commands on the host.

```bash
# Start the postgres service first (required before backend)
docker compose up -d postgres

# Run alembic migrations (required before first backend start)
docker compose run --rm backend alembic upgrade head

# Start the backend service
docker compose up -d backend

# Start the frontend service
docker compose up -d frontend

# Or start all services at once (after initial migration)
docker compose up -d --build backend

# Run commands inside the container
./scripts/run.sh pytest tests/unit/
./scripts/run.sh pytest tests/unit/test_foo.py::test_bar   # single test
./scripts/run.sh ruff check src/
./scripts/run.sh pyright src/
./scripts/run.sh python -m fuzzy_umbrella.<module>
```

## One-Time Setup Steps

After cloning the repo and before running `docker compose up`:

1. Copy `.env.example` to `.env` and fill in real values (or keep placeholders for local dev).
2. `docker compose up -d postgres` — start only the Postgres service and wait for it to pass its healthcheck.
3. `docker compose run --rm backend alembic upgrade head` — creates the `items` table. **Must complete before the backend starts handling any requests.**
4. `docker compose up -d backend` — start the backend (Postgres is already healthy; no race condition).
5. `docker compose up -d frontend` — start the frontend service.

**Check / reset agent budget:**
```bash
python3 scripts/budget_guard.py status
python3 scripts/budget_guard.py reset
```

## Slash commands

| Command | Purpose |
|---|---|
| `/start-container` | Build and start the dev container |
| `/new-feature <description>` | Kick off the planner agent for a new feature |
| `/pr-check` | Run reviewer + pre-commit checklist |
| `/reset-budget` | Reset per-session agent call counters |

## Agent workflow

The **orchestrator** is the single entry point for any coding task. It reads `.agent-comms/state.json`, delegates to the appropriate specialist, and gates progression between phases:

```
planner → plan-reviewer → implementer → tester → reviewer
```

Each phase writes results to `.agent-comms/outbox/<agent>.md` and updates `state.json`. The orchestrator reads the outbox to decide the next step. Phases that require user approval are gated — the orchestrator waits for explicit confirmation before advancing.

**state.json key fields:** `phase`, `feature`, `brief_path`, `plan_review_status`, `source_files`, `test_files`, `review_status`

**Phases:** `idle` → `planning` → `plan-review` → `implementing` → `testing` → `reviewing` → `done`

## Agent roles (read-only vs write)

- **planner** — writes feature briefs to `docs/features/<name>.md`
- **plan-reviewer** — read-only; flags gaps in briefs
- **implementer** — writes source files under `src/`
- **tester** — writes and runs tests under `tests/`
- **reviewer** — read-only; produces `READY` or `BLOCKED` verdict

## Architecture

```
.agent-comms/
  state.json              ← shared workflow state (phase, paths, statuses)
  inbox/<agent>.md        ← task written by orchestrator for each agent
  outbox/<agent>.md       ← results written by each agent back to orchestrator
.claude/
  agents/                 ← agent definitions (orchestrator, planner, etc.)
  commands/               ← slash command definitions
  settings.json           ← hooks: budget guard, container guard, secret file block
docs/features/            ← feature briefs written by planner
src/fuzzy_umbrella/       ← application source (populated by implementer)
tests/unit/               ← unit tests (populated by tester)
tests/integration/        ← integration tests (populated by tester)
scripts/
  run.sh                  ← executes commands inside the running container
  budget_guard.py         ← enforces per-session agent call/token limits (20 calls, 200k tokens)
  container_guard.py      ← PreToolUse hook; blocks python/pytest/ruff on host
```

## Guardrails (enforced via hooks in settings.json)

- **Budget guard** — `PreToolUse` on Agent tool blocks if session limits exceeded; `PostToolUse` increments counters.
- **Container guard** — `PreToolUse` on Bash blocks `python`, `pytest`, `ruff`, `pyright`, `pip`, `uv` unless running inside the container or prefixed with `./scripts/run.sh`.
- **Secret file block** — `PreToolUse` on Write/Edit blocks modifications to `.env`, `secrets.json`, etc.

## Python environment

- Python 3.12, managed inside Docker
- `PYTHONPATH=/workspace` (set in docker-compose.yml — note: changed from `/workspace/src` to `/workspace` so that `alembic/env.py` and the test suite can use `from src.api.db_models import Base` import paths)
- Package installed editable via `pip install -e '.[dev]'` in devcontainer
- Linter: `ruff` | Type checker: `pyright` | Test runner: `pytest`
