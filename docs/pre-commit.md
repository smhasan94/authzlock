# pre-commit hooks

authzlock ships two [pre-commit](https://pre-commit.com) hooks, declared in
`.pre-commit-hooks.yaml` at the root of this repository:

| Hook id | Runs | Use |
|---------|------|-----|
| `authzlock-check` | `authzlock check` | Fails the commit when `authz.lock` does not match the project. |
| `authzlock-update` | `authzlock update` | Rewrites `authz.lock`; fails when the file changed so you can stage it. |

Both run once per commit on the whole project (`always_run: true`, `pass_filenames: false`),
whichever files are staged. `authzlock-check` is the one to enable; `authzlock-update` runs
only if you list it in your config.

## Configuration

Add this to `.pre-commit-config.yaml` at the root of your Django project and run
`pre-commit install`:

```yaml
repos:
  - repo: https://github.com/smhasan94/authzlock
    rev: v0.3.1  # use the latest release tag
    hooks:
      - id: authzlock-check
        args: ["--settings", "mysite.settings"]
        additional_dependencies:
          - "django==5.2.*"
          - "djangorestframework==3.16.*"
```

### Django settings

authzlock loads your project to read its access rules, so it needs a settings module. Give
it in one of two ways:

- `args: ["--settings", "mysite.settings"]` in the hook entry, as above. This overrides the
  environment variable.
- `DJANGO_SETTINGS_MODULE` set in the environment that runs `git commit`. Leave out `args`
  in that case.

Without either, the hook fails with `No Django settings module or FastAPI app given.`
For a FastAPI app, pass `args: ["--app", "main:app"]` or set `AUTHZLOCK_APP` instead.

pre-commit runs the hooks from the repository root, and authzlock puts the current
directory first on the import path, as `manage.py` does. A settings module in the
repository (such as `mysite/settings.py`) can therefore be imported without setting
`PYTHONPATH`. The hook entry is `python -m authzlock`, which gets the same import path from
the interpreter; running the `authzlock` command by hand from the repository root behaves
the same. If your project lives in a subdirectory, set `PYTHONPATH` to that directory in the
environment that runs `git commit`.

### Dependencies

pre-commit installs each hook into its own virtualenv, which contains authzlock and nothing
else. Your project is imported inside that virtualenv, so list under
`additional_dependencies` every package your settings and URL configuration import:
Django and Django REST Framework at the versions your project uses, plus third-party apps in
`INSTALLED_APPS` and any packages your views import at module level (for example
`drf-nested-routers`). Pin them to the versions in your own requirements, so the hook
extracts the same routes as your CI.

When a dependency is missing, the hook fails with a message naming the module that could not
be imported. After changing `additional_dependencies`, pre-commit rebuilds the hook
environment on the next run.

## Output

When `authz.lock` is up to date the hook passes. When it is stale, the hook fails and prints
the same report as `authzlock check`, ending with the fix:

```text
authzlock check..........................................................Failed
- hook id: authzlock-check
- exit code: 1

authz.lock is out of date.
added:
  GET ^invoices/summary/$ -> billing.views.InvoiceViewSet

To fix: run `authzlock update` and commit authz.lock.
```

Exit code 2 means authzlock could not run, for example when `authz.lock` does not exist yet
or the project failed to load; the message says what to do. See [cli.md](cli.md) for the
exit codes and messages.

## Updating the lockfile from the hook

To have the hook rewrite `authz.lock` instead of only checking it, use `authzlock-update`
(with the same `args` and `additional_dependencies`):

```yaml
      - id: authzlock-update
        args: ["--settings", "mysite.settings"]
        additional_dependencies:
          - "django==5.2.*"
          - "djangorestframework==3.16.*"
```

When the lockfile is stale, the hook rewrites it and fails with `files were modified by this
hook`. Review the change with `git diff authz.lock`, stage it and commit again; the second
run passes. Prefer `authzlock-check` if access-rule changes should always be a deliberate
step: `authzlock-update` makes it easy to stage a loosened permission without reading it.

## Running the hook by hand

```console
$ pre-commit run authzlock-check --all-files
```
