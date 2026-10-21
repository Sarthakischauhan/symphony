# Publishing packages to PyPI

Symphony's GitHub Actions workflow publishes three distributions: `symphony-core`, `symphony-harness`, and `symphony-code`. The workspace-only `core-server` and `symphony-browser` packages are not included.

## One-time trusted-publisher setup

On PyPI, sign in and open **Account settings → Publishing**. Add a GitHub pending publisher for each package. The publisher configuration must match the workflow exactly:

| Field | Value |
| --- | --- |
| PyPI project name | `symphony-core`, `symphony-harness`, or `symphony-code` (one publisher per package) |
| Owner | `Sarthakischauhan` |
| Repository | `symphony` |
| Workflow name | `publish-core.yml` for `symphony-core`; `publish-harness.yml` for `symphony-harness`; `publish-code.yml` for `symphony-code` |
| Environment name | `pypi` |

A pending publisher does not reserve the project name. PyPI creates the project on its first successful matching upload. Check that the names are available before the first release. In GitHub repository settings, create the `pypi` environment; configure any desired approvals. Do not create or share an API token: the workflow uses OIDC Trusted Publishing.

## First release: 0.0.1

1. Confirm the three pending publishers use their respective workflow filenames from the table and the shared `pypi` environment. The workflow filename differs per package so each pending publisher has a distinct GitHub OIDC identity. Each workflow at `.github/workflows/publish-{core,harness,code}.yml` triggers only when a GitHub Release is **published**.
2. Merge the reviewed release-preparation changes to `main`. They set all three published package versions to `0.0.1` and keep the source-install instructions clear that PyPI availability begins only after a successful upload.
3. Confirm CI passes on `main`. CI builds the same distributions that the publish job will upload. You can also build locally from a clean checkout:

   ```sh
   uv sync --locked --all-packages --dev
   uv run ruff check .
   uv run pytest coding_agent/tests core_ai/tests core_harness/tests core_server/tests browser_agent/tests
   uv build --package symphony-core -o dist
   uv build --package symphony-harness -o dist
   uv build --package symphony-code -o dist
   ```

4. Create a GitHub Release for the merged commit with tag `v0.0.1` and publish the release. Do not publish the release until CI has passed and the PyPI publishers and GitHub `pypi` environment are configured. Publishing the release triggers the upload; merely pushing the tag does not.
5. Monitor the `Upload Python Packages to PyPI` workflow in Actions. It builds all three distributions and uses the `pypi` GitHub environment and OIDC to publish them. `skip-existing: true` skips already-uploaded files; it cannot replace a published version, so use new versions for subsequent releases.
6. Verify all three `0.0.1` project pages on PyPI. Version 0.0.1 was published from tag `v0.0.1`; the installation guide may advertise only versions that are actually on PyPI.

## Subsequent releases

Bump package versions in `core_ai/pyproject.toml`, `core_harness/pyproject.toml`, and/or `coding_agent/pyproject.toml` as appropriate, keep dependency constraints consistent, update the changelog, pass CI, and publish a GitHub Release. PyPI versions are immutable.

Release tags follow `symphony-code`: the tag must be `v<symphony-code version>` or the `symphony-code` job fails. `symphony-core` and `symphony-harness` publish only when the tag also equals their own version; otherwise their jobs skip, so an unchanged package can stay on its earlier version. The same release triggers `publish-web.yml`, which attaches `web-<version>.tar.gz` for `symphony web`.

The package-specific publisher workflows are [`.github/workflows/publish-core.yml`](../../.github/workflows/publish-core.yml), [`.github/workflows/publish-harness.yml`](../../.github/workflows/publish-harness.yml), and [`.github/workflows/publish-code.yml`](../../.github/workflows/publish-code.yml). The unprivileged `.github/workflows/publish.yml` builds all release distributions for inspection but does not upload them. CI mirrors the package build commands. A prepared version number is not evidence that a distribution has been published.

}
