# Command-line reference

authzlock is run as `authzlock <command>`; `python -m authzlock <command>` is equivalent.
There are three commands: [`update`](#authzlock-update), [`check`](#authzlock-check) and
[`diff`](#authzlock-diff). This page lists every option that `--help` shows;
`tests/test_docs.py` fails when the two disagree.

## Global options

These go before the command, for example `authzlock --version`.

| Option | Default | Meaning |
|--------|---------|---------|
| `--version` | | Print `authzlock <version>` and exit. |
| `--help` | | List the commands and exit. `authzlock` with no command does the same. |

## Shared conventions

Every command that reads a project or a lockfile accepts these options:

| Option | Default | Meaning |
|--------|---------|---------|
| `--settings MODULE` | `DJANGO_SETTINGS_MODULE` | Django settings module to load. Overrides the environment variable and [configuration](#configuration). |
| `--lockfile PATH` | `authz.lock` | Lockfile path, relative to the current directory. Overrides [configuration](#configuration). |
| `--quiet`, `-q` | off | Print nothing on success. Errors are still printed. |
| `--help` | | Show the command's options and exit. |

The project is loaded in the authzlock process, so its settings module and packages must be
importable. Run authzlock from the project root, the directory that holds `manage.py`:
authzlock puts the current directory first on the import path, as `manage.py` does. To run
it from another directory, put the project root on `PYTHONPATH`.

Exit codes:

| Code | Meaning |
|------|---------|
| 0 | Success. |
| 1 | The lockfile and the project differ (used by `check` and `diff`). |
| 2 | Error: the project could not be loaded, the lockfile could not be read or written, or git failed (used by `diff`). |

Errors are printed to stderr as one or two plain lines starting with `authzlock:`. The
second line says what to do, for example:

```text
authzlock: No Django settings module given.
Set DJANGO_SETTINGS_MODULE or pass --settings, for example --settings mysite.settings.
```

## Configuration

Instead of passing the same options every time, set them once in a `[tool.authzlock]` table
in `pyproject.toml`. authzlock reads the nearest `pyproject.toml` in the current directory or
one of its parents; the table is optional.

```toml
[tool.authzlock]
settings = "mysite.settings"
lockfile = "config/authz.lock"
fail_on = "loosened"
```

| Key | Meaning |
|-----|---------|
| `settings` | Django settings module, as for `--settings`. |
| `lockfile` | Lockfile path, relative to the directory that holds `pyproject.toml`, so every command finds the same file from any directory. |
| `fail_on` | `any` or `loosened`, as for `diff --fail-on`. |

Precedence, highest first:

- settings module: `--settings`, then `DJANGO_SETTINGS_MODULE`, then `settings`;
- lockfile: `--lockfile`, then `lockfile`, then `authz.lock`;
- fail-on: `--fail-on`, then `fail_on`, then `any`.

Every key must be a non-empty string. An unknown key, a value of the wrong type, a `fail_on`
other than `any` or `loosened`, or a file that is not valid TOML is an error (exit 2) that
names the file and the key or line. When the settings module from `pyproject.toml` fails to
import, the error says so. The settings module must still be importable from where authzlock
runs; see [Shared conventions](#shared-conventions).

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

## authzlock diff

Compares the lockfile committed at a git ref with a fresh extraction of the project and
labels every difference. This is the command the
[GitHub Action](github-action.md) runs on a pull request.
[scenario.md](scenario.md) walks through a complete example.

```console
$ authzlock diff --base origin/main --settings mysite.settings
```

| Option | Default | Meaning |
|--------|---------|---------|
| `--base REF` | required | Git ref (branch, tag or commit) whose committed lockfile is the old side. |
| `--format text\|markdown\|json\|sarif` | `text` | Output format. `json` and `sarif` are described below. |
| `--fail-on any\|loosened` | `any` | `any`: exit 1 on any change. `loosened`: exit 1 only when a route is loosened. Overrides [configuration](#configuration). |

`--settings`, `--lockfile` and `--quiet` work as for the other commands.

The old side is the lockfile as committed at `--base`, read with
`git show <ref>:<path>`, where the path is the `--lockfile` path made relative to the
repository root (`git rev-parse --show-toplevel`), so `diff` works from any directory of
the checkout. The new side is the project as it is in the working tree, extracted fresh;
the lockfile in the working tree is not read, so a pull request whose lockfile is stale is
still compared correctly. When the base ref has no lockfile at that path, the base counts
as empty, every current route is reported as `added`, and the output starts with the note
`base ref has no authz.lock (<ref>:<path>); every route is reported as added`.

Every route that differs gets one label: `added`, `removed`, `loosened`, `tightened` or
`changed-unknown`. [classification.md](classification.md) lists the rules R1 to R8 that
decide between the last three.

### Text output

One line per route, grouped by label in the order loosened, tightened, added, removed,
changed-unknown, with a blank line between groups. Each line is the label (padded to 15
characters), the route key `<METHODS> <path> -> <view>`, then the field changes as
`field: old -> new` separated by `; ` and, for a changed route, the rule and reason in
parentheses. Added and removed routes show their `permission_classes` and `django_auth`
instead. Custom permission registry changes follow as `custom-permission added|removed|changed`
lines. The last line is the summary line.

```text
loosened        DELETE,GET orders/<int:pk>/ -> api.views.OrderDetailView  permission_classes: [api.permissions.IsOwner] -> [rest_framework.permissions.IsAuthenticated]  (R2: custom class api.permissions.IsOwner replaced by built-in rest_framework.permissions.IsAuthenticated)

tightened       GET explicit/ -> api.views.ExplicitView  permission_classes: [rest_framework.permissions.IsAuthenticated] -> [rest_framework.permissions.IsAdminUser]  (R1: strongest built-in rest_framework.permissions.IsAuthenticated -> rest_framework.permissions.IsAdminUser)

custom-permission changed api.permissions.IsOwner  used_by: [DELETE,GET orders/<int:pk>/ -> api.views.OrderDetailView, GET composed/ -> api.views.ComposedView, GET notes/ -> api.views.NotesView] -> [GET composed/ -> api.views.ComposedView, GET notes/ -> api.views.NotesView]

1 loosened, 1 tightened, 0 added, 0 removed, 0 changed-unknown
```

When nothing differs, the output is the single line `no changes`.

### Markdown output

Meant for a pull request comment. The first line is the hidden marker `<!-- authzlock -->`,
which the GitHub Action uses to find and update its own comment. Then come a heading, the
note when the base has no lockfile, the summary line, a table of the `loosened` and
`tightened` routes, and one collapsed `<details>` section each for `added`, `removed` and
`changed-unknown` routes and for custom permission registry changes. Every table has the
columns Change, Methods, Path, View and Details; Details holds the rule and reason and one
`field`: `old` → `new` entry per changed field. A `|` inside a value is escaped as `\|`.

```markdown
<!-- authzlock -->
### authzlock: access-control changes

1 loosened, 1 tightened, 0 added, 0 removed, 0 changed-unknown

| Change | Methods | Path | View | Details |
|---|---|---|---|---|
| loosened | DELETE,GET | `orders/<int:pk>/` | `api.views.OrderDetailView` | `R2: custom class api.permissions.IsOwner replaced by built-in rest_framework.permissions.IsAuthenticated`<br>`permission_classes`: `[api.permissions.IsOwner]` → `[rest_framework.permissions.IsAuthenticated]` |
| tightened | GET | `explicit/` | `api.views.ExplicitView` | `R1: strongest built-in rest_framework.permissions.IsAuthenticated -> rest_framework.permissions.IsAdminUser`<br>`permission_classes`: `[rest_framework.permissions.IsAuthenticated]` → `[rest_framework.permissions.IsAdminUser]` |
```

When nothing differs, the summary line has five zeros and is followed by
`No access-control changes against <ref>.`

### Summary line

Both formats contain exactly one summary line, on a line of its own:

```text
<n> loosened, <n> tightened, <n> added, <n> removed, <n> changed-unknown
```

The five counts are always present, in this order, and count routes. Custom permission
registry changes are not counted. CI scripts may parse this line.

### JSON output

`--format json` prints one JSON document with the summary counts, every change with its
label, rule, reason, changed fields and the file and line of its view, and the custom
permission registry changes. [diff-json.md](diff-json.md) describes every key and
[diff.schema.json](diff.schema.json) is its JSON Schema. The document is printed even with
`--quiet`.

### SARIF and GitHub code scanning

`--format sarif` prints a [SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html)
log built from the same document: one rule per label and one result per changed route,
at the line of the route's view. Levels: `loosened` is an error, `added` and
`changed-unknown` are warnings, `tightened` and `removed` are notes. Each result carries
the route key in `partialFingerprints`, so code scanning keeps one alert per route across
pushes. Custom permission registry changes have no route and are not results. A base ref
without a lockfile adds a note to the run's `toolExecutionNotifications`.

The log describes the changes in one pull request, not the state of the repository: after
the pull request is merged, the next diff is empty and the alerts close. To show the
results in a pull request's code scanning view:

```yaml
name: authzlock code scanning
on: pull_request
permissions:
  contents: read
  security-events: write
jobs:
  authzlock:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: pip install authzlock
      - run: >
          authzlock diff --base origin/${{ github.base_ref }} --format sarif
          --settings mysite.settings > authzlock.sarif || true
      - uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: authzlock.sarif
          category: authzlock
```

`|| true` keeps the job going when `diff` exits 1 so the upload step runs; code scanning
then reports the loosened routes as errors.

### Exit codes

- 0: no differences, or `--fail-on loosened` and no route is loosened.
- 1: with `--fail-on any` (the default), anything differs, including a custom permission
  registry change; with `--fail-on loosened`, at least one route is loosened.
- 2: error: the current directory is not inside a git repository, the ref does not exist
  (the message names the ref and includes git's error), the lockfile path is outside the
  repository, the base lockfile cannot be parsed or has a newer `schema_version`, git is not
  installed, or the project cannot be loaded.

Git and the base lockfile are read before the project is loaded. With `--quiet`, nothing is
printed when nothing differs; any difference is always printed.
