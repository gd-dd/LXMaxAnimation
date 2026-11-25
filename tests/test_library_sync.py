import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ui import integrations as git
from ui.library import Library


class SharedLibrarySyncTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        env = patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': str(self.base / 'gitconfig'),
                                      'GIT_CONFIG_NOSYSTEM': '1'})
        env.start()
        self.addCleanup(env.stop)
        try:
            self.run_git(self.base, 'lfs', 'version')
        except (OSError, ValueError, RuntimeError) as error:
            self.skipTest(str(error))
        self.remote = self.base / 'remote.git'
        self.run_git(self.base, 'init', '--bare', '-b', 'main', str(self.remote))
        self.cloud = self.base / 'publisher'
        self.local = self.base / 'personal'
        Library(self.cloud).initialize()
        self.run_git(self.cloud, 'init', '-b', 'main')
        self.identity(self.cloud)
        self.run_git(self.cloud, 'lfs', 'install', '--local')
        self.run_git(self.cloud, 'remote', 'add', 'origin', str(self.remote))
        self.asset = 'characters/示例/scene.max'
        self.add_cloud_version(b'first max scene')
        self.first = self.head(self.cloud)
        self.run_git(self.base, 'clone', str(self.remote), str(self.local))
        self.identity(self.local)
        self.run_git(self.local, 'lfs', 'install', '--local')

    def run_git(self, root, *args):
        return git.git_run(root, *args)

    def identity(self, root):
        self.run_git(root, 'config', 'user.name', 'Artist')
        self.run_git(root, 'config', 'user.email', 'artist@example.invalid')

    def head(self, root):
        return self.run_git(root, 'rev-parse', 'HEAD')

    def add_cloud_version(self, content, extra=None):
        path = self.cloud / self.asset
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if extra:
            (self.cloud / extra).write_text('cloud', encoding='utf-8')
        git.sync_git(self.cloud, 'push')
        return self.head(self.cloud)

    def test_refresh_and_fast_forward_pull_include_lfs_data(self):
        target = self.add_cloud_version(b'second max scene')
        state = git.library_sync_state(self.local, check_cloud=True)
        self.assertEqual((state['ahead'], state['behind']), (0, 1))
        self.assertEqual(self.head(self.local), self.first)
        git.sync_git(self.local, 'pull')
        self.assertEqual(self.head(self.local), target)
        self.assertEqual((self.local / self.asset).read_bytes(), b'second max scene')

    def test_overwrite_preserves_diverged_commit_and_dirty_files(self):
        self.add_cloud_version(b'cloud scene')
        tracked = self.local / self.asset
        tracked.write_bytes(b'committed local scene')
        self.run_git(self.local, 'add', '--', self.asset)
        self.run_git(self.local, 'commit', '-m', 'Unpushed scene')
        tip = self.head(self.local)
        tracked.write_bytes(b'next local scene')
        draft = self.local / 'characters/draft.json'
        draft.write_text('new draft', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '未提交'):
            git.sync_git(self.local, 'pull')
        result = git.sync_git(self.local, 'overwrite')
        self.assertIn('备份分支', result)
        self.assertIn('储藏', result)
        self.assertEqual(self.head(self.local), self.head(self.cloud))
        self.assertEqual(tracked.read_bytes(), b'cloud scene')
        backup = self.run_git(self.local, 'for-each-ref', '--format=%(objectname)', 'refs/heads/lx-backup')
        self.assertEqual(backup, tip)
        self.assertEqual(self.run_git(self.local, 'show', 'stash@{0}^3:characters/draft.json'), 'new draft')
        self.run_git(self.local, 'switch', self.run_git(self.local,'branch','--list','lx-backup/*'))
        self.run_git(self.local, 'stash', 'apply', '--index')
        self.assertEqual(tracked.read_bytes(), b'next local scene')
        self.assertEqual(draft.read_text('utf-8'), 'new draft')

    def test_restore_and_revert_keep_remote_untouched(self):
        target = self.add_cloud_version(b'second max scene')
        git.sync_git(self.local, 'pull')
        tracked = self.local / self.asset
        tracked.write_bytes(b'draft max scene')
        result = git.sync_git(self.local, 'restore')
        self.assertIn('储藏', result)
        self.assertEqual(tracked.read_bytes(), b'second max scene')
        git.sync_git(self.local, 'revert', commit=target)
        self.assertEqual(tracked.read_bytes(), b'first max scene')
        self.assertNotEqual(self.head(self.local), target)
        self.assertEqual(self.run_git(self.remote, 'rev-parse', 'HEAD'), target)
        with self.assertRaisesRegex(ValueError, '创建了资产库'):
            git.sync_git(self.local, 'revert', commit=self.first)

    def test_incompatible_cloud_keeps_working_files_and_head(self):
        self.run_git(self.cloud, 'rm', 'library.json')
        self.run_git(self.cloud, 'commit', '-m', 'Remove marker')
        self.run_git(self.cloud, 'push')
        tracked = self.local / self.asset
        tracked.write_bytes(b'local draft')
        with self.assertRaisesRegex(ValueError, '缺少有效'):
            git.sync_git(self.local, 'overwrite')
        self.assertEqual(self.head(self.local), self.first)
        self.assertEqual(tracked.read_bytes(), b'local draft')
