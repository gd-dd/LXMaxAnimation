import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ui.asset_git_status import asset_git_state, asset_paths, asset_status
from ui.integrations import git_run


class AssetGitStatusTests(unittest.TestCase):
    paths = {
        'Jump': 'characters/角色/animation/跳跃/versions/v001',
        'Jump neighbor': 'characters/角色/animation/跳跃2/versions/v001',
        'Walk': 'characters/角色/animation/行走/versions/v001',
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = patch.dict('os.environ', {
            'GIT_CONFIG_GLOBAL': str(self.root / 'global-git-config'),
            'GIT_CONFIG_NOSYSTEM': '1',
        })
        config.start()
        self.addCleanup(config.stop)
        self.repo = self.root / 'artist'
        self.peer = self.root / 'peer'
        self.remote = self.root / 'remote.git'
        self.repo.mkdir()
        git_run(self.repo, 'init', '-b', 'main')
        git_run(self.root, 'init', '--bare', '-b', 'main', str(self.remote))
        self.identity(self.repo)
        for path in self.paths:
            self.write(self.repo, path, 'original')
        self.commit(self.repo, 'Original versions')
        git_run(self.repo, 'remote', 'add', 'origin', str(self.remote))
        git_run(self.repo, 'push', '-u', 'origin', 'main')
        git_run(self.root, 'clone', str(self.remote), str(self.peer))
        self.identity(self.peer)

    def identity(self, repo):
        git_run(repo, 'config', 'user.name', 'Artist')
        git_run(repo, 'config', 'user.email', 'artist@example.invalid')

    def write(self, repo, path, contents):
        file = repo / self.paths.get(path, path) / 'asset.json'
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(contents, encoding='utf-8')

    def commit(self, repo, message):
        git_run(repo, 'add', '--all')
        git_run(repo, 'commit', '-m', message)

    def state(self, name, state=None, *, exact=False, historical=False):
        versions = {'_directory': str(self.repo / self.paths[name])}
        return asset_status(state if state is not None else asset_git_state(self.repo),
                            asset_paths(self.repo, versions, exact=exact), historical=historical)

    def test_changed_group_does_not_pollute_neighbor_or_historical_status(self):
        self.write(self.repo, 'Jump', 'changed')
        state = asset_git_state(self.repo)
        self.assertEqual(self.state('Jump', state)['text'], '已修改')
        self.assertEqual(self.state('Jump neighbor', state)['text'], '最新')
        self.assertEqual(self.state('Walk', state, exact=True, historical=True)['text'], '旧版本')
        empty = asset_status(None, 'characters/角色/animation/跳跃')
        self.assertTrue(empty['refresh_required'])
        new = 'characters/角色/animation/跳跃/versions/v002'
        self.write(self.repo, new, 'new')
        exact = asset_paths(self.repo, {'_directory': str(self.repo / new)}, exact=True)
        self.assertTrue(asset_status(asset_git_state(self.repo), exact)['untracked'])

    def test_only_fetched_content_changes_asset_state(self):
        before = asset_git_state(self.repo)
        self.write(self.peer, 'Jump', 'cloud addition')
        self.commit(self.peer, 'Cloud edits Jump')
        git_run(self.peer, 'push')
        cached = asset_git_state(self.repo)
        self.assertEqual(cached['cloud_oid'], before['cloud_oid'])
        self.assertEqual(self.state('Jump', cached)['text'], '最新')
        git_run(self.repo, 'fetch', 'origin')
        fetched = asset_git_state(self.repo)
        self.assertNotEqual(fetched['cloud_oid'], before['cloud_oid'])
        self.assertEqual(self.state('Jump', fetched)['text'], '旧版本')
        self.assertEqual(self.state('Walk', fetched)['text'], '最新')

    def test_outgoing_changes_and_incoming_changes_are_scoped_in_diverged_history(self):
        self.write(self.repo, 'Walk', 'local Walk')
        self.commit(self.repo, 'Local edits Walk')
        self.write(self.peer, 'Jump', 'cloud Jump')
        self.commit(self.peer, 'Cloud edits Jump')
        git_run(self.peer, 'push')
        git_run(self.repo, 'fetch', 'origin')
        state = asset_git_state(self.repo)
        self.assertEqual(self.state('Walk', state)['text'], '待推送')
        self.assertEqual(self.state('Jump', state)['text'], '旧版本')
        self.assertEqual(self.state('Jump neighbor', state)['text'], '最新')

    def test_actual_conflict_and_deleted_cloud_asset(self):
        self.write(self.repo, 'Walk', 'local conflict')
        self.commit(self.repo, 'Local edits Walk')
        self.write(self.peer, 'Walk', 'cloud conflict')
        git_run(self.peer, 'rm', self.paths['Jump']+'/asset.json')
        self.commit(self.peer, 'Delete Jump and edit Walk')
        git_run(self.peer, 'push')
        git_run(self.repo, 'fetch', 'origin')
        state = asset_git_state(self.repo)
        self.assertEqual(self.state('Walk', state)['text'], '双端有更新')
        jump = self.state('Jump', state)
        self.assertEqual(jump['text'], '旧版本')
        self.assertIn('云端已经删除', jump['detail'])
        with self.assertRaises(RuntimeError):
            git_run(self.repo, 'merge', 'origin/main')
        status = self.state('Walk')
        self.assertTrue(status['conflict'])
        self.assertEqual(status['text'], '有冲突')

    def test_unfetched_origin_does_not_guess_status(self):
        git_run(self.repo, 'update-ref', '-d', 'refs/remotes/origin/main')
        state = asset_git_state(self.repo)
        self.assertFalse(state['checked'])
        self.assertEqual(self.state('Walk', state)['text'], '云端待检查')


class AssetPathsTests(unittest.TestCase):
    def test_preserves_legacy_scope_and_exact_named_revision(self):
        root = Path.cwd()
        new = root / 'characters/角色/animation/起跑/versions/latest'
        legacy = root / 'characters/角色/animation/起跑--旧版'
        versions = [{'_directory': str(new)}, {'_directory': str(legacy)}]
        self.assertEqual(asset_paths(root, versions),
                         ('characters/角色/animation/起跑', 'characters/角色/animation/起跑--旧版'))
        self.assertEqual(asset_paths(root, versions, exact=True),
                         ('characters/角色/animation/起跑--旧版', 'characters/角色/animation/起跑/versions/latest'))
