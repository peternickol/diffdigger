from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parent
INSTALLER = runpy.run_path(str(ROOT / 'install.py'))
BUILDER = runpy.run_path(str(ROOT / 'tools/build_release.py'))


class Response(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data)
        self.url = url

    def geturl(self):
        return self.url


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.dist = self.root / 'release'
        self.version = BUILDER['build'](self.dist)
        _, self.payload = INSTALLER['local_payload'](self.dist)
        self.bin = self.root / 'bin with spaces'

    def install(self, version=None, payload=None, **kwargs):
        with redirect_stdout(io.StringIO()):
            INSTALLER['install'](self.bin, version or self.version, payload or self.payload, **kwargs)

    def newer(self):
        version = '99.0.0'
        payload = {name: data.replace(f"VERSION = '{self.version}'".encode(), f"VERSION = '{version}'".encode())
                   for name, data in self.payload.items()}
        return version, payload

    def remote(self, version, payload):
        assets = []
        urls = {}
        for name, data in payload.items():
            url = f'{INSTALLER["DOWNLOADS"]}/v{version}/{name}'
            urls[url] = data
            assets.append({'name': name, 'browser_download_url': url,
                           'digest': 'sha256:' + hashlib.sha256(data).hexdigest()})
        metadata = {'tag_name': f'v{version}', 'draft': False, 'prerelease': False, 'assets': assets}
        def open_url(request, timeout):
            self.assertTrue(request.full_url.startswith('https://'))
            self.assertEqual(timeout, 30)
            data = json.dumps(metadata).encode() if request.full_url.startswith(INSTALLER['API']) else urls[request.full_url]
            return Response(data, request.full_url)
        return metadata, urls, open_url

    def test_clean_install_and_repeat_update_from_local_artifacts(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / 'install.py'), '--from-dir', str(self.dist), '--bin-dir', str(self.bin)],
            check=True, capture_output=True, text=True,
        )
        self.assertIn('Installed Diffdigger', result.stdout)
        for name, data in self.payload.items():
            self.assertEqual((self.bin / name).read_bytes(), data)
            self.assertTrue(os.access(self.bin / name, os.X_OK))
            self.assertIn(b'Permission is hereby granted', data)
        version = subprocess.check_output([str(self.bin / 'diffdigger'), '--version'], text=True)
        self.assertEqual(version.strip(), f'diffdigger {self.version}')
        repeated = subprocess.run(
            [str(self.bin / 'diffdigger-update'), '--from-dir', str(self.dist)],
            check=True, capture_output=True, text=True,
        )
        self.assertIn('already installed', repeated.stdout)
        self.assertEqual(set(path.name for path in self.bin.iterdir()), set(self.payload))

    def test_update_command_uses_the_installed_updater(self):
        self.install()
        with patch.object(sys, 'argv', [str(self.bin / 'diffdigger'), '--update']), patch('subprocess.call', return_value=0) as call:
            with self.assertRaises(SystemExit) as exit_status:
                runpy.run_path(str(self.bin / 'diffdigger'), run_name='__main__')
        self.assertEqual(exit_status.exception.code, 0)
        call.assert_called_once_with([sys.executable, str(self.bin / 'diffdigger-update')])

    def test_downloaded_updater_defaults_to_user_bin_but_installed_one_stays_in_place(self):
        self.assertEqual(INSTALLER['default_bin_dir'](self.root / 'diffdigger-update'), Path.home() / '.local/bin')
        self.install()
        self.assertEqual(INSTALLER['default_bin_dir'](self.bin / 'diffdigger-update'), self.bin)

    def test_download_and_update_a_verified_release(self):
        self.install()
        version, payload = self.newer()
        _, _, opener = self.remote(version, payload)
        with patch('urllib.request.urlopen', side_effect=opener):
            offered, downloaded = INSTALLER['release_payload']()
        self.install(offered, downloaded)
        for name, data in payload.items():
            self.assertEqual((self.bin / name).read_bytes(), data)
        result = subprocess.check_output([str(self.bin / 'diffdigger'), '--version'], text=True)
        self.assertEqual(result.strip(), f'diffdigger {version}')

    def test_checksum_failure_leaves_existing_installation_untouched(self):
        self.install()
        version, payload = self.newer()
        _, urls, opener = self.remote(version, payload)
        urls[f'{INSTALLER["DOWNLOADS"]}/v{version}/diffdigger'] += b'\n# corrupt download\n'
        with patch('urllib.request.urlopen', side_effect=opener), redirect_stdout(io.StringIO()):
            with patch.object(sys, 'argv', ['install.py', '--bin-dir', str(self.bin)]):
                with self.assertRaisesRegex(RuntimeError, 'Checksum mismatch'):
                    INSTALLER['main']()
        for name, data in self.payload.items():
            self.assertEqual((self.bin / name).read_bytes(), data)

    def test_release_metadata_cannot_change_the_source_or_skip_verification(self):
        for case in ('url', 'digest', 'draft', 'prerelease', 'version'):
            with self.subTest(case=case):
                metadata, _, opener = self.remote(self.version, self.payload)
                if case == 'url':
                    metadata['assets'][0]['browser_download_url'] = 'https://example.invalid/diffdigger'
                elif case == 'digest':
                    metadata['assets'][0]['digest'] = None
                elif case == 'version':
                    metadata['tag_name'] = 'not-a-version'
                else:
                    metadata[case] = True
                with patch('urllib.request.urlopen', side_effect=opener):
                    with self.assertRaises(RuntimeError):
                        INSTALLER['release_payload']()

    def test_network_errors_are_actionable(self):
        errors = (
            (urllib.error.HTTPError(INSTALLER['API'], 404, 'Not found', {}, None), 'published release'),
            (urllib.error.HTTPError(INSTALLER['API'], 403, 'Forbidden', {}, None), 'rate limit'),
            (urllib.error.URLError('offline'), 'Download failed'),
        )
        for error, message in errors:
            with self.subTest(error=error):
                with patch('urllib.request.urlopen', side_effect=error):
                    with self.assertRaisesRegex(RuntimeError, message):
                        INSTALLER['release_payload']()

    def test_partial_replacement_failure_restores_the_old_programs(self):
        self.install()
        version, payload = self.newer()
        replace = os.replace
        def fail_second(source, destination):
            if Path(source).name.startswith('.diffdigger-update-'):
                raise PermissionError('simulated replacement failure')
            replace(source, destination)
        with patch('os.replace', side_effect=fail_second):
            with self.assertRaisesRegex(PermissionError, 'simulated replacement failure'):
                self.install(version, payload)
        for name, data in self.payload.items():
            self.assertEqual((self.bin / name).read_bytes(), data)
        self.assertEqual(set(path.name for path in self.bin.iterdir()), set(self.payload))

    def test_unrelated_files_symlinks_and_source_checkouts_are_preserved(self):
        self.bin.mkdir()
        program = self.bin / 'diffdigger'
        program.write_text('unrelated program\n')
        with self.assertRaises(RuntimeError):
            self.install()
        self.assertEqual(program.read_text(), 'unrelated program\n')
        program.unlink()
        program.symlink_to(self.dist / 'diffdigger')
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            self.install()
        self.assertTrue(program.is_symlink())
        program.unlink()
        program.write_bytes(self.payload['diffdigger'])
        (self.bin / '.git').mkdir()
        (self.bin / '.git/HEAD').write_text('ref: refs/heads/main\n')
        with self.assertRaisesRegex(RuntimeError, 'source checkout'):
            self.install()
        self.assertEqual(program.read_bytes(), self.payload['diffdigger'])

    def test_downgrade_requires_an_explicit_version(self):
        version, payload = self.newer()
        self.install(version, payload)
        with self.assertRaisesRegex(RuntimeError, 'no downgrade'):
            self.install()
        self.install(allow_downgrade=True)
        self.assertEqual((self.bin / 'diffdigger').read_bytes(), self.payload['diffdigger'])

    def test_build_checks_tag_and_writes_matching_checksums(self):
        with self.assertRaisesRegex(RuntimeError, 'does not match'):
            BUILDER['build'](self.root / 'bad-release', tag='v99.0.0')
        for line in (self.dist / 'SHA256SUMS').read_text().splitlines():
            digest, name = line.split('  ')
            self.assertEqual(hashlib.sha256((self.dist / name).read_bytes()).hexdigest(), digest)

    def test_program_metadata_is_inspected_without_execution(self):
        data = b"raise RuntimeError('must not execute')\nAPP_ID = 'diffdigger'\nVERSION = '1.2.3'\n"
        self.assertEqual(INSTALLER['program_version'](data, 'diffdigger'), '1.2.3')


if __name__ == '__main__':
    unittest.main()
