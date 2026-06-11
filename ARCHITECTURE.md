# 🏛️ Architecture — FinanceBuddy (Trading & Sentiment AI)

> **Living document.** This file is the single source of truth for the app's
> rules, structure, and component responsibilities. **It MUST be updated in the
> same change-set as any structural change** (new module, model, task, service,
> dependency, or convention). See [Maintenance Rule](#-maintenance-rule).

**Last updated:** 2026-06-11 · **Roadmap phase:** Phase 1 ✅ · Phase 2 ✅ · Phase 3 ✅ · Phase 4 🚧 (relevance + source quality + NER/RSS; **rung 3 self-supervised classifier deferred — see §8 reminder**) · Phase 5 ✅ (paper trading + execution costs + live metrics + WebSocket; broker/multi-user deferred) · Phase 6 ✅ (educational wiki at `/wiki/`) (see [ROADMAP.md](ROADMAP.md))

---

## 1. Purpose

Self-hosted platform that correlates financial **price data** with **news
sentiment** to support trading decisions. Prices and news are ingested on a
schedule, scored for sentiment (FinBERT or a keyword fallback), and served
through a REST API + single-page dashboard. The tracked universe is the global
**top ~500 companies by market cap** (validated yfinance tickers,
[core/data/global_top500.csv](core/data/global_top500.csv)); users can also
add/remove assets from the dashboard.

---

## 2. Tech Stack

| Layer       | Technology                                                        |
|-------------|-------------------------------------------------------------------|
| Backend     | Python 3.11+, Django 5.x, Django REST Framework, django-filter    |
| Async/Queue | Celery 5.x (worker + beat), Redis 7 (broker & result backend + Channels layer) |
| Database    | PostgreSQL 15 (Alpine)                                             |
| NLP         | HuggingFace Transformers — ProsusAI/finbert (sentiment) + facebook/bart-large-mnli (zero-shot theme categorization, opt-in), PyTorch (CPU-only) |
| Data feed   | yfinance (prices + per-ticker news) + feedparser (curated quality RSS, linked to assets via NER) |
| TA / math   | pandas + numpy (pure-pandas EMA/RSI/MACD + backtester; Backtrader/pandas-ta avoided — numpy 2.x) |
| Frontend    | TailwindCSS, Alpine.js, TradingView Lightweight Charts v4.2.3 (CDN, pinned). Opens on a home/overview ("Panoramica": market summary via `/api/summary/`, latest alerts, Top Opportunità, Paper Trading); asset detail (chart, correlation, news, sandbox) shown on click |
| Real-time   | Django Channels 4 + channels-redis + Daphne (ASGI) — WebSocket portfolio stream (Phase 5). redis-py pinned `>=5,<6`: dalla 6.x il read-timeout socket scatta sui comandi bloccanti (BZPOPMIN, 5s) di channels-redis → TimeoutError e drop del WebSocket ogni 5s |
| Runtime     | Docker Compose (web, db, redis, celery_worker, celery_beat). **Prod-safe base** (`docker-compose.yml`: Daphne, no DB/Redis host ports, `restart: unless-stopped`, healthchecks, `DB_PASSWORD` required) + **dev override** (`docker-compose.override.yml`: runserver autoreload, DEBUG=True, ports 5435/6379 — merged automatically by `docker compose up`). Static files via WhiteNoise (`collectstatic` in entrypoint, web only). Deploy: GitHub Actions → tailnet → SSH (`.github/workflows/deploy.yml`) |

---

## 3. Directory Structure

```
FinanceBuddy/
├── ARCHITECTURE.md            # THIS FILE — living architecture spec
├── ROADMAP.md                 # Phased product roadmap
├── Dockerfile                 # App image; ENTRYPOINT = entrypoint.sh
├── entrypoint.sh              # Wait-for-DB → migrate → bootstrap → exec CMD
├── docker-compose.yml         # PROD-SAFE base: Daphne, healthchecks, restart policy, no DB/Redis host ports
├── docker-compose.override.yml# Dev-only overrides (runserver, DEBUG, host ports) — auto-merged locally
├── .github/workflows/deploy.yml # Push to main → tailnet (ephemeral node) → SSH → pull + compose up
├── DEPLOYMENT_PLAN.md         # Hosting/hardening plan (Oracle Always Free + Tailscale)
├── .env.example               # Committed env template (placeholders); real .env gitignored
├── manage.py                  # On `runserver`, auto-starts/stops the Compose stack (see docker_boot)
├── requirements.txt
├── finance_buddy/             # Django project (settings, urls, celery, asgi/wsgi)
│   ├── settings.py            # Env-driven config + Celery beat schedule + LOGGING (console + logs/ file)
│   ├── celery.py              # Celery app + autodiscovery
│   ├── docker_boot.py         # Dev: `runserver` → `docker compose up -d`, stop on exit (stdlib-only)
│   ├── asgi.py                # ASGI ProtocolTypeRouter: HTTP (Django) + WebSocket (Channels) — Phase 5
│   └── urls.py                # DRF router (assets/prices/news) + /api/indicators/ + dashboard
└── core/                      # Single domain app
    ├── constants.py           # Seed assets + tuning params (TA periods, alert thresholds)
    ├── models.py              # Asset, PriceData, NewsArticle, Alert
    ├── serializers.py         # DRF serializers
    ├── indicators.py          # Phase 2: pure-pandas EMA/RSI/MACD compute helpers
    ├── correlation.py         # Phase 2: sentiment↔forward-return correlation (Pearson/Spearman)
    ├── alerts.py              # Phase 2: sentiment-threshold eval + multi-channel dispatch
    ├── backtest.py            # Phase 3: pure pandas/numpy sentiment-strategy backtester + grid_search (train/test split) (delegates metrics → metrics.py)
    ├── monitoring.py          # Ops: /healthz checks, task-failure→Telegram (cooldown), data-health summary/report
    ├── category_impact.py     # Phase 4: per-category forward-impact stats (which themes move prices)
    ├── metrics.py             # Phase 3/5: shared equity-curve risk/return math (Sharpe/Sortino/drawdown/win-rate/buy-hold)
    ├── execution.py           # Phase 3/5: shared trade-cost model (commission + adverse slippage) for backtest + paper
    ├── relevance.py           # Phase 4: cold-start news categorization + forward price impact
    ├── sources.py             # Phase 4: news source quality registry lookup (tier/country/language)
    ├── entities.py            # Phase 4: entity linking (NER) — attribute articles to tracked assets
    ├── rss.py                 # Phase 4: RSS feed fetch + entry normalization (feedparser, lazy import)
    ├── universe.py            # Phase 4: load the asset universe (global top ~500) from data CSV
    ├── ranking.py             # Phase 4: composite "Top Opportunità" score (sentiment+momentum+technical+price)
    ├── paper_trading.py       # Phase 5: pure paper-trading engine (latest signal, position sizing)
    ├── portfolio.py           # Phase 5: shared portfolio read model (payload for REST + WebSocket)
    ├── realtime.py            # Phase 5: WebSocket broadcaster (push portfolio snapshot to dashboards)
    ├── consumers.py           # Phase 5: PortfolioConsumer (Channels WebSocket stream)
    ├── routing.py             # Phase 5: websocket_urlpatterns (ws/portfolio/)
    ├── data/
    │   └── global_top500.csv  # Committed, yfinance-validated global top ~500 by market cap
    ├── views.py               # ViewSets (incl. AlertViewSet) + Indicators/Correlation/Backtest + Dashboard
    ├── tasks.py               # Celery tasks (incl. startup_catch_up) + ingest/scoring helpers
    ├── migrations/            # 0001_initial … 0007_asset_earnings_calendar
    ├── management/commands/
    │   ├── bootstrap_assets.py  # Phase 1 idempotent seeding command
    │   └── data_status.py       # On-demand data-freshness report (prices/news/forward-impact)
    ├── tests/                 # Unit tests (test_indicators.py, test_backtest.py, test_wiki.py …)
    └── templates/core/
        ├── dashboard.html     # Single-page dashboard (links into the wiki via ℹ︎ anchors)
        └── wiki.html          # Phase 6: educational Knowledge Base (/wiki/, KaTeX, search)

logs/                          # Rotating ingestion log (gitignored); written by both the
                               # local runserver and the celery_worker container (shared via the
                               # .:/app bind mount) — open logs/finance_buddy.log to watch ingest.
```

---

## 4. Data Model

```
Asset (symbol PK) ──1:N──► PriceData   (asset, timestamp) unique
                  ├─1:N──► NewsArticle (asset, url)        unique
                  ├─1:N──► Alert        (asset, level, created_at) indexed
                  └─1:1──► AssetScore   (composite opportunity ranking)

Portfolio (Phase 5) ─1:N─► Position          (portfolio, asset) unique — open holdings
                    ├─1:N─► PaperTrade        executed virtual BUY/SELL orders
                    └─1:N─► PortfolioSnapshot mark-to-market equity over time
```

- **Asset** — `symbol` (PK), `name`, `asset_type` (Stock|ETF), `next_earnings_date`
  + `earnings_checked_at` (earnings calendar, refreshed in rotating daily batches).
- **PriceData** — OHLCV per `timestamp`; ordered by timestamp; indexed `(asset, timestamp)`.
- **NewsArticle** — `title`, `source`, `url`, `extracted_text`, `sentiment_score`
  (−1.0…+1.0), `sentiment_label` (Positivo|Neutrale|Negativo). **Phase 4:**
  `category` (theme; cold-start keyword vote), `is_relevant` (True|False|null =
  unknown), `forward_impact` (JSON `{"1":pct,"3":pct,"7":pct}` forward return
  from publish — the supervision signal for the self-calibrating filter),
  `source_tier` (premium|quality|unverified, from the curated source registry).
- **Alert** — fired sentiment-threshold event: `level` (Positivo|Negativo),
  `avg_sentiment`, `article_count`, `message`, `created_at`. Persisted for
  cooldown/dedupe and UI history.
- **AssetScore** — latest composite opportunity ranking per asset (1:1):
  `score` (0–100), `rank`, `components` (JSON: sentiment / sentiment_momentum /
  technical / momentum, each −1..1), `n_articles`, `low_news`, `updated_at`.
  Upserted by `compute_rankings`; read by `/api/ranking/`.
- **Portfolio** (Phase 5) — a virtual paper-trading account (play money):
  `name` (unique), `initial_capital`, `cash`. A single "Default" is auto-created.
- **Position** (Phase 5) — open virtual holding, one per (`portfolio`, `asset`):
  `quantity`, `avg_entry_price`, `opened_at`.
- **PaperTrade** (Phase 5) — executed virtual order: `side` (BUY|SELL),
  `quantity`, `price`, `value`, `reason` (sentiment|stop_loss), `realized_pnl`
  (SELL only), `executed_at`.
- **PortfolioSnapshot** (Phase 5) — per-cycle mark-to-market: `timestamp`,
  `cash`, `holdings_value`, `total_value` (the equity-curve points).

---

## 5. Components & Responsibilities

| Service        | Role                                                                 |
|----------------|----------------------------------------------------------------------|
| `web`          | Django/DRF API + dashboard, **ASGI via Daphne** (HTTP + `ws/portfolio/`). **Sole owner** of migrations + bootstrap. |
| `db`           | PostgreSQL persistent store (`postgres_data` volume).                |
| `redis`        | Celery broker + result backend, **and the Channels layer** (WebSocket fan-out). |
| `celery_worker`| Executes ingest/scoring tasks; loads FinBERT (cache in `hf_cache`).  |
| `celery_beat`  | Triggers periodic tasks on the schedule below.                       |

### Periodic schedule (`settings.CELERY_BEAT_SCHEDULE`)
- `fetch_market_data` — every 15 min (recent prices, batched multi-ticker
  `yf.download` so the ~500-asset universe stays tractable).
- `fetch_news` — every 30 min → a capped random sample of assets via yfinance
  per-ticker news (`YFINANCE_NEWS_MAX_ASSETS`) + curated RSS feeds
  (`RSS_INGEST_ENABLED`, linked to assets via NER) → chains `analyze_sentiment`.
- `analyze_sentiment` — every 30 min (scores unscored articles).
- `check_sentiment_alerts` — every 30 min (fires threshold alerts; see §6).
- `update_news_relevance` — every 30 min (Phase 4: tag source quality tier,
  categorize new articles, (re)compute forward price impact as history matures).
- `compute_rankings` — every 30 min (Phase 4: recompute the composite
  opportunity score per asset → upsert AssetScore).
- `run_paper_trading` — every 30 min (Phase 5: one virtual paper-trading cycle —
  apply the sentiment strategy forward, open/close positions, snapshot equity).
- `refresh_earnings_calendar` — daily 07:10 (rotating `EARNINGS_REFRESH_BATCH`
  slice, oldest-checked first → next_earnings_date via yfinance `.calendar`).
- `send_health_report` — weekly Mon 08:00 (data-freshness report → Telegram).
- `startup_catch_up` — **event-driven** (on `worker_ready`, not periodic): one-off
  gap-recovery pipeline run when the service comes online (see §6).

Celery `task_failure` signal → [core/monitoring.py](core/monitoring.py) pushes a
Telegram ops alert (per-task cooldown `MONITORING_FAILURE_COOLDOWN_MIN`).

---

## 6. Data Flow

```
beat ──schedule──► worker
   fetch_market_data → yfinance → PriceData (upsert)
   fetch_news        → yfinance (per-ticker) + RSS feeds → NewsArticle (insert) → analyze_sentiment
      fetch_rss_news → feedparser → entities.match_symbols (NER) → NewsArticle per matched asset
   analyze_sentiment → FinBERT | keywords → sentiment_score/label
web (DRF) ──reads──► PostgreSQL ──JSON──► dashboard.html (charts)
   /api/indicators/  → indicators.compute_indicators(close series) → EMA/RSI/MACD JSON
   /api/correlation/ → correlation.compute_sentiment_correlation(news, prices) → Pearson/Spearman @1/3/7d
   /api/backtest/    → backtest.run_backtest(prices, news, params) → equity curve + trades + signals + metrics
   /api/news/        → reads NewsArticle (filter ?asset= &category= &relevant= &quality=verified|premium|quality|unverified)
   /api/ranking/     → reads AssetScore leaderboard (?limit= &order=top|bottom)
   /api/summary/     → home/overview snapshot: assets tracked, news 24h, avg sentiment 7d, alerts 7d, best/worst score (windows in constants.py)
   /api/portfolio/   → paper portfolio snapshot (cash, positions M2M, P&L, return, performance)
   /api/portfolio/history/ → PortfolioSnapshot equity curve
   ws/portfolio/     → WebSocket: same snapshot pushed live after each paper cycle
   /api/alerts/      → reads fired Alert rows
   /api/category-impact/ → category_impact.category_impact(category × forward_impact)
                       → which news themes move prices (home card; ?asset= optional)
   /api/backtest/optimize/ → backtest.grid_search(prices, news) → top param combos
                       ranked on train Sharpe with out-of-sample test metrics
   /healthz          → monitoring.health_status (DB+Redis liveness, 200/503; no auth)
   /wiki/            → static educational wiki page (WikiView; deep-link anchors
                       are the targets of the dashboard's contextual ℹ︎ icons)
beat ─► compute_rankings → ranking.rank_assets(per-asset sentiment+technical+momentum) → AssetScore upsert
beat ─► run_paper_trading → paper_trading (latest_signal + position_size) → realtime.broadcast (WS push)
   sells first (sentiment reversal / stop-loss) → buys strongest signals with cash
   → Position open/close + PaperTrade log + PortfolioSnapshot (mark-to-market)
beat ─► update_news_relevance → sources + relevance helpers
   classify_pending_sources    → NewsArticle.source_tier (curated quality registry; also set at ingest)
   categorize_pending_articles → NewsArticle.category/is_relevant (cold-start keyword vote)
   backfill_forward_impact     → NewsArticle.forward_impact (matures with price history)
beat ─► check_sentiment_alerts → alerts.run_sentiment_alert_check
   per asset: rolling avg sentiment (lookback) → threshold cross + cooldown
   → Alert (insert) → dispatch to log + Telegram/Discord/Email (if configured)
```

News ingest normalizes both the new (≥0.2.40, nested `content`) and legacy
yfinance `.news` schemas via `_normalize_news_item`. TA indicators, the
sentiment↔price correlation matrix, and the Phase 3 strategy backtest are all
computed **on read** from stored prices + scored news (no extra columns/tables). The correlation matrix is the measurement primitive
for the long-term self-calibration goal (learn news relevance from market
reaction over ~1 year) — recent articles without enough forward price history
are excluded, so the matrix populates as history accumulates.

### Startup (every container boot, via `entrypoint.sh`)
1. Wait for Postgres.
2. `web` only: `migrate` (`RUN_MIGRATIONS=True`) → `collectstatic` (`RUN_COLLECTSTATIC=True`,
   for WhiteNoise under DEBUG=False) → `bootstrap_assets --no-sentiment` (`RUN_BOOTSTRAP=True`).
3. `exec` the service command (prod: Daphne ASGI; dev override: runserver).

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
> via yfinance (the Phase 4 RSS feeds widen coverage but are likewise window-based,
> not a full archive). Price history is fully recoverable because fetches are
> window-based.

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
   FinBERT failures fall back to keyword scoring (`USE_REAL_NLP` flag) and zero-shot
   NLI categorization falls back to the keyword classifier (`USE_ZERO_SHOT_NLP`
   flag); a failing alert channel is logged and skipped without blocking the others.
8. **Single owner for migrations/bootstrap** (the `web` service) to avoid races.
9. **Production-safe defaults.** `DEBUG` defaults to **False**; `SECRET_KEY` is
   **required** when DEBUG=False (startup fails loudly otherwise); `ALLOWED_HOSTS`/
   `CSRF_TRUSTED_ORIGINS`/`SECURE_COOKIES` are env-driven; `DB_PASSWORD` has **no
   default** (compose refuses to start without it). Dev convenience lives only in
   `docker-compose.override.yml` + the local `.env` — the committed base compose is
   safe to run on a public VM. Never expose Postgres/Redis host ports in production;
   app access goes through the tailnet (no public ports).

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
  - ✅ Unit tests for indicator + correlation + alert logic ([core/tests/](core/tests/)).
- **Phase 3 — Backtesting engine ✅**
  - ✅ Pure pandas/numpy sentiment-strategy backtester via [core/backtest.py](core/backtest.py)
    (long-only, rolling-sentiment entry/exit + stop-loss, no look-ahead), served
    at `/api/backtest/?asset=&buy_threshold=&sell_threshold=&stop_loss_pct=&sentiment_window_days=&initial_capital=`.
  - ✅ Metrics: total return, buy & hold benchmark + **alpha**, **Sharpe**, **Sortino**,
    **max drawdown**, win rate, trade count; full equity curve + trade log + buy/sell signals.
    The risk/return math lives in the shared [core/metrics.py](core/metrics.py) (reused by Phase 5).
  - ✅ Execution costs: fills carry commission + adverse slippage via the shared
    [core/execution.py](core/execution.py) (same model as the paper trader, so a
    backtest and the live paper run of a strategy stay comparable). On by default;
    `run_backtest(commission_pct=, slippage_pct=)` can zero them to isolate logic.
  - ✅ Dashboard "Strategy Sandbox" card: tunable rule inputs, metric tiles, equity-curve
    area chart, and BUY/SELL markers overlaid on the price candles.
  - ✅ Unit tests for the engine ([core/tests/test_backtest.py](core/tests/test_backtest.py)); 35 tests total.
  - ⏭ Deferred: TimescaleDB and Backtrader/PyAlgoTrade — the pure-pandas engine is
    sufficient at current data scale and avoids the numpy 2.x dependency conflicts;
    revisit if history grows to millions of rows.
- **Phase 4 — Custom NLP & multi-source scrapers 🚧 (in progress)**
  - ✅ **Self-calibrating relevance filter — cold-start (rung 1 of 3).**
    [core/relevance.py](core/relevance.py): keyword-vote theme categorization
    (earnings, guidance, M&A, regulatory, geopolitics, monetary policy, corporate
    event; noise vs. signal) + per-article forward price impact at 1/3/7d (reuses
    the correlation primitive, no look-ahead). New `NewsArticle` fields
    `category`/`is_relevant`/`forward_impact` (migration 0003); `update_news_relevance`
    beat task + `startup_catch_up` wiring; `/api/news/?category=&relevant=` filters;
    dashboard relevance filter (theme dropdown + Tutte/Rilevanti/Rumore toggle),
    category badges, and forward-impact in the article drawer.
  - ✅ **Source quality registry.** [core/sources.py](core/sources.py) + curated
    `constants.SOURCE_REGISTRY` map each outlet to a tier (premium|quality|
    unverified) + country + language, so aggregators/opinion blogs (Insider
    Monkey, Stocktwits, Simply Wall St…) are separated from trusted press
    (Reuters, Bloomberg, FT, WSJ, Il Sole 24 Ore, Nikkei, Handelsblatt, NRC,
    Caixin…). `source_tier` set at ingest + backfilled (migration 0004); the
    dashboard defaults to "Solo verificate" with a per-article shield/tier badge,
    and `/api/news/?quality=` filters server-side. Yahoo Finance stays the feed;
    this is a quality layer on top of it (and the slot future RSS/Reddit feeds
    plug into). Unit tests ([test_relevance.py](core/tests/test_relevance.py),
    [test_sources.py](core/tests/test_sources.py)) + DB task tests
    ([test_relevance_tasks.py](core/tests/test_relevance_tasks.py)); 62 tests total.
  - ✅ **Zero-shot NLI categorization (rung 2 of 3).** Opt-in
    `facebook/bart-large-mnli` zero-shot classifier (`USE_ZERO_SHOT_NLP`, off by
    default) assigns the theme without training, scoring each article against the
    `NEWS_CATEGORY_NLI_HYPOTHESES`; below `NLI_MIN_CONFIDENCE` it stays
    uncategorized. Lazy `get_zeroshot_pipeline()` loader (CPU, shared HF cache);
    `categorize_pending_articles` uses it when enabled and **falls back per-article
    to the keyword cold-start on any model failure** (same contract as FinBERT).
    `recategorize_all()` upgrades existing keyword-tagged rows. Pure decode tested
    + DB/mock tests; 69 tests total.
  - ✅ **Entity linking (NER) + multi-source RSS ingestion.**
    [core/entities.py](core/entities.py) links a general article to tracked assets
    via a per-asset alias dictionary (symbol + cleaned company name + curated
    `ASSET_ALIASES`, whole-word match) — reliable for a known universe; a
    model-based NER can be layered later. [core/rss.py](core/rss.py) (feedparser,
    lazy import) + curated `constants.RSS_FEEDS` (25 feeds across 11 countries —
    US/UK/DE/FR/IT/NL/ES/JP/HK/SG/IN, all validated live) pull quality newspapers;
    `fetch_rss_news` normalizes entries, attributes each to assets via
    NER, stores one row per matched asset (dedup on (asset, url)), tags
    `source_tier`, and degrades gracefully per dead feed. Gated by
    `RSS_INGEST_ENABLED` (default on), wired into `fetch_news` + `startup_catch_up`.
    Pure tests ([test_entities.py](core/tests/test_entities.py),
    [test_rss.py](core/tests/test_rss.py)) + DB/mock task tests; 86 tests total.
  - ✅ **Global top ~500 universe.** The tracked set is the worldwide top ~500 by
    market cap ([core/data/global_top500.csv](core/data/global_top500.csv),
    yfinance-validated; 5 unlisted tickers pruned), loaded by
    [core/universe.py](core/universe.py) and seeded idempotently. Scaling: prices
    fetched via batched multi-ticker `yf.download` (`fetch_prices_batched`); bootstrap
    deep-backfills only assets without history (no re-upsert every boot); yfinance
    per-ticker news capped to a random sample per cycle (`YFINANCE_NEWS_MAX_ASSETS`),
    with the broad universe covered by RSS + NER. Users can still add/remove assets.
  - ✅ **Composite "Top Opportunità" ranking.** [core/ranking.py](core/ranking.py)
    blends sentiment level + sentiment momentum + a technical read (RSI/MACD) +
    price momentum into a transparent 0–100 score per asset (weights/windows in
    constants; components exposed for explainability). Computed by the
    `compute_rankings` task into `AssetScore` (snapshot, fast reads), served at
    `/api/ranking/`, and shown as a prominent dashboard leaderboard (Migliori /
    Peggiori, click-to-open). Labeled "not investment advice". Pure + DB tests.
  - ✅ **Category-impact analysis (pre-rung-3 measurement).**
    [core/category_impact.py](core/category_impact.py) crosses the stored
    `category` × `forward_impact` fields into per-theme stats (mean |return|,
    signed mean, "mover" rate at +1/3/7d vs `CATEGORY_IMPACT_MOVE_THRESHOLD_PCT`).
    Served at `/api/category-impact/` (`?asset=` optional) and shown as the
    "Quali temi muovono i prezzi" home card. Pure + endpoint tests.
  - ✅ **Earnings calendar.** `Asset.next_earnings_date`/`earnings_checked_at`
    (migration 0007), refreshed by the daily `refresh_earnings_calendar` task in
    rotating batches (yfinance `.calendar`, both dict and legacy DataFrame
    shapes); `days_to_earnings` in the Asset API; amber "Earnings tra Xg" badge
    in the asset detail header. Pure + DB/mock tests.
  - ⚠️ **REMINDER — rung 3 of 3 is DEFERRED, not done.** The self-supervised
    relevance classifier fine-tuned on the accumulated `forward_impact` labels —
    **the core of the self-calibration vision** — still has to be built. It was
    postponed on 2026-06-04 only because there isn't enough resolved
    `forward_impact` history yet to train on ("needs ~a week+ of data"; real
    target ~1 year). **When the history matures, build it:** auto-label an
    article market-moving when |forward return| exceeds a noise threshold, fit a
    lightweight classifier (scikit-learn over text features / FinBERT embeddings),
    persist it, and refresh on a schedule. Also still open in Phase 4: Reddit
    ingestion (PRAW), model-based NER for unknown orgs, local FinBERT fine-tuning;
    Twitter/X deferred on API cost.
- **Phase 5 — Paper/live trading ✅ (closed 2026-06-10 — broker & multi-user deferred)**
  - ✅ **Virtual paper-trading portfolio (foundation).** A local, no-risk
    portfolio running the Phase 3 sentiment strategy forward in time.
    [core/paper_trading.py](core/paper_trading.py) holds the pure engine
    (`rolling_sentiment`, `latest_signal`, `position_size`, `execution_price`,
    `commission`); `run_paper_trading` (beat + `startup_catch_up`) orchestrates a
    cycle via thin helpers in [core/tasks.py](core/tasks.py): sell on sentiment
    reversal / stop-loss, then buy the strongest fresh signals (fraction-of-equity
    sizing, max-positions cap, verified-source news only), then snapshot the equity.
    Models Portfolio / Position / PaperTrade / PortfolioSnapshot (migration 0006);
    `/api/portfolio/` + `/api/portfolio/history/`; dashboard "Paper Trading" section
    (value, return, P&L, positions, trades, equity curve). Labeled "not investment
    advice, no real money".
  - ✅ **Realistic execution costs.** Every fill carries commission
    (`TRADING_COMMISSION_PCT`) + adverse slippage (`TRADING_SLIPPAGE_PCT`) via the
    shared [core/execution.py](core/execution.py) so the equity curve isn't
    optimistic; costs only ever make results worse. Round-trip `realized_pnl` nets
    both sides' fees. The **same model is applied to the Phase 3 backtester**, so
    paper and backtest of one strategy are directly comparable.
  - ✅ **Live performance metrics.** `PortfolioView` returns a `performance` block
    (Sharpe, Sortino, max drawdown, win rate, equal-weight Buy & Hold benchmark of
    the traded names, and alpha) computed from snapshots + closed trades via the
    shared [core/metrics.py](core/metrics.py) — same math as the Phase 3 backtest,
    so paper and backtest stay comparable. Shown as a "Performance" tile row in the
    dashboard with plain-language tooltips.
  - ✅ **Real-time WebSocket streaming.** Django Channels over the Redis channel
    layer: [core/consumers.py](core/consumers.py) `PortfolioConsumer` (route
    `ws/portfolio/` in [core/routing.py](core/routing.py)) sends a snapshot on
    connect, then relays each push; [core/realtime.py](core/realtime.py) broadcasts
    the fresh snapshot after every paper-trading cycle. The REST endpoint and the
    socket share one payload builder ([core/portfolio.py](core/portfolio.py)).
    [asgi.py](finance_buddy/asgi.py) routes HTTP→Django + WS→Channels; `daphne`
    leads `INSTALLED_APPS` so `runserver` serves ASGI. The dashboard subscribes and
    updates the tiles/positions/trades/equity-curve live, with a 60s polling
    fallback + auto-reconnect when the socket drops. Tests use the in-memory layer
    (no Redis needed).
  - Pure tests ([test_paper_trading.py](core/tests/test_paper_trading.py) +
    [test_metrics.py](core/tests/test_metrics.py)) + DB cycle tests
    ([test_paper_trading_tasks.py](core/tests/test_paper_trading_tasks.py)) +
    consumer tests ([test_consumers.py](core/tests/test_consumers.py));
    149 tests total.
  - ⏭ Deferred (phase closed without them, 2026-06-10): Alpaca paper-broker API
    and multi-user portfolios. Rationale: the internal simulation already models
    costs + metrics, so a paper broker adds no simulation value; a broker is only
    the on-ramp to live money (real risk, out of scope), and the stack runs
    on-demand/intermittently — incompatible with a live broker bot. Multi-user
    only matters alongside per-user broker keys (single-user self-hosted → YAGNI).
    Revisit both only if/when going live with real money.
- **Ops / server readiness ✅ (2026-06-11)**
  - `/healthz` liveness endpoint (DB+Redis, 200/503) for external uptime monitors.
  - Celery `task_failure` → Telegram ops alert with per-task cooldown
    ([core/monitoring.py](core/monitoring.py), registered in `CoreConfig.ready()`).
  - Weekly data-health Telegram report (`send_health_report`, Mon 08:00) sharing
    its aggregation with the `data_status` management command.
  - Grid search "Ottimizza" in the Strategy Sandbox: `backtest.grid_search`
    (chronological train/test split, ranked on train Sharpe, out-of-sample
    metrics alongside; click-to-apply params), `/api/backtest/optimize/`.
  - Compose `mem_limit` per service (worker 8g for FinBERT) + daily
    [scripts/backup_db.sh](scripts/backup_db.sh) (pg_dump, 14-day rotation,
    `backup/` gitignored).
- **Phase 6 — Knowledge Base / educational wiki ✅**
  - ✅ `/wiki/` route (`WikiView`, static template
    [core/templates/core/wiki.html](core/templates/core/wiki.html)) with the
    dashboard's design system (Tailwind glassmorphism, Outfit/Inter, Alpine).
  - ✅ 7 themed sections + alphabetical glossary, ~40 entries; every entry follows
    the fixed structure *definizione → spiegazione semplice → esempio numerico →
    formula (KaTeX) → dove lo vedi nell'app*, Italian text with the standard
    English term alongside.
  - ✅ Sidebar index with scroll-tracked active section, live text search
    (filters entries + sections), deep-linkable anchors (e.g. `/wiki/#sharpe`).
  - ✅ Contextual ℹ︎ deep-links from the dashboard (Top Opportunità, Paper
    Trading, Equity Curve, Performance, price chart/EMA, RSI, MACD, correlation
    matrix, Strategy Sandbox) + a Wiki button in the sidebar header.
  - ✅ Smoke tests pin the route, template, and the anchor ids the dashboard
    links to ([core/tests/test_wiki.py](core/tests/test_wiki.py)).

---

## 🔄 Maintenance Rule

**On every iteration that changes structure**, update this file in the same
commit: bump *Last updated*, adjust the relevant section (structure, model,
components, conventions), and move the Phase Status when a roadmap phase
completes. This rule is also encoded as the project skill
[`.claude/skills/architecture-sync`](.claude/skills/architecture-sync/SKILL.md)
and referenced from [CLAUDE.md](CLAUDE.md).
