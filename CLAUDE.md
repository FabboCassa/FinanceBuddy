# FinanceBuddy — Project Instructions

Trading & Sentiment AI platform (Django + Celery + FinBERT). See
[ARCHITECTURE.md](ARCHITECTURE.md) for full structure and rules, and
[ROADMAP.md](ROADMAP.md) for the phased plan.

## Core rule: keep the architecture doc live

**`ARCHITECTURE.md` is a living document.** Any change that touches structure —
a module, model, Celery task, service, management command, dependency, Docker
service, or convention, or a completed ROADMAP phase — MUST update
`ARCHITECTURE.md` in the **same change-set** (bump *Last updated*, edit the
affected section, move Phase Status when a phase completes).

This rule is encoded as the project skill
[`.claude/skills/architecture-sync`](.claude/skills/architecture-sync/SKILL.md) —
invoke it (or follow it) on every structural change. A structural change with a
stale `ARCHITECTURE.md` is an incomplete task.

## Conventions

Follow the enforced conventions in [ARCHITECTURE.md §7](ARCHITECTURE.md#7-conventions--rules-enforced):
no magic values inline (use `core/constants.py`), thin Celery tasks delegating to
reusable helpers, idempotent ingest, small focused files, env-driven config.

## Common commands

```bash
docker compose up --build          # full stack (auto migrate + bootstrap)
python manage.py bootstrap_assets  # seed assets + backfill prices/news/sentiment
python manage.py makemigrations core && python manage.py migrate
```
