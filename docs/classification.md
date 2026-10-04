# Classification

`authzlock diff` labels every route that differs between two inventories. A route only in
the current inventory is `added`, a route only in the base is `removed`, and a route on both
sides whose fields differ is classified by the rules below as `loosened`, `tightened`,
`changed-unknown` or `equivalent`. Rules R1 to R8 were agreed on 2026-09-29, R9 was added by
SHA-239, R10 by SHA-243, and they live in `src/authzlock/classify.py`.

A false `loosened` alarm is worse than `changed-unknown`, so the rules are conservative:
authzlock never guesses what a custom, third-party, composed or `dynamic` permission does.
When no rule covers a change, the answer is `changed-unknown`.
[heuristics-and-limits.md](heuristics-and-limits.md) explains what the lockfile cannot see,
and so what no label can tell you.

## Ranking tables

DRF built-in permission classes, weakest first. A `permission_classes` list is an AND, and
each class implies every class below it, so a list of ranked classes is as strong as its
strongest member. An empty list allows anyone, like `AllowAny`.

| Rank | Class |
|------|-------|
| 0 | `rest_framework.permissions.AllowAny` |
| 1 | `rest_framework.permissions.IsAuthenticatedOrReadOnly` |
| 2 | `rest_framework.permissions.IsAuthenticated` |
| 3 | `rest_framework.permissions.IsAdminUser` |

Django auth on plain views, weakest first: none, `login_required`, `permission_required`
(a non-empty list of permission strings).

Every other permission entry is unranked: custom classes (any module other than
`rest_framework.permissions`), third-party classes and the other DRF built-ins such as
`DjangoModelPermissions`. They are handled only by the removal and addition rules R2 to R4.
Composed expressions such as `(a.IsAuthenticated | b.IsOwner)` and the `dynamic` sentinel
are never ranked.

## Per-method permissions

Two DRF built-ins mean different things for different HTTP methods.
`IsAuthenticatedOrReadOnly` allows anyone on the safe methods GET, HEAD and OPTIONS and
requires authentication on every other method; `DjangoModelPermissionsOrAnonReadOnly`
allows anyone on the safe methods and requires `DjangoModelPermissions` on every other.
Rule R9 rewrites each side of a change into one permission list per method of the route,
replacing those two classes by what they mean for that method and dropping `AllowAny` from
any list that has other members, and classifies each method's pair with R1 to R8. The
route gets the most severe per-method label, and the reason names the method that decided
it, for example `R9: POST [rest_framework.permissions.DjangoModelPermissions] ->
[rest_framework.permissions.IsAuthenticated] (R2: ...)`. When the lists differ but no
method's effective list does, the route is `equivalent`: the change has no effect on who
may call it. `equivalent` never fails `diff --fail-on loosened`, but `check` still reports
the route, because the lockfile no longer matches.

The expansion happens only during classification; the lockfile keeps one list per route.
Custom, third-party and composed classes and `dynamic` are copied unchanged, so they stay
as opaque as under R1 to R8, and `DjangoModelPermissions` stays unranked.

## FastAPI dependencies

A FastAPI route's `permission_classes` lists the dependencies in its dependency tree and its
`authentication_classes` the security schemes, with `permission_source` set to `dependency`
(see [heuristics-and-limits.md](heuristics-and-limits.md)). A dependency is only a name:
removing `get_db` and removing `get_current_user` look the same to authzlock. So rule R10
never ranks a dependency list. A changed list is `changed-unknown`. When nothing but the
security schemes changed, losing every scheme is `loosened` and gaining the first one is
`tightened`; any other scheme change is `changed-unknown`. Any other change to a FastAPI
route, such as gained methods, falls through to R7 and R8.

## Rules

The rules run in order and the first one that applies decides; R10 runs first, then R9. R1 to R4 apply only when
`permission_classes` is the one access field that changed and both sides are plain lists of
classes (no `dynamic`, no composed expression, not null). The fields `name`,
`permission_source` and `authentication_source` say where a rule came from, not who may call
the route, so they may change alongside any rule. Every result carries its rule id, and its
reason starts with that id.

| Rule | Applies when | Label | Example |
|------|--------------|-------|---------|
| R10 | Either side's `permission_source` is `dependency` (FastAPI) and `permission_classes` or `authentication_classes` changed | `changed-unknown` when `permission_classes` changed; with only `authentication_classes` changed, `loosened` when every scheme is removed, `tightened` when the first is added, otherwise `changed-unknown` | `[fastapi.security.oauth2.OAuth2PasswordBearer]` to `[]` with the dependencies unchanged is `loosened` |
| R9 | `permission_classes` changed, either side holds `IsAuthenticatedOrReadOnly` or `DjangoModelPermissionsOrAnonReadOnly`, and `methods` is not `any` | The most severe per-method result of R1 to R8 (`loosened`, then `changed-unknown`, then `tightened`); `equivalent` when no method's effective permissions changed | `[IsAuthenticated]` to `[IsAuthenticatedOrReadOnly]` on a POST-only route is `equivalent` |
| R1 | Both lists hold only ranked built-ins and the strongest class differs | `loosened` if the strongest class is weaker, `tightened` if stronger | `[IsAuthenticated]` to `[AllowAny]` is `loosened` |
| R2 | An unranked class is removed, the new list holds no unranked class, and the new strongest built-in is at most `IsAuthenticated` or at most the old strongest built-in | `loosened` | `[shop.permissions.IsOwner]` to `[IsAuthenticated]` is `loosened` |
| R3 | An unranked class is replaced by another unranked class, or by `IsAdminUser` | `changed-unknown` | `[shop.permissions.IsOwner]` to `[IsAdminUser]` is `changed-unknown` |
| R4 | An unranked class is added and every old entry is kept | `tightened` | `[IsAuthenticated]` to `[IsAuthenticated, shop.permissions.IsOwner]` is `tightened` |
| R5 | Either side of a changed field is `dynamic` | `changed-unknown` | `dynamic` to `[IsAuthenticated]` is `changed-unknown` |
| R6 | Only `django_auth.login_required` or `django_auth.permission_required` changed | `tightened` when the Django auth rank rises or `permission_required` gains entries; `loosened` for the reverse | `login_required` true to false is `loosened` |
| R7 | Only `methods` (and `actions`) changed and `methods` gained entries | `changed-unknown` | `[DELETE, GET]` to `[DELETE, GET, PUT]` is `changed-unknown` |
| R8 | Anything else | `changed-unknown` | `[(IsAuthenticated \| shop.permissions.IsOwner)]` to `[IsAuthenticated]` is `changed-unknown` |

## Examples

The class names below are short for `rest_framework.permissions.<Name>`; the lockfile and
the reasons always use full dotted paths.

- R1: `[IsAuthenticated]` to `[AllowAny]` gives `loosened`, reason
  `R1: strongest built-in rest_framework.permissions.IsAuthenticated -> rest_framework.permissions.AllowAny`.
- R2: `[IsAuthenticated, shop.permissions.IsOwner]` to `[IsAuthenticated]` gives `loosened`,
  reason `R2: custom class shop.permissions.IsOwner removed`.
- R3: `[shop.permissions.IsOwner]` to `[shop.permissions.IsTenantAdmin]` gives
  `changed-unknown`: the tool cannot tell which of two custom classes is stricter.
- R4: `[IsAuthenticated]` to `[IsAuthenticated, shop.permissions.IsOwner]` gives `tightened`:
  one more AND term can only restrict access.
- R5: a view that starts overriding `get_permissions` (`[IsAuthenticated]` to `dynamic`)
  gives `changed-unknown`.
- R6: `@login_required` replaced by `@permission_required("shop.view_order")` gives
  `tightened`; `permission_required` going from `[shop.add_order, shop.view_order]` to
  `[shop.view_order]` gives `loosened`.
- R7: a ViewSet route that gains `PUT` with the same permissions gives `changed-unknown`:
  the permissions did not change, but a new method is reachable.
- R9: `[IsAuthenticated]` to `[IsAuthenticatedOrReadOnly]` on a POST-only action gives
  `equivalent`: POST still requires authentication. `[AllowAny]` to
  `[IsAuthenticatedOrReadOnly]` gives `equivalent` on a GET-only route and `tightened` on a
  GET and POST route, with the reason naming POST.
  `[DjangoModelPermissionsOrAnonReadOnly]` to `[IsAuthenticated]` on a GET and POST route
  gives `loosened`: GET goes from anyone to authenticated users, but POST goes from model
  permissions to any authenticated user, and R2 calls that loosened.
- R8: any change that touches a composed expression, `authentication_classes`,
  `object_scoping`, or more than one kind of access field at once gives `changed-unknown`.

## Known conservative outcomes

These are `changed-unknown` on purpose, even where a human reviewer might call them
loosened or tightened.

- A list that keeps an unranked class while its built-in part changes, for example
  `[IsAdminUser, shop.permissions.IsOwner]` to `[IsAuthenticated, shop.permissions.IsOwner]`.
- A list that drops one unranked class and keeps another, for example
  `[shop.permissions.IsOwner, shop.permissions.IsTenantAdmin]` to
  `[shop.permissions.IsOwner]`. No change whose new list holds an unranked class is ever
  `loosened`.
- Two ranked lists with the same strongest class, for example `[IsAuthenticated]` to
  `[IsAuthenticated, IsAuthenticatedOrReadOnly]`.
- A Django auth change while a `user_passes_test` check applies, or while
  `permission_required` has an argument authzlock could not read, on either side.
- A permission change made together with a change to methods, authentication or object
  scoping on the same route.
- Authentication class changes, composed expressions and per-method effects are outside
  the MVP rules.
