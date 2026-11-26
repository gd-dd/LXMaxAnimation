import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ui import clips, unity_export
from ui.library import Library, read_json


class UnityImportTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.library = Library(self.root / 'library')
        self.library.initialize()
        self.library.create_character('飞碟')
        self.project = self.make_project('团队/游戏')
        self.receiver = self.root / 'Receiver.cs'
        self.receiver.write_text('// test fixture', encoding='utf-8')
        self.work = self.root / 'exports'

    def tearDown(self):
        self.directory.cleanup()

    def make_project(self, name):
        project = self.root / name
        (project / 'Assets').mkdir(parents=True)
        (project / 'ProjectSettings').mkdir()
        (project / 'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 2022.3.20f1\n')
        return project

    def asset(self, name, kind, file='asset.fbx', payload=b'FBX fixture'):
        source = Path(tempfile.mkdtemp(dir=self.root))
        (source / file).write_bytes(payload)
        return self.library.publish('飞碟', name, kind, source, file,
                                    metadata={'start': 12, 'end': 60, 'frame': 38, 'fps': 24})

    def prepare(self, entries, **kwargs):
        return unity_export.prepare_import(self.library, self.project, entries, self.receiver,
                                           self.root / 'export.py', None, self.work, **kwargs)

    def request(self, ticket):
        return read_json(ticket.with_name(ticket.name.replace('.result.json', '.request.json')))

    def finish(self, tickets):
        for ticket in tickets:
            ticket.with_name(ticket.name.replace('.result.json', '.request.json')).unlink()

    def test_scans_one_or_more_projects_without_entering_unity_cache(self):
        next_project = self.make_project('演示/项目')
        self.make_project('用户/Library/忽略')
        self.assertEqual({x[0] for x in unity_export.scan_projects(self.root)}, {self.project, next_project})
        self.assertEqual(unity_export.scan_projects(self.project), [(self.project, '2022.3.20f1')])

    def test_export_two_animations_repeat_overwrite_and_after_rename(self):
        walk = self.asset('行走', 'animation')
        idle = self.asset('待机', 'animation')
        config = clips.document(walk)
        config['clips'][0]['name'] = '行走半程'
        config['clips'][0]['lastFrame'] = 28
        config['clips'][0]['settings']['loopTime'] = True
        clips.save(self.library, walk, config)
        tickets, _ = self.prepare([(walk, 'animation'), (idle, 'animation')])
        request = self.request(tickets[0])
        path = self.project / request['path']
        self.assertEqual(request['sourceStart'], 12)
        self.assertEqual(request['clips'][0]['lastFrame'], 28)
        self.assertTrue(json.loads(next(s['json'] for s in request['clips'][0]['settings']
                                        if s['name'] == 'loopTime')))
        self.assertEqual(path.relative_to(self.project).as_posix(), 'Assets/Charactor/飞碟/Animations/行走.fbx')
        meta = path.with_suffix('.fbx.meta')
        meta.write_bytes(b'guid: keep-on-overwrite')
        self.finish(tickets)

        newest = self.asset('行走', 'animation', payload=b'new revision')
        stable_role = self.library.character_id('飞碟')
        self.library.rename_character('飞碟', '新飞碟')
        self.assertEqual(self.library.character_id('新飞碟'), stable_role)
        current, _ = self.library.list_assets('新飞碟')
        renamed = next(item for item in current if item['id'] == newest['id'])
        tickets, _ = self.prepare([(renamed, 'animation')])
        self.assertEqual(self.request(tickets[0])['path'], request['path'])
        self.assertEqual(path.read_bytes(), b'new revision')
        self.assertEqual(meta.read_bytes(), b'guid: keep-on-overwrite')
        self.finish(tickets)
        rerun = unity_export.prepare_reimport(self.project, self.receiver)
        self.assertEqual(len(rerun), 2)
        self.assertEqual({self.request(ticket)['path'] for ticket in rerun}, set(unity_export.import_manifest(self.project)['assets']))

    def test_export_model_pose_and_tpose_in_one_max_batch(self):
        model = self.asset('基准', 'model', 'source.max')
        pose = self.asset('摆手', 'pose', 'source.max')
        def runner(_max, _script, _staging, jobs):
            self.assertEqual([item['kind'] for item in jobs], ['model', 'pose', 'tpose'])
            for job in jobs:
                Path(job['output']).write_bytes(b'FBX ' + job['kind'].encode())
            return {job['output']: {'start': 38, 'end': 39, 'fps': 24} for job in jobs}
        with patch.object(unity_export, 'max_export', side_effect=runner):
            tickets, _ = self.prepare([(model, 'model'), (pose, 'pose'), (model, 'tpose')], model_rig='Humanoid')
        payloads = [self.request(ticket) for ticket in tickets]
        self.assertEqual([p['rig'] for p in payloads], ['Humanoid'] * 3)
        self.assertEqual([Path(p['path']).parent.name for p in payloads], ['Model', 'Poses', 'TPose'])
        self.assertEqual([(p['clips'][0]['firstFrame'], p['clips'][0]['lastFrame']) for p in payloads[1:]],
                         [(38, 39), (38, 39)])

    def test_refuse_other_project_files_and_rollback_partial_copy(self):
        walk = self.asset('行走', 'animation')
        idle = self.asset('待机', 'animation')
        original_copy = unity_export.atomic_copy
        def unreliable_copy(source, destination):
            if destination.name == '待机.fbx':
                raise OSError('blocked')
            original_copy(source, destination)
        with patch.object(unity_export, 'atomic_copy', side_effect=unreliable_copy):
            with self.assertRaisesRegex(OSError, 'blocked'):
                self.prepare([(walk, 'animation'), (idle, 'animation')])
        self.assertFalse(list((self.project / 'Assets/Charactor').rglob('*.fbx')))
        unrelated = self.project / 'Assets/Charactor/飞碟'
        unrelated.mkdir(exist_ok=True)
        (unrelated / 'artist.fbx').write_bytes(b'manual')
        # The stable directory has already been created by the previous failed import.
        tickets, _ = self.prepare([(walk, 'animation')])
        self.assertIn('--', self.request(tickets[0])['path'])
        self.assertEqual((unrelated / 'artist.fbx').read_bytes(), b'manual')

    def test_different_editor_version_does_not_upgrade_the_project(self):
        exe = self.root / 'Unity.exe'
        exe.touch()
        version_file = self.project / 'ProjectSettings/ProjectVersion.txt'
        original = version_file.read_bytes()
        tickets, _ = self.prepare([(self.asset('行走', 'animation'), 'animation')])
        with (patch.object(unity_export, 'editor_version', return_value='6000.3.19f1'),
              patch.object(unity_export.subprocess, 'run') as run):
            with self.assertRaisesRegex(ValueError, '项目需要 2022.3.20f1'):
                unity_export.process_imports(self.project, tickets, exe)
            run.assert_not_called()
        self.assertEqual(version_file.read_bytes(), original)
