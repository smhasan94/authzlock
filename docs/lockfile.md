# Lockfile reference

`authzlock update` writes the authorization surface of a project to `authz.lock`, and
`authzlock check` compares a fresh extraction with it. The file is YAML, generated, and
meant to be committed and read in code review. Do not edit it by hand; regenerate it.

## Example

```yaml
schema_version: 1
routes:
- path: api/orders/
  name: api:order-list
  view: api.views.OrderViewSet
  methods:
  - GET
  - POST
  actions:
    GET: list
    POST: create
  permission_classes:
  - rest_framework.permissions.IsAuthenticated
  permission_source: settings-default
  authentication_classes:
  - rest_framework.authentication.SessionAuthentication
  authentication_source: settings-default
  django_auth: null
  object_scoping: null
- path: api/orders/<pk>/
  name: api:order-detail
  view: api.views.OrderViewSet
  methods:
  - DELETE
  - GET
  actions:
    DELETE: destroy
    GET: retrieve
  permission_classes:
  - api.permissions.IsOwner
  - rest_framework.permissions.IsAuthenticated
  permission_source: view
  authentication_classes:
  - rest_framework.authentication.SessionAuthentication
  authentication_source: settings-default
  django_auth: null
  object_scoping: null
- path: api/reports/
  name: api:reports
  view: api.views.ReportView
  methods:
  - GET
  actions: {}
  permission_classes: dynamic
  permission_source: view
  authentication_classes:
  - rest_framework.authentication.SessionAuthentication
  authentication_source: settings-default
  django_auth: null
  object_scoping: null
- path: members/
  name: members-only
  view: shop.views.members_only
  methods:
  - any
  actions: {}
  permission_classes: null
  permission_source: null
  authentication_classes: null
  authentication_source: null
  django_auth:
    login_required: true
    permission_required: []
    unknown_decorators: []
    user_passes_test: false
  object_scoping: null
custom_permissions:
  api.permissions.IsOwner:
    docstring: Only the owner of an order may read or delete it.
    name: IsOwner
    used_by:
    - DELETE,GET api/orders/<pk>/ -> api.views.OrderViewSet
```

## Top-level keys

- `schema_version`: the lockfile format version, currently `1`. authzlock refuses to read
  a lockfile with a newer version and asks you to upgrade.
- `ignore` (optional): the routes `authzlock update` leaves out, as `paths` (URL pattern
  prefixes) and `views` (view module prefixes), each sorted and deduplicated. Only non-empty
  lists are written, and the key is absent when nothing is ignored, so a lockfile without
  an ignore list is byte-identical to one written before the key existed. `check` and
  `diff` apply the recorded list; see [cli.md](cli.md#ignoring-routes).

  ```yaml
  ignore:
    paths:
    - admin/
    views:
    - debug_toolbar
  ```

- `routes`: one entry per URL pattern, sorted by `path`, then `view`.
- `custom_permissions`: permission classes whose module is not `rest_framework.permissions`
  (third-party classes included), keyed by dotted path and sorted by it. authzlock only
  inspects them; it never instantiates or calls them.

## Route keys

Keys always appear in this order.

- `path`: the full URL pattern as Django reports it, with the prefixes of every `include()`
  joined. `re_path` patterns keep their regex source, for example `^archive/(?P<year>[0-9]{4})/$`.
- `name`: the URL name with its namespaces joined by `:`, for example `api:order-list`, or
  `null` for an unnamed pattern.
- `view`: the dotted path of the view. Class-based views and ViewSets are named by their
  class, decorated functions by the function they wrap.
- `methods`: the HTTP methods the view accepts, upper-case and sorted, never `HEAD` or
  `OPTIONS`. A function view with no method restriction has `[any]`.
- `actions`: for DRF ViewSet routes, a map from method to action name such as
  `GET: list`; `{}` for every other view.
- `permission_classes`: the effective DRF permission classes as sorted dotted paths
  (composed permissions as expressions such as `(a.IsAuthenticated | b.IsOwner)` or
  `(~b.IsBlocked)`), the
  string `dynamic` when the view overrides `get_permissions` and authzlock will not guess,
  or `null` for views that are not DRF views. For a FastAPI route it lists the route's
  dependencies by dotted path, `Security` scopes as `path[scope]`.
- `permission_source`: `view` when the view or one of its base classes sets the classes
  (or overrides `get_permissions`), `action` when an `@action` sets its own
  `permission_classes`, `settings-default` when they come from
  `REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]`, `dependency` for every FastAPI route,
  `null` for non-DRF views.
- `authentication_classes`: like `permission_classes`, for authentication, with `dynamic`
  when the view overrides `get_authenticators`. For a FastAPI route, the class paths of the
  security schemes in its dependency tree.
- `authentication_source`: like `permission_source`, for authentication.
- `django_auth`: for plain Django views, the rules set by decorators and mixins:
  `login_required`, `permission_required` (sorted permission strings), `user_passes_test`
  (whether a custom test applies; the test is never run), and `unknown_decorators`
  (decorators authzlock saw but could not classify). `null` for DRF views.
- `object_scoping`: a heuristic for generic class-based views (DRF `GenericAPIView` and
  ViewSets, Django's `SingleObjectMixin` and `MultipleObjectMixin`). For each object hook
  (`get_object`, `get_queryset`, `perform_create`) it records `overridden`, true when the
  view or one of the project's own base classes or mixins defines the hook (the defaults in
  DRF and Django do not count), and `references_request_user`, true when the override reads
  `self.request.user` or `request.user` directly, false when it does not, `null` when the
  hook is not overridden or its source cannot be read. Calls into helpers are not followed,
  and the hooks are never run. `null` for every other view.

`dynamic`, `object_scoping`, `django_auth` and composed permissions are read by heuristics;
[heuristics-and-limits.md](heuristics-and-limits.md) says what each can and cannot tell you.

## Custom permission keys

- `docstring`: the first paragraph of the class's own docstring, or `null`.
- `name`: the class name.
- `used_by`: the route keys of every route that uses the class, sorted.

## Route key

Diffs, `used_by` lists and command output identify a route by its key:
`"<METHODS> <path> -> <view>"`, with the methods joined by commas, for example
`DELETE,GET api/orders/<pk>/ -> api.views.OrderViewSet`.

## Formatting guarantees

- UTF-8, `\n` line endings, block style, a single trailing newline.
- No YAML anchors or aliases.
- Every list whose order carries no meaning (`methods`, class lists, permission strings,
  `unknown_decorators`, `used_by`) is sorted, and mapping keys inside `actions`,
  `django_auth` and `object_scoping` are sorted, so the same project always produces the
  same bytes.

## What is guaranteed to be stable

For the same project source and the same installed Django and DRF versions, `authzlock
update` writes byte-identical output regardless of:

- the run: repeated runs, under any `PYTHONHASHSEED`, give the same bytes;
- the working directory `authzlock` runs from, and the order of entries on `sys.path` or
  `PYTHONPATH`;
- where the project is checked out: two clones at different absolute locations give the
  same bytes;
- the machine and operating system user;
- the Python version, from 3.10 to 3.13.

The lockfile never contains an absolute file path, a date or time, a hostname or the
authzlock version. Views and classes are named by dotted path, never by file. If a value
that would be written as a dotted path looks like an absolute path (it starts with `/`, a
drive letter such as `C:\` or a `\\` share), `update` fails with an error instead of writing
it. URL patterns and docstrings are the project's own text and are written as they are.

Not guaranteed: identical output across Django or DRF versions that genuinely build
different URL patterns. For example, DRF 3.14's `DefaultRouter` writes its API root and
format-suffix routes as regexes (`^$`, `^\.(?P<format>[a-z0-9]+)/?$`) where DRF 3.15 and
later write `''` and `<drf_format_suffix:format>`. Upgrading such a dependency can change
the lockfile; regenerate it with `authzlock update` and review the change like any other.

The test suite enforces this: it compares bytes across hash seeds, working directories and
checkout locations, and every CI cell (each supported Python, Django and DRF combination)
compares the lockfiles of the fixture projects with committed golden files.
