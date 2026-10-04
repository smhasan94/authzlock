# authzlock documentation

Start with the [README](../README.md) for installation and a quickstart.

## Using authzlock

- [cli.md](cli.md): the `update`, `check` and `diff` commands, their options, output formats
  and exit codes.
- [lockfile.md](lockfile.md): the `authz.lock` format, every key, and what is guaranteed to
  stay stable.
- [diff-json.md](diff-json.md): the JSON document of `authzlock diff --format json`, which
  `--format sarif` is built from.
- [classification.md](classification.md): the rules R1 to R9 that label a change `loosened`,
  `tightened`, `changed-unknown` or `equivalent`.
- [heuristics-and-limits.md](heuristics-and-limits.md): what `dynamic`, the object-scoped
  flag, decorator detection and composed permissions can and cannot tell you, and what a
  passing `check` does not prove.
- [scenario.md](scenario.md): a pull request that drops `IsOwner` from a DELETE endpoint,
  end to end.

## Integrations

- [github-action.md](github-action.md): the GitHub Action that comments `authzlock diff`
  results on pull requests.
- [pre-commit.md](pre-commit.md): the `authzlock-check` and `authzlock-update` hooks.

## Project

- [CONTRIBUTING.md](../CONTRIBUTING.md): development setup, conventions and adding a fixture
  project.
- [DEVELOPMENT.md](../DEVELOPMENT.md): the project brief and development commands.
- [releasing.md](releasing.md): how a release is tagged and published.
- [requirements.md](requirements.md): the requirements the MVP is built against.
- [backlog.md](backlog.md): a mirror of the Linear backlog.
- [plans/README.md](plans/README.md): implementation plans, one per ticket.
- [CHANGELOG.md](../CHANGELOG.md): changes by release.
