# GitHub Action

authzlock ships a composite action, `action.yml` at the root of this repository. On a pull
request it runs [`authzlock diff`](cli.md#authzlock-diff) against the pull request's base
branch, posts the result as a comment, and fails the job when a route is loosened.

The action keeps one comment per pull request. Its first line is the hidden marker
`<!-- authzlock -->`; on every later push the action finds the newest comment that starts
with the marker and edits it instead of adding another, so the thread stays clean.

## Workflow

Save this as `.github/workflows/authzlock.yml` in your Django project and change the
settings module, Python version and install command to match your project:

```yaml
name: authzlock

on:
  pull_request:

permissions:
  contents: read
  pull-requests: write

jobs:
  authzlock:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - uses: smhasan94/authzlock@v1
        with:
          settings-module: mysite.settings
          python-version: "3.12"
```

authzlock loads your project to read its access rules, so the project's dependencies must
be installed before the action runs, in the same Python the action uses. The action runs
`actions/setup-python` with its `python-version` input; give it the version you installed
your dependencies with, or set `python-version: ""` to skip that step and use the Python
already on `PATH`. The action then installs authzlock from the action's own checkout, at
the version named after the `@`, into that Python.

The default shallow checkout is enough: the action fetches the base branch itself, one
commit deep, and reads the base lockfile with `git show`.

## Permissions

The action uses only the workflow's `github.token`; it declares no secrets. The job needs
two permissions:

| Permission | Why |
|------------|-----|
| `contents: read` | Check out the code and fetch the base branch. |
| `pull-requests: write` | Create and update the pull request comment. |

On pull requests from forks GitHub gives `github.token` read access only, so the comment
cannot be posted and the comment step fails. Set `comment: false` for such workflows; the
report is still printed in the job log and the job summary.

## Inputs

| Input | Default | Meaning |
|-------|---------|---------|
| `settings-module` | required | Django settings module, for example `mysite.settings`. |
| `lockfile` | `authz.lock` | Lockfile path, relative to `working-directory`. |
| `python-version` | `3.12` | Python version for `actions/setup-python`; empty to skip that step. |
| `fail-on-loosened` | `true` | Fail the job when at least one route is loosened. |
| `comment` | `true` | Post or update the pull request comment. With `false`, nothing is posted and the report appears only in the job log and the job summary. |
| `working-directory` | `.` | Directory of the Django project inside the checkout. authzlock runs there, so the project's packages are importable from it. |
| `base-ref` | empty | Git ref to compare with. Empty means the pull request's base branch, fetched and compared as `origin/<base branch>`. Set it to compare with another ref, or to run the action outside a `pull_request` event; the ref must already exist in the checkout. |

## Outputs

| Output | Meaning |
|--------|---------|
| `report-path` | Path of the markdown report, `$RUNNER_TEMP/authzlock-diff.md`. |
| `summary` | The summary line, for example `1 loosened, 0 tightened, 0 added, 0 removed, 0 changed-unknown`. |
| `loosened` | Number of loosened routes. |

Give the action step an `id` to read them, for example
`${{ steps.authzlock.outputs.loosened }}`.

## What the action does

1. Sets up Python (unless `python-version` is empty) and installs authzlock.
2. Fetches the base branch from `origin` (unless `base-ref` is set).
3. Runs `authzlock diff --base origin/<base branch> --format markdown` in
   `working-directory`, prints the report to the job log and adds it to the job summary.
   If `authzlock diff` exits with 2 (the project or a lockfile could not be loaded, or git
   failed), the job fails here with the error in the log and no comment is posted.
4. When `comment` is `true`, creates the comment or updates the newest one that starts with
   the marker. Older marker comments, for example from an earlier bug, are left untouched
   and never deleted. Outside a pull request event the step prints a warning and posts
   nothing.
5. When `fail-on-loosened` is `true` and the summary line counts at least one loosened
   route, fails the job. Tightened, added, removed and changed-unknown routes never fail it.

The comment is the markdown described in
[cli.md](cli.md#markdown-output): the marker, a heading, the summary line, a table of
loosened and tightened routes, and collapsed sections for the rest. When nothing changed it
says `No access-control changes against origin/<base branch>.` A report longer than
GitHub's comment limit is cut short with a note pointing at the job log.

The action needs `git` and the GitHub CLI `gh`, both preinstalled on GitHub-hosted runners.
Self-hosted runners without `gh` are not supported.

## Checking the lockfile too

The action compares the base branch's committed lockfile with the code in the pull request.
It does not check that the pull request's own `authz.lock` was updated. To require that,
add a step after the action that runs `authzlock check`:

```yaml
      - run: authzlock check --settings mysite.settings
```

## Testing the action

`.github/workflows/action-e2e.yml` runs this repository's own action (`uses: ./`) on the
project from [scenario.md](scenario.md). Each job copies `tests/fixtures/scenario_loosen`
into a new git repository under `$RUNNER_TEMP` with `scripts/ci/prepare_scenario.py`,
committing the fixture and its golden lockfile as `authz.lock`. That repository has no
`origin`, so every job passes `base-ref: HEAD`, and `python-version: ""` so the action uses
the Python the job installed Django and Django REST Framework into. The jobs read the report
from the action's `report-path` output and check it with `scripts/ci/assert_summary.py`.

On every pull request to `main` three jobs run, none of which posts a comment:

| Job | Scenario | Checks |
|-----|----------|--------|
| `loosened` | loosening edit applied, `fail-on-loosened: false` | The summary line is exactly `1 loosened, 0 tightened, 0 added, 0 removed, 0 changed-unknown` and the one `loosened` row contains `DELETE` and `billing.views.InvoiceDetailView`; the row is printed in the log. |
| `clean` | unchanged | The summary line counts nothing and the report says no access-control changes. |
| `fails-when-loosened` | loosening edit applied, `fail-on-loosened: true` | The action step, run with `continue-on-error`, has the outcome `failure`, and its report counts one loosened route, so the failure came from the gate. |

The fourth job, `sticky-comment`, runs only when the workflow is started by hand. It posts
a real comment, so it needs a pull request to post on: open one (a draft is enough), then
run the workflow on `main` with that pull request's number:

```console
$ gh workflow run action-e2e.yml --ref main -f pr_number=<N>
$ gh run watch
```

The job runs the action twice with `comment: false`, first on the unchanged scenario and
then on the loosened one, and after each run calls the same
`python -m authzlock._github upsert-comment` command the action's comment step runs: the
action itself only comments on `pull_request` events, and a manual run is not one. The
second body ends with the run id. The job then checks that the second upsert updated the
comment the first one wrote, and with `scripts/ci/check_sticky_comment.py` that the pull
request has exactly one comment starting with `<!-- authzlock -->`, whose body has the
loosened summary line and this run's id. Run it a second time against the same pull
request: the log shows `updated comment <id>` with the same id as the first run, and the
comment now names the second run. Close the pull request afterwards.

`tests/test_action_e2e.py` runs the prepare and check scripts locally on the same scenario
and checks the workflow's job definitions, so most mistakes fail `pytest` before they reach
GitHub.
