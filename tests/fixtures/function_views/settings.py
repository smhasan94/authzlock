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
# Django's auth decorators read request.user, so tests that request these views (SHA-244's
# generated tests) need the auth middleware. Signed-cookie sessions need no database.
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
