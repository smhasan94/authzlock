# authzlock

An "authorization lockfile" for Django and Django REST Framework (FastAPI later).

## Project brief

**Problem.** Broken access control is the #1 web risk (OWASP Top 10:2025, A01). In
Django/DRF, who-can-call-what is scattered across `permission_classes`,
`DEFAULT_PERMISSION_CLASSES`, `get_queryset`/`get_object` overrides and decorators. A pull
request can silently loosen access and reviewers rarely notice. Existing tools (Hadrian,
AuthProbe, ZAP access control) test a running app from outside and need a hand-written roles
file plus seeded data. Nothing reads the rules from the code and shows changes in review.

**Users.** Teams building Django/DRF APIs, especially multi-tenant SaaS; code reviewers;
security engineers who want an access-control inventory.

**MVP scope.**

1. Extraction: import the target project's URLconf via `DJANGO_SETTINGS_MODULE`, walk the
   URL resolver, and for every route record: path pattern, name, HTTP methods, view
   (`module.Class` or function), resolved `permission_classes` and `authentication_classes`
   including settings defaults, `login_required`/`permission_required`/`user_passes_test`
   decorators, whether `get_queryset`/`get_object`/`perform_create` are overridden and whether
   they reference `request.user` (an "object-scoped" heuristic flag), and custom permission
   classes as opaque names with their docstring. Dynamic `get_permissions()` is recorded as
   `dynamic`, never guessed.
2. Lockfile: a deterministic, sorted, human-readable `authz.lock` (YAML) with a schema
   version, committed to the repo.
3. CLI (Typer): `authzlock update` writes or refreshes the lockfile; `authzlock check` exits
   non-zero when code and lockfile disagree and prints a readable diff;
   `authzlock diff --base <git ref>` classifies each change as added, removed, loosened,
   tightened, or changed-unknown.
4. Integrations: a GitHub Action that runs diff on pull requests and posts the result as a PR
   comment; a pre-commit hook for check.
5. Compatibility: Python 3.10+, Django 4.2 and 5.x, DRF 3.14+. Must handle routers, nested
   routers, ViewSets, APIView, generic views and plain function views.

**Out of scope for MVP:** FastAPI, generating pytest cases, black-box HTTP testing, proving
custom permission logic is correct, any hosted service or telemetry.

**Constraints:** runs in-process and offline with no network calls; never modifies the target
project; output is stable across runs and machines; a false "loosened" alarm is worse than
"changed-unknown", so classification is conservative.

**Success for MVP:** on a fixture project, a PR that changes `IsOwner` to `IsAuthenticated` on
a DELETE endpoint produces a PR comment naming the endpoint and calling the change
"loosened", and `check` fails in CI until the lockfile is updated.

Full requirements: `docs/requirements.md`. Backlog mirror: `docs/backlog.md`.

## Engineering conventions

- Python 3.10+, `pyproject.toml` with hatchling, Typer, PyYAML, pytest. Published to PyPI as
  `authzlock`. MIT license.
- Layout: `src/authzlock/` package, `tests/` with fixture Django projects under
  `tests/fixtures/`, one per view style.
- Tooling: ruff for lint and format, mypy strict on the package, nox sessions for lint,
  typecheck and tests across Python 3.10-3.13 and Django 4.2/5.x. GitHub Actions runs the
  nox matrix on every PR.
- Git: trunk-based on `main`. Branch names are the lowercase Linear identifier, a hyphen,
  and a short slug of the ticket title (example: `sha-12-url-resolver-walk`). Conventional
  commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`, `ci:`). All code changes go through
  a PR; `docs/plans` and `docs/backlog.md` may be committed directly to `main`.
- Linear: project "authzlock", team "Shakooky". Workflow states: Todo, In Progress,
  In Review, Done. Epics are parent issues labelled `Epic`; tickets are sub-issues.
- Definition of done: every T-case in the ticket passes in CI, ruff and mypy pass, docs
  updated, PR reviewed and merged.
- Ticket descriptions use the Context / Scope / Acceptance criteria / Test plan /
  Definition of done / Dependencies template. Every AC has at least one T-case and every
  T-case names an AC.

## Commands

Set up a dev environment once:

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install nox
```

Lint and format check (what CI runs):

```sh
nox -s lint
# equivalent to:
ruff check . && ruff format --check .
```

Auto-fix formatting and lint:

```sh
ruff format . && ruff check --fix .
```

Type check (mypy strict on the package):

```sh
nox -s typecheck
# equivalent to:
mypy src/authzlock
```

Tests, full matrix (Python 3.10-3.13 x Django 4.2/5.x):

```sh
nox -s tests
```

Tests, one interpreter and Django version:

```sh
nox -s "tests-3.12(django='5.2')"
# or directly in the active venv:
pytest
```

Run everything CI runs:

```sh
nox
```

Run the CLI against a fixture project:

```sh
DJANGO_SETTINGS_MODULE=fixture_drf_viewsets.settings PYTHONPATH=tests/fixtures/drf_viewsets \
  authzlock update
```

Exact nox session names are defined in `noxfile.py`; if a command above disagrees with
`noxfile.py`, the noxfile wins and this file should be updated.

## Rules for AI sessions

- Do not add requirements beyond `docs/requirements.md` and the Linear tickets. Put ideas in
  the "Later" epic.
- Keep classification conservative. When unsure, the answer is `changed-unknown`.
- Never make network calls from the package.
- Keep lockfile output deterministic: sort everything, never write absolute paths,
  timestamps or version strings into `authz.lock`.
- Keep language in docs and messages plain.
