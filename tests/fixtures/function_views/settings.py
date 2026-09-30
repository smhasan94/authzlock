"""Settings for the function_views fixture project."""

SECRET_KEY = "fixture-not-secret"
DEBUG = False
ALLOWED_HOSTS: list[str] = []
USE_TZ = True
ROOT_URLCONF = "urls"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "shop",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
