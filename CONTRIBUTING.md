# Contributing to authzlock

This page covers the development setup, the checks a change must pass, the branch and commit
conventions, and how to add a fixture project. [DEVELOPMENT.md](DEVELOPMENT.md) holds the
project brief and the same commands; `tests/test_docs.py` fails when the shell commands on
the two pages differ, so change both together. [docs/index.md](docs/index.md) lists the
reference pages.

## Setup

Python 3.10 or newer and git are needed. Set up a dev environment once:

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install nox
```

## Checks

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
nox -s "tests(python='3.12', django='5.2')"
# or directly in the active venv:
pytest
```

Tests against the oldest supported DRF (3.14, on Python 3.12 and Django 4.2):

```sh
nox -s tests_min_drf
```

Tests against the oldest supported FastAPI (0.100, on Python 3.12 and Django 5.2):

```sh
nox -s tests_min_fastapi
```

Run everything CI runs:

```sh
nox
```

Session names are defined in `noxfile.py`. CI runs the same sessions on every pull request:
`lint`, `typecheck`, one `tests (python=X, django=Y)` job per cell of the README
compatibility table, and the oldest-DRF and oldest-FastAPI jobs, plus the GitHub Action
end-to-end jobs described in [docs/github-action.md](docs/github-action.md#testing-the-action).

`lint`, `typecheck` and every `tests (...)` job are required checks on `main` (ruleset
`protect-main`). The check names include the matrix values, so when a Python or Django
version is added or dropped, update the ruleset in the same change or pull requests will
wait for a check that never runs.

## Branches, commits and pull requests

- Work happens on short-lived branches off `main`. A branch is named after its Linear
  ticket: the lowercase identifier, a hyphen and a short slug of the title, for example
  `sha-12-url-resolver-walk`.
- Commits use conventional prefixes: `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `ci:`.
- Tests come first. Each test carries the ticket's T-case id in its name, for example
  `test_t3_missing_module_raises_project_load_error`, and is committed before the change
  that makes it pass.
- Every code change goes through a pull request against `main`. It is merged once CI passes
  and it has been reviewed. `docs/plans` and `docs/backlog.md` may be committed to `main`
  directly.
- A change is done when every T-case of its ticket passes in CI, ruff and mypy pass and the
  docs are updated.
- Add a line to the `## [Unreleased]` section of [CHANGELOG.md](CHANGELOG.md) for any change
  a user would notice.

Keep these rules from [DEVELOPMENT.md](DEVELOPMENT.md#working-rules) in mind: classification
stays conservative (when unsure, `changed-unknown`), the package makes no network calls,
lockfile output stays deterministic, and docs and messages use plain language.

## Adding a fixture project

Fixture projects under `tests/fixtures/` are small Django projects, one per view style.
[tests/fixtures/README.md](tests/fixtures/README.md) describes their layout and how tests
use them. To add one:

1. Create `tests/fixtures/<style>/` with `settings.py` (`ROOT_URLCONF`, `INSTALLED_APPS`,
   and `REST_FRAMEWORK` defaults where DRF is used), `urls.py` and one app package holding
   only the views the tests assert on. The settings module is always `settings`.
2. Write the tests first, using `run_extract("<style>")` from `tests/harness.py`. It runs
   the extraction in a separate process, because Django can only be set up once per
   process.
3. Check the CLI against it from the repository root:

   ```sh
   DJANGO_SETTINGS_MODULE=settings PYTHONPATH=tests/fixtures/drf_viewsets \
     authzlock check --lockfile tests/fixtures/drf_viewsets/authz.lock.expected
   ```

   (with your fixture's directory in place of `drf_viewsets`; for a new fixture, use
   `authzlock update` with the same options to write its first lockfile).
4. To have its lockfile compared byte for byte in every CI cell, add the fixture's name to
   `DETERMINISM_FIXTURES` in `tests/test_determinism.py` and write its golden lockfile,
   `authz.lock.expected`:

   ```sh
   pytest tests/test_determinism.py -k t5 --update-golden
   ```

   This rewrites the most specific golden file that exists for the installed Django and
   DRF. If DRF 3.14 builds different routes for the fixture (the `tests_min_drf` session
   fails), create `authz.lock.drf-3.14.expected` as a copy of `authz.lock.expected` and
   rewrite it with `nox -s tests_min_drf -- tests/test_determinism.py -k t5 --update-golden`.
   Read the generated files before committing them; they are the expected output from then
   on.
5. Describe the fixture under "Current fixtures" in `tests/fixtures/README.md`.

## Generated docs

The output blocks in [docs/scenario.md](docs/scenario.md) and the `diff` output in
[README.md](README.md) are produced by the tests, which fail when they are stale. After a
change to the output, rewrite them and review the diff:

```sh
pytest tests/test_scenario.py tests/test_readme.py --update-docs
```

`tests/test_docs.py` also checks that [docs/cli.md](docs/cli.md) lists exactly the options
in `--help`, that relative links resolve and that no `authzlock` command in a code block uses
an option that does not exist. Update the docs in the same pull request as the change.
