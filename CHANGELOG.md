# Changelog

All notable changes to authzlock are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `[tool.authzlock]` in `pyproject.toml` sets `settings`, `lockfile` and `fail_on` for
  `update`, `check` and `diff`. Flags and `DJANGO_SETTINGS_MODULE` still take precedence. See
  `docs/cli.md`.

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
