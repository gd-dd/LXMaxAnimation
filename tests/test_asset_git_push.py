import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ui import asset_git_push as asset_sync
from ui.integrations import git_run, init_git, sync_git
from ui.library import Library, read_json, write_json


class AssetPushTests(unittest.TestCase):
    def setUp(self):
        area=tempfile.TemporaryDirectory()
        self.addCleanup(area.cleanup)
        self.base=Path(area.name)
        config=patch.dict(os.environ,{'GIT_CONFIG_GLOBAL':str(self.base/'config'),
                                      'GIT_CONFIG_NOSYSTEM':'1'})
        config.start()
        self.addCleanup(config.stop)
        try:
            git_run(self.base,'lfs','version')
        except (OSError,ValueError,RuntimeError) as error:
            self.skipTest(str(error))
        self.remote=self.base/'remote.git'
        git_run(self.base,'init','--bare','-b','main',str(self.remote))
        self.root=self.base/'local'
        self.library=Library(self.root)
        self.library.initialize()
        init_git(self.root)
        git_run(self.root,'remote','add','origin',str(self.remote))
        self.identity(self.root)
        self.library.create_character('月猫')
        self.source=self.base/'source'
        self.source.mkdir()

    def identity(self, root):
        git_run(root,'config','user.name','Animator')
        git_run(root,'config','user.email','animator@example.invalid')

    def animation(self, name, scene=b'Max scene bytes'):
        (self.source/'scene.max').write_bytes(scene)
        return self.library.publish('月猫',name,'animation',self.source,'scene.max')

    def path(self, asset, filename='asset.json'):
        return (Path(asset['_directory'])/filename).relative_to(self.root).as_posix()

    def edit_notes(self, asset, notes):
        metadata=self.root/self.path(asset)
        value=read_json(metadata)
        value['notes']=notes
        write_json(metadata,value)

    def remote_head(self):
        return git_run(self.remote,'rev-parse','HEAD')

    def remote_files(self):
        paths=git_run(self.remote,'ls-tree','-r','-z','--name-only','HEAD',strip=False)
        return set(paths.rstrip('\0').split('\0'))

    def test_first_push_includes_selected_family_and_required_records_only(self):
        walk=self.animation('行走 [1]')
        alternate=self.animation('行走 [1]',b'second version')
        jump=self.animation('跳跃',b'other animation')
        jump_path=self.path(jump)
        git_run(self.root,'add','--',jump_path)
        before=git_run(self.root,'ls-files','--stage','--',jump_path)

        self.assertIn('已推送',asset_sync.push_asset(self.root,walk,'Export walk'))
        remote=self.remote_files()
        self.assertIn(self.path(walk),remote)
        self.assertIn(self.path(alternate),remote)
        self.assertIn('library.json',remote)
        self.assertIn('characters/月猫/character.json',remote)
        self.assertIn('.gitattributes',remote)
        self.assertNotIn(jump_path,remote)
        self.assertEqual(git_run(self.root,'ls-files','--stage','--',jump_path),before)
        self.assertTrue((self.root/self.path(jump,'scene.max')).exists())
        self.assertEqual(git_run(self.root,'status','--porcelain','--',self.path(walk)),'')
        self.assertEqual(git_run(self.root,'rev-parse','HEAD'),self.remote_head())

        recipient=self.base/'recipient'
        git_run(self.base,'clone',str(self.remote),str(recipient))
        git_run(recipient,'lfs','install','--local')
        git_run(recipient,'lfs','pull')
        self.assertEqual((recipient/self.path(walk,'scene.max')).read_bytes(),b'Max scene bytes')
        self.assertEqual((recipient/self.path(alternate,'scene.max')).read_bytes(),b'second version')

    def test_unrelated_staged_and_unstaged_changes_survive(self):
        a=self.animation('行走')
        b=self.animation('跑步')
        sync_git(self.root,'push')
        self.edit_notes(a,'walk ready')
        self.edit_notes(b,'staged note')
        b_path=self.path(b)
        git_run(self.root,'add','--',b_path)
        staged=git_run(self.root,'show',':'+b_path)
        self.edit_notes(b,'working note')
        unrelated=self.root/'unrelated.txt'
        unrelated.write_text('leave unchanged',encoding='utf-8')

        asset_sync.push_asset(self.root,a)
        self.assertEqual(git_run(self.remote,'diff-tree','--no-commit-id','--name-only','-r','-z','HEAD',
                                 strip=False).rstrip('\0'),self.path(a))
        self.assertEqual(git_run(self.root,'show',':'+b_path),staged)
        self.assertEqual(read_json(self.root/b_path)['notes'],'working note')
        self.assertEqual(unrelated.read_text('utf-8'),'leave unchanged')

    def test_renamed_legacy_role_requires_whole_library_push_once(self):
        walk=self.animation('行走')
        legacy=self.root/'characters/月猫/character.json'
        marker=read_json(legacy)
        marker.pop('id')
        write_json(legacy,marker)
        sync_git(self.root,'push')
        before=self.remote_head()
        renamed=self.library.rename_character('月猫','月夜猫')
        current=self.library.list_assets(renamed)[0][0]
        self.assertEqual(current['id'],walk['id'])
        with self.assertRaisesRegex(ValueError,'角色已重命名'):
            asset_sync.push_asset(self.root,current)
        self.assertEqual(self.remote_head(),before)
        self.assertIn(self.path(walk),self.remote_files())
        self.assertNotIn(self.path(current),self.remote_files())
        sync_git(self.root,'push')
        self.assertNotIn(self.path(walk),self.remote_files())
        self.assertIn(self.path(current),self.remote_files())
        self.edit_notes(current,'renamed role is now synchronized')
        self.assertIn('已推送',asset_sync.push_asset(self.root,current))

    def test_same_asset_existing_commit_can_be_pushed(self):
        a=self.animation('行走')
        sync_git(self.root,'push')
        self.edit_notes(a,'local commit')
        git_run(self.root,'add','--',self.path(a))
        git_run(self.root,'commit','-m','walk only')
        local=git_run(self.root,'rev-parse','HEAD')
        git_run(self.root,'tag','-a','local-only','-m','private test tag')
        git_run(self.root,'config','push.followTags','true')
        asset_sync.push_asset(self.root,a)
        self.assertEqual(self.remote_head(),local)
        self.assertEqual(git_run(self.remote,'tag','--list'),'')
        self.assertIn('没有待推送',asset_sync.push_asset(self.root,a))

    def test_refuses_a_push_target_other_than_the_read_target(self):
        a=self.animation('行走')
        wrong_remote=self.base/'different.git'
        git_run(self.base,'init','--bare','-b','main',str(wrong_remote))
        git_run(self.root,'remote','set-url','--push','origin',str(wrong_remote))
        with self.assertRaisesRegex(ValueError,'同一个读取和推送地址'):
            asset_sync.push_asset(self.root,a)
        self.assertEqual(git_run(wrong_remote,'for-each-ref'),'')
        self.assertEqual(git_run(self.remote,'for-each-ref'),'')

    def test_refuses_unrelated_commit_even_if_later_reverted(self):
        a=self.animation('行走')
        b=self.animation('跳跃')
        sync_git(self.root,'push')
        remote=self.remote_head()
        self.edit_notes(b,'private unrelated')
        git_run(self.root,'add','--',self.path(b))
        git_run(self.root,'commit','-m','jump only')
        git_run(self.root,'revert','--no-edit','HEAD')
        self.edit_notes(a,'walk ready')
        with self.assertRaisesRegex(ValueError,'其他资产'):
            asset_sync.push_asset(self.root,a)
        self.assertEqual(self.remote_head(),remote)
        self.assertEqual(read_json(self.root/self.path(a))['notes'],'walk ready')

    def test_cloud_ahead_leaves_working_and_staged_content(self):
        a=self.animation('行走')
        sync_git(self.root,'push')
        publisher=self.base/'publisher'
        git_run(self.base,'clone',str(self.remote),str(publisher))
        self.identity(publisher)
        original=git_run(self.root,'rev-parse','HEAD')
        metadata=publisher/self.path(a)
        remote_change=read_json(metadata)
        remote_change['notes']='cloud change'
        write_json(metadata,remote_change)
        git_run(publisher,'add','--',self.path(a))
        git_run(publisher,'commit','-m','cloud edit')
        git_run(publisher,'push')
        cloud=self.remote_head()
        self.edit_notes(a,'local note')
        git_run(self.root,'add','--',self.path(a))
        staged=git_run(self.root,'show',':'+self.path(a))
        with self.assertRaisesRegex(ValueError,'云端有更新'):
            asset_sync.push_asset(self.root,a)
        self.assertEqual(self.remote_head(),cloud)
        self.assertEqual(git_run(self.root,'rev-parse','HEAD'),original)
        self.assertEqual(git_run(self.root,'show',':'+self.path(a)),staged)

    def test_push_includes_deletion_of_old_layout_revision(self):
        old=self.animation('行走')
        original=Path(old['_directory'])
        old_folder=self.root/'characters/月猫/animation/legacy-old-version'
        original.rename(old_folder)
        old['_directory']=str(old_folder)
        a=self.animation('行走',b'new layout')
        sync_git(self.root,'push')
        self.assertIn(self.path(old),self.remote_files())
        self.library.delete_asset(old)
        asset_sync.push_asset(self.root,a)
        self.assertNotIn(self.path(old),self.remote_files())
        self.assertIn(self.path(a),self.remote_files())
