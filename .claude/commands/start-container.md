---
description: Build and start the dev container. Run this before invoking any agent that executes code.
---

## Container Status
!`docker compose ps 2>/dev/null || echo "docker compose not available"`

Start the dev container:

!`docker compose up -d --build app && echo "Container ready."`

The container mounts the repo at `/workspace`. All code execution by agents goes through `./scripts/run.sh`.
