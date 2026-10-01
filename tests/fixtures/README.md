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

## Golden lockfiles

`class_views`, `drf_apiview`, `drf_viewsets`, `function_views` and `scenario_loosen` each hold
`authz.lock.expected`, the exact bytes `authzlock update` must write for that project.
`tests/test_determinism.py` (T5) compares with it in every nox cell. Where a Django or DRF
release genuinely builds different routes, a version-specific file takes precedence:
`authz.lock.drf-<major.minor>.expected`, then `authz.lock.django-<major.minor>.expected`.
Today the only one is `drf_viewsets/authz.lock.drf-3.14.expected`, because DRF 3.14's
`DefaultRouter` writes its root and format-suffix routes as regexes.

After an intended change to extraction or the lockfile format, regenerate them with
`pytest tests/test_determinism.py -k t5 --update-golden` (and, for a version-specific file,
the same command inside the matching nox session, for example
`nox -s tests_min_drf -- tests/test_determinism.py -k t5 --update-golden`), then review the
diff. A new complete fixture is compared only once it is listed in `DETERMINISM_FIXTURES` in
`tests/test_determinism.py`.

The output blocks in `docs/scenario.md` are generated from `scenario_loosen` the same way:
`tests/test_scenario.py` (T6) fails when they are stale, and
`pytest tests/test_scenario.py -k t6 --update-docs` rewrites them.

## Current fixtures

- `drf_apiview`: DRF views with `REST_FRAMEWORK` defaults set (`IsAuthenticatedOrReadOnly`,
  `SessionAuthentication`): explicit class attributes, a generic view on the defaults, a
  custom `IsOwner` class, a base class carrying `permission_classes`, overrides of
  `get_permissions` and `get_authenticators` that raise if called, one plain Django view,
  and for the custom permission registry: `IsOwner` on three routes, an undocumented `NoDoc`,
  an `Exploding` class that raises if instantiated or called, and composed
  `IsAuthenticated | IsOwner` and `~IsBlocked` permissions; and under `scoped/` the
  object-scoping cases: a `ModelViewSet` with no overrides, an owner-filtered
  `get_queryset` plus `perform_create`, an unfiltered `get_queryset`, and a view inheriting
  the project's `OwnedQuerysetMixin` (over an unmanaged `Order` model).
- `drf_viewsets`: a `ModelViewSet` on a `DefaultRouter` with two `@action`s (one with its own
  `permission_classes`), a `ReadOnlyModelViewSet`, a `drf-nested-routers` child resource,
  and the same ViewSet on a second `SimpleRouter` under `v2/`. No models; nothing is queried.
- `function_views`: plain function views (one public, one under `login_required`, one under
  `permission_required`, one wrapped by a decorator without `functools.wraps`, one under
  `require_http_methods(["POST", "PUT"])`, one under `require_GET` plus a `functools.wraps`
  decorator, `permission_required` with a string, a list and a module constant,
  `user_passes_test` with a test that raises if called, and `cache_page`), a top-level
  `re_path`, and the `shop` app's URLconf (`app_name = "shop"`, with a class-based view, an
  unnamed route and a nested `re_path`) included three times under the namespaces `shop`,
  `a` and `b`.
- `class_views`: `View` subclasses with different handler sets (one restricted by
  `http_method_names`), a `TemplateView` and a `RedirectView`, and one view per auth form:
  `LoginRequiredMixin`, `method_decorator(login_required, name="dispatch")`,
  `PermissionRequiredMixin` with a string attribute, `UserPassesTestMixin`.
- `scenario_loosen`: the project of [docs/scenario.md](../../docs/scenario.md), used by
  `tests/test_scenario.py` and the GitHub Action end-to-end test: one
  `RetrieveDestroyAPIView` at `invoices/<int:pk>/` (`billing.views.InvoiceDetailView`) with
  `permission_classes = [IsAuthenticated, IsOwner]`, the documented custom `IsOwner`, and an
  unused custom `IsTenantAdmin` that a test swaps in. The scenario's edit removes `, IsOwner`
  from that one line of `billing/views.py`; keep the line as it is.
- `minimal`: a single view; used to prove fixtures run in separate processes.
- `broken`: a `settings.py` that raises at import time; used to test error reporting. It is
  not a complete project.
