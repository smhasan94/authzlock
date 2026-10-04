# diff JSON document

`authzlock diff --base <ref> --format json` prints one JSON document to stdout. It is the
same information as the text and markdown output, for other tools to read.
[`diff.schema.json`](diff.schema.json) is its JSON Schema; `tests/test_diff_formats.py`
fails when this page and the schema list different keys. `--format sarif` is built from
the same document; see [cli.md](cli.md#sarif-and-github-code-scanning).

The document is printed even with `--quiet`, so redirecting it to a file always gives a
valid document. Exit codes and `--fail-on` work as for the other formats; on an error
stdout is empty and the message is on stderr. Keys always appear in the order below, two
runs on the same tree print the same bytes, and no value contains an absolute path.

```json
{
  "schema_version": 1,
  "tool": {"name": "authzlock", "version": "0.3.0"},
  "base": {"ref": "origin/main", "lockfile": "authz.lock", "lockfile_found": true},
  "ignore": {"base": {"paths": [], "views": []}, "current": {"paths": [], "views": []},
             "changed": false},
  "summary": {"loosened": 1, "tightened": 0, "added": 0, "removed": 0, "changed_unknown": 0,
              "equivalent": 0},
  "changes": [
    {
      "label": "loosened",
      "rule": "R2",
      "reason": "R2: custom class billing.permissions.IsOwner removed",
      "route": {
        "key": "DELETE,GET invoices/<int:pk>/ -> billing.views.InvoiceDetailView",
        "path": "invoices/<int:pk>/",
        "methods": ["DELETE", "GET"],
        "view": "billing.views.InvoiceDetailView"
      },
      "fields": [
        {
          "field": "permission_classes",
          "old": ["billing.permissions.IsOwner", "rest_framework.permissions.IsAuthenticated"],
          "new": ["rest_framework.permissions.IsAuthenticated"]
        }
      ],
      "location": {"file": "billing/views.py", "line": 9}
    }
  ],
  "custom_permissions": {"added": [], "removed": ["billing.permissions.IsOwner"], "changed": []}
}
```

## Keys

`[]` marks the items of a list.

| Key | Type | Meaning |
|-----|------|---------|
| `schema_version` | integer | Version of this document, `1`. Independent of the lockfile schema version. |
| `tool` | object | The program that wrote the document. |
| `tool.name` | string | Always `authzlock`. |
| `tool.version` | string | The authzlock version. |
| `base` | object | Where the old side came from. |
| `base.ref` | string | The `--base` ref as given. |
| `base.lockfile` | string | Lockfile path relative to the repository root, with forward slashes. |
| `base.lockfile_found` | boolean | `false` when the ref has no lockfile at that path; every route is then `added`. |
| `ignore` | object | The route ignore lists ([cli.md](cli.md#ignoring-routes)) on both sides. |
| `ignore.base` | object | The list recorded in the base lockfile; empty lists when it has none or there is no base lockfile. |
| `ignore.base.paths` | list | Ignored path prefixes, sorted. |
| `ignore.base.views` | list | Ignored view module prefixes, sorted. |
| `ignore.current` | object | The list applied to the current project: the working tree's lockfile's, or the base's when the working tree has no lockfile. |
| `ignore.current.paths` | list | Ignored path prefixes, sorted. |
| `ignore.current.views` | list | Ignored view module prefixes, sorted. |
| `ignore.changed` | boolean | `true` when the two lists differ; routes the change drops or restores are then `removed` or `added`, and SARIF output carries the same note as the text output. |
| `summary` | object | Number of routes per label, the same counts as the summary line. |
| `summary.loosened` | integer | Routes labelled `loosened`. |
| `summary.tightened` | integer | Routes labelled `tightened`. |
| `summary.added` | integer | Routes labelled `added`. |
| `summary.removed` | integer | Routes labelled `removed`. |
| `summary.changed_unknown` | integer | Routes labelled `changed-unknown`. |
| `summary.equivalent` | integer | Routes labelled `equivalent`: the permission list changed but no method's effective rule did. |
| `changes` | list | One entry per route that differs, sorted by route key. Empty when nothing differs. |
| `changes[].label` | string | `loosened`, `tightened`, `added`, `removed`, `changed-unknown` or `equivalent`. |
| `changes[].rule` | string or null | The rule that decided the label, `R1` to `R10` (see [classification.md](classification.md)); `null` for added and removed routes. |
| `changes[].reason` | string | One-line reason; starts with the rule id for changed routes. |
| `changes[].route` | object | The route: the current one, or the base one when removed. |
| `changes[].route.key` | string | Route key, `<METHODS> <path> -> <view>`, as in `used_by` and the other outputs. |
| `changes[].route.path` | string | URL pattern. |
| `changes[].route.methods` | list | HTTP methods. |
| `changes[].route.view` | string | Dotted path of the view. |
| `changes[].fields` | list | Changed lockfile fields. For an added or removed route, every lockfile field of the route except `path`, `view` and `methods`, with `null` on the missing side. |
| `changes[].fields[].field` | string | Lockfile field name; a nested field is dotted, for example `django_auth.login_required`. |
| `changes[].fields[].old` | any | Value in the base lockfile, exactly as in the lockfile: `dynamic`, `null` and composed expressions are passed through. |
| `changes[].fields[].new` | any | Value in the current extraction, in the same form. |
| `changes[].location` | object | Where to look in the repository. |
| `changes[].location.file` | string | File that defines the view, relative to the repository root with forward slashes. Falls back to the lockfile path when the view cannot be found in the checkout (removed routes, views in installed packages, views without source). |
| `changes[].location.line` | integer | First line of the view definition, or `1` for the fallback. |
| `custom_permissions` | object | Changes to the custom permission registry of the lockfile. |
| `custom_permissions.added` | list | Dotted paths of classes added to the registry. |
| `custom_permissions.removed` | list | Dotted paths of classes removed from the registry. |
| `custom_permissions.changed` | list | Registry entries that changed. |
| `custom_permissions.changed[].path` | string | Dotted path of the class. |
| `custom_permissions.changed[].fields` | list | Changed registry fields. |
| `custom_permissions.changed[].fields[].field` | string | Registry field name, for example `docstring`. |
| `custom_permissions.changed[].fields[].old` | any | Old value. |
| `custom_permissions.changed[].fields[].new` | any | New value. |

Source locations are resolved when `diff` runs and are never written to the lockfile:
line numbers change with every edit, and the lockfile only records access rules.
