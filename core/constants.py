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
