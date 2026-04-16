# fuzzy-umbrella

A multi-agent Claude Code setup for feature development. Specialized agents cover each phase of the development lifecycle — planning, reviewing the plan, implementing, testing, and code review — coordinated by an orchestrator and protected by budget and container guardrails.

---

## Quick Start

```bash
# 1. Start the dev container (required before any code execution)
docker compose up -d --build app

# 2. Start a new feature
# In Claude Code:
use the orchestrator agent to build <feature description>
```

---

## Agents

### Orchestrator

The single entry point for all coding tasks. Reads current state, delegates to specialists in sequence, gates progression between phases, and loops on feedback.

```
use the orchestrator agent to <anything>
```

### Specialists

| Agent | Role | Read-only? |
|---|---|---|
| **planner** | Clarifies requirements, explores the codebase, writes a feature brief in `docs/features/` | No (writes briefs) |
| **plan-reviewer** | Reviews the brief for missing edge cases, ambiguous requirements, and scope gaps — outputs APPROVED or NEEDS REVISION | Yes |
| **implementer** | Writes source code against an approved brief | No |
| **tester** | Writes unit and integration tests for completed modules | No |
| **reviewer** | Final quality gate on the git diff — outputs READY or BLOCKED | Yes |

---

## Slash Commands

| Command | What it does |
|---|---|
| `/new-feature <description>` | Injects branch + existing briefs context, launches the planner |
| `/pr-check` | Injects the current git diff, launches the reviewer + pre-commit checklist |
| `/start-container` | Builds and starts the dev container |
| `/reset-budget` | Resets agent call and token counters for a new session |

---

## Feature Workflow

### Full pipeline via orchestrator

```
use the orchestrator agent to build <feature description>
```

```
orchestrator reads state.json + git status
        │
        ├─ no brief exists
        │       └─ planner: clarifies requirements, explores codebase
        │                   writes docs/features/<name>.md
        │           plan-reviewer: checks brief for gaps
        │               │
        │           NEEDS REVISION ──→ planner revises ──→ plan-reviewer re-checks
        │               │
        │           APPROVED ──→ user confirms before proceeding
        │
        ├─ brief approved
        │       └─ implementer: reads brief, writes source files
        │                       reports which acceptance criteria are met
        │
        ├─ source written
        │       └─ tester: reads source + brief, writes tests, runs them
        │                  reports pass/fail + coverage
        │
        └─ tests pass
                └─ reviewer: checks diff for bugs, security, conventions
                        │
                    BLOCKED ──→ implementer/tester fix ──→ reviewer re-checks
                        │
                    READY ──→ safe to commit
```

### Targeted invocations

Skip the orchestrator when you only need one phase:

```bash
/new-feature <description>           # planner only
use the implementer agent to...      # implement a specific brief
use the tester agent to...           # write tests for a specific module
/pr-check                            # reviewer + checklist on current diff
```

---

## Agent Communication

Agents share state through a file-based message bus at `.agent-comms/`.

```
.agent-comms/
  state.json          ← global workflow state (phase, brief path, source files, statuses)
  inbox/<agent>.md    ← task + context written by orchestrator before each delegation
  outbox/<agent>.md   ← structured result written by agent when done
  messages.jsonl      ← append-only audit log (runtime, gitignored)
```

**Protocol:**
1. Orchestrator writes the agent's inbox (task, file paths, prior context) → invokes agent
2. Agent reads its inbox + relevant prior outboxes → does its work
3. Agent writes its outbox (status, artifacts, notes for next agent) + updates `state.json`
4. Orchestrator reads outbox → decides next step

Inbox/outbox files are runtime-only and gitignored. `state.json` resets at the start of each new feature. Full message format spec: `.agent-comms/README.md`.

---

## Container Isolation

All code execution runs inside a Docker container — never on the host.

```bash
# Start container (first time or after Dockerfile changes)
docker compose up -d --build app

# Run commands in the container
./scripts/run.sh pytest tests/unit/
./scripts/run.sh ruff check src/
./scripts/run.sh python -m mymodule
```

**How it works:**
- `scripts/run.sh` routes commands through `docker compose exec app`. If already inside the container (e.g. in a devcontainer session), it runs directly.
- A `PreToolUse` hook (`scripts/container_guard.py`) intercepts bare `python`, `pytest`, `ruff`, `pip`, and `pyright` calls. If the command isn't prefixed with `./scripts/run.sh` and the host isn't a container, the hook blocks the call and tells the agent to use the wrapper.

**VS Code / Cursor:** open the repo and choose "Reopen in Container" — `.devcontainer/devcontainer.json` handles the rest.

---

## Budget Guardrails

A per-session budget prevents runaway agent calls from burning through API quota.

| Limit | Default | Override (env var in `settings.json`) |
|---|---|---|
| Max agent calls per session | 20 | `BUDGET_MAX_AGENT_CALLS` |
| Max estimated tokens per session | 200,000 | `BUDGET_MAX_TOKENS` |
| Estimated tokens per agent call | 8,000 | `BUDGET_TOKENS_PER_CALL` |

**How it works:** a `PreToolUse` hook on the Agent tool checks `.agent-comms/budget.json` before every subagent invocation. If either limit is exceeded, it exits 1 and blocks the call. A `PostToolUse` hook increments the counters after each call.

```bash
python3 scripts/budget_guard.py status   # check current spend
/reset-budget                            # reset counters for a new session
```

Adjust limits in `.claude/settings.json` under `env`.

---

## Project Structure

```
.
├── .agent-comms/           ← agent message bus (runtime files gitignored)
│   ├── state.json          ← workflow state
│   ├── inbox/              ← per-agent task inboxes (written by orchestrator)
│   ├── outbox/             ← per-agent result outboxes (written by agents)
│   └── README.md           ← message format spec
├── .claude/
│   ├── agents/
│   │   ├── orchestrator.md ← entry point; delegates and gates between phases
│   │   ├── planner.md      ← feature brief writer
│   │   ├── plan-reviewer.md← brief quality gate (read-only)
│   │   ├── implementer.md  ← source code writer
│   │   ├── tester.md       ← test suite writer
│   │   └── reviewer.md     ← code quality gate (read-only)
│   ├── commands/
│   │   ├── new-feature.md  ← /new-feature
│   │   ├── pr-check.md     ← /pr-check
│   │   ├── start-container.md ← /start-container
│   │   └── reset-budget.md ← /reset-budget
│   └── settings.json       ← hooks: budget guard, container guard, .env protection
├── .devcontainer/
│   └── devcontainer.json   ← VS Code / Cursor devcontainer config
├── docs/
│   └── features/           ← feature briefs (written by planner, approved by you)
├── scripts/
│   ├── run.sh              ← container execution wrapper
│   ├── budget_guard.py     ← agent call + token budget enforcement
│   └── container_guard.py  ← blocks bare python/pytest/ruff on host
├── src/
│   └── fuzzy_umbrella/
├── tests/
│   ├── unit/
│   └── integration/
├── Dockerfile
└── docker-compose.yml
```

---

## Design Principles

- **Orchestrator is the only coordinator** — specialists never invoke each other directly
- **Plan before code** — planner + plan-reviewer run before a single line is written
- **Read-only reviewers** — plan-reviewer and reviewer find issues; implementer and tester fix them
- **Container-first execution** — no code runs on the host; drift between dev and test environments is eliminated
- **Fail-safe budget** — a confused or looping agent is blocked before it exhausts quota
- **Shared state over implicit context** — all inter-agent context is written to `.agent-comms/`, not passed as ad-hoc strings
