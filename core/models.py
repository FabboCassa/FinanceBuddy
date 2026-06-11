from django.db import models

class Asset(models.Model):
    ASSET_TYPES = [
        ('Stock', 'Stock'),
        ('ETF', 'ETF'),
    ]
    
    symbol = models.CharField(max_length=20, unique=True, primary_key=True, help_text="e.g., AAPL or SWDA.MI")
    name = models.CharField(max_length=255)
    asset_type = models.CharField(max_length=10, choices=ASSET_TYPES, default='Stock')

    # Earnings calendar (Phase 4 enrichment): next scheduled report date, if
    # known. Refreshed in rotating daily batches by `refresh_earnings_calendar`
    # (earnings_checked_at drives the rotation: oldest-checked first).
    next_earnings_date = models.DateField(null=True, blank=True)
    earnings_checked_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.symbol} - {self.name} ({self.asset_type})"


class PriceData(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='prices')
    timestamp = models.DateTimeField(db_index=True)
    open = models.DecimalField(max_digits=14, decimal_places=4)
    high = models.DecimalField(max_digits=14, decimal_places=4)
    low = models.DecimalField(max_digits=14, decimal_places=4)
    close = models.DecimalField(max_digits=14, decimal_places=4)
    volume = models.BigIntegerField()

    class Meta:
        ordering = ['timestamp']
        unique_together = ('asset', 'timestamp')
        indexes = [
            models.Index(fields=['asset', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.asset.symbol} @ {self.timestamp.strftime('%Y-%m-%d %H:%M')}: C={self.close}"


class NewsArticle(models.Model):
    SENTIMENT_LABELS = [
        ('Positivo', 'Positivo'),
        ('Neutrale', 'Neutrale'),
        ('Negativo', 'Negativo'),
    ]

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='news')
    timestamp = models.DateTimeField(db_index=True)
    title = models.CharField(max_length=500)
    source = models.CharField(max_length=100)
    url = models.URLField(max_length=1000)
    extracted_text = models.TextField(blank=True, default='')
    sentiment_score = models.FloatField(null=True, blank=True, help_text="Between -1.0 and +1.0")
    sentiment_label = models.CharField(max_length=15, choices=SENTIMENT_LABELS, null=True, blank=True)

    # -- Phase 4: self-calibrating relevance filter -------------------------
    category = models.CharField(
        max_length=20, null=True, blank=True, db_index=True,
        help_text="Theme category (cold-start keyword vote; refined by later NLP stages).",
    )
    is_relevant = models.BooleanField(
        null=True, blank=True,
        help_text="Whether the category is price-relevant; null = unknown (not yet decided).",
    )
    forward_impact = models.JSONField(
        null=True, blank=True,
        help_text="Forward % return at 1/3/7d from publish — supervision signal for self-calibration.",
    )
    source_tier = models.CharField(
        max_length=12, null=True, blank=True, db_index=True,
        help_text="Source quality tier (premium|quality|unverified) from the curated registry.",
    )

    class Meta:
        ordering = ['-timestamp']
        unique_together = ('asset', 'url')  # Avoid duplicate news entries for same asset
        indexes = [
            models.Index(fields=['asset', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.asset.symbol} - {self.title[:50]}... [{self.sentiment_label or 'No Sentiment'}]"


class Alert(models.Model):
    """A fired sentiment-threshold alert (Phase 2).

    Persisted to support cooldown/dedupe and to surface a history in the UI.
    """
    LEVELS = [
        ('Positivo', 'Positivo'),
        ('Negativo', 'Negativo'),
    ]

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='alerts')
    level = models.CharField(max_length=15, choices=LEVELS)
    avg_sentiment = models.FloatField(help_text="Rolling average sentiment that triggered the alert.")
    article_count = models.PositiveIntegerField(default=0)
    message = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['asset', 'level', 'created_at']),
        ]

    def __str__(self):
        return f"[{self.level}] {self.asset.symbol} @ {self.created_at:%Y-%m-%d %H:%M} (avg={self.avg_sentiment:.2f})"


class AssetScore(models.Model):
    """Latest composite "Top Opportunità" score per asset (Phase 4).

    One row per asset, upserted by the `compute_rankings` task. `components`
    stores the normalized sub-scores so the UI can explain the ranking.
    """
    asset = models.OneToOneField(
        Asset, on_delete=models.CASCADE, related_name='score', primary_key=True,
    )
    score = models.FloatField(default=0.0, db_index=True, help_text="Composite 0–100 opportunity score.")
    rank = models.PositiveIntegerField(null=True, blank=True)
    components = models.JSONField(default=dict, help_text="Normalized sub-scores (-1..1).")
    n_articles = models.PositiveIntegerField(default=0)
    low_news = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-score']

    def __str__(self):
        return f"{self.asset_id}: {self.score:.1f} (#{self.rank})"


class Portfolio(models.Model):
    """A virtual paper-trading portfolio (Phase 5).

    Play money only — no broker, no real orders. The `run_paper_trading` task
    applies the Phase 3 sentiment strategy forward in time, opening/closing
    `Position`s and logging `PaperTrade`s against this portfolio's `cash`.
    A single "Default" portfolio is auto-created; multi-user comes later.
    """
    name = models.CharField(max_length=100, unique=True)
    initial_capital = models.FloatField(default=0.0)
    cash = models.FloatField(default=0.0, help_text="Uninvested virtual cash.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Portfolio<{self.name}> cash={self.cash:.2f}"


class Position(models.Model):
    """An open virtual holding in a paper portfolio (Phase 5). One per asset."""
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='positions')
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='positions')
    quantity = models.FloatField(default=0.0)
    avg_entry_price = models.FloatField(default=0.0)
    opened_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('portfolio', 'asset')
        ordering = ['asset_id']

    def __str__(self):
        return f"{self.asset_id} x{self.quantity:.4f} @ {self.avg_entry_price:.2f}"


class PaperTrade(models.Model):
    """A single executed virtual order against a paper portfolio (Phase 5)."""
    SIDES = [('BUY', 'BUY'), ('SELL', 'SELL')]

    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='trades')
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='paper_trades')
    side = models.CharField(max_length=4, choices=SIDES)
    quantity = models.FloatField()
    price = models.FloatField()
    value = models.FloatField(help_text="quantity × price (cash moved).")
    reason = models.CharField(max_length=20, help_text="Signal that triggered it (buy/sentiment/stop_loss).")
    realized_pnl = models.FloatField(null=True, blank=True, help_text="Profit/loss closed by a SELL (null for BUY).")
    executed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-executed_at']
        indexes = [models.Index(fields=['portfolio', 'executed_at'])]

    def __str__(self):
        return f"[{self.side}] {self.asset_id} x{self.quantity:.4f} @ {self.price:.2f}"


class PortfolioSnapshot(models.Model):
    """Point-in-time mark-to-market value of a paper portfolio (Phase 5).

    One row per paper-trading cycle; feeds the equity curve in the dashboard.
    """
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='snapshots')
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    cash = models.FloatField()
    holdings_value = models.FloatField(help_text="Mark-to-market value of all open positions.")
    total_value = models.FloatField(help_text="cash + holdings_value (the equity).")

    class Meta:
        ordering = ['timestamp']
        indexes = [models.Index(fields=['portfolio', 'timestamp'])]

    def __str__(self):
        return f"{self.portfolio_id} @ {self.timestamp:%Y-%m-%d %H:%M}: {self.total_value:.2f}"
