import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('profile', Path(__file__).resolve().parents[1] / 'bin/project-profile.py')
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic Test')
        self.git('config', 'user.email', 'synthetic@example.test')
        self.put('AGENTS.md', 'Synthetic fixture rules.\n')
        self.commit()

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.DEVNULL)

    def put(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'Synthetic fixture')

    def saved(self):
        p = Path(self.temp.name) / 'profile.json'
        p.write_text(json.dumps(profile.discover(self.root)))
        return p

    def test_lite_no_execution_authority(self):
        value = profile.discover(self.root)
        self.assertEqual(value['profile_tier'], 'lite')
        self.assertEqual(value['activation'], 'observe_only')
        self.assertFalse(value['policy_proposal']['allow_merge'])

    def test_partial_role_and_full_rules(self):
        self.put('docs/project/agent-roles/builder.md', 'Builder fixture')
        self.assertEqual(profile.discover(self.root)['profile_tier'], 'partial')
        for role in profile.ROLE_NAMES:
            self.put('docs/project/agent-roles/' + role + '.md', 'Fixture role: ' + role)
        self.put('docs/project/single-developer-workflow.md', 'Fixture workflow')
        self.assertEqual(profile.discover(self.root)['profile_tier'], 'full')

    def test_inline_roles_are_partial_not_empty_lite(self):
        self.put('AGENTS.md', '# Rules\n### 1.1 Product Agent\n### 1.2 Builder Agent\n### 1.3 Reviewer Agent\n')
        value = profile.discover(self.root)
        self.assertEqual(value['profile_tier'], 'partial')
        self.assertEqual(len(value['inline_role_hints']), 3)
        self.assertEqual(value['activation'], 'observe_only')

    def test_uncommitted_rules_flagged(self):
        self.put('AGENTS.md', 'Modified fixture')
        value = profile.discover(self.root)
        self.assertFalse(value['rules'][0]['matches_revision'])
        self.assertTrue(any('uncommitted_rule' in w for w in value['warnings']))

    def test_changed_rule_invalidates_snapshot(self):
        p = self.saved()
        self.put('AGENTS.md', 'Changed after scan')
        with self.assertRaisesRegex(ValueError, 'rule_bytes_changed'):
            profile.check(p)

    def test_new_commit_invalidates_revision(self):
        p = self.saved()
        self.put('readme.txt', 'new fixture revision')
        self.commit()
        with self.assertRaisesRegex(ValueError, 'repository_revision_changed'):
            profile.check(p)

    def test_validate_profile_runs_full_check_and_refuses_stale_revision(self):
        import sys
        from unittest import mock
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
        import project_adapter, runtime
        runtime_root = Path(self.temp.name) / 'runtime'
        (runtime_root / 'profiles').mkdir(parents=True)
        (runtime_root / 'bin').mkdir()
        (runtime_root / 'bin/project-profile.py').symlink_to(Path(__file__).resolve().parents[1] / 'bin/project-profile.py')
        (runtime_root / 'profiles/p.json').write_text(json.dumps(profile.discover(self.root)))
        with mock.patch.object(runtime, 'ROOT', runtime_root), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(project_adapter.validate_profile('p.json')['repository_root'], str(self.root.resolve()))
            self.put('readme.txt', 'new fixture revision')
            self.commit()
            with self.assertRaisesRegex(ValueError, 'repository_revision_changed'):
                project_adapter.validate_profile('p.json')
            with self.assertRaisesRegex(ValueError, 'under profiles'):
                project_adapter.validate_profile('../p.json')

    def test_symlink_cannot_read_outside_repo(self):
        outside = Path(self.temp.name) / 'outside.md'
        outside.write_text('private-synthetic-marker')
        self.put('docs/project/agent-roles/.keep', '')
        (self.root / 'docs/project/agent-roles/reviewer.md').symlink_to(outside)
        value = profile.discover(self.root)
        self.assertNotIn('reviewer', value['detected_roles'])
        self.assertTrue(any('symlink' in w for w in value['warnings']))
        self.assertNotIn('private-synthetic-marker', json.dumps(value))

    def test_profile_cannot_enable_itself(self):
        p = self.saved()
        value = json.loads(p.read_text());value['activation'] = 'execute'
        p.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'cannot_enable_execution'):
            profile.check(p)

    def test_profile_traversal_rejected(self):
        p = self.saved()
        value = json.loads(p.read_text());value['rules'][0]['path'] = '../outside.md'
        p.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'invalid_rule_path'):
            profile.check(p)

    def test_checks_discovered_but_not_executed(self):
        self.put('package.json', json.dumps({'scripts': {'test': 'exit 99', 'build': 'exit 99'}}))
        value = profile.discover(self.root)
        self.assertEqual(value['suggested_checks']['test']['command'], ['npm', 'run', 'test'])
        self.assertTrue(value['suggested_checks']['test']['review_required'])

if __name__ == '__main__':
    unittest.main(verbosity=2)
