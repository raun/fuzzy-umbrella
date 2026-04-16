#!/usr/bin/env python3
"""
Budget guard for agent runs.

Tracks agent (subagent) invocations and token spend per session.
Called by Claude Code hooks on every Agent tool use.

Usage (via hooks — not intended for direct use):
  python3 scripts/budget_guard.py pre   # check before invoking an agent; exits 1 to block
  python3 scripts/budget_guard.py post  # record after an agent completes
  python3 scripts/budget_guard.py status
  python3 scripts/budget_guard.py reset
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

BUDGET_FILE = Path(".agent-comms/budget.json")

# Limits — override via environment variables in .claude/settings.json
MAX_AGENT_CALLS = int(os.environ.get("BUDGET_MAX_AGENT_CALLS", "20"))
MAX_TOKENS = int(os.environ.get("BUDGET_MAX_TOKENS", "200000"))


def _load() -> dict:
    if not BUDGET_FILE.exists():
        return _fresh()
    with open(BUDGET_FILE) as f:
        return json.load(f)


def _save(data: dict) -> None:
    BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BUDGET_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _fresh() -> dict:
    return {
        "session_start": datetime.now().isoformat(),
        "agent_calls": 0,
        "estimated_tokens": 0,
        "last_call": None,
    }


def pre() -> None:
    """Called before an Agent tool use. Exits 1 to block if limits exceeded."""
    budget = _load()
    errors = []

    if budget["agent_calls"] >= MAX_AGENT_CALLS:
        errors.append(
            f"agent call limit reached: {budget['agent_calls']}/{MAX_AGENT_CALLS} calls used this session"
        )

    if budget["estimated_tokens"] >= MAX_TOKENS:
        errors.append(
            f"token limit reached: ~{budget['estimated_tokens']:,}/{MAX_TOKENS:,} tokens used this session"
        )

    if errors:
        print(
            f"\n[BUDGET GUARD] Run blocked — {'; '.join(errors)}.\n"
            f"Run /reset-budget to start a new session or raise limits in .claude/settings.json.\n",
            file=sys.stderr,
        )
        sys.exit(1)

    remaining_calls = MAX_AGENT_CALLS - budget["agent_calls"]
    remaining_tokens = MAX_TOKENS - budget["estimated_tokens"]
    print(
        f"[BUDGET] {budget['agent_calls']}/{MAX_AGENT_CALLS} agent calls used | "
        f"~{budget['estimated_tokens']:,}/{MAX_TOKENS:,} tokens used | "
        f"{remaining_calls} calls / ~{remaining_tokens:,} tokens remaining",
        file=sys.stderr,
    )


def post() -> None:
    """Called after an Agent tool use. Increments counters."""
    budget = _load()
    budget["agent_calls"] += 1
    budget["last_call"] = datetime.now().isoformat()
    # Rough token estimate per agent invocation: input context + output.
    # Real token counts aren't accessible in hooks; this is a conservative estimate.
    budget["estimated_tokens"] += int(os.environ.get("BUDGET_TOKENS_PER_CALL", "8000"))
    _save(budget)


def status() -> None:
    budget = _load()
    print(
        f"Session started : {budget['session_start']}\n"
        f"Agent calls     : {budget['agent_calls']} / {MAX_AGENT_CALLS}\n"
        f"Estimated tokens: ~{budget['estimated_tokens']:,} / {MAX_TOKENS:,}\n"
        f"Last call       : {budget['last_call'] or 'none'}"
    )


def reset() -> None:
    _save(_fresh())
    print("[BUDGET] Session reset. Counters cleared.")


COMMANDS = {"pre": pre, "post": post, "status": status, "reset": reset}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}. Use: {', '.join(COMMANDS)}", file=sys.stderr)
        sys.exit(2)
    COMMANDS[cmd]()
