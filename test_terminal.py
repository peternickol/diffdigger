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


if __name__ == '__main__':
    unittest.main()
