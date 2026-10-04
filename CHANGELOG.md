# Changelog

All notable changes to authzlock are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-10-04

### Added

- The GitHub Action takes an `app` input for FastAPI apps, and `settings-module` is now
  optional: with neither set, authzlock reads the project from the job's environment or
  `[tool.authzlock]`. See `docs/github-action.md`.
- `diff --format json` has an `ignore` object with the base and current route ignore lists
  and whether they differ, and `--format sarif` adds the "ignore list changed" note that text
  and markdown output already print. The document's `schema_version` stays 1; validators
  using an older copy of `docs/diff.schema.json` need the new one.

## [0.2.0] - 2026-10-04

### Added

- `[tool.authzlock]` in `pyproject.toml` sets `settings`, `lockfile` and `fail_on` for
  `update`, `check` and `diff`. Flags and `DJANGO_SETTINGS_MODULE` still take precedence. See
  `docs/cli.md`.
- `authzlock diff --format json` prints a machine-readable document (see
  `docs/diff-json.md` and `docs/diff.schema.json`), and `--format sarif` a SARIF 2.1.0 log
  for GitHub code scanning. Each change points at the file and line of its view.
- `authzlock update --ignore-path PREFIX --ignore-view PREFIX` leaves routes out of the
  lockfile, for example the Django admin; the list is recorded under `ignore` and applied
  by `check` and `diff`. `--no-ignore` clears it. Lockfiles without a list are unchanged.
- `authzlock gen-tests` writes a pytest module from the lockfile that checks anonymous
  requests are refused on routes protected by DRF built-ins or Django auth decorators; routes
  it cannot reason about get a skipped test naming why. See `docs/cli.md`.
- Rule R9 judges `IsAuthenticatedOrReadOnly` and `DjangoModelPermissionsOrAnonReadOnly` per
  HTTP method, and the new label `equivalent` marks a permission change that no method's
  effective rule notices. See `docs/classification.md`.
- FastAPI support: `update`, `check` and `diff` read a FastAPI app named by `--app
  MODULE:ATTR`, `AUTHZLOCK_APP` or `app` in `[tool.authzlock]`, without calling any of its
  code. Each route's dependencies are recorded in `permission_classes` and its security
  schemes in `authentication_classes`, with `permission_source: dependency`; the lockfile
  schema is unchanged. `--framework auto|django|fastapi` chooses between the two kinds of
  project. Rule R10 labels FastAPI route changes: a changed dependency list is
  `changed-unknown`, and removing every security scheme is `loosened`. `gen-tests` refuses
  FastAPI lockfiles. See the README and `docs/heuristics-and-limits.md`.

### Changed

- With neither a settings module nor an app given, the error now reads `No Django settings
  module or FastAPI app given.` instead of `No Django settings module given.`
- The `diff` summary line has a sixth count, `equivalent`, at the end:
  `1 loosened, 0 tightened, 0 added, 0 removed, 0 changed-unknown, 0 equivalent`. The JSON
  document gains `summary.equivalent` and the label, and SARIF a rule of level `note`. The
  `v1` Action tag moves to this release, so the Action's `summary` output and pull request
  comment gain the same count for every workflow that uses `smhasan94/authzlock@v1`.

## [0.1.0] - 2026-10-02

First release.

### Added

- Package skeleton with the `authzlock` command and `authzlock --version`.
- Loading a Django project from `DJANGO_SETTINGS_MODULE`, with plain error messages when the
  settings module is missing or fails to import.
- Support for Python 3.10 to 3.13, Django 4.2, 5.1, 5.2, 6.0 and 6.1, and Django REST
  Framework 3.14 and newer, tested in CI on every pull request.
- Release workflow that publishes to PyPI from a version tag using trusted publishing.
- `authzlock update` writes the project's access rules to `authz.lock`, a sorted YAML file
  with schema version 1, and `authzlock check` exits 1 with a readable report when the
  project and the lockfile differ. See `docs/lockfile.md` and `docs/cli.md`.
- pre-commit hooks `authzlock-check` and `authzlock-update`. See `docs/pre-commit.md`.
- `authzlock diff --base <ref>`: compares the lockfile committed at a git ref with the
  current project and labels each route `loosened`, `tightened`, `added`, `removed` or
  `changed-unknown`, as text or as markdown for a pull request comment, with
  `--fail-on loosened` to fail only on loosened routes.
- GitHub Action (`smhasan94/authzlock@v1`): runs `authzlock diff` on a pull request, keeps one
  comment with the changes up to date across pushes, and fails the job when a route is
  loosened (`fail-on-loosened`, default true). See `docs/github-action.md`.
- Reference documentation indexed in `docs/index.md`, including
  `docs/heuristics-and-limits.md` on what the heuristics cannot tell you, and a contributor
  guide, `CONTRIBUTING.md`.

### Fixed

- `authzlock` now declares Django 4.2 or newer as a dependency, so `pip install authzlock`
  followed by `authzlock --version` works in a fresh environment. DRF stays optional.
- The `authzlock` command now finds the project's settings module when run from the project
  root without `PYTHONPATH`: the current directory is put first on the import path, as
  `manage.py` and `python -m authzlock` do.
