# 🏛️ Architecture — FinanceBuddy (Trading & Sentiment AI)

> **Living document.** This file is the single source of truth for the app's
> rules, structure, and component responsibilities. **It MUST be updated in the
> same change-set as any structural change** (new module, model, task, service,
> dependency, or convention). See [Maintenance Rule](#-maintenance-rule).

**Last updated:** 2026-06-01 · **Roadmap phase:** Phase 1 ✅ · Phase 2 ✅ (see [ROADMAP.md](ROADMAP.md))

---

## 1. Purpose

Self-hosted platform that correlates financial **price data** with **news
sentiment** to support trading decisions. Prices and news are ingested on a
schedule, scored for sentiment (FinBERT or a keyword fallback), and served
through a REST API + single-page dashboard.

---

## 2. Tech Stack

| Layer       | Technology                                                        |
|-------------|-------------------------------------------------------------------|
| Backend     | Python 3.11+, Django 5.x, Django REST Framework, django-filter    |
| Async/Queue | Celery 5.x (worker + beat), Redis 7 (broker & result backend)     |
| Database    | PostgreSQL 15 (Alpine)                                             |
| NLP         | HuggingFace Transformers (ProsusAI/finbert), PyTorch (CPU-only)   |
| Data feed   | yfinance (prices + news)                                          |
| TA / math   | pandas (pure-pandas EMA/RSI/MACD; pandas-ta avoided — numpy 2.x)  |
| Frontend    | TailwindCSS, Alpine.js, TradingView Lightweight Charts v4.2.3 (CDN, pinned) |
| Runtime     | Docker Compose (web, db, redis, celery_worker, celery_beat)       |

---

## 3. Directory Structure

```
FinanceBuddy/
├── ARCHITECTURE.md            # THIS FILE — living architecture spec
├── ROADMAP.md                 # Phased product roadmap
├── Dockerfile                 # App image; ENTRYPOINT = entrypoint.sh
├── entrypoint.sh              # Wait-for-DB → migrate → bootstrap → exec CMD
├── docker-compose.yml         # 5-service orchestration; secrets via ${VAR} from .env
├── .env.example               # Committed env template (placeholders); real .env gitignored
├── manage.py
├── requirements.txt
├── finance_buddy/             # Django project (settings, urls, celery, asgi/wsgi)
│   ├── settings.py            # Env-driven config + Celery beat schedule
│   ├── celery.py              # Celery app + autodiscovery
│   └── urls.py                # DRF router (assets/prices/news) + /api/indicators/ + dashboard
└── core/                      # Single domain app
    ├── constants.py           # Seed assets + tuning params (TA periods, alert thresholds)
    ├── models.py              # Asset, PriceData, NewsArticle, Alert
    ├── serializers.py         # DRF serializers
    ├── indicators.py          # Phase 2: pure-pandas EMA/RSI/MACD compute helpers
    ├── correlation.py         # Phase 2: sentiment↔forward-return correlation (Pearson/Spearman)
    ├── alerts.py              # Phase 2: sentiment-threshold eval + multi-channel dispatch
    ├── views.py               # ViewSets (incl. AlertViewSet) + Indicators/Correlation + Dashboard
    ├── tasks.py               # Celery tasks (incl. startup_catch_up) + ingest/scoring helpers
    ├── migrations/            # 0001_initial, 0002_alert …
    ├── management/commands/
    │   └── bootstrap_assets.py  # Phase 1 idempotent seeding command
    ├── tests/                 # Unit tests (test_indicators.py …)
    └── templates/core/dashboard.html
```

---

## 4. Data Model

```
Asset (symbol PK) ──1:N──► PriceData   (asset, timestamp) unique
                  ├─1:N──► NewsArticle (asset, url)        unique
                  └─1:N──► Alert        (asset, level, created_at) indexed
```

- **Asset** — `symbol` (PK), `name`, `asset_type` (Stock|ETF).
- **PriceData** — OHLCV per `timestamp`; ordered by timestamp; indexed `(asset, timestamp)`.
- **NewsArticle** — `title`, `source`, `url`, `extracted_text`, `sentiment_score`
  (−1.0…+1.0), `sentiment_label` (Positivo|Neutrale|Negativo).
- **Alert** — fired sentiment-threshold event: `level` (Positivo|Negativo),
  `avg_sentiment`, `article_count`, `message`, `created_at`. Persisted for
  cooldown/dedupe and UI history.

---

## 5. Components & Responsibilities

| Service        | Role                                                                 |
|----------------|----------------------------------------------------------------------|
| `web`          | Django/DRF API + dashboard. **Sole owner** of migrations + bootstrap. |
| `db`           | PostgreSQL persistent store (`postgres_data` volume).                |
| `redis`        | Celery broker + result backend.                                      |
| `celery_worker`| Executes ingest/scoring tasks; loads FinBERT (cache in `hf_cache`).  |
| `celery_beat`  | Triggers periodic tasks on the schedule below.                       |

### Periodic schedule (`settings.CELERY_BEAT_SCHEDULE`)
- `fetch_market_data` — every 15 min (recent prices, 30d@1h, daily fallback).
- `fetch_news` — every 30 min → chains `analyze_sentiment`.
- `analyze_sentiment` — every 30 min (scores unscored articles).
- `check_sentiment_alerts` — every 30 min (fires threshold alerts; see §6).
- `startup_catch_up` — **event-driven** (on `worker_ready`, not periodic): one-off
  gap-recovery pipeline run when the service comes online (see §6).

---

## 6. Data Flow

```
beat ──schedule──► worker
   fetch_market_data → yfinance → PriceData (upsert)
   fetch_news        → yfinance → NewsArticle (insert) → analyze_sentiment
   analyze_sentiment → FinBERT | keywords → sentiment_score/label
web (DRF) ──reads──► PostgreSQL ──JSON──► dashboard.html (charts)
   /api/indicators/  → indicators.compute_indicators(close series) → EMA/RSI/MACD JSON
   /api/correlation/ → correlation.compute_sentiment_correlation(news, prices) → Pearson/Spearman @1/3/7d
   /api/alerts/      → reads fired Alert rows
beat ─► check_sentiment_alerts → alerts.run_sentiment_alert_check
   per asset: rolling avg sentiment (lookback) → threshold cross + cooldown
   → Alert (insert) → dispatch to log + Telegram/Discord/Email (if configured)
```

News ingest normalizes both the new (≥0.2.40, nested `content`) and legacy
yfinance `.news` schemas via `_normalize_news_item`. TA indicators and the
sentiment↔price correlation matrix are computed **on read** from stored data
(no extra columns/tables). The correlation matrix is the measurement primitive
for the long-term self-calibration goal (learn news relevance from market
reaction over ~1 year) — recent articles without enough forward price history
are excluded, so the matrix populates as history accumulates.

### Startup (every container boot, via `entrypoint.sh`)
1. Wait for Postgres.
2. `web` only: `migrate` (`RUN_MIGRATIONS=True`) → `bootstrap_assets --no-sentiment` (`RUN_BOOTSTRAP=True`).
3. `exec` the service command.

Bootstrap is **idempotent** (get_or_create + upsert) — safe on every boot.

### Gap recovery for intermittent operation
The stack is designed to run **on-demand** (e.g. opened once a day) without losing
data. All ingested data + sentiment live in the `postgres_data` volume, so they
survive restarts (never use `docker compose down -v`). On every **worker boot** the
`worker_ready` signal dispatches `startup_catch_up`, which re-pulls the recent price
window (covers the offline gap), fetches news, scores all pending sentiment, and
evaluates alerts — so opening the service after hours/days immediately ingests AND
analyzes the missed window, independent of Celery beat timing.

> Limitation: yfinance `.news` only returns the latest ~10 items per asset, so
> intraday articles that scrolled off the list while offline cannot be backfilled
> (addressed later by Phase 4 multi-source scrapers). Price history is fully
> recoverable because fetches are window-based.

---

## 7. Conventions & Rules (enforced)

1. **No magic values inline.** Seed data and tuning params live in
   [core/constants.py](core/constants.py).
2. **Reusable helpers, thin tasks.** `tasks.py` Celery tasks delegate to small
   helpers (`fetch_price_history`, `fetch_news_for_asset`, `score_pending_articles`)
   that are also called by management commands. Functions stay < 50 lines.
3. **Idempotent ingest.** All writes use `get_or_create` / `update_or_create`.
4. **Immutability first.** Build new objects over in-place mutation, except where
   the Django ORM model-save pattern is the idiomatic exception.
5. **Many small, focused files** (200–400 lines typical, 800 max).
6. **Env-driven config / no committed secrets.** Secrets/connection strings via env.
   Real values live in the gitignored `.env`; `docker-compose.yml` references them
   with `${VAR:-default}` interpolation and `.env.example` documents every key, so
   the committed tree never contains real credentials. Alert channels
   (Telegram/Discord/Email) and thresholds are all env-configurable; absent channel
   config → that channel is skipped. **Note:** `DB_PASSWORD` must match the value the
   `postgres_data` volume was first initialized with, or recreate the volume.
7. **Graceful degradation.** Per-asset ingest errors are logged and skipped;
   FinBERT failures fall back to keyword scoring (`USE_REAL_NLP` flag); a failing
   alert channel is logged and skipped without blocking the others.
8. **Single owner for migrations/bootstrap** (the `web` service) to avoid races.

---

## 8. Phase Status (vs [ROADMAP.md](ROADMAP.md))

- **Phase 1 — Automation & Bootstrapping ✅**
  - `bootstrap_assets` management command (seed + historical backfill + news).
  - Full Docker Compose orchestration (web, db, redis, worker, beat) with
    DB-wait + auto-migrate + auto-bootstrap entrypoint.
  - Persistent HuggingFace/FinBERT cache via `hf_cache` Docker volume (`HF_HOME`).
- **Phase 2 — Technical indicators & correlation ✅**
  - ✅ Server-side EMA (20/50/200), RSI (14), MACD (12/26/9) via
    [core/indicators.py](core/indicators.py), served at `/api/indicators/?asset=`.
  - ✅ Dashboard overlays EMA lines on the candles + RSI/MACD sub-panes with
    synced time scales and EMA toggle chips.
  - ✅ Pearson/Spearman sentiment↔price correlation matrix (1/3/7d) via
    [core/correlation.py](core/correlation.py), served at `/api/correlation/?asset=`
    and rendered as a matrix card in the dashboard.
  - ✅ Automated sentiment-threshold alerts via [core/alerts.py](core/alerts.py)
    (`check_sentiment_alerts` beat task): log + Telegram/Discord/Email channels,
    `Alert` model with cooldown/dedupe, `/api/alerts/` + dashboard alert panel.
  - ✅ Unit tests for indicator + correlation + alert logic ([core/tests/](core/tests/), 26 tests).
- Phase 3 — Backtesting engine · *planned*
- Phase 4 — Custom NLP & multi-source scrapers · *planned*
- Phase 5 — Paper/live trading · *planned*

---

## 🔄 Maintenance Rule

**On every iteration that changes structure**, update this file in the same
commit: bump *Last updated*, adjust the relevant section (structure, model,
components, conventions), and move the Phase Status when a roadmap phase
completes. This rule is also encoded as the project skill
[`.claude/skills/architecture-sync`](.claude/skills/architecture-sync/SKILL.md)
and referenced from [CLAUDE.md](CLAUDE.md).
