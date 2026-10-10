from pathlib import Path
import os
from dotenv import load_dotenv

try:
    import pymysql
    pymysql.install_as_MySQLdb()
except ImportError:
    pass

try:
    load_dotenv()
except Exception:
    pass  # .env is git-crypt encrypted on Render; use injected env vars instead

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-secret-key-change-in-production-xyz123")
DEBUG = os.environ.get("DEBUG", "True") == "True"
ALLOWED_HOSTS = ["*"]

# Tell Django it's behind an HTTPS reverse proxy (ngrok/nginx)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CSRF_COOKIE_HTTPONLY = False  # JS needs to read cookie for SPA-style requests

# Allow cookies cross-origin (required for ngrok/external domains)
CSRF_COOKIE_SAMESITE = 'None'
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = 'None'
SESSION_COOKIE_SECURE = True

CSRF_TRUSTED_ORIGINS = [
    "http://localhost",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://*.ngrok-free.app",
    "https://*.ngrok.io",
    "https://rlaihub.com",
    "https://www.rlaihub.com",
    "https://happyhome.rlaihub.com",
    "https://happyhelper.onrender.com",
    "https://*.onrender.com",
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "interview.apps.InterviewConfig",
]

MIDDLEWARE = [
    "interview.ext_middleware.ExtCorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "happyhelper.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "happyhelper.wsgi.application"

_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_MYSQL_HOST = os.environ.get("MYSQL_HOST", "")
if _DATABASE_URL:
    import dj_database_url
    DATABASES = {"default": dj_database_url.config(default=_DATABASE_URL, conn_max_age=600)}
elif _MYSQL_HOST:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ.get("MYSQL_DB", "u288315318_parakeetai"),
            "USER": os.environ.get("MYSQL_USER", "u288315318_parakeetai"),
            "PASSWORD": os.environ.get("MYSQL_PASSWORD", ""),
            "HOST": _MYSQL_HOST,
            "PORT": os.environ.get("MYSQL_PORT", "3306"),
            "OPTIONS": {"charset": "utf8mb4"},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# MySQL backup config (credentials via env vars)
MYSQL_BACKUP_CONFIG = {
    "host": os.environ.get("MYSQL_HOST", ""),
    "port": int(os.environ.get("MYSQL_PORT", "3306")),
    "database": os.environ.get("MYSQL_DB", "u288315318_parakeetai"),
    "user": os.environ.get("MYSQL_USER", "u288315318_parakeetai"),
    "password": os.environ.get("MYSQL_PASSWORD", ""),
}
MYSQL_BACKUP_ENABLED = bool(os.environ.get("MYSQL_HOST", ""))

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# MariaDB on Hostinger shared hosting does not have timezone tables loaded.
# Render's server timezone is UTC. Storing naive datetimes in UTC is correct here.
USE_TZ = False
TIME_ZONE = "UTC"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

EXT_TOKEN = os.environ.get("EXT_TOKEN", "pkai-local-dev")

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLIC_KEY = os.environ.get("STRIPE_PUBLIC_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_PRO = os.environ.get("STRIPE_PRICE_PRO", "")
STRIPE_PRICE_TEAM = os.environ.get("STRIPE_PRICE_TEAM", "")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_WHISPER_MODEL = os.environ.get("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
