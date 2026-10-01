# Fixture Django projects

Each directory here is a small, self-contained Django project used to test extraction,
one per view style. The directory name is the style it covers, in snake case, for example
`function_views`, `class_views`, `drf_apiview`, `drf_viewsets`, `scenario_loosen`.

## Layout

Every fixture project must contain:

- `settings.py` with `ROOT_URLCONF`, `INSTALLED_APPS` and, where DRF is used,
  `REST_FRAMEWORK` defaults.
- `urls.py` as the root URLconf.
- One or more app packages holding the views the fixture exists to exercise.

Keep fixtures minimal: only the routes and views the tests assert on.

## How tests select a fixture

Extraction imports the target project in-process and Django can only be set up once per
process, so tests never import two fixtures into the same interpreter. The `run_extract`
helper in `tests/harness.py` (also available as a pytest fixture of the same name) runs
`python -m authzlock._dump` in a subprocess with `PYTHONPATH` pointing at the fixture
directory and `DJANGO_SETTINGS_MODULE` set to `settings`, then returns the parsed JSON. A test
names the fixture it wants by directory name, for example `run_extract("drf_viewsets")`.

To simulate a missing optional dependency without a separate environment, pass
`block_modules`, for example `run_extract("function_views", block_modules=("rest_framework",))`.
The named modules are made unimportable in the child process before extraction starts.

## Current fixtures

- `drf_apiview`: DRF views with `REST_FRAMEWORK` defaults set (`IsAuthenticatedOrReadOnly`,
  `SessionAuthentication`): explicit class attributes, a generic view on the defaults, a
  custom `IsOwner` class, a base class carrying `permission_classes`, overrides of
  `get_permissions` and `get_authenticators` that raise if called, and one plain Django view.
- `function_views`: plain function views (one public, one under `login_required`, one under
  `permission_required`, one wrapped by a decorator without `functools.wraps`, one under
  `require_http_methods(["POST", "PUT"])`, one under `require_GET` plus a `functools.wraps`
  decorator), a top-level
  `re_path`, and the `shop` app's URLconf (`app_name = "shop"`, with a class-based view, an
  unnamed route and a nested `re_path`) included three times under the namespaces `shop`,
  `a` and `b`.
- `class_views`: `View` subclasses with different handler sets (one restricted by
  `http_method_names`), a `TemplateView` and a `RedirectView`.
- `minimal`: a single view; used to prove fixtures run in separate processes.
- `broken`: a `settings.py` that raises at import time; used to test error reporting. It is
  not a complete project.
