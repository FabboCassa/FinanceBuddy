from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_portfolio_papertrade_portfoliosnapshot_position'),
    ]

    operations = [
        migrations.AddField(
            model_name='asset',
            name='next_earnings_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='asset',
            name='earnings_checked_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
