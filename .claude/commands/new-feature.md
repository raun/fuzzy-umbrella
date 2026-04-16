---
description: Kick off a new feature using the full planning workflow. Launches the planner agent with the feature description.
---

Start a new feature: $ARGUMENTS

## Current State
- Branch: !`git branch --show-current`
- Uncommitted changes: !`git status --short`
- Existing feature briefs: !`ls docs/features/ 2>/dev/null || echo "none yet"`

Launch the **planner** agent with the feature description above. The planner will:
1. Ask any clarifying questions
2. Explore the codebase for context
3. Produce a brief in `docs/features/`

Do not write any code until the brief is approved.
