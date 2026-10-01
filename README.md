# authzlock

An authorization lockfile for Django and Django REST Framework.

authzlock reads who-can-call-what from your Django project's URLconf and views, writes it to
a committed `authz.lock` file, and shows in code review when a change makes an endpoint's
access rules looser. Broken access control is the number one web application risk, and in
Django the rules are scattered across permission classes, settings defaults, queryset
overrides and decorators. authzlock puts them in one reviewable place.

**Status: pre-alpha.** `authzlock update` writes `authz.lock` and `authzlock check` fails
when it is out of date; `diff` is not built yet. See `docs/cli.md` for the commands and `docs/lockfile.md` for the file format.

## Install

```sh
pip install authzlock  # not yet published
```

## Development

See `DEVELOPMENT.md` for the development commands and `docs/requirements.md` for the full
requirements. The backlog lives in Linear and is mirrored in `docs/backlog.md`.

## CI

Every pull request and every push to `main` runs the GitHub Actions workflow in
`.github/workflows/ci.yml`: a `lint` job (ruff), a `typecheck` job (mypy strict) and one
`tests (python=X, django=Y)` job per supported combination, eleven in all, plus
`tests (python=3.12, django=4.2, drf=3.14)`, which runs the suite against the oldest
supported DRF. The jobs are the same nox sessions that `nox` runs locally with no arguments.
Mark `lint`, `typecheck` and every `tests (...)` job as required status checks on `main` in
the repository settings so a red check blocks merging.

## License

MIT. See `LICENSE`.
