# Contributing

Bug reports and small, focused pull requests are welcome. Diffdigger should remain
easy to run: Python's standard library, optional Git, and no background service.

For a bug report, include `diffdigger --version`, `python3 --version`, your operating
system and terminal, the command you ran, and a small example of the expected and
actual output. Include `git --version` for Git-related issues. Remove sensitive
file contents and paths before posting output.

From the repository root, run:

```bash
python3 -m unittest -v
git diff --check
```

Installer tests use temporary directories and simulated GitHub responses. They
do not download from GitHub or modify your installed copy. When changing the terminal
renderer, regenerate the example with `python3 tools/preview.py`.

Run checks locally before submitting changes. Keep the minimum supported Python
version (3.10) in mind when using standard-library APIs.

The installer and updater download directly from `master`. Push changes there to
make them available to users. Keep `VERSION` in `diffdigger` and `install.py` in
sync when changing the version number.
