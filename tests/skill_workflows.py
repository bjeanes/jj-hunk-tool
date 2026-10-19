"""Executable JJ scenarios for the skill recipes. Run: python3 tests/skill_workflows.py."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class SkillWorkflows(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='jj-skill-workflows-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.env = {**os.environ, 'JJ_CONFIG': '/dev/null'}
        subprocess.run(['jj', 'git', 'init', str(self.repo)], env=self.env,
                       check=True, capture_output=True)

    def jj(self, *args):
        result = subprocess.run(['jj', '--no-pager', '--color=never',
                                 '--config', 'user.name="Skill test"',
                                 '--config', 'user.email="skill@example.invalid"', *args],
                                cwd=self.repo, env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def value(self, rev, template='change_id'):
        return self.jj('log', '--no-graph', '-r', rev, '-T', template)

    def commit(self, name, filename, content):
        (self.repo / filename).write_text(content)
        self.jj('commit', '-m', name)
        return self.value('@-')

    def duplicate(self, rev, name):
        self.jj('duplicate', rev)
        copy = self.value(f'description(substring:"{name}") ~ {rev}')
        self.assertNotEqual(copy, rev)
        return copy

    def test_restore_chain_preserves_original_ids_and_tip_tree(self):
        a = self.commit('A', 'a', 'original A\n')
        b = self.commit('B', 'b', 'original B\n')
        child = self.commit('child', 'child', 'dependent work\n')
        self.jj('duplicate', f'{a}::{b}')
        da = self.value(f'description(substring:"A") ~ {a}')
        db = self.value(f'description(substring:"B") ~ {b}')
        self.jj('edit', da)
        (self.repo / 'a').write_text('polished A\n')
        self.jj('describe', '-m', 'polished A')
        self.jj('edit', db)
        (self.repo / 'b').write_text('polished B\n')
        self.jj('describe', '-m', 'polished B')
        self.jj('new')
        before = self.value(b, 'commit_id')
        self.jj('restore', '--from', da, '--into', a)
        self.jj('describe', a, '-m', 'polished A')
        self.jj('restore', '--from', db, '--into', b)
        self.jj('describe', b, '-m', 'polished B')
        self.assertEqual(self.jj('diff', '--git', '--from', db, '--to', b), '')
        for original in (a, b, child):
            self.assertEqual(self.value(original), original)
        self.assertNotEqual(self.value(b, 'commit_id'), before)
        self.assertEqual(self.value(b, 'description.first_line()'), 'polished B')
        self.assertEqual(self.jj('file', 'show', '-r', child, 'child'), 'dependent work')
        self.assertEqual(self.value('conflicts()'), '')
        self.jj('new', child)
        self.jj('abandon', f'{da}::{db}')
        self.assertEqual(self.value(f'{a}::{child}', 'change_id ++ "\n"').splitlines(),
                         [child, b, a])

    def test_other_worker_uses_temporary_duplicate_then_returns(self):
        a = self.commit('A', 'a', 'original A\n')
        b = self.commit('B', 'b', 'worker B\n')
        da = self.duplicate(a, 'A')
        self.jj('rebase', '-s', b, '-d', da)
        self.jj('edit', a)
        (self.repo / 'a').write_text('polished A\n')
        self.jj('new', b)
        self.jj('rebase', '-s', b, '-d', a)
        self.jj('abandon', da)
        self.assertEqual(self.value(b + '-'), a)
        self.assertEqual(self.jj('file', 'show', '-r', b, 'a'), 'polished A')
        self.assertEqual(self.jj('file', 'show', '-r', b, 'b'), 'worker B')
        self.assertEqual(self.value(b), b)
        self.assertEqual(self.value('conflicts()'), '')

    def test_workspace_parent_check_catches_wrong_parent(self):
        a = self.commit('A', 'a', 'A\n')
        b = self.commit('B', 'b', 'B\n')
        workspace = self.root / 'worker'
        self.jj('workspace', 'add', str(workspace), '--name', 'worker', '-r', a)
        self.assertEqual(self.value('worker@-'), a)
        self.assertNotEqual(self.value('worker@-'), b)
        self.jj('workspace', 'forget', 'worker')


if __name__ == '__main__':
    unittest.main(verbosity=2)
