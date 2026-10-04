# Heuristics and limits

authzlock reads access rules from code without running a request. Some rules can be read
exactly, such as a `permission_classes` list on a view. Others can only be estimated, and a
few cannot be read at all. This page says, for each case, what the lockfile records, what
that tells a reviewer and what it does not. When in doubt the tool records less and labels
a change `changed-unknown` rather than guess; see [classification.md](classification.md).

Nothing on this page runs project code that decides access: no view is instantiated, no
`get_permissions`, `get_queryset` or `user_passes_test` callable is called, and no
permission class is instantiated or asked for a decision. authzlock does set up Django with
the project's settings and import its URL configuration, which runs the module-level code of
the settings, the installed apps and every module the URL configuration imports.

## `dynamic`

A DRF view that overrides `get_permissions` chooses its permission classes at request time,
often per action or per user. authzlock does not call the method and does not try to read
its body, so `permission_classes` is recorded as the string `dynamic` and
`permission_source` as `view`. The same applies to `authentication_classes` when the view
overrides `get_authenticators`. The override counts when the view or any of its base
classes defines the method; DRF's own default does not.

What it tells you: access on this route is decided by code that the lockfile does not
capture, so it needs a human reading the method.

What it does not tell you: which classes apply to which action, or whether the method is
stricter or looser than the `permission_classes` attribute it may also define. Custom
classes returned only by `get_permissions` do not appear under `custom_permissions`.

In a diff, any change where either side is `dynamic` is `changed-unknown` (rule R5),
including a view that starts or stops overriding `get_permissions`.

## The object-scoped flag

Most multi-tenant bugs are not in `permission_classes` but in which objects a view lets the
caller reach. For generic class-based views (DRF `GenericAPIView` and ViewSets, Django's
`SingleObjectMixin` and `MultipleObjectMixin`) the lockfile has an `object_scoping` entry
with three hooks: `get_object`, `get_queryset` and `perform_create`. For each it records:

- `overridden`: true when the view, or one of the project's own base classes or mixins,
  defines the hook. A definition in a class from the `rest_framework` or `django` packages
  does not count, so DRF's `GenericAPIView.get_queryset` is not an override.
- `references_request_user`: read from the override's source with Python's `ast` module.
  True when the method body reads `self.request.user` or `request.user` directly, false
  when it does not, `null` when the hook is not overridden or its source cannot be read.

What it tells you: whether a view scopes its objects in its own code, and whether that code
mentions the requesting user. A change from true to false is worth a look.

What it does not tell you:

- That the filter is correct. `Order.objects.filter(owner=self.request.user)` and
  `Order.objects.exclude(owner=self.request.user)` both give true.
- Anything that happens in a helper. `return scoped_to(self.request, Order.objects)` gives
  false, because calls are not followed, even if the helper filters by user.
- Anything about other ways to read the user, such as `self.request.auth` or a tenant taken
  from a header or a middleware attribute.
- Anything about views that are not generic class-based views; their `object_scoping` is
  `null`.

The hooks are never run. Any change to `object_scoping` is `changed-unknown` (rule R8).

## Decorator detection

For plain Django views, `django_auth` records `login_required`, `permission_required`,
`user_passes_test` and `unknown_decorators`. authzlock finds them in two passes:

1. Runtime: it follows the view's `__wrapped__` chain and reads the closures that Django's
   own decorators leave behind, which gives the exact permission strings even when they come
   from a constant or a list built elsewhere. For class-based views it also looks at
   `LoginRequiredMixin`, `PermissionRequiredMixin`, `UserPassesTestMixin` and
   `method_decorator` on `dispatch`.
2. Source: it parses the decorators written above the view's definition with `ast`. This
   catches decorators that leave nothing at runtime, for example a wrapper written without
   `functools.wraps`.

What it tells you: which of Django's auth decorators and mixins apply, with their
permission strings.

What it does not tell you:

- What a `user_passes_test` check does. The test is never called; the lockfile only records
  that one applies.
- What any other decorator does. A decorator authzlock cannot classify is listed by name
  under `unknown_decorators`; it may grant, deny or not touch access. Common decorators that
  only restrict methods (`require_http_methods`, `require_GET`, `require_POST`,
  `require_safe`) are understood and not listed.
- The argument of `permission_required` when it is neither a string nor a list of strings
  in the source and cannot be read at runtime. That case is recorded as
  `permission_required(<non-literal>)` in `unknown_decorators`.
- Checks made inside the view body, such as `if not request.user.is_staff: raise
  PermissionDenied`.

Django auth changes are classified by rule R6 only when no `user_passes_test` check and no
unreadable `permission_required` argument is involved on either side; otherwise they are
`changed-unknown`.

## Composed permissions

DRF lets permission classes be combined with `&`, `|` and `~`. The lockfile writes such an
entry as an expression of dotted paths, for example
`(rest_framework.permissions.IsAuthenticated | billing.permissions.IsOwner)` or
`(~billing.permissions.IsBlocked)`. Custom classes inside the expression are listed under
`custom_permissions`.

What it tells you: exactly which classes are combined and how.

What it does not tell you: whether one expression is stricter than another. Comparing
boolean expressions over classes whose logic is unknown is not something authzlock tries,
so any change that touches a composed expression is `changed-unknown` (rule R8), even one
that looks obvious, such as dropping `| IsOwner`.

## Per-method permissions

The lockfile keeps one permission list per route, even when the route serves several HTTP
methods. Two DRF built-ins depend on the method, and only during classification (rule R9)
are they expanded per method: `IsAuthenticatedOrReadOnly` (anyone on GET, HEAD and
OPTIONS, authenticated users otherwise) and `DjangoModelPermissionsOrAnonReadOnly` (anyone
on the safe methods, `DjangoModelPermissions` otherwise). Nothing else is expanded: custom
and third-party classes that check `request.method` themselves, such as a user-defined
`IsOwnerOrReadOnly`, are opaque, and so is `DjangoObjectPermissions`.
`DjangoModelPermissions` stays unranked: its per-method model permission map is not
modelled, so it only takes part through the custom-class rules R2 to R4, which treat it as
requiring at least an authenticated user. A route whose `methods` is `any` is not expanded.

## Custom permission classes

A permission class from any module other than `rest_framework.permissions`, including
third-party packages, is recorded under `custom_permissions` by dotted path, with the first
paragraph of its docstring and the routes that use it. Its code is never run or judged.
Rules R2 to R4 can still label some changes, because they reason only about a custom class
being added to or removed from a list; replacing one custom class with another is
`changed-unknown` (rule R3).

## Lockfiles across Django and DRF versions

The lockfile records the URL patterns Django builds, and different Django or DRF versions
can build different patterns for the same code. For example, DRF 3.14's `DefaultRouter`
writes its API root and format-suffix routes as regexes, where DRF 3.15 and later write
`''` and `<drf_format_suffix:format>`. Upgrading such a dependency can therefore change the
lockfile with no change to the project; regenerate it with `authzlock update` and review
the result. This repository keeps one golden lockfile per fixture project and a
version-specific one where a version differs (see [lockfile.md](lockfile.md)).

## What `check` does not prove

`authzlock check` passing means one thing: the lockfile matches what authzlock extracts
from the code with the installed Django and DRF. It does not mean:

- that the access rules are right, only that they have not changed since the lockfile was
  last written and reviewed;
- that a `dynamic` view, a custom class, a composed expression, a `user_passes_test` check
  or an unknown decorator does what its name suggests;
- that querysets are scoped to the caller (see the object-scoped flag above);
- that routes added outside the URL configuration, such as by middleware or a different
  settings module, are covered: only the settings module given to authzlock is read;
- that a reviewer read the lockfile change. `authzlock update` makes a loosened permission
  easy to commit; the [pre-commit page](pre-commit.md) explains why `authzlock-check` is the
  safer hook.

Likewise, `authzlock diff` labelling nothing as `loosened` does not prove nothing was
loosened: `changed-unknown` routes need a human, and changes inside a custom class, a
`get_permissions` override or a helper function do not change the lockfile at all.

### What generated tests do not prove

`authzlock gen-tests` turns the lockfile into anonymous-request tests. A green run shows
that each tested route refuses an anonymous request at one sample URL. It does not show
that an authenticated user without the right role is refused, that object-level checks
work, or anything about the routes it skips or leaves without assertions; the summary
line says how many those are. The tests check the lockfile against the running project, so
a lockfile that already records a wrong rule produces tests that confirm the wrong rule.

