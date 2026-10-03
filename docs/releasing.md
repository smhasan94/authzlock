# Releasing authzlock

Releases are published to PyPI by `.github/workflows/release.yml` when a `v*` tag is pushed.
The workflow uses trusted publishing, so no API token is stored in GitHub. A manual run of
the same workflow publishes to TestPyPI instead, as a dry run.

## One-time setup

Only the repository owner can do this, and it must be done before the first publish.

1. On [PyPI](https://pypi.org/manage/account/publishing/), add a pending trusted publisher:
   project `authzlock`, owner `smhasan94`, repository `authzlock`, workflow `release.yml`,
   environment `pypi`.
2. On [TestPyPI](https://test.pypi.org/manage/account/publishing/), add the same publisher
   with environment `testpypi`.
3. In the GitHub repository settings, under Environments, create `pypi` and `testpypi`.
   For `pypi`, limit deployments to tags matching `v*` and, if you want a final check,
   add yourself as a required reviewer.

## Release steps

### 1. Update the changelog

In `CHANGELOG.md`, rename the `## [Unreleased]` section to `## [X.Y.Z] - YYYY-MM-DD` and
add a new empty `## [Unreleased]` section above it.

### 2. Bump the version

Set `__version__` in `src/authzlock/__init__.py` to `X.Y.Z`. Open a pull request with the
changelog and version change and merge it once CI passes.

### 3. Tag the release

On an up-to-date `main`:

```sh
git checkout main && git pull
git tag -a vX.Y.Z -m "authzlock X.Y.Z"
```

The tag must be `v` followed by exactly the version in `__version__`. If they differ, the
workflow fails at "Check the tag matches the package version" and names both versions,
before anything is published.

### 4. Push the tag

```sh
git push origin vX.Y.Z
```

This starts the Release workflow, which builds the sdist and wheel, checks the version and
publishes to PyPI. Watch it under the repository's Actions tab.

### 5. Move the v1 tag

Workflows use the GitHub Action as `smhasan94/authzlock@v1`, so `v1` follows the newest 1.x
release (0.x releases included). Point it at the release commit:

```sh
git tag -fa v1 -m "authzlock v1 (X.Y.Z)" vX.Y.Z^{commit}
git push --force origin v1
```

This is the only tag that is ever force-pushed. The first time, when `v1` does not exist yet,
`--force` is not needed.

### 6. Create the GitHub release

Create a release for `vX.Y.Z` with the changelog section as its notes:

```sh
awk '/^## \[X.Y.Z\]/{on=1; next} /^## \[/{on=0} on' CHANGELOG.md > notes.md
gh release create vX.Y.Z --title vX.Y.Z --notes-file notes.md
rm notes.md
```

### 7. Verify the install

In a fresh virtual environment:

```sh
pip install authzlock==X.Y.Z
authzlock --version
```

The output must be `authzlock X.Y.Z`. Then run the post-release workflow, which does the same
on Python 3.10 and 3.13, runs the README quickstart against the installed package, checks
that `v1` points at the release and runs the action through `smhasan94/authzlock@v1`:

```sh
gh workflow run post-release-verify.yml -f version=X.Y.Z
```

## A version is published once

PyPI never accepts the same version twice, even after the files are deleted. If something is
wrong after a release, fix it on `main` and release the next patch version; do not move or
re-push a `vX.Y.Z` tag. Git refuses to push an existing tag without `--force`
(`! [rejected] vX.Y.Z -> vX.Y.Z (already exists)`), and if a tag were forced through, the
Release workflow would fail at the publish step because PyPI rejects files for a version it
already has (`400 File already exists`). A broken release can be yanked on PyPI, which keeps
it installable only by exact pin.

## Dry run to TestPyPI

TestPyPI never accepts the same version twice, so each dry run needs a new development
version such as `0.0.1.dev1`, `0.0.1.dev2`.

1. On a branch, set `__version__` to the next unused `0.0.1.devN`.
2. Run the workflow on that branch with target `testpypi`:

   ```sh
   gh workflow run release.yml --ref <branch> -f target=testpypi -f tag=v0.0.1.devN
   ```

3. Check the install:

   ```sh
   pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ \
     authzlock==0.0.1.devN
   ```

To check that a wrong tag is refused, run with a `tag` that does not match `__version__`,
for example `-f tag=v9.9.9`. The build job fails at the version check with both versions in
the log, and nothing is published.
