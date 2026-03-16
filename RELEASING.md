# Releasing pydoglog to PyPI

## One-time setup

1. **Create a PyPI account** at https://pypi.org/account/register/

2. **Set up Trusted Publishing** (no API token needed — PyPI verifies via GitHub Actions OIDC):
   - Go to https://pypi.org/manage/account/publishing/
   - Add a new trusted publisher:
     - PyPI project name: `pydoglog`
     - GitHub owner: `prestomation`
     - GitHub repo: `pydoglog`
     - Workflow filename: `publish.yml`
     - Environment name: `pypi`

3. **Create a `pypi` environment in GitHub**:
   - Go to https://github.com/prestomation/pydoglog/settings/environments
   - Create environment named `pypi`
   - Optionally add a protection rule (e.g. require approval before publishing)

## Releasing a new version

1. **Bump the version** in `pyproject.toml`:
   ```toml
   version = "0.1.0"
   ```

2. **Commit and push**:
   ```bash
   git add pyproject.toml
   git commit -m "chore: bump version to 0.1.0"
   git push
   ```

3. **Tag the release**:
   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

4. That's it — GitHub Actions will:
   - Run the full test suite
   - Build the wheel + sdist
   - Publish to PyPI automatically

## Verify the release

```bash
pip install pydoglog==0.1.0
python3 -c "import pydoglog; print(pydoglog.__version__)"
```

PyPI page: https://pypi.org/project/pydoglog/
