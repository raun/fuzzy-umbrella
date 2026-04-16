# Agent Communication Protocol

This directory is the shared message bus for all agents. It persists state and passes context between agents across separate invocations.

## Directory Structure

```
.agent-comms/
  state.json          ← global workflow state (phase, feature, file paths, statuses)
  messages.jsonl      ← append-only audit log of every message (runtime, gitignored)
  inbox/
    <agent>.md        ← task + context written by orchestrator before delegating
  outbox/
    <agent>.md        ← structured output written by agent when done
```

## state.json Fields

| Field | Values | Description |
|---|---|---|
| `feature` | string / null | Current feature name (kebab-case) |
| `phase` | `idle` `planning` `plan-review` `implementing` `testing` `reviewing` `done` | Current workflow phase |
| `brief_path` | path / null | Path to the feature brief |
| `plan_review_status` | `APPROVED` `NEEDS REVISION` / null | Outcome of plan-reviewer |
| `source_files` | array of paths | Source files written/modified by implementer |
| `test_files` | array of paths | Test files written by tester |
| `review_status` | `READY` `BLOCKED` / null | Outcome of reviewer |
| `last_agent` | agent name | Last agent to run |
| `last_updated` | ISO timestamp | When state was last written |
| `notes` | object | Free-form key/value notes agents leave for each other |

## Inbox Format

Written by the orchestrator to `.agent-comms/inbox/<agent>.md` before invoking an agent:

```markdown
---
from: orchestrator
to: <agent>
feature: <feature name>
phase: <current phase>
sent_at: <ISO timestamp>
---

## Task
<specific task for this agent>

## Context from Prior Agents
<what has already been done — agent name, what it produced, any status/findings>

## Relevant Files
- <path> — <why it's relevant>

## Expected Output
<what this agent should produce or check>
```

## Outbox Format

Written by an agent to `.agent-comms/outbox/<agent>.md` when finished:

```markdown
---
from: <agent>
feature: <feature name>
status: <COMPLETE | APPROVED | NEEDS REVISION | READY | BLOCKED>
finished_at: <ISO timestamp>
---

## What I Did
<one paragraph summary>

## Produced / Changed
- <path> — <description>

## Status
<COMPLETE | APPROVED | NEEDS REVISION | READY | BLOCKED>

## For the Next Agent
<context, file paths, or warnings the next agent needs>

## Issues Found
<findings if status is NEEDS REVISION or BLOCKED; empty otherwise>
```

## Communication Rules

1. **Orchestrator writes inboxes** — it is the only agent that writes to another agent's inbox
2. **Agents write their own outbox** — each agent writes only to `outbox/<own-name>.md`
3. **Agents update state.json** — each agent updates the relevant fields when it finishes
4. **Orchestrator reads outboxes** — after delegation, the orchestrator reads the outbox to get the result
5. **Inbox is cleared before each invocation** — orchestrator overwrites the inbox before calling an agent
6. **messages.jsonl is append-only** — agents may append a one-line JSON entry to the log for audit purposes

## Runtime Files (gitignored)

`inbox/*.md`, `outbox/*.md`, `messages.jsonl` are runtime files — they are gitignored and recreated each session. `state.json` is reset to its template state at the start of each new feature.
