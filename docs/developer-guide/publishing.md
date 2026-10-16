# Publishing packages to PyPI

Symphony publishes three workspace packages to PyPI through GitHub Actions and PyPI Trusted Publishing (OIDC): `symphony-core`, `symphony-harness`, and `symphony-code`. The workspace-only `core-server` and `symphony-browser` packages are not included in the publishing workflow.

## One-time PyPI and GitHub setup

1. On PyPI, sign in to the account that will own the projects and open **Account settings → Publishing**.
2. Under **Add a new pending publisher**, select GitHub and register a pending publisher for each of the three package names above. Use these values each time:
   - **Owner:** `Sarthakischauhan`
   - **Repository:** `symphony`
   - **Workflow name:** `publish.yml`
   - **Environment name:** `pypi`
3. Submit each form. Pending publishers allow the first matching trusted workflow upload to create the project; they do not reserve project names. Confirm the project names are available before relying on this first-publish flow.
4. In the GitHub repository, create an environment named exactly `pypi` under **Settings → Environments**. Configure any desired approval rules. The publish workflow requests the GitHub OIDC token and uses this environment; do not create or share a PyPI API token.

The workflow is `.github/workflows/publish.yml`. Its `pypi-publish` job uses the `pypi` environment and `id-token: write` permission. The publisher's owner, repository, workflow filename, and environment must match those values exactly.

## Each release

1. Choose a new version that is not already published on PyPI. PyPI does not permit replacing an existing version. Update the `[project].version` in the package metadata for every package being released:
   - `core_ai/pyproject.toml` — `symphony-core`
   - `core_harness/pyproject.toml` — `symphony-harness`
   - `coding_agent/pyproject.toml` — `symphony-code`
2. Check package dependencies and release notes for consistency, commit the release changes, and push the commit to GitHub. Keep unrelated working-tree changes out of the release commit.
3. Run the package test suite and CI checks. Rehearse the exact distribution builds used by the workflow:

   ```sh
   uv build --package symphony-core -o dist
   uv build --package symphony-harness -o dist
   uv build --package symphony-code -o dist
   ```

   Inspect the distributions in `dist/`. The CI workflow also builds these packages; the publish workflow itself builds distributions but does not run the test suite.
4. In GitHub, create a Release for the intended release commit (and its tag), then **publish** the Release. The workflow triggers on the GitHub `release.published` event; pushing a tag alone does not trigger it.
5. Monitor the `Upload Python Packages to PyPI` workflow in the Actions tab. It builds the three packages, passes the artifact to the PyPI publishing job, and uploads using Trusted Publishing. The workflow sets `skip-existing: true`, so existing distributions are skipped; that is not a substitute for choosing a fresh version.
6. Verify each intended version on PyPI, then update installation and availability documentation to reflect what was actually published.

For a first publication, confirm the PyPI pending publishers and GitHub `pypi` environment are configured before publishing the GitHub Release. If a run fails, inspect its Actions logs and correct the configuration or release before retrying; published version files cannot be overwritten.

## Workflow implementation

The source of truth for the automated release is [`.github/workflows/publish.yml`](../../.github/workflows/publish.yml). CI builds the same three distributions in `.github/workflows/ci.yml`.

Note: the repository may have unreleased or workspace-only changes. Publishing should only be initiated from a reviewed, committed release state; the workflow does not decide which changes are appropriate for a release.

---

This guide documents the workflow currently configured in this repository. It does not assert that any package has already been published.

**Availability:** The packages are not published on PyPI until a successful release upload has occurred. See the [source installation guide](../getting-started/installation.md) in the meantime.

}
