# Release Checklist

Prepared release: `0.11.4`

This checklist is for the operator after the polish PR is merged. Do not publish,
push tags, or create a GitHub release from the polish automation branch.

## Verify

```bash
python -m pip install -e ".[dev]"
ruff check .
PYTHONPATH=src python3 -m pytest
scripts/check-counts
PYTHONPATH=src python3 scripts/validate_catalog.py
PYTHONPATH=src python3 scripts/check_release_ready.py --skip-build
PYTHONPATH=src python3 scripts/check_release_ready.py
```

`check_release_ready.py` now bootstraps its own compatible `twine`/`pkginfo`
environment before running `twine check`, so host packaging-tool drift does not
block the full release smoke.

## Tag

Run after the PR is merged and the verified commit is on `main`:

```bash
git switch main
git pull --ff-only
git tag -a v0.11.4 -m "freellmpool 0.11.4"
```

## Build And Publish

Only the operator should run the publish step:

```bash
rm -rf dist
python3 -m build
python3 -m twine check dist/*
python3 -m twine upload dist/*
```

After upload, smoke-test the published artifact:

```bash
python3 scripts/check_release_ready.py --check-pypi
```

## Post-Release

```bash
git push origin v0.11.4
```

Create the GitHub release from the pushed tag and paste the `0.11.4` changelog
entry. Do not include API keys, provider credentials, or unpublished issue draft
details in the release notes.
