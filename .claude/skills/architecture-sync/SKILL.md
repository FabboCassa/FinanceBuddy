---
name: architecture-sync
description: Keep ARCHITECTURE.md in sync with the FinanceBuddy codebase. Use whenever a change adds or alters structure — a module, model, Celery task, service, management command, dependency, Docker service, or convention — or when a ROADMAP phase completes. Ensures the living architecture doc never drifts from reality.
---

# Architecture Sync

`ARCHITECTURE.md` at the repo root is the **living source of truth** for
FinanceBuddy's structure and rules. It must never drift from the code.

## When to apply (triggers)

Update `ARCHITECTURE.md` **in the same change-set** whenever you:

- add/remove/rename a module, package, or significant file
- change a model, migration, or the data model relationships
- add/change a Celery task, beat schedule entry, or service
- add a management command, dependency, or env var
- change a Docker service, volume, or the entrypoint flow
- change a project convention/rule
- complete (or start) a ROADMAP phase

## How to update

1. Open `ARCHITECTURE.md`.
2. Bump the **Last updated** date (and **Roadmap phase** if it changed).
3. Edit the specific section(s) affected — keep them accurate and terse:
   - §3 Directory Structure · §4 Data Model · §5 Components ·
     §6 Data Flow · §7 Conventions · §8 Phase Status.
4. If a roadmap phase completed, move it to ✅ in §8 and cross-check
   [ROADMAP.md](../../../ROADMAP.md).
5. Keep edits minimal and consistent with the existing tables/format.

## Checklist before marking work complete

- [ ] Does this change touch structure, models, tasks, services, deps, or rules?
- [ ] If yes, is `ARCHITECTURE.md` updated in the same commit?
- [ ] Is **Last updated** bumped?
- [ ] Is §8 Phase Status still accurate vs `ROADMAP.md`?

Treat a structural change with a stale `ARCHITECTURE.md` as an **incomplete task**.
