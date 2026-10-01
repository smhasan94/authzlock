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
    name: IsOwner
    doc: Only the owner of an order may read or delete it.
    used_by:
    - DELETE,GET api/orders/<pk>/ -> api.views.OrderViewSet
```

## Top-level keys

- `schema_version`: the lockfile format version, currently `1`. authzlock refuses to read
  a lockfile with a newer version and asks you to upgrade.
- `routes`: one entry per URL pattern, sorted by `path`, then `view`.
- `custom_permissions`: permission classes that are not part of DRF, keyed by dotted path
  and sorted by it.

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
- `permission_classes`: the effective DRF permission classes as sorted dotted paths, the
  string `dynamic` when the view overrides `get_permissions` and authzlock will not guess,
  or `null` for views that are not DRF views.
- `permission_source`: `view` when the view or one of its base classes sets the classes
  (or overrides `get_permissions`), `action` when an `@action` sets its own
  `permission_classes`, `settings-default` when they come from
  `REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]`, `null` for non-DRF views.
- `authentication_classes`: like `permission_classes`, for authentication, with `dynamic`
  when the view overrides `get_authenticators`.
- `authentication_source`: like `permission_source`, for authentication.
- `django_auth`: for plain Django views, the rules set by decorators and mixins:
  `login_required`, `permission_required` (sorted permission strings), `user_passes_test`
  (whether a custom test applies; the test is never run), and `unknown_decorators`
  (decorators authzlock saw but could not classify). `null` for DRF views.
- `object_scoping`: for class-based views with generic object lookups, a map from each
  object hook (`get_queryset`, `get_object`, `perform_create`) to whether the view
  overrides it and whether that code reads `request.user`; `null` for other views.

## Custom permission keys

- `name`: the class name.
- `doc`: the first paragraph of the class docstring, or `null`.
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
