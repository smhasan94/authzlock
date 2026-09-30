# authzlock requirements

Status: draft for review. Last updated 2026-09-29.

## 1. Problem statement

Broken access control is the number one web application risk (OWASP Top 10:2025, A01).
In Django and Django REST Framework (DRF), the rules for who may call which endpoint are
spread across many places:

- `permission_classes` and `authentication_classes` on views and viewsets
- `DEFAULT_PERMISSION_CLASSES` and `DEFAULT_AUTHENTICATION_CLASSES` in settings
- `get_permissions()` overrides that pick classes at runtime
- `get_queryset()`, `get_object()` and `perform_create()` overrides that scope data to the caller
- `login_required`, `permission_required` and `user_passes_test` decorators and their mixin forms

Because the rules are scattered, a pull request can loosen access without anyone noticing.
Reviewers see a one-line change to a class attribute, not "anonymous users can now delete
invoices". Existing tools (Hadrian, AuthProbe, ZAP access control add-on) test a running app
from the outside. They need a hand-written roles file and seeded data, and they say nothing
during code review.

authzlock reads the access rules from the code, writes them to a committed lockfile, and
shows what changed in review.

## 2. Target users and jobs to be done

| User | Job to be done |
|------|----------------|
| Backend developer on a Django/DRF API, often multi-tenant SaaS | Know the effective permissions of every endpoint without reading every file. Catch my own mistakes before review. |
| Code reviewer | See in the PR which endpoints changed access rules and whether the change made them looser. |
| Security engineer | Keep an up-to-date inventory of every route and its access rules, and get alerted when it changes. |
| Platform or DevEx engineer | Add one CI step and one pre-commit hook that enforce the inventory stays in sync. |

## 3. MVP scope

### In scope

1. **Extraction.** Import the target project's URLconf using `DJANGO_SETTINGS_MODULE`, walk
   the URL resolver, and record for every route:
   - path pattern, route name, HTTP methods
   - view identity (`module.Class` or `module.function`)
   - resolved `permission_classes` and `authentication_classes`, including settings defaults
   - `login_required`, `permission_required` and `user_passes_test` decorators
   - whether `get_queryset`, `get_object` and `perform_create` are overridden, and whether
     the override references `request.user` (the "object-scoped" heuristic flag)
   - custom permission classes as opaque names plus their docstring
   - a dynamic `get_permissions()` override is recorded as `dynamic`, never guessed
2. **Lockfile.** A deterministic, sorted, human-readable `authz.lock` file in YAML with a
   schema version, committed to the repo.
3. **CLI** built with Typer:
   - `authzlock update` writes or refreshes the lockfile
   - `authzlock check` exits non-zero when code and lockfile disagree and prints a readable diff
   - `authzlock diff --base <git ref>` classifies each change as `added`, `removed`,
     `loosened`, `tightened` or `changed-unknown`
4. **Integrations.** A GitHub Action that runs `diff` on pull requests and posts the result
   as a PR comment. A pre-commit hook that runs `check`.
5. **Compatibility.** Python 3.10+, Django 4.2 and 5.x, DRF 3.14+. Routers, nested routers,
   ViewSets, APIView, generic views and plain function views are all handled.

### Out of scope for MVP

- FastAPI support
- Generating pytest cases from the lockfile
- Black-box HTTP testing against a running app
- Proving that custom permission logic is correct
- Any hosted service or telemetry

## 4. User stories

- US1. As a developer, I run `authzlock update` in my project and get an `authz.lock` that lists
  every route with its access rules, so I can commit it.
- US2. As a developer, I run `authzlock check` and it tells me which routes differ from the
  lockfile, so I know to update it before pushing.
- US3. As a reviewer, I open a PR and see a comment listing which endpoints changed access
  rules and whether each change is loosened, tightened, added, removed or changed-unknown.
- US4. As a reviewer, when a PR replaces `IsOwner` with `IsAuthenticated` on a DELETE
  endpoint, the PR comment names that endpoint and calls the change loosened.
- US5. As a platform engineer, I add the GitHub Action and pre-commit hook with a few lines of
  config and `check` fails CI until the lockfile is updated.
- US6. As a security engineer, I read `authz.lock` and see every custom permission class, its
  docstring, and every route that uses it.
- US7. As a developer, I see `dynamic` on a route whose view overrides `get_permissions()`,
  so I know the tool did not guess.
- US8. As a developer, I see an object-scoped flag on routes whose `get_queryset`,
  `get_object` or `perform_create` reference `request.user`, so I know the view narrows
  data to the caller.

## 5. Functional requirements

### Extraction (FR-E)

- FR-E1. Load the target project by importing `DJANGO_SETTINGS_MODULE` and calling
  `django.setup()` in-process.
- FR-E2. Walk the root URL resolver recursively, flattening `include()`, namespaces and
  `re_path`, and produce one record per route.
- FR-E3. Record the path pattern exactly as Django reports it, the fully qualified route
  name (with namespace) or null, and the view identity as `module.QualifiedName`.
- FR-E4. Record HTTP methods: for DRF ViewSets, from the router action map; for class-based
  views, from `http_method_names` intersected with implemented handlers; for function views,
  from `require_http_methods` and friends when present, otherwise `any`.
- FR-E5. For DRF views, resolve `permission_classes` and `authentication_classes` from the
  class attribute, falling back to `DEFAULT_PERMISSION_CLASSES` and
  `DEFAULT_AUTHENTICATION_CLASSES`. Record each class as its dotted path.
- FR-E6. If a DRF view overrides `get_permissions()` or `get_authenticators()`, record the
  corresponding field as `dynamic` and do not evaluate it.
- FR-E7. Record DRF `@action` routes with their own `permission_classes` when set.
- FR-E8. Record `login_required`, `permission_required` (with the permission strings) and
  `user_passes_test` on function views, and their `method_decorator` and mixin forms
  (`LoginRequiredMixin`, `PermissionRequiredMixin`, `UserPassesTestMixin`) on class-based views.
- FR-E9. For each of `get_queryset`, `get_object` and `perform_create`, record whether the
  view class overrides it and whether the override's source references `request.user` or
  `self.request.user`.
- FR-E10. Record every permission class not defined in `rest_framework.permissions` as a
  custom class: name, dotted path and docstring (or null). Do not evaluate it.
- FR-E11. Nested routers (`drf-nested-routers`) produce routes like any other.
- FR-E12. Extraction never modifies the target project, never writes files other than the
  lockfile on `update`, and makes no network calls.

### Lockfile (FR-L)

- FR-L1. The lockfile is YAML with a top-level `schema_version` integer.
- FR-L2. Routes are sorted by path, then by view identity. Lists inside a route are sorted
  where order has no meaning (permission classes, methods).
- FR-L3. Two runs on the same code produce byte-identical output, on any machine, with any
  `PYTHONHASHSEED`, from any working directory.
- FR-L4. The lockfile contains no absolute paths, timestamps, hostnames or tool version
  strings that would change between machines.
- FR-L5. The loader rejects a lockfile with an unknown or newer `schema_version` with a clear
  message.

### CLI (FR-C)

- FR-C1. `authzlock update` writes `authz.lock` in the current directory (or the path given
  by `--lockfile`) and exits 0.
- FR-C2. `authzlock check` re-extracts, compares with the lockfile, prints a readable diff on
  mismatch and exits 1. It exits 0 when they match. It exits 2 on errors such as a missing
  lockfile or a Django import failure.
- FR-C3. `authzlock diff --base <ref>` reads the lockfile from the given git ref, compares it
  with the current extraction, and prints each change with its classification.
- FR-C4. `diff` supports a text format for terminals and a markdown format for PR comments.
- FR-C5. Classification is conservative: a change is only `loosened` or `tightened` when a
  documented rule says so. Anything else is `changed-unknown`.
- FR-C6. All commands accept `--settings` to override `DJANGO_SETTINGS_MODULE`, and print a
  clear error if Django cannot be imported or set up.

### Integrations (FR-I)

- FR-I1. A GitHub Action in this repo runs `authzlock diff --base <PR base>` and posts the
  markdown output as a PR comment, updating its own earlier comment instead of adding a new one.
- FR-I2. The action exposes an input that makes the job fail when any change is `loosened`.
- FR-I3. A `.pre-commit-hooks.yaml` entry runs `authzlock check`.

## 6. Non-functional requirements

### Performance

- NFR-P1. Extraction on a project with 500 routes finishes in under 10 seconds on a laptop,
  excluding the time Django takes to import the project.
- NFR-P2. `check` and `diff` add no measurable overhead beyond one extraction.

### Security

- NFR-S1. No network calls at any point. Nothing is uploaded.
- NFR-S2. Custom permission classes are never executed. Their source is only read.
- NFR-S3. Running the tool never changes the target project's files, database or settings.
- NFR-S4. The GitHub Action uses the minimum token permissions needed to post a comment.

### Portability

- NFR-PO1. Python 3.10, 3.11, 3.12 and 3.13.
- NFR-PO2. Django 4.2 LTS and Django 5.x; DRF 3.14 and newer.
- NFR-PO3. Works on Linux and macOS; CI runs on Linux. Line endings in the lockfile are
  always `\n`.
- NFR-PO4. Works without DRF installed (plain Django projects still get decorator data).

### Developer experience

- NFR-D1. Install with `pip install authzlock` and run with no config in the common case.
- NFR-D2. Errors say what went wrong and what to do next, in one or two lines.
- NFR-D3. The lockfile is readable enough that a reviewer can understand a route entry
  without docs.
- NFR-D4. The diff output names the route path, HTTP methods and view for every change.

## 7. Constraints

- Runs in-process and offline; no network calls.
- Never modifies the target project.
- Output is stable across runs and machines.
- A false `loosened` alarm is worse than `changed-unknown`, so classification stays conservative.
- Python 3.10+, hatchling, Typer, PyYAML, pytest; MIT license; published to PyPI as `authzlock`.

## 8. Assumptions

- A1. The target project can be imported and set up in the environment where authzlock runs
  (dependencies installed, settings importable). authzlock does not manage that environment.
- A2. Extraction imports the project in the same process, so import-time side effects of the
  target project are the target project's responsibility.
- A3. A single lockfile per repository at the repository root is the common case.
- A4. The lockfile records effective permission classes per route, not per HTTP method,
  except where DRF gives per-action classes (`@action`) which produce their own routes.
- A5. Django's built-in admin routes are recorded like any other routes.
- A6. The GitHub Action runs inside the target repo's own workflow, where the project's
  dependencies are already installed.

## 9. Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Importing arbitrary Django projects fails in odd ways (missing env vars, database access at import) | Tool unusable on some projects | Clear error messages; document that `update`/`check` need the same env as `manage.py check` |
| Decorator detection on function views is unreliable because `functools.wraps` hides which decorator was applied | Missed `login_required` | Combine runtime introspection with AST inspection of the view's source; record `unknown-decorator` when unsure |
| False `loosened` alarms erode trust | Users ignore the comment | Only rank built-in DRF/Django classes; everything else is `changed-unknown`; test the rules table |
| Non-deterministic output (dict order, set order, machine paths) | Noisy diffs, CI flakes | Sort everything, ban absolute paths, byte-equality tests across runs and hash seeds |
| DRF changes internals (router action maps, `initkwargs`) | Breakage on new DRF | Test matrix across DRF versions; rely on documented attributes where possible |
| Object-scoped heuristic gives false confidence | Reviewer trusts a flag that only says "mentions request.user" | Name it a heuristic in docs and in the lockfile key (`references_request_user`) |

## 10. Open questions

All five questions raised in Step 1 were answered on 2026-09-29. The decisions are recorded
here and mirrored in `docs/backlog.md`.

- OQ1 (answered). `diff --base` compares the base ref's committed lockfile with a fresh
  extraction of the current code. If the base ref has no lockfile, every route is reported as
  `added` and the output notes that the base had no lockfile.
- OQ2 (answered). Only DRF built-ins are ranked: `AllowAny` < `IsAuthenticatedOrReadOnly` <
  `IsAuthenticated` < `IsAdminUser`. Django decorators rank as none < `login_required` <
  `permission_required`. Removing a custom class, or replacing it with a built-in ranked at or
  below `IsAuthenticated`, is `loosened`. Replacing it with `IsAdminUser` or another custom
  class is `changed-unknown`. Adding a custom class is `tightened`. Any change involving
  `dynamic` is `changed-unknown`. See ticket SHA-229 for the full rule table.
- OQ3 (answered). MVP configuration is `DJANGO_SETTINGS_MODULE` plus `--settings` and
  `--lockfile`. A `[tool.authzlock]` section in `pyproject.toml` is in the Later epic.
- OQ4 (answered). The GitHub Action is a composite action in this repo, used as
  `smhasan94/authzlock@v1`. It updates its own earlier comment instead of posting a new one,
  and has a `fail-on-loosened` input that defaults to true.
- OQ5 (answered). One lockfile entry per route with a sorted methods list and one permission
  set. DRF `@action` routes get their own entry. Per-method effective permissions are in the
  Later epic.

No open questions remain for the MVP.
