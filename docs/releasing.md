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

### 5. Verify the install

In a fresh virtual environment:

```sh
pip install authzlock==X.Y.Z
authzlock --version
```

The output must be `authzlock X.Y.Z`.

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
