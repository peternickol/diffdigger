# Diffdigger

A live stream of code diffs in your terminal. See what agents change as they save files.

```bash
./diffdigger ~/temp/electrologytraining.com
```

Requires Python 3 and Git. No packages, server, configuration, or installation.
Omit the directory to watch the current repository. Press **Ctrl+C** to stop.

The current files become the starting baseline. Each subsequent save prints its
diff against the previously observed contents, with green additions and red
deletions. Staging and committing do not reset the feed.

The first version watches one checkout, checking every half-second. It includes
tracked and untracked files, respects Git ignore rules, and skips symlinks and
submodules. Rapid saves between checks are combined. Binary/non-UTF-8 files and
files over 1 MiB get a change summary. Only saved changes after startup appear.

Diffdigger reads files and keeps its baseline in memory. It never changes your repo.

Run the tests with `python3 -m unittest -v`.
