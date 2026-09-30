# authzlock

An authorization lockfile for Django and Django REST Framework.

authzlock reads who-can-call-what from your Django project's URLconf and views, writes it to
a committed `authz.lock` file, and shows in code review when a change makes an endpoint's
access rules looser. Broken access control is the number one web application risk, and in
Django the rules are scattered across permission classes, settings defaults, queryset
overrides and decorators. authzlock puts them in one reviewable place.

**Status: pre-alpha.** Nothing works yet beyond `authzlock --version`.

## Install

```sh
pip install authzlock  # not yet published
```

## Development

See `DEVELOPMENT.md` for the development commands and `docs/requirements.md` for the full
requirements. The backlog lives in Linear and is mirrored in `docs/backlog.md`.

## License

MIT. See `LICENSE`.
