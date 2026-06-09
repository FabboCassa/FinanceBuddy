import os
from pathlib import Path
from celery.schedules import crontab

from core import constants

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file manually if it exists to support local development runserver
env_path = BASE_DIR / '.env'
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ.setdefault(key.strip(), val.strip())

# Quick-start development settings - unsuitable for production
SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-highly-secret-dev-key-12345')

DEBUG = os.environ.get('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = ['*']

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third party apps
    'rest_framework',
    'django_filters',
    
    # Local apps
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'finance_buddy.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'finance_buddy.wsgi.application'
ASGI_APPLICATION = 'finance_buddy.asgi.application'

# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases
DB_NAME = os.environ.get('DB_NAME', 'finance_buddy')
DB_USER = os.environ.get('DB_USER', 'postgres')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'postgres_pwd')
DB_HOST = os.environ.get('DB_HOST', 'db')
DB_PORT = os.environ.get('DB_PORT', '5432')

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': DB_NAME,
        'USER': DB_USER,
        'PASSWORD': DB_PASSWORD,
        'HOST': DB_HOST,
        'PORT': DB_PORT,
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Europe/Rome'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ]
}

# Celery Configuration
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# Celery Beat Periodic Tasks
CELERY_BEAT_SCHEDULE = {
    'fetch-market-data-every-15-min': {
        'task': 'core.tasks.fetch_market_data',
        'schedule': crontab(minute='*/15'),
    },
    'fetch-news-every-30-min': {
        'task': 'core.tasks.fetch_news',
        'schedule': crontab(minute='*/30'),
    },
    'analyze-sentiment-every-30-min': {
        'task': 'core.tasks.analyze_sentiment',
        'schedule': crontab(minute='*/30'),
    },
    'check-sentiment-alerts-every-30-min': {
        'task': 'core.tasks.check_sentiment_alerts',
        'schedule': crontab(minute='*/30'),
    },
    'update-news-relevance-every-30-min': {
        'task': 'core.tasks.update_news_relevance',
        'schedule': crontab(minute='*/30'),
    },
    'compute-rankings-every-30-min': {
        'task': 'core.tasks.compute_rankings',
        'schedule': crontab(minute='*/30'),
    },
    'run-paper-trading-every-30-min': {
        'task': 'core.tasks.run_paper_trading',
        'schedule': crontab(minute='*/30'),
    },
}

# Sentiment NLP flag
USE_REAL_NLP = os.environ.get('USE_REAL_NLP', 'False') == 'True'
# Phase 4 (rung 2): zero-shot NLI theme categorization (else keyword cold-start).
USE_ZERO_SHOT_NLP = os.environ.get('USE_ZERO_SHOT_NLP', 'False') == 'True'
# Phase 4: pull news from curated quality RSS feeds (linked to assets via NER).
RSS_INGEST_ENABLED = os.environ.get(
    'RSS_INGEST_ENABLED', str(constants.RSS_INGEST_ENABLED_DEFAULT)) == 'True'
# Phase 4: cap how many assets get yfinance per-ticker news per cycle (no batch
# API); the rest rely on RSS + NER. Keeps a ~500-asset universe tractable.
YFINANCE_NEWS_MAX_ASSETS = int(os.environ.get(
    'YFINANCE_NEWS_MAX_ASSETS', constants.YFINANCE_NEWS_MAX_ASSETS_DEFAULT))

# -- Sentiment alerting (Phase 2) -------------------------------------------
# Thresholds default to core.constants but can be overridden per-deployment.
SENTIMENT_ALERT_LOW = float(os.environ.get('SENTIMENT_ALERT_LOW', constants.SENTIMENT_ALERT_LOW))
SENTIMENT_ALERT_HIGH = float(os.environ.get('SENTIMENT_ALERT_HIGH', constants.SENTIMENT_ALERT_HIGH))
ALERT_LOOKBACK_HOURS = int(os.environ.get('ALERT_LOOKBACK_HOURS', constants.ALERT_LOOKBACK_HOURS))
ALERT_COOLDOWN_HOURS = int(os.environ.get('ALERT_COOLDOWN_HOURS', constants.ALERT_COOLDOWN_HOURS))
ALERT_MIN_ARTICLES = int(os.environ.get('ALERT_MIN_ARTICLES', constants.ALERT_MIN_ARTICLES))

# Alert delivery channels (all optional; absent → channel skipped).
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL', '')

# Email channel (uses console backend in dev so it never crashes unconfigured).
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '25'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'False') == 'True'
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'finance-buddy@localhost')
ALERT_EMAIL_RECIPIENTS = [
    e.strip() for e in os.environ.get('ALERT_EMAIL_RECIPIENTS', '').split(',') if e.strip()
]

# -- Logging -----------------------------------------------------------------
# Make data ingestion observable. INFO from the `core` app (the fetch/score/rank
# tasks) goes to the console AND to a rotating file under logs/. Because
# docker-compose mounts the repo at /app, the celery_worker container -- where
# ingestion actually runs -- writes to the SAME logs/ dir you see locally, so you
# can open logs/finance_buddy.log to confirm data is really being fetched.
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} [{levelname}] {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'ingest_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOG_DIR / 'finance_buddy.log'),
            'maxBytes': 5 * 1024 * 1024,  # 5 MB per file
            'backupCount': 5,
            'encoding': 'utf-8',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'core': {  # all core.* loggers (tasks, alerts, ...)
            'handlers': ['console', 'ingest_file'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
    },
}

# Let Celery use the Django LOGGING config above instead of hijacking the root
# logger, so task INFO logs land in the same console + ingest file.
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
