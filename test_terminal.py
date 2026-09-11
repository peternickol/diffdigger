import io
import os
from pathlib import Path
import re
import runpy
import unittest
from unittest.mock import patch

APP = runpy.run_path(str(Path(__file__).with_name('diffdigger')))
ANSI = re.compile(r'\x1b\[[0-9;]*m')


class TTY(io.StringIO):
    def isatty(self):
        return True


class TerminalTest(unittest.TestCase):
    def render(self, old, new, name='src/example.py', columns=80):
        stream = TTY()
        with patch.dict(os.environ, {'TERM': 'xterm-256color'}):
            terminal = APP['Terminal'](stream=stream, columns=columns)
            before = ((), old, None, '') if old is not None else None
            after = ((), new, None, '') if new is not None else None
            terminal.file_event(name, before, after)
        return ANSI.sub('', stream.getvalue())

    def test_line_numbers_and_change_counts(self):
        output = self.render('one\ntwo\nthree\n', 'one\nreplacement\nthree\n')
        self.assertIn('MODIFIED', output)
        self.assertIn('src/example.py', output)
        self.assertIn('+1  −1', output)
        self.assertRegex(output, r'│\s+2\s+│ − two')
        self.assertRegex(output, r'│\s+2 │ \+ replacement')
        self.assertIn('@@ −1,3 +1,3 @@', output)

    def test_wrapping_keeps_content_and_fits_narrow_terminals(self):
        value = 'prefix_' + '界' * 30 + '_suffix\x1b[2J'
        output = self.render(None, value, name='a/very/long/path/to/the/new/source/file.py', columns=50)
        self.assertIn('↳', output)
        self.assertIn('No newline at end of file', output)
        self.assertIn('\\x1b[2J', output)
        self.assertEqual(output.count('界'), 30)
        for line in output.splitlines():
            self.assertLessEqual(APP['cell_width'](line), 50, line)

    def test_empty_files_git_cards_and_no_color(self):
        self.assertIn('Empty file', self.render(None, ''))
        stream = TTY()
        with patch.dict(os.environ, {'TERM': 'xterm', 'NO_COLOR': '1'}):
            terminal = APP['Terminal'](stream=stream, columns=60)
            terminal.git_event(0, 'COMMIT 1234abcd · A message with \x1b[2J')
        self.assertIn('GIT / COMMIT', stream.getvalue())
        self.assertIn('1234abcd', stream.getvalue())
        self.assertNotIn('\x1b', stream.getvalue())
        self.assertIn('\\x1b[2J', stream.getvalue())

    def test_plain_and_narrow_output_keep_unified_diffs(self):
        for plain, columns in ((True, 100), (False, 35)):
            with self.subTest(plain=plain, columns=columns):
                stream = TTY()
                with patch.dict(os.environ, {'TERM': 'xterm'}):
                    terminal = APP['Terminal'](plain=plain, stream=stream, columns=columns)
                    terminal.file_event('example.py', ((), 'old\n', None, ''), ((), 'new\n', None, ''))
                output = ANSI.sub('', stream.getvalue())
                self.assertIn('--- a/example.py\n+++ b/example.py', output)
                self.assertIn('-old\n+new', output)
                self.assertNotIn('╭', output)

    def test_repository_labels_on_diff_and_git_events(self):
        for columns in (35, 50, 100):
            with self.subTest(columns=columns):
                stream = TTY()
                label = 'team/' + '界' * 20 + '\x1b[2J'
                with patch.dict(os.environ, {'TERM': 'xterm'}):
                    terminal = APP['Terminal'](stream=stream, columns=columns, repo=label)
                    terminal.file_event('code.py', ((), 'old\n', None, ''), ((), 'new\n', None, ''))
                    terminal.git_event(0, 'COMMIT 1234abcd · Save code')
                output = ANSI.sub('', stream.getvalue())
                self.assertEqual(output.count('team/'), 2)
                self.assertEqual(output.count('界'), 40)
                self.assertNotIn('\x1b', output)
                if columns >= 50:
                    self.assertEqual(output.count('repo · '), 2)
                    for line in output.splitlines():
                        self.assertLessEqual(APP['cell_width'](line), columns, line)
                else:
                    self.assertIn('] Modified code.py', output)
                    self.assertIn('] Git COMMIT', output)
                    self.assertIn('--- a/code.py\n+++ b/code.py', output)

    def test_startup_progress_fits_the_terminal_and_clears_on_failure(self):
        stream = TTY()
        with patch.dict(os.environ, {'TERM': 'xterm', 'NO_COLOR': '1'}):
            with self.assertRaises(RuntimeError):
                with APP['StartupProgress'](stream=stream, columns=90) as progress:
                    progress.update(Path('/tmp/project/\x1b[2J' + '界' * 40), 12345, (), force=True)
                    raise RuntimeError('scan failed')
        output = stream.getvalue()
        self.assertIn('Building baseline', output)
        self.assertIn('12,345 files', output)
        self.assertNotIn('\x1b[2J', output)
        self.assertIn('\\x1b[2J', output)
        self.assertNotIn('Baseline ready', output)
        self.assertTrue(output.endswith('\r\x1b[2K'))
        for frame in output.split('\r'):
            self.assertLessEqual(APP['cell_width'](frame.replace('\x1b[2K', '')), 90)

    def test_plain_startup_progress_has_no_terminal_control_codes(self):
        stream = TTY()
        with APP['StartupProgress'](plain=True, stream=stream) as progress:
            progress.update(Path('/tmp/project'), 10, (), force=True)
        output = stream.getvalue()
        self.assertIn('Building baseline · 10 files', output)
        self.assertIn('Baseline ready', output)
        self.assertNotIn('\x1b', output)
        self.assertNotIn('\r', output)


if __name__ == '__main__':
    unittest.main()
