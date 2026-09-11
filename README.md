# Diffdigger

A live stream of code diffs and Git activity in your terminal.

```bash
./diffdigger ~/temp/electrologytraining.com
```

Requires Python 3 and Git. No packages, server, configuration, or installation.
Omit the directory to watch the current repository. Press **Ctrl+C** to stop.

The current files become the starting baseline. Each subsequent save prints its
diff against the previously observed contents, with green additions and red
deletions. Staging and committing do not reset the feed.

Git activity appears in the same stream:

```text
[14:32:08] Git COMMIT a1b2c3d4 · Fix validation
[14:32:10] Git PUSH origin/main → a1b2c3d4
[14:32:15] Git FETCH origin/main → e5f6a7b8 · fast-forward
[14:32:17] Git PULL HEAD → e5f6a7b8 · Fast-forward
```

This reads new entries from Git's local reflog files and watches `FETCH_HEAD`.
It requires no hooks or Git configuration changes and does not replay old commits.
If only `FETCH_HEAD` changes, the entry says **FETCH/PULL activity** because that
file cannot distinguish those commands or prove they succeeded. Pushes appear
when Git records a remote-tracking ref update; failed/up-to-date pushes and other
operations that leave no local record are not visible. This is local activity
monitoring, not remote polling or a complete command audit.

See Git's [reflog](https://git-scm.com/docs/git-reflog) and
[fetch](https://git-scm.com/docs/git-fetch) documentation for those local records.

The first version watches one checkout, checking every half-second. It includes
tracked and untracked files, respects Git ignore rules, and skips symlinks and
submodules. Rapid saves between checks are combined. Binary/non-UTF-8 files and
files over 1 MiB get a change summary. Only saved changes after startup appear.

Diffdigger reads files and keeps its baseline in memory. It never changes your repo.

Run the tests with `python3 -m unittest -v`.
