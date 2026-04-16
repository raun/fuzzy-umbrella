#!/usr/bin/env python3
"""
PreToolUse hook for Bash — enforces that Python/test/lint commands
run inside the dev container via ./scripts/run.sh.

Reads the Bash tool input from $CLAUDE_TOOL_INPUT (JSON).
Exits 1 (blocking the tool call) if a guarded command is invoked bare
on the host machine instead of through the container wrapper.
"""

import json
import os
import sys

# Commands that must run inside the container
GUARDED = frozenset({"python", "python3", "pytest", "ruff", "pyright", "pip", "pip3", "uv"})

# Prefixes that mean the command is already routed through the container
ALLOWED_PREFIXES = (
    "./scripts/run.sh",
    "scripts/run.sh",
    "docker compose exec",
    "docker exec",
)


def main() -> None:
    raw = os.environ.get("CLAUDE_TOOL_INPUT", "{}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)  # can't parse — let it through

    command: str = data.get("command", "").strip()
    if not command:
        sys.exit(0)

    # If already inside a container, always allow
    if os.path.exists("/.dockerenv"):
        sys.exit(0)

    # If command is routed through the container wrapper or docker, allow
    if any(command.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        sys.exit(0)

    # Check the first token against the guarded set
    first_token = command.split()[0].split("/")[-1]  # handle paths like /usr/bin/python
    if first_token in GUARDED:
        print(
            f"\n[CONTAINER GUARD] '{first_token}' must run inside the dev container.\n\n"
            f"  Use: ./scripts/run.sh {command}\n\n"
            f"Or start the container first with /start-container, then re-run.\n",
            file=sys.stderr,
        )
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
