# Implementation plans

One file per ticket, named by Linear identifier. Each plan is also posted on its ticket as a
comment whose first line is "Implementation plan". Plans written 2026-09-30 for the remaining
MVP tickets share the design decisions below so that tickets built in parallel fit together.

## Module layout (package `src/authzlock/`)

| Module | Owner ticket | Purpose |
|--------|--------------|---------|
| `errors.py` | SHA-197 | `AuthzlockError` base, `ProjectLoadError`, `LockfileError`; exit codes 0 ok, 1 mismatch or changes, 2 error |
| `django_loader.py` | SHA-197 | `load_project(settings_module: str | None) -> None` |
| `model.py` | SHA-197 (skeleton), SHA-200 (routes) | frozen dataclasses `Route`, `Inventory`, plus `to_dict` / `from_dict` |
| `extract/__init__.py` | SHA-197 | `extract() -> Inventory`; each later ticket adds one enrichment step |
| `extract/urls.py` | SHA-200 | `walk_urlconf()` |
| `extract/methods.py` | SHA-203 | HTTP methods and ViewSet action maps |
| `extract/drf.py` | SHA-205, SHA-207 | permission and authentication resolution, router and `@action` handling |
| `extract/decorators.py` | SHA-209 | Django auth decorators and mixins |
| `extract/scoping.py` | SHA-210 | object-scoped heuristic |
| `extract/custom.py` | SHA-211 | custom permission registry and composed expressions |
| `extract/source.py` | SHA-209 | shared AST helpers: source of a callable or method, decorator list, attribute chains |
| `_dump.py` | SHA-197 | `python -m authzlock._dump` prints the inventory as JSON; used by the test harness |
| `lockfile.py` | SHA-224 | `dump`, `load`, schema version 1 |
| `diff.py` | SHA-228 | `compute(base, current) -> Diff` |
| `classify.py` | SHA-229 | rules R1 to R8 |
| `render.py` | SHA-230, SHA-241 | text, markdown and JSON output |
| `gitutil.py` | SHA-230 | read a file at a git ref |
| `locate.py` | SHA-241 | source file and line of a view, for JSON and SARIF output |
| `sarif.py` | SHA-241 | SARIF 2.1.0 output built from the JSON document |
| `gen_tests.py` | SHA-244 | `gen-tests`: pytest module of anonymous-access checks from the lockfile |
| `cli.py` | SHA-225, SHA-226, SHA-230 | Typer commands `update`, `check`, `diff` |

## Data model

`Route` fields, in lockfile order: `path`, `name`, `view`, `methods`, `actions`,
`permission_classes`, `permission_source`, `authentication_classes`, `authentication_source`,
`django_auth`, `object_scoping`. Sentinels: the string `dynamic` for a class list the tool
must not guess, the string `any` as the only entry in `methods` for an unrestricted function
view, `null` for a field that does not apply. `Inventory` holds `schema_version`, `routes`
sorted by `(path, view)` and `custom_permissions` keyed by dotted path. The route key used
in `used_by`, diffs and output is `"<METHODS joined by comma> <path> -> <view>"`.

## Test harness

`tests/harness.py` provides `run_extract(fixture: str, *, block_modules=()) -> dict`. It runs
`python -m authzlock._dump` in a subprocess with `PYTHONPATH=tests/fixtures/<fixture>` and
`DJANGO_SETTINGS_MODULE=settings`, so every fixture is a separate Django process. Fixture
projects are named by view style and contain `settings.py`, `urls.py` and one app package.

## Conventions

Tests are written before implementation and carry the T-case id in the name, for example
`test_t3_missing_module_raises_project_load_error`. Every plan stays under one page. Plans
list proposed AC or T-case amendments explicitly; the ticket is edited only after approval.
