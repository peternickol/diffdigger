import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest

SCRIPT = Path(__file__).with_name('diffdigger')


class DiffdiggerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'repo with spaces'
        self.root.mkdir()
        self.git('init', '-q')
        (self.root / 'code.py').write_text('before\n')
        (self.root / '.gitignore').write_text('ignored/\n*.log\n')
        self.git('add', '.')
        self.process = subprocess.Popen(
            [sys.executable, str(SCRIPT), str(self.root)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.addCleanup(self.stop)
        self.output, self.messages = queue.Queue(), queue.Queue()
        for pipe, target in ((self.process.stdout, self.output), (self.process.stderr, self.messages)):
            threading.Thread(target=lambda p=pipe, q=target: [q.put(line.rstrip('\n')) for line in p], daemon=True).start()
        while not self.messages.get(timeout=5).startswith('Ready.'):
            pass

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Diff Test',
                               '-c', 'user.email=test@example.invalid', *args], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=5)
        self.process.stdout.close()
        self.process.stderr.close()

    def change(self):
        lines = []
        while True:
            line = self.output.get(timeout=3)
            if not line:
                return '\n'.join(lines)
            lines.append(line)

    def quiet(self):
        with self.assertRaises(queue.Empty):
            self.output.get(timeout=0.8)
        self.assertIsNone(self.process.poll())

    def test_saved_diffs_continue_across_commits(self):
        self.quiet()
        path = self.root / 'code.py'
        path.write_text('first save\n')
        self.assertIn('-before\n+first save', self.change())
        self.git('add', 'code.py')
        self.git('commit', '-qm', 'commit while watching')
        event = self.change()
        self.assertIn('Git COMMIT', event)
        self.assertIn('commit while watching', event)
        self.quiet()
        path.write_text('second save\n')
        diff = self.change()
        self.assertIn('-first save\n+second save', diff)
        self.assertNotIn('-before', diff)
        path.write_text('second save\n')
        self.quiet()

    def test_new_deleted_and_atomically_saved_files(self):
        directory = self.root / 'new'
        directory.mkdir()
        path = directory / 'file.py'
        path.write_text('new file\n')
        diff = self.change()
        self.assertIn('Created new/file.py', diff)
        self.assertIn('--- /dev/null', diff)
        self.assertIn('+new file', diff)
        temporary = directory / 'replacement'
        temporary.write_text('atomic save\n')
        os.replace(temporary, path)
        diff = self.change()
        self.assertIn('Modified new/file.py', diff)
        self.assertIn('-new file\n+atomic save', diff)
        path.unlink()
        diff = self.change()
        self.assertIn('Deleted new/file.py', diff)
        self.assertIn('-atomic save', diff)

    def test_ignore_rules_binary_files_and_terminal_escapes(self):
        ignored = self.root / 'ignored'
        ignored.mkdir()
        (ignored / 'noise.py').write_text('ignored\n')
        (self.root / 'debug.log').write_text('ignored\n')
        external = Path(self.temp.name) / 'external.txt'
        external.write_text('external contents\n')
        (self.root / 'link.txt').symlink_to(external)
        self.quiet()
        (self.root / 'image.bin').write_bytes(b'\x00binary')
        self.assertIn('Binary/non-UTF-8', self.change())
        (self.root / 'control.py').write_text('\x1b]52;c;bad\x07\n')
        diff = self.change()
        self.assertIn('+\\x1b]52;c;bad\\x07', diff)
        self.assertNotIn('\x1b', diff)
        # A file becoming ignored should not be presented as deleted.
        (self.root / '.gitignore').write_text('ignored/\n*.log\ncontrol.py\n')
        self.assertIn('Modified .gitignore', self.change())
        self.quiet()

    def test_push_fetch_and_pull_with_a_local_remote(self):
        self.git('commit', '-qm', 'initial commit')
        self.assertIn('Git COMMIT', self.change())
        remote = Path(self.temp.name) / 'remote.git'
        subprocess.run(['git', 'init', '--bare', '-q', '--initial-branch=main', str(remote)], check=True)
        self.git('remote', 'add', 'origin', str(remote))
        self.git('push', '-u', 'origin', 'HEAD:main')
        self.assertIn('Git PUSH origin/main', self.change())
        self.quiet()

        peer = Path(self.temp.name) / 'peer'
        subprocess.run(['git', 'clone', '-q', str(remote), str(peer)], check=True)
        (peer / 'code.py').write_text('change from a peer\n')
        def peer_git(*args):
            subprocess.run(['git', '-C', str(peer), '-c', 'user.name=Peer',
                            '-c', 'user.email=peer@example.invalid', *args], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        peer_git('add', 'code.py')
        peer_git('commit', '-qm', 'remote change')
        peer_git('push', 'origin', 'main')
        self.git('fetch', 'origin')
        self.assertIn('Git FETCH origin/main', self.change())
        self.quiet()  # Fetching does not change working files or create a local commit.

        self.git('pull', '--ff-only', 'origin', 'main')
        records = self.change() + '\n' + self.change()
        self.assertIn('Git PULL HEAD', records)
        self.assertIn('-before\n+change from a peer', records)
        self.quiet()

        # A fetch with no ref updates still writes FETCH_HEAD.
        self.git('fetch', 'origin')
        self.assertIn('Git FETCH/PULL activity', self.change())
        self.quiet()
        # An up-to-date push leaves no record: never invent a success event.
        self.git('push', 'origin', 'HEAD:main')
        self.quiet()

    def test_multiple_commits_and_reflog_rewrite(self):
        self.git('commit', '-qm', 'first commit')
        self.git('commit', '--allow-empty', '-qm', 'second commit')
        records = [self.change(), self.change()]
        self.assertIn('Git COMMIT', records[0])
        self.assertIn('first commit', records[0])
        self.assertIn('second commit', records[1])
        self.quiet()
        self.git('reflog', 'expire', '--expire=never', '--all')
        self.quiet()  # Rewriting the log must not replay its history.
        self.git('commit', '--allow-empty', '-qm', 'after log rewrite')
        self.assertIn('after log rewrite', self.change())


if __name__ == '__main__':
    unittest.main()
