# Releasing Diffdigger

Release assets are standalone Python scripts. There is no PyPI package or
architecture-specific build. The installer downloads only published stable
releases from `peternickol/diffdigger`, using GitHub's asset SHA-256 digests to check
the downloads before installation.

## Prepare

1. Set the same `VERSION` in `diffdigger` and `install.py`.
2. Update `CHANGELOG.md` and add `docs/releases/vX.Y.Z.md` with the release notes.
3. Run `python3 -m unittest -v` and `python3 tools/build_release.py --tag vX.Y.Z`.
4. Test the artifacts in a temporary bin directory:

   ```bash
   python3 install.py --from-dir dist --bin-dir /tmp/diffdigger-release-check/bin
   /tmp/diffdigger-release-check/bin/diffdigger --version
   /tmp/diffdigger-release-check/bin/diffdigger /path/to/test-folder
   ```

5. Review and commit the changes. Confirm the GitHub Actions test matrix passes,
   including macOS, before claiming support for that release.

## Publish

Push the reviewed commit, then create and push its matching `vX.Y.Z` Git tag.
The workflow checks the tag against the source version, runs the tests, and
creates a **draft** GitHub release containing:

- `diffdigger`
- `diffdigger-update` (the standalone installer/updater)
- `LICENSE`
- `SHA256SUMS`

Ensure the repository is public, then review the draft and publish it manually.
The public installation command starts
working only after the first stable release is published. A tag or draft release
alone is not sufficient. Leave released versions unchanged; publish a new version
for fixes.

After publication, test a fresh installation and `diffdigger --update` against the
public assets. Local tests simulate the network responses, so this final check
confirms GitHub's actual asset metadata and download path.

If a release needs to be skipped by the default updater, mark it as a prerelease.
Users can intentionally install an older stable release with
`diffdigger-update --version X.Y.Z`.

The updater relies on GitHub's HTTPS endpoints and
[release asset metadata](https://docs.github.com/en/rest/releases/releases#get-the-latest-release).
Checksums detect incorrect downloads; they are not an independent publisher
signature. No network requests run during normal file watching.
