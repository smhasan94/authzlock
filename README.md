# authzlock

[![CI](https://github.com/smhasan94/authzlock/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/smhasan94/authzlock/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/authzlock.svg)](https://pypi.org/project/authzlock/)

An authorization lockfile for Django, Django REST Framework and FastAPI.

A one-line change to `permission_classes` or a decorator can open an endpoint to more
users, and in review it looks like any other line. authzlock records who may call every
route in a committed file, `authz.lock`, and on each pull request tells you which routes
changed and whether access got looser.

## Install

```sh
pip install authzlock
```

Install it in the same environment as your project: authzlock imports your settings and
URLs to read the rules. Django REST Framework and FastAPI are optional.

## Quickstart

From your project root, inside a git repository, with your own settings module:

```sh quickstart
export DJANGO_SETTINGS_MODULE=mysite.settings
authzlock update
git add authz.lock
git commit -m "Add authz.lock"
authzlock check
```

`update` writes `authz.lock`. `check` confirms the lockfile matches the code.

Now loosen a rule. Here an action only admins could call is opened to every signed-in user:

```diff
-    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
+    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
     def archive(self, request: Request, pk: Any = None) -> Response:
```

```sh quickstart
authzlock check  # exits 1
authzlock diff --base HEAD  # exits 1
```

`check` fails because the code no longer matches the lockfile. `diff` shows what changed
since `HEAD`; the action has three routes and all three are `loosened`:

<!-- readme-diff:start -->
```text
loosened        POST ^invoices/(?P<pk>[^/.]+)/archive/$ -> billing.views.InvoiceViewSet  permission_classes: [rest_framework.permissions.IsAdminUser] -> [rest_framework.permissions.IsAuthenticated]  (R1: strongest built-in rest_framework.permissions.IsAdminUser -> rest_framework.permissions.IsAuthenticated)
loosened        POST ^invoices/(?P<pk>[^/.]+)/archive\.(?P<format>[a-z0-9]+)/?$ -> billing.views.InvoiceViewSet  permission_classes: [rest_framework.permissions.IsAdminUser] -> [rest_framework.permissions.IsAuthenticated]  (R1: strongest built-in rest_framework.permissions.IsAdminUser -> rest_framework.permissions.IsAuthenticated)
loosened        POST v2/^invoices/(?P<pk>[^/.]+)/archive/$ -> billing.views.InvoiceViewSet  permission_classes: [rest_framework.permissions.IsAdminUser] -> [rest_framework.permissions.IsAuthenticated]  (R1: strongest built-in rest_framework.permissions.IsAdminUser -> rest_framework.permissions.IsAuthenticated)

3 loosened, 0 tightened, 0 added, 0 removed, 0 changed-unknown, 0 equivalent
```
<!-- readme-diff:end -->

If the change is intended, record it and commit it with the code:

```sh quickstart
authzlock update
git commit -am "Let signed-in users archive invoices"
authzlock check
```

Every command exits 0 on success, 1 when the lockfile and the code differ, and 2 on an
error. [docs/scenario.md](docs/scenario.md) walks through a longer example.

## The lockfile

`authz.lock` is sorted YAML, so the same code always gives the same file and review diffs
show only real changes. Don't edit it by hand; run `authzlock update`. One route:

```yaml
schema_version: 1
routes:
- path: ^invoices/(?P<pk>[^/.]+)/archive/$
  name: invoice-archive
  view: billing.views.InvoiceViewSet
  methods:
  - POST
  actions:
    POST: archive
  permission_classes:
  - rest_framework.permissions.IsAdminUser
  permission_source: action
  authentication_classes:
  - rest_framework.authentication.SessionAuthentication
  authentication_source: settings-default
  django_auth: null
  object_scoping:
    get_object:
      overridden: false
      references_request_user: null
    get_queryset:
      overridden: false
      references_request_user: null
    perform_create:
      overridden: false
      references_request_user: null
custom_permissions: {}
```

[docs/lockfile.md](docs/lockfile.md) describes every key.

## How changes are labelled

`authzlock diff` gives each changed route one label:

- `loosened`: more users can call the route than before.
- `tightened`: fewer users can call it.
- `added` / `removed`: the route is new, or gone.
- `changed-unknown`: the rules changed, but authzlock can't tell which way, for example a
  custom permission class was swapped for another.
- `equivalent`: the rules were rewritten but every HTTP method allows the same users.

authzlock ranks only the built-in classes (`AllowAny` < `IsAuthenticatedOrReadOnly` <
`IsAuthenticated` < `IsAdminUser`, and `login_required` < `permission_required`) and never
guesses what custom code does, so it reports `changed-unknown` rather than a false alarm.
[docs/classification.md](docs/classification.md) has the full rules, R1 to R10.

## Use it in CI

**GitHub Action.** Comments the `diff` on each pull request and fails when a route is
loosened. Save as `.github/workflows/authzlock.yml`:

```yaml
name: authzlock

on:
  pull_request:

permissions:
  contents: read
  pull-requests: write

jobs:
  authzlock:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - uses: smhasan94/authzlock@v1
        with:
          settings-module: mysite.settings
          python-version: "3.12"
```

Install your project's dependencies first. For FastAPI, pass `app: main:app` instead of
`settings-module`. More in [docs/github-action.md](docs/github-action.md).

**pre-commit.** Blocks a commit when `authz.lock` is out of date. List the packages your
settings and URLs import under `additional_dependencies`:

```yaml
repos:
  - repo: https://github.com/smhasan94/authzlock
    rev: v0.3.1
    hooks:
      - id: authzlock-check
        args: ["--settings", "mysite.settings"]
        additional_dependencies:
          - "django==5.2.*"
          - "djangorestframework==3.16.*"
```

More in [docs/pre-commit.md](docs/pre-commit.md).

## FastAPI

Point authzlock at your app as `module:attr` instead of a settings module. Everything else
works the same:

```sh
export AUTHZLOCK_APP=main:app
authzlock update
```

Each route's dependencies and security schemes are recorded. A changed dependency is
`changed-unknown`; removing every security scheme from a route is `loosened`.
[docs/heuristics-and-limits.md](docs/heuristics-and-limits.md#fastapi) covers the details.

## What authzlock does not do

- It does not check that custom permission logic is correct. A class such as `IsOwner` is
  recorded by name; its code is never run.
- It does not test a running app. It reads code and settings and sends no requests.
- It does not generate tests for signed-in users. `authzlock gen-tests` only writes tests
  that anonymous requests to protected routes are refused, for Django projects.

A passing `check` means the lockfile matches the code, not that the rules are right.
[docs/heuristics-and-limits.md](docs/heuristics-and-limits.md) explains what authzlock can
and cannot see.

## Compatibility

| Python | Django 4.2 | Django 5.1 | Django 5.2 | Django 6.0 | Django 6.1 |
|--------|------------|------------|------------|------------|------------|
| 3.10 | yes | yes | yes | no | no |
| 3.11 | yes | yes | yes | no | no |
| 3.12 | yes | yes | yes | yes | yes |
| 3.13 | no | yes | yes | yes | yes |

Django REST Framework 3.14 or newer, including `drf-nested-routers`. FastAPI 0.100 or newer.

## Documentation

- [docs/cli.md](docs/cli.md): every command, option and output format.
- [docs/lockfile.md](docs/lockfile.md): the lockfile format.
- [docs/classification.md](docs/classification.md): how changes are labelled.
- [docs/heuristics-and-limits.md](docs/heuristics-and-limits.md): what authzlock can and
  cannot see.
- [docs/index.md](docs/index.md): all pages.
- [CHANGELOG.md](CHANGELOG.md): changes by release.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests and conventions.

## License

MIT. See [LICENSE](LICENSE).
