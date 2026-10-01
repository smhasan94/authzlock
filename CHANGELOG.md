# Changelog

All notable changes to authzlock are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Package skeleton with the `authzlock` command and `authzlock --version`.
- Loading a Django project from `DJANGO_SETTINGS_MODULE`, with plain error messages when the
  settings module is missing or fails to import.
- Support for Python 3.10 to 3.13, Django 4.2, 5.1 and 5.2, and Django REST Framework 3.14
  and newer, tested in CI on every pull request.
- Release workflow that publishes to PyPI from a version tag using trusted publishing.
- `authzlock update` writes the project's access rules to `authz.lock`, a sorted YAML file
  with a schema version, and `authzlock check` exits 1 with a readable report when the
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

- The `authzlock` command now finds the project's settings module when run from the project
  root without `PYTHONPATH`: the current directory is put first on the import path, as
  `manage.py` and `python -m authzlock` do.
