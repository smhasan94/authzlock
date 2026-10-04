# authzlock

[![CI](https://github.com/smhasan94/authzlock/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/smhasan94/authzlock/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/authzlock.svg)](https://pypi.org/project/authzlock/)

An authorization lockfile for Django and Django REST Framework.

In a Django project, the rules for who may call which endpoint are spread across
`permission_classes` on views, `DEFAULT_PERMISSION_CLASSES` in settings, `get_permissions()`
and `get_queryset()` overrides, and decorators such as `login_required`. A pull request can
make an endpoint reachable by more users with a one-line change, and the reviewer sees the
line, not the effect. authzlock reads those rules from the code, writes them for every route
to a committed file, `authz.lock`, and on each pull request reports which routes changed and
whether a change made access looser.

**Status: pre-release.** The first release, 0.1.0, is not published yet. Until it is,
`pip install authzlock`, the `smhasan94/authzlock@v1` action tag and the `v0.1.0` pre-commit
rev below do not resolve; install from GitHub instead, as shown under Install.

## Install

```sh
pip install authzlock
```

Install it into the same environment as your project, because authzlock imports your
settings and URL configuration. Django 4.2 or newer is installed with it if missing; Django REST
Framework is optional and only needed if your project uses it. Before the first release, install from the repository:

```sh
pip install git+https://github.com/smhasan94/authzlock
```

## Quickstart

Run these from your project root, the directory that holds `manage.py`, inside a git
repository. Replace `mysite.settings` with your settings module.

```sh quickstart
export DJANGO_SETTINGS_MODULE=mysite.settings
authzlock update
git add authz.lock
git commit -m "Add authz.lock"
authzlock check
```

`update` writes `authz.lock` and prints how many routes it recorded. `check` prints
`authz.lock: up to date` and exits 0.

Now change an access rule. In the example project used to test this README, an `@action`
that only admins may call is opened to every signed-in user:

```diff
-    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
+    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
     def archive(self, request: Request, pk: Any = None) -> Response:
```

```sh quickstart
authzlock check  # exits 1
authzlock diff --base HEAD  # exits 1
```

`check` exits 1 and lists the routes whose rules no longer match `authz.lock`. `diff` compares
the lockfile committed at `HEAD` with the code as it is now and labels each change. The
action is served by three routes, and all three are `loosened`, because `IsAuthenticated`
lets in more users than `IsAdminUser`:

<!-- readme-diff:start -->
```text
loosened        POST ^invoices/(?P<pk>[^/.]+)/archive/$ -> billing.views.InvoiceViewSet  permission_classes: [rest_framework.permissions.IsAdminUser] -> [rest_framework.permissions.IsAuthenticated]  (R1: strongest built-in rest_framework.permissions.IsAdminUser -> rest_framework.permissions.IsAuthenticated)
loosened        POST ^invoices/(?P<pk>[^/.]+)/archive\.(?P<format>[a-z0-9]+)/?$ -> billing.views.InvoiceViewSet  permission_classes: [rest_framework.permissions.IsAdminUser] -> [rest_framework.permissions.IsAuthenticated]  (R1: strongest built-in rest_framework.permissions.IsAdminUser -> rest_framework.permissions.IsAuthenticated)
loosened        POST v2/^invoices/(?P<pk>[^/.]+)/archive/$ -> billing.views.InvoiceViewSet  permission_classes: [rest_framework.permissions.IsAdminUser] -> [rest_framework.permissions.IsAuthenticated]  (R1: strongest built-in rest_framework.permissions.IsAdminUser -> rest_framework.permissions.IsAuthenticated)

3 loosened, 0 tightened, 0 added, 0 removed, 0 changed-unknown
```
<!-- readme-diff:end -->

`diff` exits 1 whenever something changed; with `--fail-on loosened` it exits 1 only when a
route is loosened. To accept the change, record it and commit it with the code:

```sh quickstart
authzlock update
git commit -am "Let signed-in users archive invoices"
authzlock check
```

`check` exits 0 again. In CI, run `check` to make sure `authz.lock` is current, and `diff`
against the target branch to see what a pull request changes; the GitHub Action below does
the second. [docs/scenario.md](docs/scenario.md) walks through a longer example.

Exit codes for every command: 0 success, 1 the lockfile and the code differ, 2 error (the
project could not be loaded, the lockfile could not be read, or git failed).

## The lockfile

`authz.lock` is YAML, sorted and stable, so the same code always gives the same bytes and a
review diff shows only real changes. Do not edit it by hand; run `authzlock update`. Two of
the routes from the example project:

```yaml
schema_version: 1
routes:
- path: ^customers/$
  name: customer-list
  view: billing.views.CustomerViewSet
  methods:
  - GET
  actions:
    GET: list
  permission_classes:
  - rest_framework.permissions.IsAuthenticated
  permission_source: settings-default
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

Each route records its path, URL name, view, HTTP methods, the effective DRF permission and
authentication classes and where they come from (`view`, `action` or `settings-default`),
Django decorators for plain views, and whether the view overrides the hooks that scope
objects to the caller. A `get_permissions()` override is recorded as `dynamic`. Custom
permission classes are listed under `custom_permissions` with their docstring and the
routes that use them. [docs/lockfile.md](docs/lockfile.md) describes every key.

## How changes are classified

`authzlock diff` gives every route that differs one label: `added`, `removed`, `loosened`,
`tightened` or `changed-unknown`. For a route on both sides, the rules below run in order and
the first that applies decides. Only DRF's built-in classes are ranked (`AllowAny` <
`IsAuthenticatedOrReadOnly` < `IsAuthenticated` < `IsAdminUser`), and Django decorators
(none < `login_required` < `permission_required`). A false `loosened` alarm is worse than
`changed-unknown`, so authzlock never guesses what a custom, composed or `dynamic`
permission does.

| Rule | Applies when | Label | Example |
|------|--------------|-------|---------|
| R1 | Both lists hold only ranked built-ins and the strongest class differs | `loosened` if the strongest class is weaker, `tightened` if stronger | `[IsAuthenticated]` to `[AllowAny]` is `loosened` |
| R2 | An unranked class is removed, the new list holds no unranked class, and the new strongest built-in is at most `IsAuthenticated` or at most the old strongest built-in | `loosened` | `[shop.permissions.IsOwner]` to `[IsAuthenticated]` is `loosened` |
| R3 | An unranked class is replaced by another unranked class, or by `IsAdminUser` | `changed-unknown` | `[shop.permissions.IsOwner]` to `[IsAdminUser]` is `changed-unknown` |
| R4 | An unranked class is added and every old entry is kept | `tightened` | `[IsAuthenticated]` to `[IsAuthenticated, shop.permissions.IsOwner]` is `tightened` |
| R5 | Either side of a changed field is `dynamic` | `changed-unknown` | `dynamic` to `[IsAuthenticated]` is `changed-unknown` |
| R6 | Only `django_auth.login_required` or `django_auth.permission_required` changed | `tightened` when the Django auth rank rises or `permission_required` gains entries; `loosened` for the reverse | `login_required` true to false is `loosened` |
| R7 | Only `methods` (and `actions`) changed and `methods` gained entries | `changed-unknown` | `[DELETE, GET]` to `[DELETE, GET, PUT]` is `changed-unknown` |
| R8 | Anything else | `changed-unknown` | `[(IsAuthenticated \| shop.permissions.IsOwner)]` to `[IsAuthenticated]` is `changed-unknown` |

R1 to R4 apply only when `permission_classes` is the one access field that changed.
[docs/classification.md](docs/classification.md) has the full rules, examples and the
cases that are `changed-unknown` on purpose.

## GitHub Action

The action runs `authzlock diff` on a pull request against its base branch, posts the result
as one comment that it updates on every push, and fails the job when a route is loosened.
Save this as `.github/workflows/authzlock.yml`:

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

Install your project's dependencies before the action, in the Python version you give it.
Inputs, outputs, fork pull requests and how to also run `check` are in
[docs/github-action.md](docs/github-action.md).

## pre-commit

The `authzlock-check` hook fails a commit when `authz.lock` does not match the code. Add this
to `.pre-commit-config.yaml` and run `pre-commit install`:

```yaml
repos:
  - repo: https://github.com/smhasan94/authzlock
    rev: v0.1.0
    hooks:
      - id: authzlock-check
        args: ["--settings", "mysite.settings"]
        additional_dependencies:
          - "django==5.2.*"
          - "djangorestframework==3.16.*"
```

The hook runs in its own virtualenv, so list every package your settings and URL
configuration import under `additional_dependencies`, pinned like your project. The
`authzlock-update` hook and the details are in [docs/pre-commit.md](docs/pre-commit.md).

## What authzlock does not do

- It does not support FastAPI or any framework other than Django and Django REST Framework.
- It does not prove that custom permission logic is correct. A custom class such as
  `IsOwner` is recorded by name with its docstring; its code is never run or judged.
- It does not do black-box testing of a running app. It reads code and settings, sends no
  HTTP requests and needs no users, roles file or seeded data.
- It does not generate tests for logged-in users. `authzlock gen-tests` writes pytest
  checks from the lockfile that anonymous requests to protected routes are refused, using
  Django's test client in-process; routes it cannot reason about get a skipped test that
  says why.

Some of what it records comes from a heuristic, and the lockfile names it as such.
`dynamic` means the view overrides `get_permissions()` and the classes are only known at
request time. `object_scoping` records whether `get_object`, `get_queryset` and
`perform_create` are overridden and whether the override reads `request.user` directly; it
does not follow helper calls and does not show that the query is correct. Decorators are
detected by reading the view's source, and ones authzlock cannot classify are listed under
`unknown_decorators`. A green `check` means the lockfile matches the code, not that the
rules are right. authzlock runs offline and sends nothing anywhere.
[docs/heuristics-and-limits.md](docs/heuristics-and-limits.md) covers each heuristic and its
limits.

## Compatibility

| Python | Django 4.2 | Django 5.1 | Django 5.2 | Django 6.0 | Django 6.1 |
|--------|------------|------------|------------|------------|------------|
| 3.10 | yes | yes | yes | no | no |
| 3.11 | yes | yes | yes | no | no |
| 3.12 | yes | yes | yes | yes | yes |
| 3.13 | no | yes | yes | yes | yes |

Django REST Framework 3.14 and newer. CI runs every cell above with DRF 3.16 or newer, and
DRF 3.14 on Django 4.2 with Python 3.12. Routers from `drf-nested-routers` are supported.
Django 4.2 does not support Python 3.13, and Django 6.0 and newer need Python 3.12.

## Documentation

[docs/index.md](docs/index.md) lists every page. The main ones:

- [docs/cli.md](docs/cli.md): commands, options, output formats and exit codes.
- [docs/lockfile.md](docs/lockfile.md): the lockfile format and its stability guarantees.
- [docs/classification.md](docs/classification.md): the rules R1 to R8.
- [docs/heuristics-and-limits.md](docs/heuristics-and-limits.md): what the heuristics can
  and cannot tell you, and what a green `check` does not prove.
- [docs/scenario.md](docs/scenario.md): a pull request that drops `IsOwner`, end to end.
- [docs/github-action.md](docs/github-action.md): the GitHub Action.
- [docs/pre-commit.md](docs/pre-commit.md): the pre-commit hooks.
- [CHANGELOG.md](CHANGELOG.md): changes by release.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the setup, conventions and how to add a test
project, [DEVELOPMENT.md](DEVELOPMENT.md) for the project brief and development commands,
[docs/requirements.md](docs/requirements.md) for the requirements and
[docs/releasing.md](docs/releasing.md) for the release steps. The backlog lives in Linear and
is mirrored in [docs/backlog.md](docs/backlog.md). `tests/test_readme.py` runs the quickstart
above against the `drf_viewsets` test project and checks the lockfile excerpt, the rule table
and the snippets against their sources; `pytest tests/test_readme.py --update-docs` rewrites
the `diff` output shown above.

Every pull request and every push to `main` runs `.github/workflows/ci.yml`: a `lint` job
(ruff), a `typecheck` job (mypy strict) and one `tests (python=X, django=Y)` job per supported
combination, eleven in all, plus `tests (python=3.12, django=4.2, drf=3.14)` against the
oldest supported DRF. The jobs are the same nox sessions that `nox` runs locally with no
arguments. Mark `lint`, `typecheck` and every `tests (...)` job as required status checks on
`main` in the repository settings so a red check blocks merging.

## License

MIT. See [LICENSE](LICENSE).
