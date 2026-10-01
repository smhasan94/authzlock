# Command-line reference

authzlock is run as `authzlock <command>`; `python -m authzlock <command>` is equivalent.
`authzlock --version` prints the version and `authzlock --help` lists the commands.

## Shared conventions

Every command that reads a project or a lockfile accepts these options:

| Option | Default | Meaning |
|--------|---------|---------|
| `--settings MODULE` | `DJANGO_SETTINGS_MODULE` | Django settings module to load. Overrides the environment variable. |
| `--lockfile PATH` | `authz.lock` | Lockfile path, relative to the current directory. |
| `--quiet`, `-q` | off | Print nothing on success. Errors are still printed. |

The project is loaded in the authzlock process, so its packages must be importable: run
authzlock from the project root or put the project on `PYTHONPATH`.

Exit codes:

| Code | Meaning |
|------|---------|
| 0 | Success. |
| 1 | The lockfile and the project differ (used by `check` and `diff`). |
| 2 | Error: the project could not be loaded, or the lockfile could not be read or written. |

Errors are printed to stderr as one or two plain lines starting with `authzlock:`. The
second line says what to do, for example:

```text
authzlock: No Django settings module given.
Set DJANGO_SETTINGS_MODULE or pass --settings, for example --settings mysite.settings.
```

## authzlock update

Loads the project, extracts its access rules and writes them to the lockfile. See
[lockfile.md](lockfile.md) for the file format.

```console
$ authzlock update --settings mysite.settings
authz.lock: 12 routes written
```

- The lockfile's directory is created if it does not exist.
- The file is written only when its content changes. When the existing file already holds
  exactly the new content it is left untouched (its modification time does not change) and
  the command prints `authz.lock: unchanged`.
- With `--quiet`, nothing is printed on success.
- Exit code 0 on success, 2 on any error, such as a settings module that cannot be found
  or raises on import, or a lockfile path that cannot be written. A settings module that
  raises has its exception text printed on the second stderr line.

Run `authzlock update` after changing views, URLs or permission settings, and commit the
updated `authz.lock` with the change.

## authzlock check

Loads the project, extracts its access rules and compares them with the lockfile. This is
the command to run in CI and in a pre-commit hook.

```console
$ authzlock check --settings mysite.settings
authz.lock: up to date
```

The comparison is between the parsed lockfile and the fresh extraction, not between file
bytes, so a lockfile that differs only in YAML formatting (blank lines, quoting, key
order) passes. Routes are matched by path and view.

When they differ, `check` prints what changed and exits with code 1. Routes the project has
but the lockfile lacks are listed under `added`, routes only in the lockfile under
`removed`, and routes whose recorded fields differ under `changed`, with one
`field: old -> new` line per field (nested fields are dotted, such as
`object_scoping.get_queryset.overridden`). Changes to the custom permission registry follow
in their own groups. Empty groups are left out.

```text
authz.lock is out of date.
added:
  GET ^invoices/summary/$ -> billing.views.InvoiceViewSet
removed:
  GET ^reports/$ -> billing.views.ReportViewSet
changed:
  POST ^invoices/(?P<pk>[^/.]+)/archive/$ -> billing.views.InvoiceViewSet
    permission_classes: [rest_framework.permissions.AllowAny] -> [rest_framework.permissions.IsAdminUser]
custom permissions added:
  billing.permissions.IsOwner

To fix: run `authzlock update` and commit authz.lock.
```

Each route is shown by its key, `<METHODS> <path> -> <view>`. Values are shown on one line:
lists as `[a, b]`, mappings as `{key: value}`, a missing value as `null`, and a text with
line breaks in double quotes with `\n` escapes.

- Exit code 0 when the lockfile is up to date, 1 when it differs from the project, 2 on any
  error: the lockfile is missing (the message suggests `authzlock update`), it cannot be
  read or parsed, its `schema_version` is newer than this authzlock supports, or the project
  cannot be loaded.
- The lockfile is read before the project is loaded and is never written.
- With `--quiet`, nothing is printed when the lockfile is up to date. A mismatch is always
  printed.
