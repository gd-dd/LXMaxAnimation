import json
from pathlib import Path
import tempfile
import unittest
from ui.library import Library, safe_name, contained
from ui.integrations import send_unity


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.library=Library(self.root/'library');self.library.initialize();self.library.create_character('纳西妲')
        self.source=self.root/'walk.fbx';self.source.write_bytes(b'test fixture, not a valid FBX')
    def tearDown(self):self.temp.cleanup()
    def asset(self):return self.library.import_fbx('纳西妲','行走','animation',self.source)
    def test_versions_never_overwrite(self):
        first,second=self.asset(),self.asset()
        self.assertNotEqual(first['_directory'],second['_directory'])
        self.assertEqual(len(self.library.list_assets('纳西妲')[0]),2)
        self.assertTrue(self.library.verify(first).exists())
    def test_tampering_detected(self):
        asset=self.asset();Path(asset['_directory'],'asset.fbx').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):self.library.verify(asset)
    def test_path_escape_rejected(self):
        for value in ('../bad','CON','COM1.txt','bad/name','bad\\name','a:foo','x.'):
            with self.assertRaises(ValueError):safe_name(value)
        with self.assertRaises(ValueError):contained(self.root,'../escape')
    def test_case_collisions_rejected(self):
        self.library.create_character('Hero')
        with self.assertRaises(ValueError):self.library.create_character('hero')
    def test_search_and_corruption_reporting(self):
        asset=self.asset()
        self.assertEqual(len(self.library.list_assets('纳西妲','行')[0]),1)
        Path(asset['_directory'],'asset.json').write_text('{}')
        good,errors=self.library.list_assets('纳西妲')
        self.assertEqual(good,[]);self.assertEqual(len(errors),1)
    def test_unity_delivery_and_duplicate_prevention(self):
        project=self.root/'Unity';(project/'Assets').mkdir(parents=True);(project/'ProjectSettings').mkdir()
        (project/'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 2022.3.62f1')
        receiver=Path(__file__).resolve().parents[1]/'unity/LXMaxAnimationReceiver.cs'
        asset=self.asset();result=send_unity(self.library,asset,project,receiver)
        request=result.with_name(result.name.replace('.result.json','.request.json'))
        data=json.loads(request.read_text('utf-8'))
        self.assertTrue((project/data['path']).exists())
        self.assertFalse(result.exists()) # copying is not claimed as editor success
        with self.assertRaises(ValueError):send_unity(self.library,asset,project,receiver)
    def test_empty_file_not_published(self):
        self.source.write_bytes(b'')
        with self.assertRaises(ValueError):self.asset()
        self.assertEqual(self.library.list_assets()[0],[])


if __name__=='__main__':unittest.main()
