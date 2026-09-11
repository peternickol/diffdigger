<p align="center">
  <img src="docs/diffdigger-logo.png" alt="Diffdigger logo: a shovel beside a file diff" width="160" height="160">
</p>

<h1 align="center">Diffdigger</h1>

<p align="center"><strong>Watch code change as agents work.</strong></p>

Diffdigger streams saved file diffs and Git activity from a repository into your
terminal. Point it at a checkout, leave it running, and follow changes from agents,
editors, or scripts as they happen.

![Diffdigger terminal preview with sample events](docs/terminal.svg)

*Preview uses sample events.*

## Quick start

Requires **Python 3** and **Git**. Tested on Linux. The executable uses only the
Python standard library; there are no packages to install or services to start.

```bash
git clone https://github.com/peternickol/diffdigger.git
cd diffdigger
./diffdigger /path/to/repo
```

Use the path to the repository you want to watch. Press **Ctrl+C** to stop.

## What you see

- **Saved changes:** created, modified, and deleted files, with additions and
  deletions shown as they are observed.
- **Readable diffs:** timestamps, old/new line numbers, change counts, surrounding
  context, and colored rows. Long lines wrap to fit the terminal.
- **Git activity:** commit, push, pull, and fetch events when Git leaves a local
  record that Diffdigger can detect.
- **A continuous feed:** earlier events stay in your terminal's scrollback.
  Staging and committing do not reset the file diff baseline.

## Usage

```text
diffdigger [--plain] [directory]
```

Run the executable by its path, or put it on your `PATH` to use `diffdigger`
from anywhere. The directory defaults to the current repository.

```bash
# Watch a specific checkout
./diffdigger ~/projects/my-app

# Watch the current repository (when diffdigger is on PATH)
diffdigger

# Use compact unified diffs without cards or colors
./diffdigger --plain /path/to/repo

# Keep the cards but disable colors
NO_COLOR=1 ./diffdigger /path/to/repo
```

Interactive terminals show decorated cards. Redirected output and very narrow
terminals use a plain layout automatically. `--plain` disables both cards and
colors; `NO_COLOR=1` disables colors.

## How the live feed works

At startup, Diffdigger takes a snapshot of the repository's current files. Every
half-second, it checks for changes and compares each changed file with its
previously observed contents. Existing uncommitted changes become the starting
baseline; they are not replayed when you launch it.

This lets you follow work before it reaches a commit. Only saved changes appear,
and several saves between checks may appear as a single diff.

Tracked files and untracked files allowed by Git's ignore rules are included.
Diffdigger reads the repository and keeps its baseline in memory. It does not
modify files, install hooks, or change Git configuration.

## Git activity

Git events appear alongside file diffs. Diffdigger reads new entries in local
reflog files and watches `FETCH_HEAD`; it does not contact remotes or replay old
commits.

| Event | What triggers it |
| --- | --- |
| **COMMIT** | A new commit entry in the checkout's HEAD reflog. |
| **PUSH** | A remote-tracking reflog records an update by push. |
| **PULL** | A HEAD or remote-tracking reflog records a pull. |
| **FETCH** | A remote-tracking reflog records a fetch. |
| **FETCH/PULL activity** | `FETCH_HEAD` changes without a corresponding fetch or pull reflog event in that check. |

`FETCH_HEAD` alone cannot distinguish a fetch from a pull or prove the command
succeeded. Failed or up-to-date pushes, and other operations that leave no
applicable local record, are not visible. Git activity detection relies on
file-based reflogs; repositories with reflogs disabled or reftable storage will
have limited coverage. This feed is not a complete command history.

## Current limits

- Watches one checkout at a time. Other worktrees need their own instance.
- Skips symlinks and submodule contents.
- Reports a change summary for binary/non-UTF-8 files and files larger than
  1 MiB, without a text diff.
- Shows renames as a deletion and a creation.
- Observes saved file changes; it cannot identify which agent or process made them.

## Development

The watcher and terminal renderer live in [`diffdigger`](diffdigger). Tests use
temporary repositories and local remotes, with no network access needed.

```bash
python3 -m unittest -v
```

To regenerate the sample terminal preview from the renderer:

```bash
python3 tools/preview.py
```

The generated image is [`docs/terminal.svg`](docs/terminal.svg).

## License

[MIT](LICENSE) — Copyright (c) 2026 Peter Nickol.
