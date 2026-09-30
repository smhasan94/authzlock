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
