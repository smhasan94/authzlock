# authzlock backlog

Mirror of the Linear project [authzlock](https://linear.app/shakooky/project/authzlock-fb75cf17a0e5)
(team Shakooky, key `SHA`). Linear is the source of truth for status; this file records the
structure and dependency order. Created 2026-09-29. Update it when tickets are added or split.

Conventions: branch name is the lowercase identifier, a hyphen, and a short slug
(`sha-181-package-skeleton`). Every ticket uses the Context / Scope / Acceptance criteria /
Test plan / Definition of done / Dependencies template. Estimates are in points; one point is
roughly half a day.

Decisions recorded on 2026-09-29 (answers to the open questions in `docs/requirements.md`):

- `diff --base` compares the base ref's committed lockfile with a fresh extraction of the current
  code. A base without a lockfile reports every route as `added` with a note.
- Classification ranks only DRF built-ins (`AllowAny` < `IsAuthenticatedOrReadOnly` <
  `IsAuthenticated` < `IsAdminUser`) and Django decorators (none < `login_required` <
  `permission_required`). Removing a custom class, or replacing it with a built-in at or below
  `IsAuthenticated`, is `loosened`. Replacing it with `IsAdminUser` or another custom class is
  `changed-unknown`. Adding a custom class is `tightened`. Anything touching `dynamic` is
  `changed-unknown`.
- Configuration is `DJANGO_SETTINGS_MODULE` plus `--settings` and `--lockfile`. A
  `pyproject.toml` section is in the Later epic.
- The GitHub Action is a composite action in this repo, used as `smhasan94/authzlock@v1`,
  posts one sticky comment per PR, and has a `fail-on-loosened` input defaulting to true.
- The lockfile has one entry per route with a sorted methods list and one permission set.
  DRF `@action` routes get their own entry. Per-method effective permissions are in Later.

## Epic 1: Repo scaffolding (SHA-174)

Ends with: CI green on an empty package that prints its version.

| Ticket | Title | Estimate | Blocked by |
|--------|-------|----------|------------|
| SHA-181 | Package skeleton and CLI entry point | 1 | none |
| SHA-182 | Lint, format and type tooling | 1 | SHA-181 |
| SHA-183 | Test harness and nox matrix | 1 | SHA-181 |
| SHA-184 | CI workflow on pull requests | 1 | SHA-182, SHA-183 |
| SHA-185 | Release tooling to PyPI | 1 | SHA-184 |
| SHA-272 | Matrix cell for minimum DRF 3.14 on Django 4.2 (follow-up from the SHA-183 plan) | 1 | SHA-183 |

## Epic 2: Extraction core (SHA-175)

Ends with: a Python API that returns a full route inventory for every fixture project.

| Ticket | Title | Estimate | Blocked by |
|--------|-------|----------|------------|
| SHA-197 | Django bootstrap and fixture harness | 2 | SHA-183 |
| SHA-200 | URL resolver walk and route model | 2 | SHA-197 |
| SHA-203 | HTTP methods and view identity for functions, CBVs and ViewSets | 2 | SHA-200 |
| SHA-205 | DRF permission and authentication resolution with settings defaults | 2 | SHA-203 |
| SHA-207 | ViewSets, routers, nested routers and @action routes | 2 | SHA-205 |
| SHA-209 | Django auth decorators and mixins | 2 | SHA-203 |
| SHA-210 | Object-scoped heuristic for get_queryset, get_object and perform_create | 1 | SHA-205 |
| SHA-211 | Custom permission class registry | 1 | SHA-205 |

## Epic 3: Lockfile, update and check (SHA-176)

Ends with: a project can commit `authz.lock` and enforce it locally.

| Ticket | Title | Estimate | Blocked by |
|--------|-------|----------|------------|
| SHA-224 | Lockfile schema v1, serializer and loader | 2 | SHA-200 |
| SHA-225 | Typer CLI skeleton and authzlock update | 1 | SHA-224, SHA-207 |
| SHA-226 | authzlock check command | 1 | SHA-225 |
| SHA-227 | Determinism guarantees for the lockfile | 1 | SHA-225 |

## Epic 4: Diff and classification (SHA-177)

Ends with: `authzlock diff --base` gives a classified report on the success scenario.

| Ticket | Title | Estimate | Blocked by |
|--------|-------|----------|------------|
| SHA-228 | Structural diff engine between two inventories | 1 | SHA-224 |
| SHA-229 | Classification rules: loosened, tightened, changed-unknown | 2 | SHA-228 |
| SHA-230 | authzlock diff --base command with text and markdown output | 2 | SHA-229, SHA-226 |
| SHA-231 | End-to-end success scenario: IsOwner to IsAuthenticated on DELETE | 1 | SHA-230, SHA-211 |

## Epic 5: Integrations (SHA-178)

Ends with: a target repo gets PR comments and a pre-commit hook with a few config lines.

| Ticket | Title | Estimate | Blocked by |
|--------|-------|----------|------------|
| SHA-232 | GitHub Action with sticky PR comment | 2 | SHA-230 |
| SHA-233 | pre-commit hook for authzlock check | 1 | SHA-226 |
| SHA-234 | Action end-to-end test on the fixture scenario | 1 | SHA-232, SHA-231 |

## Epic 6: Docs and first release (SHA-179)

Ends with: authzlock 0.1.0 on PyPI with usable docs.

| Ticket | Title | Estimate | Blocked by |
|--------|-------|----------|------------|
| SHA-235 | README: install, quickstart, lockfile example, classification table | 1 | SHA-232, SHA-233 |
| SHA-236 | Reference docs: lockfile schema, CLI, heuristics and limits, contributing | 1 | SHA-235 |
| SHA-237 | Release 0.1.0 to PyPI | 1 | SHA-236, SHA-185 |

## Epic 7: Later (SHA-180)

Not scheduled. Placeholders only; they get the full template when pulled into an MVP-style epic.

| Ticket | Title | Estimate | Blocked by |
|--------|-------|----------|------------|
| SHA-238 | Later: [tool.authzlock] config in pyproject.toml | 1 | SHA-225, SHA-230 |
| SHA-239 | Later: per-method effective permissions | - | none |
| SHA-241 | Later: JSON and SARIF output for diff | - | none |
| SHA-243 | Later: FastAPI extraction | - | none |
| SHA-244 | Later: generate pytest cases from the lockfile | - | SHA-225, SHA-227, SHA-229 |
| SHA-245 | Later: ignore list for routes | - | SHA-211, SHA-230 |

## Critical path to the MVP success case

SHA-181 > SHA-183 > SHA-197 > SHA-200 > SHA-203 > SHA-205 > SHA-207 > SHA-225 > SHA-226 >
SHA-230 > SHA-231 > SHA-232 > SHA-234. Everything else can run in parallel beside it.

Total MVP estimate (Epics 1 to 6): 42 points across 30 tickets.
