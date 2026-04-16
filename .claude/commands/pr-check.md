---
description: Run a pre-commit quality check using the reviewer agent plus a standard checklist.
---

## Current Diff
!`git diff HEAD --stat`

## Branch
!`git branch --show-current`

Launch the **reviewer** agent to review all uncommitted changes, then apply this checklist:

## Pre-Commit Checklist

- [ ] All new public functions have type annotations
- [ ] All new public functions have docstrings
- [ ] No `print()` statements in source code
- [ ] No hardcoded secrets or API keys
- [ ] Tests exist for new functionality
- [ ] Tests pass
- [ ] Linting passes
- [ ] Feature brief exists in `docs/features/` if this is a new feature
- [ ] `CLAUDE.md` updated if new conventions were established

Report final status: **READY** or **BLOCKED** with specific items to fix.
