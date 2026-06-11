from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Register Celery signal handlers (task-failure → Telegram ops alert).
        # Cheap and side-effect free outside a worker process.
        from core import monitoring
        monitoring.register_signal_handlers()
