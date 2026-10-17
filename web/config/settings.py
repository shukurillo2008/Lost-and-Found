"""Django settings for the Campus Lost & Found project.

All secrets and runtime paths are loaded from environment variables (see
``.env.example``). The same settings module is reused by the web, bot and
worker services so every process talks to the identical SQLite database
through the Django ORM.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# BASE_DIR = web/ (contains manage.py); REPO_ROOT = repository root.
BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

load_dotenv(REPO_ROOT / ".env")


def env(key, default=""):
    return os.environ.get(key, default)


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-secret-key")
DEBUG = env("DJANGO_DEBUG", "False").lower() in ("1", "true", "yes")
ALLOWED_HOSTS = [
    host.strip()
    for host in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,web").split(",")
    if host.strip()
]
if "test" in sys.argv:  # Django test client requests arrive from server "testserver"
    ALLOWED_HOSTS.append("testserver")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Campus Lost & Found domain apps
    "catalog",
    "bot_app",
    "reports",
    "storage",
    "matching",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# SQLite on a shared Docker volume; concurrency is handled by the PRAGMAs
# registered in config/db_hooks.py (WAL journal mode + busy_timeout).
SQLITE_PATH = env("SQLITE_PATH") or str(BASE_DIR / "data" / "db.sqlite3")
os.makedirs(Path(SQLITE_PATH).parent, exist_ok=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": SQLITE_PATH,
        "OPTIONS": {
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;",
            "transaction_mode": "IMMEDIATE",
            "timeout": 5,
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
TIME_ZONE = env("DJANGO_TIMEZONE", "Asia/Tashkent")
USE_I18N = True
USE_TZ = True

MEDIA_ROOT = env("MEDIA_ROOT") or str(BASE_DIR / "media")
MEDIA_URL = "/media/"
os.makedirs(MEDIA_ROOT, exist_ok=True)

STATIC_URL = "static/"
STATIC_ROOT = env("STATIC_ROOT") or str(BASE_DIR / "staticfiles")

# WhiteNoise serves static files (admin CSS/JS) straight from Django/gunicorn
# while DEBUG=False, so no reverse proxy is needed for the static mount.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Bot / office integration values (used by bot and worker services).
BOT_TOKEN = env("BOT_TOKEN")
OFFICE_GROUP_ID = env("OFFICE_GROUP_ID")

# Register connection hooks that enforce WAL mode / busy_timeout PRAGMAs
# on every new SQLite connection in every process (web, bot, worker).
import config.db_hooks  # noqa: E402,F401  (registration on import)
