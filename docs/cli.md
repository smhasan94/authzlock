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
