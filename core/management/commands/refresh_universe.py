"""On-demand universe refresh.

Pulls the live top-N by market cap (companiesmarketcap.com), seeds any newly
large / newly listed companies (validated on yfinance), and reports names that
fell out of the top-N (kept, not deleted). Same logic as the monthly
`refresh_universe` Celery task - this is the manual/console entry point.

    python manage.py refresh_universe                 # top 500, with backfill
    python manage.py refresh_universe --top-n 300      # narrower universe
    python manage.py refresh_universe --no-backfill    # skip history deep-fill
"""
from django.core.management.base import BaseCommand

from core import constants
from core.universe_refresh import refresh_universe_members


class Command(BaseCommand):
    help = "Add newly-large / newly-listed companies to the tracked universe."

    def add_arguments(self, parser):
        parser.add_argument('--top-n', type=int, default=constants.UNIVERSE_TARGET_SIZE,
                            help="How many top-market-cap names to track.")
        parser.add_argument('--no-backfill', action='store_true',
                            help="Don't deep-backfill price history for new assets.")

    def handle(self, *args, **options):
        w = self.stdout.write
        w(self.style.MIGRATE_HEADING("FinanceBuddy - universe refresh"))
        result = refresh_universe_members(
            top_n=options['top_n'], backfill=not options['no_backfill'])

        if not result['added'] and not result['dropped'] and not result['invalid']:
            w("No changes (source unreachable or universe already current).")
            return

        w(self.style.SUCCESS(f"Added: {result['added']}"))
        if result['added_symbols']:
            w("  " + ", ".join(result['added_symbols']))
        if result['invalid']:
            w(self.style.WARNING(f"Invalid on yfinance, skipped: {result['invalid']}"))
        w(f"Dropped out of top-{options['top_n']} (kept, not deleted): {result['dropped']}")
        if result['dropped_symbols']:
            w("  " + ", ".join(result['dropped_symbols']))
