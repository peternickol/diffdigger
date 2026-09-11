#!/usr/bin/env python3
"""Install or update Diffdigger from a published GitHub release."""
# MIT License
#
# Copyright (c) 2026 Peter Nickol
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile
import urllib.error
import urllib.request

APP_ID = 'diffdigger-update'
VERSION = '0.1.0'
MIN_PYTHON = (3, 10)
REPOSITORY = 'peternickol/diffdigger'
API = f'https://api.github.com/repos/{REPOSITORY}/releases'
DOWNLOADS = f'https://github.com/{REPOSITORY}/releases/download'
MAX_DOWNLOAD = 2 * 1024 * 1024
PROGRAMS = ('diffdigger', 'diffdigger-update')


def version_tuple(version):
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise RuntimeError(f'Invalid release version: {version!r}')
    return tuple(map(int, version.split('.')))


def program_version(data, name):
    """Inspect metadata without executing downloaded or existing programs."""
    try:
        tree = ast.parse(data)
        values = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        values[target.id] = node.value.value
        version = values.get('VERSION')
        if values.get('APP_ID') != name or not isinstance(version, str):
            raise ValueError('Missing program identity or version')
        version_tuple(version)
        return version
    except (SyntaxError, UnicodeError, ValueError, TypeError) as error:
        raise RuntimeError(f'{name} is not a recognized Diffdigger program: {error}') from None


def download(url):
    request = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github+json' if url.startswith(API) else 'application/octet-stream',
        'User-Agent': f'diffdigger-installer/{VERSION}',
        'X-GitHub-Api-Version': '2026-03-10',
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if not response.geturl().startswith('https://'):
                raise RuntimeError('Refusing a download redirected away from HTTPS.')
            data = response.read(MAX_DOWNLOAD + 1)
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 404:
            raise RuntimeError('Release or asset not found. A published release is required; draft releases are not installable.') from None
        if error.code in (403, 429):
            raise RuntimeError('GitHub refused the request or its rate limit was reached. Try again later.') from None
        raise RuntimeError(f'Download failed: HTTP {error.code}') from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f'Download failed: {error}') from None
    if len(data) > MAX_DOWNLOAD:
        raise RuntimeError('Download exceeded the expected size limit.')
    return data


def release_payload(version=None):
    if version:
        version = version.removeprefix('v')
        version_tuple(version)
    url = f'{API}/tags/v{version}' if version else f'{API}/latest'
    try:
        release = json.loads(download(url))
        tag = release['tag_name']
        if not isinstance(tag, str) or not tag.startswith('v'):
            raise ValueError('Invalid release tag')
        offered = tag[1:]
        version_tuple(offered)
        if release.get('draft') or release.get('prerelease'):
            raise ValueError('Only published stable releases can be installed')
        if version and offered != version:
            raise ValueError('Release version does not match the requested version')
        assets = {asset['name']: asset for asset in release['assets']}
        payload = {}
        for name in PROGRAMS:
            asset = assets[name]
            expected_url = f'{DOWNLOADS}/{tag}/{name}'
            digest = asset.get('digest', '')
            if asset['browser_download_url'] != expected_url:
                raise ValueError(f'Unexpected download URL for {name}')
            if not isinstance(digest, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
                raise ValueError(f'GitHub did not provide a SHA-256 digest for {name}')
            data = download(expected_url)
            if hashlib.sha256(data).hexdigest() != digest[7:]:
                raise ValueError(f'Checksum mismatch for {name}; installed files were not changed')
            if program_version(data, name) != offered:
                raise ValueError(f'Version mismatch in {name}')
            payload[name] = data
        return offered, payload
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError(f'Invalid release metadata or download: {error}') from None


def local_payload(directory):
    directory = Path(directory).expanduser().resolve()
    payload = {name: (directory / name).read_bytes() for name in PROGRAMS}
    versions = {program_version(data, name) for name, data in payload.items()}
    if len(versions) != 1:
        raise RuntimeError('The local release files have different versions.')
    return versions.pop(), payload


def install(bin_dir, version, payload, allow_downgrade=False):
    bin_dir = Path(bin_dir).expanduser().resolve()
    targets = {name: bin_dir / name for name in PROGRAMS}
    for name, target in targets.items():
        if target.is_symlink():
            raise RuntimeError(f'Refusing to replace a symlink: {target}')
        if target.exists():
            if not target.is_file():
                raise RuntimeError(f'Not a regular file: {target}')
            # Source checkouts should be updated with Git, not overwritten by a release.
            if any((parent / '.git/HEAD').is_file() or (parent / '.git').is_file()
                   for parent in (bin_dir, *bin_dir.parents)):
                raise RuntimeError(f'Refusing to overwrite a source checkout: {target}')
            current = program_version(target.read_bytes(), name)
            if not allow_downgrade and version_tuple(current) > version_tuple(version):
                raise RuntimeError(f'{name} {current} is newer than release {version}; no downgrade was performed.')
    if all(target.is_file() and target.read_bytes() == payload[name] and os.access(target, os.X_OK)
           for name, target in targets.items()):
        print(f'Diffdigger {version} is already installed in {bin_dir}.')
        return
    bin_dir.mkdir(parents=True, exist_ok=True)
    staged = {}
    previous = {name: (target.read_bytes(), target.stat().st_mode & 0o777) if target.exists() else None
                for name, target in targets.items()}
    replaced = []
    try:
        # Download and stage everything before replacing either installed program.
        for name, data in payload.items():
            with tempfile.NamedTemporaryFile(prefix=f'.{name}-', dir=bin_dir, delete=False) as stream:
                staged[name] = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            staged[name].chmod(0o755)
        for name in PROGRAMS:
            os.replace(staged[name], targets[name])
            replaced.append(name)
    except BaseException:
        # If a later replacement fails, restore already replaced files atomically.
        for name in reversed(replaced):
            if previous[name] is None:
                targets[name].unlink()
            else:
                data, mode = previous[name]
                with tempfile.NamedTemporaryFile(prefix='.diffdigger-restore-', dir=bin_dir, delete=False) as stream:
                    restore = Path(stream.name)
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    restore.chmod(mode)
                    os.replace(restore, targets[name])
                finally:
                    restore.unlink(missing_ok=True)
        raise
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)
    print(f'Installed Diffdigger {version} in {bin_dir}.')
    print('Run: diffdigger /path/to/folder')
    print('Update: diffdigger-update (or diffdigger --update)')
    path_entries = {Path(entry).expanduser().resolve() for entry in os.get_exec_path() if entry}
    if bin_dir not in path_entries:
        print(f'Add this directory to your PATH: export PATH={shlex.quote(str(bin_dir))}:"$PATH"')


def default_bin_dir(script):
    script = Path(script).resolve()
    sibling = script.with_name('diffdigger')
    if script.name == 'diffdigger-update' and sibling.is_file() and os.access(sibling, os.X_OK):
        try:
            program_version(sibling.read_bytes(), 'diffdigger')
        except (OSError, RuntimeError):
            pass
        else:
            return script.parent
    return Path.home() / '.local/bin'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default_dir = default_bin_dir(__file__)
    parser.add_argument('--bin-dir', default=str(default_dir), help='Installation directory (default: ~/.local/bin, or this updater\'s directory)')
    parser.add_argument('--version', help='Install a specific published version, e.g. 0.1.0; permits an intentional downgrade')
    parser.add_argument('--from-dir', help='Install trusted local release files without downloading')
    args = parser.parse_args()
    if sys.version_info < MIN_PYTHON:
        parser.error('Python 3.10 or newer is required.')
    if os.name != 'posix':
        parser.error('The installer supports Linux and macOS. On Windows, use WSL.')
    if args.version and args.from_dir:
        parser.error('--version cannot be combined with --from-dir.')
    print('Preparing local files…' if args.from_dir else 'Checking published Diffdigger releases…', flush=True)
    version, payload = local_payload(args.from_dir) if args.from_dir else release_payload(args.version)
    install(args.bin_dir, version, payload, allow_downgrade=bool(args.version))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, RuntimeError) as error:
        print(f'diffdigger installer: {error}', file=sys.stderr)
        raise SystemExit(1)
