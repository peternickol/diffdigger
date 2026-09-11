import os
from pathlib import Path
import queue
import runpy
import subprocess
import sys
import tempfile
import threading
import unittest

SCRIPT = Path(__file__).with_name('diffdigger')
APP = runpy.run_path(str(SCRIPT))


class RepositoriesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)

    def git(self, root, *args):
        return subprocess.run(
            ['git', '-C', str(root), '-c', 'user.name=Diff Test',
             '-c', 'user.email=test@example.invalid', *args], check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def repo(self, relative, content='before\n'):
        root = self.parent / relative
        root.mkdir(parents=True, exist_ok=True)
        self.git(root, 'init', '-q')
        (root / 'code.py').write_text(content)
        self.git(root, 'add', '.')
        self.git(root, 'commit', '-qm', 'baseline')
        return root

    def start(self, *args, cwd=None):
        process = subprocess.Popen(
            [sys.executable, str(SCRIPT), *map(str, args)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd,
        )
        def stop():
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()
        self.addCleanup(stop)
        self.process = process
        self.output, self.messages = queue.Queue(), queue.Queue()
        for pipe, target in ((process.stdout, self.output), (process.stderr, self.messages)):
            threading.Thread(target=lambda p=pipe, q=target: [q.put(line.rstrip('\n')) for line in p],
                             daemon=True).start()
        messages = []
        while True:
            line = self.messages.get(timeout=5)
            messages.append(line)
            if line.startswith('Ready.'):
                return '\n'.join(messages)

    def event(self):
        lines = []
        while True:
            line = self.output.get(timeout=5)
            if not line:
                return '\n'.join(lines)
            lines.append(line)

    def quiet(self):
        with self.assertRaises(queue.Empty):
            self.output.get(timeout=0.8)
        self.assertIsNone(self.process.poll())

    def test_current_directory_discovers_children_and_keeps_feeds_separate(self):
        alpha = self.repo('alpha', 'alpha baseline\n')
        beta = self.repo('beta', 'beta baseline\n')
        self.repo('group/nested')
        (self.parent / 'alias').symlink_to(alpha, target_is_directory=True)
        self.git(self.parent, 'init', '--bare', '-q', str(self.parent / 'remote.git'))
        self.assertEqual(APP['repositories']([self.parent]), [alpha, beta])
        banner = self.start(cwd=self.parent)
        self.assertIn('2 repositories', banner)
        self.quiet()  # Startup must not replay either checkout's baseline commit.

        (self.parent / 'code.py').write_text('parent excluded\n')
        (self.parent / 'group/nested/code.py').write_text('nested excluded\n')
        (alpha / 'code.py').write_text('alpha saved\n')
        (beta / 'code.py').write_text('beta saved\n')
        events = [self.event(), self.event()]
        alpha_event = next(event for event in events if '[alpha]' in event)
        beta_event = next(event for event in events if '[beta]' in event)
        self.assertIn('-alpha baseline\n+alpha saved', alpha_event)
        self.assertIn('-beta baseline\n+beta saved', beta_event)
        self.quiet()

        for root in (alpha, beta):
            self.git(root, 'add', 'code.py')
            self.git(root, 'commit', '-qm', root.name + ' commit')
        commits = [self.event(), self.event()]
        self.assertTrue(any('[alpha] Git COMMIT' in event and 'alpha commit' in event for event in commits))
        self.assertTrue(any('[beta] Git COMMIT' in event and 'beta commit' in event for event in commits))
        (alpha / 'code.py').write_text('alpha next\n')
        self.assertIn('-alpha saved\n+alpha next', self.event())
        self.quiet()

    def test_current_checkout_takes_precedence_over_child_repositories(self):
        root = self.repo('.')
        self.repo('child')
        self.assertEqual(APP['repositories']([root]), [root])
        banner = self.start(cwd=root)
        self.assertIn(f'Diffdigger · {root}', banner)
        (root / 'code.py').write_text('current checkout\n')
        event = self.event()
        self.assertIn('Modified code.py', event)
        self.assertIn('-before\n+current checkout', event)
        self.quiet()

    def test_explicit_paths_deduplicate_checkouts_and_disambiguate_names(self):
        first = self.repo('team one/app')
        second = self.repo('team two/app')
        nested = first / 'src'
        nested.mkdir()
        banner = self.start(first, nested, second, first)
        self.assertIn('2 repositories', banner)
        for root in (first, second):
            (root / 'code.py').write_text('updated\n')
        events = [self.event(), self.event()]
        for root in (first, second):
            self.assertTrue(any(f'[{root}] Modified code.py' in event for event in events))
        self.quiet()  # Repeated paths must not duplicate events.

    def test_linked_worktrees_are_discovered_and_watched(self):
        root = self.repo('main')
        worktree = self.parent / 'agent-worktree'
        self.git(root, 'worktree', 'add', '-qb', 'agent', str(worktree))
        self.assertTrue((worktree / '.git').is_file())
        self.assertEqual(APP['repositories']([self.parent]), [worktree, root])
        self.start(self.parent)
        (worktree / 'code.py').write_text('agent save\n')
        event = self.event()
        self.assertIn('[agent-worktree] Modified code.py', event)
        self.assertIn('-before\n+agent save', event)
        self.git(worktree, 'add', 'code.py')
        self.git(worktree, 'commit', '-qm', 'agent commit')
        self.assertIn('[agent-worktree] Git COMMIT', self.event())
        self.quiet()

    def test_unavailable_repo_does_not_stop_other_feeds(self):
        alpha = self.repo('alpha')
        beta = self.repo('beta')
        self.start(self.parent)
        hidden = self.parent / 'alpha-moved'
        os.rename(alpha, hidden)
        error = self.messages.get(timeout=5)
        self.assertIn('[alpha]', error)
        self.assertIn('unavailable', error)
        (beta / 'code.py').write_text('still watching\n')
        self.assertIn('[beta] Modified code.py', self.event())
        self.quiet()
        with self.assertRaises(queue.Empty):
            self.messages.get(timeout=0.2)  # Do not repeat the same error every poll.
        (hidden / 'code.py').write_text('returned\n')
        os.rename(hidden, alpha)
        event = self.event()
        self.assertIn('[alpha] Modified code.py', event)
        self.assertIn('-before\n+returned', event)
        self.assertIn('[alpha] Watching again.', self.messages.get(timeout=5))

    def test_directory_without_repositories_has_a_clear_error(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(self.parent)],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn('No repositories found', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_replaced_directories_are_checked_for_symlinks_each_round(self):
        root = self.repo('repo')
        directory = root / 'src/nested'
        directory.mkdir(parents=True)
        (directory / 'code.py').write_text('inside\n')
        self.git(root, 'add', '.')
        previous = APP['snapshot'](root, {})
        self.assertEqual(previous['src/nested/code.py'][1], 'inside\n')
        external = self.parent / 'external'
        external.mkdir()
        (external / 'code.py').write_text('outside\n')
        saved = root / 'saved'
        os.rename(directory, saved)
        directory.symlink_to(external, target_is_directory=True)
        current = APP['snapshot'](root, previous)
        self.assertNotIn('src/nested/code.py', current)
        directory.unlink()
        os.rename(saved, directory)
        restored = APP['snapshot'](root, current)
        self.assertEqual(restored['src/nested/code.py'][1], 'inside\n')


if __name__ == '__main__':
    unittest.main()
