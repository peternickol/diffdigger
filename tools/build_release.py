"""Prepare standalone, versioned release assets without third-party packages."""
import argparse
import ast
import hashlib
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = runpy.run_path(str(ROOT / 'install.py'))


def build(destination, tag=None):
    sources = {'diffdigger': ROOT / 'diffdigger', 'diffdigger-update': ROOT / 'install.py'}
    payload = {name: path.read_bytes() for name, path in sources.items()}
    versions = {INSTALLER['program_version'](data, name) for name, data in payload.items()}
    if len(versions) != 1:
        raise RuntimeError('Application and installer VERSION values must match.')
    version = versions.pop()
    if tag is not None and tag != f'v{version}':
        raise RuntimeError(f'Release tag {tag!r} does not match v{version}.')
    for name, data in payload.items():
        ast.parse(data, filename=name, feature_version=(3, 10))
        if b'Permission is hereby granted, free of charge' not in data:
            raise RuntimeError(f'{name} must include the MIT license notice.')
    payload['LICENSE'] = (ROOT / 'LICENSE').read_bytes()
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in payload.items():
        path = destination / name
        path.write_bytes(data)
        path.chmod(0o755 if name in sources else 0o644)
    sums = ''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name, data in sorted(payload.items()))
    (destination / 'SHA256SUMS').write_text(sums)
    return version


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--tag', help='Require the source version to match this release tag')
    args = parser.parse_args()
    version = build(args.output, args.tag)
    print(f'Prepared Diffdigger v{version} in {args.output}.')
