from django.db import models

class Asset(models.Model):
    ASSET_TYPES = [
        ('Stock', 'Stock'),
        ('ETF', 'ETF'),
    ]
    
    symbol = models.CharField(max_length=20, unique=True, primary_key=True, help_text="e.g., AAPL or SWDA.MI")
    name = models.CharField(max_length=255)
    asset_type = models.CharField(max_length=10, choices=ASSET_TYPES, default='Stock')
    
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
