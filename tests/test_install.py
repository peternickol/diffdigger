from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = runpy.run_path(str(ROOT / 'install.py'))


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
        self.source = self.root / 'source'
        self.source.mkdir()
        self.version, self.payload = INSTALLER['local_payload'](ROOT)
        for name, source in INSTALLER['PROGRAMS'].items():
            (self.source / source).write_bytes(self.payload[name])
        self.bin = self.root / 'bin with spaces'

    def install(self, version=None, payload=None):
        with redirect_stdout(io.StringIO()):
            INSTALLER['install'](self.bin, version or self.version, payload or self.payload)

    def newer(self):
        version = '99.0.0'
        payload = {name: data.replace(f"VERSION = '{self.version}'".encode(), f"VERSION = '{version}'".encode())
                   for name, data in self.payload.items()}
        return version, payload

    def archive(self, payload):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for name, data in payload.items():
                archive.writestr(f'diffdigger-master/{INSTALLER["PROGRAMS"][name]}', data)
            # The installer only reads the two programs; other entries are never extracted.
            archive.writestr('../unexpected-file', 'must not be written')
        return stream.getvalue()

    def remote(self, data):
        def open_url(request, timeout):
            self.assertEqual(request.full_url, INSTALLER['SOURCE_URL'])
            self.assertEqual(timeout, 30)
            return Response(data, request.full_url)
        return open_url

    def test_clean_install_and_repeat_update_from_local_source(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / 'install.py'), '--from-dir', str(self.source), '--bin-dir', str(self.bin)],
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
            [str(self.bin / 'diffdigger-update'), '--from-dir', str(self.source)],
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

    def test_update_downloads_one_snapshot_even_without_a_version_bump(self):
        self.install()
        payload = {name: data + b'\n# next commit\n' for name, data in self.payload.items()}
        with patch('urllib.request.urlopen', side_effect=self.remote(self.archive(payload))) as opener:
            with patch.object(sys, 'argv', ['install.py', '--bin-dir', str(self.bin)]), redirect_stdout(io.StringIO()):
                INSTALLER['main']()
        opener.assert_called_once()
        for name, data in payload.items():
            self.assertEqual((self.bin / name).read_bytes(), data)
        result = subprocess.check_output([str(self.bin / 'diffdigger'), '--version'], text=True)
        self.assertEqual(result.strip(), f'diffdigger {self.version}')
        self.assertEqual(set(path.name for path in self.root.iterdir()), {'source', 'bin with spaces'})

    def test_bad_downloads_leave_existing_installation_untouched(self):
        self.install()
        _, newer = self.newer()
        downloads = {
            'invalid archive': b'<html>server error</html>',
            'missing installer': self.archive({'diffdigger': self.payload['diffdigger']}),
            'invalid program': self.archive({**self.payload, 'diffdigger': b'not a Python program'}),
            'version mismatch': self.archive({**self.payload, 'diffdigger': newer['diffdigger']}),
        }
        for case, download in downloads.items():
            with self.subTest(case=case), patch('urllib.request.urlopen', side_effect=self.remote(download)):
                with patch.object(sys, 'argv', ['install.py', '--bin-dir', str(self.bin)]), redirect_stdout(io.StringIO()):
                    with self.assertRaises(RuntimeError):
                        INSTALLER['main']()
                for name, data in self.payload.items():
                    self.assertEqual((self.bin / name).read_bytes(), data)

    def test_network_errors_are_actionable(self):
        errors = (
            (urllib.error.HTTPError(INSTALLER['SOURCE_URL'], 404, 'Not found', {}, None), 'Repository download not found'),
            (urllib.error.HTTPError(INSTALLER['SOURCE_URL'], 403, 'Forbidden', {}, None), 'rate limit'),
            (urllib.error.URLError('offline'), 'Download failed'),
        )
        for error, message in errors:
            with self.subTest(error=error):
                with patch('urllib.request.urlopen', side_effect=error):
                    with self.assertRaisesRegex(RuntimeError, message):
                        INSTALLER['repository_payload']()

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
        program.symlink_to(self.source / 'diffdigger')
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

    def test_program_metadata_is_inspected_without_execution(self):
        data = b"raise RuntimeError('must not execute')\nAPP_ID = 'diffdigger'\nVERSION = '1.2.3'\n"
        self.assertEqual(INSTALLER['program_version'](data, 'diffdigger'), '1.2.3')


if __name__ == '__main__':
    unittest.main()
