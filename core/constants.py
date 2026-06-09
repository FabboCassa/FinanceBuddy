"""Centralized constants for the core app.

Keeping seed data and tuning parameters here (instead of inline in tasks)
makes Phase 1 bootstrapping deterministic and easy to evolve.
"""

# Default assets seeded on first boot / via `bootstrap_assets`.
# Each entry is immutable config consumed by get_or_create.
DEFAULT_ASSETS = (
    {'symbol': 'AAPL', 'name': 'Apple Inc.', 'asset_type': 'Stock'},
    {'symbol': 'MSFT', 'name': 'Microsoft Corporation', 'asset_type': 'Stock'},
    {'symbol': 'SWDA.MI', 'name': 'iShares Core MSCI World UCITS ETF', 'asset_type': 'ETF'},
)

# Periodic (15-min) price refresh: dense, recent data for live charts.
RECENT_PRICE_PERIOD = '30d'
RECENT_PRICE_INTERVAL = '1h'

# Fallback when intraday data is unavailable for an asset.
FALLBACK_PRICE_PERIOD = '90d'
FALLBACK_PRICE_INTERVAL = '1d'

# Bootstrap seeding: deep historical backfill executed once at startup.
BOOTSTRAP_PRICE_PERIOD = '2y'
BOOTSTRAP_PRICE_INTERVAL = '1d'

# Keyword lexicons for the simulated (no-GPU) sentiment fallback.
POSITIVE_KEYWORDS = (
    'surge', 'gain', 'profit', 'rise', 'up', 'bull', 'growth', 'buy',
    'beat', 'higher', 'positive', 'outperform', 'strong',
)
NEGATIVE_KEYWORDS = (
    'drop', 'loss', 'fall', 'down', 'bear', 'sell', 'debt', 'miss',
    'lower', 'negative', 'underperform', 'weak', 'plunge', 'warn',
)

# FinBERT label -> localized label used in the DB / UI.
SENTIMENT_LABEL_MAP = {
    'positive': 'Positivo',
    'neutral': 'Neutrale',
    'negative': 'Negativo',
}

# -- Phase 2: Technical analysis indicator parameters -----------------------
# EMA look-back windows overlaid on the price candles.
EMA_PERIODS = (20, 50, 200)
# RSI (Wilder) look-back window.
RSI_PERIOD = 14
# MACD fast/slow EMA spans + signal-line span.
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# Forward-return horizons (days) for the sentiment↔price correlation matrix.
CORRELATION_HORIZONS_DAYS = (1, 3, 7)
# Minimum paired samples before a correlation coefficient is reported.
CORRELATION_MIN_SAMPLES = 3

# -- Phase 2: Sentiment alert thresholds (defaults; env can override) -------
# Average sentiment at/below LOW → bearish ("panic") alert; at/above HIGH →
# bullish ("euphoria") alert. Scale matches sentiment_score (-1.0 … +1.0).
SENTIMENT_ALERT_LOW = -0.6
SENTIMENT_ALERT_HIGH = 0.6
# Rolling window of recent scored articles considered per asset.
ALERT_LOOKBACK_HOURS = 24
# Minimum gap before the same asset/level can re-fire (dedupe / anti-spam).
ALERT_COOLDOWN_HOURS = 12
# Minimum scored articles in the window before an alert may fire.
ALERT_MIN_ARTICLES = 3

# -- Phase 3: Sentiment-strategy backtesting defaults -----------------------
# Long-only sandbox strategy: go fully long when the rolling-average sentiment
# rises at/above BUY, flatten when it falls at/below SELL or a stop-loss trips.
# Scale matches sentiment_score (-1.0 … +1.0).
BACKTEST_BUY_THRESHOLD = 0.5
BACKTEST_SELL_THRESHOLD = 0.1
# Trailing window (calendar days) for the rolling mean of daily sentiment.
BACKTEST_SENTIMENT_WINDOW_DAYS = 3
# Stop-loss: exit if close falls this fraction below the entry price (0 = off).
BACKTEST_STOP_LOSS_PCT = 0.03
# Starting virtual capital for the equity curve.
BACKTEST_INITIAL_CAPITAL = 10000.0
# Annualization + risk-free assumptions for risk-adjusted ratios.
BACKTEST_TRADING_DAYS_PER_YEAR = 252
BACKTEST_RISK_FREE_RATE = 0.0
# Minimum daily closes required before a backtest is attempted.
BACKTEST_MIN_DAYS = 5

# -- Phase 4: News relevance / self-calibration (cold-start) ----------------
# Theme taxonomy for the relevance filter. The cold-start classifier assigns one
# category per article by keyword voting (no training). Later Phase 4 rungs
# refine this: zero-shot NLI, then a self-supervised model trained on the real
# forward price impact recorded below — the system is meant to *learn* what
# matters from market reaction, so these keywords only bootstrap the loop.
NEWS_CATEGORY_UNCATEGORIZED = 'uncategorized'
NEWS_CATEGORY_NOISE = 'noise'

# Signal themes known a priori to move prices (used to bootstrap relevance).
NEWS_CATEGORY_KEYWORDS = {
    'earnings': ('earnings', 'revenue', 'profit', 'eps', 'quarterly', 'results',
                 'q1', 'q2', 'q3', 'q4', 'beats', 'misses', 'net income', 'margin'),
    'guidance': ('guidance', 'forecast', 'outlook', 'raises', 'lowers',
                 'expects', 'projection', 'cuts forecast'),
    'm_and_a': ('merger', 'acquisition', 'acquire', 'takeover', 'buyout',
                'deal', 'stake', 'bid'),
    'regulatory': ('regulator', 'antitrust', 'lawsuit', 'sue', 'fine', 'probe',
                   'investigation', 'sec ', 'ftc', 'ruling', 'settlement'),
    'geopolitics': ('tariff', 'sanction', 'war', 'conflict', 'election',
                    'trade war', 'export ban', 'geopolitical'),
    'monetary_policy': ('fed', 'rate hike', 'rate cut', 'inflation', 'interest rate',
                        'central bank', 'ecb', 'powell', 'cpi', 'monetary'),
    'corporate_event': ('ceo', 'launch', 'unveil', 'conference', 'partnership',
                        'dividend', 'buyback', 'stock split'),
}
# Noise themes to discard (not price-relevant).
NEWS_NOISE_KEYWORDS = ('celebrity', 'gossip', 'sport', 'football', 'soccer',
                       'crime', 'arrest', 'weather', 'recipe', 'lifestyle')

# Categories considered price-relevant (everything except noise/uncategorized).
RELEVANT_NEWS_CATEGORIES = frozenset(NEWS_CATEGORY_KEYWORDS.keys())

# Localized display labels for the UI (Italian + standard English term).
NEWS_CATEGORY_LABELS = {
    'earnings': 'Bilanci (Earnings)',
    'guidance': 'Stime (Guidance)',
    'm_and_a': 'Fusioni/Acquisizioni (M&A)',
    'regulatory': 'Regolatorio',
    'geopolitics': 'Geopolitica',
    'monetary_policy': 'Politica monetaria',
    'corporate_event': 'Evento aziendale',
    NEWS_CATEGORY_NOISE: 'Rumore',
    NEWS_CATEGORY_UNCATEGORIZED: 'Non categorizzato',
}

# Forward-return horizons (days) recorded per article as its price impact —
# the supervision signal for the self-calibrating relevance model. Shares the
# correlation horizons so per-article impact and the aggregate matrix align.
FORWARD_IMPACT_HORIZONS_DAYS = CORRELATION_HORIZONS_DAYS

# -- Phase 4: news source quality registry ----------------------------------
# Curated allowlist of reputable outlets. Each article's reported `source` is
# matched (case-insensitive substring on the aliases) to assign a quality tier;
# the dashboard defaults to verified-quality outlets so low-signal aggregators
# and opinion blogs don't pollute the analysis. Any new feed (RSS, Reddit, …)
# plugs into the very same tiers — keep Yahoo as a source, just tag it.
SOURCE_TIER_PREMIUM = 'premium'        # global wires + flagship financial press
SOURCE_TIER_QUALITY = 'quality'        # reputable national / quality outlets
SOURCE_TIER_UNVERIFIED = 'unverified'  # aggregators, advice blogs, social — low signal

# Tiers considered trustworthy enough to drive analysis by default.
VERIFIED_SOURCE_TIERS = frozenset({SOURCE_TIER_PREMIUM, SOURCE_TIER_QUALITY})

# canonical outlet → (tier, country, language, alias substrings matched lowercase).
SOURCE_REGISTRY = {
    # — Global wires & flagship financial press —
    'Reuters':                  (SOURCE_TIER_PREMIUM, 'Global', 'en', ('reuters',)),
    'Bloomberg':                (SOURCE_TIER_PREMIUM, 'US', 'en', ('bloomberg',)),
    'Associated Press':         (SOURCE_TIER_PREMIUM, 'US', 'en', ('associated press', 'ap news')),
    'Dow Jones Newswires':      (SOURCE_TIER_PREMIUM, 'US', 'en', ('dow jones',)),
    'Financial Times':          (SOURCE_TIER_PREMIUM, 'UK', 'en', ('financial times', 'ft.com')),
    'The Wall Street Journal':  (SOURCE_TIER_PREMIUM, 'US', 'en', ('wall street journal', 'wsj')),
    'The Economist':            (SOURCE_TIER_PREMIUM, 'UK', 'en', ('economist',)),
    'CNBC':                     (SOURCE_TIER_PREMIUM, 'US', 'en', ('cnbc',)),
    "Barron's":                 (SOURCE_TIER_PREMIUM, 'US', 'en', ('barron',)),
    'Nikkei':                   (SOURCE_TIER_PREMIUM, 'JP', 'ja', ('nikkei',)),
    # — Reputable national / quality outlets —
    'MarketWatch':              (SOURCE_TIER_QUALITY, 'US', 'en', ('marketwatch',)),
    'Yahoo Finance':            (SOURCE_TIER_QUALITY, 'US', 'en', ('yahoo finance',)),
    'The New York Times':       (SOURCE_TIER_QUALITY, 'US', 'en', ('new york times', 'nytimes')),
    'Fortune':                  (SOURCE_TIER_QUALITY, 'US', 'en', ('fortune',)),
    'The Guardian':             (SOURCE_TIER_QUALITY, 'UK', 'en', ('guardian',)),
    'The Telegraph':            (SOURCE_TIER_QUALITY, 'UK', 'en', ('telegraph',)),
    'BBC':                      (SOURCE_TIER_QUALITY, 'UK', 'en', ('bbc',)),
    'Il Sole 24 Ore':           (SOURCE_TIER_QUALITY, 'IT', 'it', ('sole 24', 'ilsole24ore')),
    'ANSA':                     (SOURCE_TIER_QUALITY, 'IT', 'it', ('ansa',)),
    'Corriere della Sera':      (SOURCE_TIER_QUALITY, 'IT', 'it', ('corriere della sera', 'corriere.it')),
    'Handelsblatt':             (SOURCE_TIER_QUALITY, 'DE', 'de', ('handelsblatt',)),
    'Frankfurter Allgemeine':   (SOURCE_TIER_QUALITY, 'DE', 'de', ('frankfurter allgemeine', 'faz.net', 'faz')),
    'Der Spiegel':              (SOURCE_TIER_QUALITY, 'DE', 'de', ('spiegel',)),
    'NRC':                      (SOURCE_TIER_QUALITY, 'NL', 'nl', ('nrc',)),
    'Het Financieele Dagblad':  (SOURCE_TIER_QUALITY, 'NL', 'nl', ('financieele dagblad', 'fd.nl')),
    'Caixin':                   (SOURCE_TIER_QUALITY, 'CN', 'zh', ('caixin',)),
    'South China Morning Post': (SOURCE_TIER_QUALITY, 'HK', 'en', ('south china morning post', 'scmp')),
    'Les Échos':                (SOURCE_TIER_QUALITY, 'FR', 'fr', ('echos', 'échos')),
    'Le Monde':                 (SOURCE_TIER_QUALITY, 'FR', 'fr', ('le monde',)),
    'El País':                  (SOURCE_TIER_QUALITY, 'ES', 'es', ('el país', 'el pais', 'elpais')),
    'Expansión':                (SOURCE_TIER_QUALITY, 'ES', 'es', ('expansión', 'expansion')),
    'The Japan Times':          (SOURCE_TIER_QUALITY, 'JP', 'en', ('japan times',)),
    'The Straits Times':        (SOURCE_TIER_QUALITY, 'SG', 'en', ('straits times',)),
    'The Economic Times':       (SOURCE_TIER_QUALITY, 'IN', 'en', ('economic times',)),
}

# Localized labels for the quality tiers (UI).
SOURCE_TIER_LABELS = {
    SOURCE_TIER_PREMIUM: 'Testata primaria',
    SOURCE_TIER_QUALITY: 'Testata di qualità',
    SOURCE_TIER_UNVERIFIED: 'Non verificata',
}

# -- Phase 4 (rung 2): zero-shot NLI categorization -------------------------
# Optional upgrade over the keyword cold-start: a zero-shot entailment model
# assigns the theme without training. Off by default (heavy model download);
# enable with USE_ZERO_SHOT_NLP=True. Falls back to keywords on any failure.
ZERO_SHOT_MODEL = 'facebook/bart-large-mnli'
# Minimum top-label confidence before trusting the zero-shot verdict; below this
# the article stays uncategorized rather than being force-labeled.
NLI_MIN_CONFIDENCE = 0.5

# Natural-language hypotheses the entailment model scores each article against.
NEWS_CATEGORY_NLI_HYPOTHESES = {
    'earnings': 'company quarterly earnings, revenue or profit results',
    'guidance': 'company financial guidance, forecast or outlook',
    'm_and_a': 'a merger, acquisition or takeover deal',
    'regulatory': 'regulation, antitrust, a lawsuit or a government investigation',
    'geopolitics': 'geopolitics, tariffs, sanctions, war or elections',
    'monetary_policy': 'central bank monetary policy, interest rates or inflation',
    'corporate_event': 'a corporate event, product launch, leadership change, dividend or buyback',
    NEWS_CATEGORY_NOISE: 'celebrity gossip, sports or news unrelated to finance',
}
# Inverse map (hypothesis string → category key) for decoding model output.
NLI_HYPOTHESIS_TO_CATEGORY = {v: k for k, v in NEWS_CATEGORY_NLI_HYPOTHESES.items()}

# -- Phase 4: entity linking (NER) + RSS multi-source ingestion -------------
# Curated extra aliases per tracked asset, beyond the symbol + company name
# (which are derived automatically). Used to attribute general RSS articles to
# the right asset. A model-based NER can be layered on later for unknown orgs.
ASSET_ALIASES = {
    'AAPL': ('apple', 'iphone'),
    'MSFT': ('microsoft', 'azure', 'windows maker'),
    'SWDA.MI': ('ishares core msci world', 'msci world'),
}
# Minimum alias length to match on (avoids ambiguous 1–2 char hits).
NER_MIN_ALIAS_LEN = 3
# Company/exchange suffixes stripped when deriving an alias from the asset name.
COMPANY_NAME_SUFFIXES = (
    'inc', 'incorporated', 'corporation', 'corp', 'company', 'co', 'ltd',
    'limited', 'plc', 'sa', 'ag', 'nv', 'spa', 'group', 'holdings', 'the',
)

# Whether RSS multi-source ingestion runs (set False to rely on yfinance only).
# Per-feed errors are always logged and skipped (graceful degradation).
RSS_INGEST_ENABLED_DEFAULT = True
# Curated quality RSS feeds (general-interest; items linked to assets via NER).
# `source` must match a SOURCE_REGISTRY alias so the tier/country/language carry
# over. All URLs validated live (returning entries) as of 2026-06; tune freely —
# dead/region-locked feeds are logged and skipped without failing the run.
RSS_FEEDS = (
    # — United States —
    {'source': 'CNBC',                'url': 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114'},
    {'source': 'MarketWatch',         'url': 'http://feeds.marketwatch.com/marketwatch/topstories/'},
    {'source': 'Yahoo Finance',       'url': 'https://finance.yahoo.com/news/rssindex'},
    {'source': 'The New York Times',  'url': 'https://rss.nytimes.com/services/xml/rss/nyt/Business.xml'},
    {'source': 'Fortune',             'url': 'https://fortune.com/feed/'},
    # — United Kingdom —
    {'source': 'Financial Times',     'url': 'https://www.ft.com/rss/home'},
    {'source': 'The Guardian',        'url': 'https://www.theguardian.com/uk/business/rss'},
    {'source': 'The Telegraph',       'url': 'https://www.telegraph.co.uk/business/rss.xml'},
    {'source': 'BBC',                 'url': 'https://feeds.bbci.co.uk/news/business/rss.xml'},
    {'source': 'The Economist',       'url': 'https://www.economist.com/finance-and-economics/rss.xml'},
    # — Germany —
    {'source': 'Handelsblatt',        'url': 'https://www.handelsblatt.com/contentexport/feed/finanzen'},
    {'source': 'Frankfurter Allgemeine', 'url': 'https://www.faz.net/rss/aktuell/wirtschaft/'},
    {'source': 'Der Spiegel',         'url': 'https://www.spiegel.de/wirtschaft/index.rss'},
    # — France —
    {'source': 'Le Monde',            'url': 'https://www.lemonde.fr/economie/rss_full.xml'},
    # — Italy —
    {'source': 'ANSA',                'url': 'https://www.ansa.it/sito/notizie/economia/economia_rss.xml'},
    {'source': 'Il Sole 24 Ore',      'url': 'https://www.ilsole24ore.com/rss/finanza.xml'},
    {'source': 'Corriere della Sera', 'url': 'https://xml2.corriereobjects.it/rss/economia.xml'},
    # — Netherlands —
    {'source': 'NRC',                 'url': 'https://www.nrc.nl/rss/'},
    # — Spain —
    {'source': 'El País',             'url': 'https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/economia/portada'},
    {'source': 'Expansión',           'url': 'https://e00-expansion.uecdn.es/rss/portada.xml'},
    # — Asia —
    {'source': 'Nikkei',              'url': 'https://asia.nikkei.com/rss/feed/nar'},
    {'source': 'The Japan Times',     'url': 'https://www.japantimes.co.jp/feed/'},
    {'source': 'South China Morning Post', 'url': 'https://www.scmp.com/rss/92/feed'},
    {'source': 'The Straits Times',   'url': 'https://www.straitstimes.com/news/business/rss.xml'},
    {'source': 'The Economic Times',  'url': 'https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms'},
)
# Cap entries processed per feed per run (recent items only).
RSS_MAX_ENTRIES_PER_FEED = 40

# -- Phase 4: scaling for a large (~500) asset universe ---------------------
# yfinance prices are fetched in batches (one multi-ticker download per batch)
# instead of one call per asset, so a 500-name universe stays tractable.
PRICE_FETCH_BATCH_SIZE = 50
# yfinance per-ticker NEWS doesn't batch, so each cycle only a random sample of
# assets is polled that way; the broad universe gets news via RSS + NER instead.
YFINANCE_NEWS_MAX_ASSETS_DEFAULT = 40

# -- Phase 4: composite "Top Opportunità" ranking ---------------------------
# A transparent 0–100 opportunity score per asset, blending sentiment level,
# sentiment momentum, a technical read (RSI/MACD), and price momentum. Weights
# sum to 1.0 and are tunable; each component is normalized to [-1, 1] first.
RANK_WEIGHT_SENTIMENT = 0.35
RANK_WEIGHT_SENTIMENT_MOMENTUM = 0.20
RANK_WEIGHT_TECHNICAL = 0.25
RANK_WEIGHT_MOMENTUM = 0.20

# Sentiment windows (days): recent vs the preceding block (for momentum).
RANK_RECENT_WINDOW_DAYS = 7
RANK_PRIOR_WINDOW_DAYS = 7
# Minimum scored articles in the recent window for the sentiment component to
# count; below this the asset is flagged low-news and scored sentiment-neutral.
RANK_MIN_ARTICLES = 3
# Price-momentum look-back (trading days) and the return that maps to full ±1.
RANK_MOMENTUM_WINDOW_DAYS = 5
RANK_MOMENTUM_FULL_SCALE = 0.10  # a ±10% move saturates the momentum component
# RSI zones for the technical component.
RANK_RSI_OVERBOUGHT = 70
RANK_RSI_OVERSOLD = 30
# Daily closes loaded per asset to compute the technical read.
RANK_TECH_LOOKBACK_DAYS = 60

# -- Phase 5: paper trading (virtual portfolio) -----------------------------
# A local, no-risk virtual portfolio that runs the Phase 3 sentiment strategy
# forward in time: each cycle it computes the latest rolling-sentiment signal
# per asset and places virtual BUY/SELL orders. No broker, no real money — the
# foundation Alpaca/WebSocket integrations later build on. All money is play
# money tracked as floats (a simulation, not accounting).
PAPER_DEFAULT_PORTFOLIO_NAME = 'Default'
PAPER_INITIAL_CAPITAL = 10000.0

# The strategy mirrors the backtest sandbox so paper results stay comparable.
PAPER_BUY_THRESHOLD = BACKTEST_BUY_THRESHOLD      # enter when rolling sentiment ≥ this
PAPER_SELL_THRESHOLD = BACKTEST_SELL_THRESHOLD    # exit when rolling sentiment ≤ this
PAPER_STOP_LOSS_PCT = BACKTEST_STOP_LOSS_PCT      # also exit if price falls this far below entry
PAPER_SENTIMENT_WINDOW_DAYS = BACKTEST_SENTIMENT_WINDOW_DAYS  # trailing window for the mean

# Portfolio construction / risk caps.
PAPER_MAX_POSITIONS = 10          # diversification cap (max simultaneous holdings)
PAPER_POSITION_FRACTION = 0.10    # target slice of total equity per new position
PAPER_MIN_TRADE_VALUE = 50.0      # skip dust orders below this cash value

# Execution costs — keep the simulation honest. A frictionless fill flatters the
# strategy; modelling cost makes the equity curve comparable to a real account.
#   * commission: a flat % fee charged on each side's gross trade value.
#   * slippage:   the fill is adverse to the observed close — a BUY pays slightly
#                 up, a SELL receives slightly less (models spread/market impact).
# Both are deliberately modest defaults (tunable via env later) and only ever
# make results worse, never better, so performance is not optimistic. Shared by
# BOTH the paper trader (Phase 5) and the backtester (Phase 3) via core/execution.py,
# so a backtest and the live paper run of the same strategy stay comparable.
TRADING_COMMISSION_PCT = 0.001    # 0.10% per side (broker fee / effective spread)
TRADING_SLIPPAGE_PCT = 0.0005     # 0.05% adverse fill vs. the reference close
# Back-compat aliases (the cost model is strategy-agnostic, not paper-only).
PAPER_COMMISSION_PCT = TRADING_COMMISSION_PCT
PAPER_SLIPPAGE_PCT = TRADING_SLIPPAGE_PCT
# Only act on sentiment from verified, non-noise news (reuses VERIFIED_SOURCE_TIERS).
PAPER_MIN_SENTIMENT_ARTICLES = 1  # min scored articles in the window to trust a signal
# How far back to look for a tradable "latest close" (markets close on weekends/
# holidays, so a few days isn't enough; mirror the recent-price window).
PAPER_PRICE_LOOKBACK_DAYS = 30
