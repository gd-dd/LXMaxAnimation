import copy
import tempfile
import unittest
from pathlib import Path
from ui.library import Library,write_json,read_json
from ui import clips

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.library=Library(self.root/'library');self.library.initialize();self.source=self.root/'source';self.source.mkdir()
        (self.source/'asset.fbx').write_bytes(b'test')
        write_json(self.source/'tpose.json',{'schema':1,'nodes':[]})
        self.metadata={'rig':'Generic','fps':24,'start':0,'end':60,'signature':[{'name':'root'}]}
        self.character=self.library.import_character('Hero',self.source,'asset.fbx',self.metadata)
    def tearDown(self):self.temp.cleanup()
    def animation(self):return self.library.publish('Hero','Walk','animation',self.source,'asset.fbx',metadata=self.metadata)
    def test_character_update_retains_animation(self):
        animation=self.animation();first=self.character['id']
        updated=self.library.import_character('Hero',self.source,'asset.fbx',self.metadata,update=True)
        self.assertNotEqual(updated['id'],first)
        self.assertEqual(self.library.character_info('Hero')['tpose']['id'],updated['id'])
        self.library.verify(animation)
        self.assertEqual(len(self.library.list_assets('Hero')[0]),3)
    def test_failed_role_creation_leaves_no_empty_role(self):
        (self.source/'asset.fbx').write_bytes(b'')
        with self.assertRaises(ValueError):self.library.import_character('Bad',self.source,'asset.fbx',self.metadata)
        self.assertNotIn('Bad',self.library.characters())
    def test_categories_and_character_assignment(self):
        self.library.add_category('主角');self.library.add_category('主角')
        self.library.update_character_info('Hero',category='主角')
        self.assertEqual(self.library.categories(),['主角'])
        self.assertEqual(self.library.character_info('Hero')['category'],'主角')
    def test_clip_independence_and_version_binding(self):
        asset=self.animation();data=clips.document(asset);second=clips.new_clip('Run',20,40);data['clips'].append(second)
        data['clips'][0]['settings']['loopTime']=True
        self.assertFalse(second['settings']['loopTime'])
        clips.save(self.library,asset,data);self.library.verify(asset)
        self.assertEqual(clips.load(self.library,asset),data)
        other=self.animation()
        with self.assertRaises(ValueError):clips.save(self.library,other,data)
    def test_invalid_clip_does_not_overwrite_good_configuration(self):
        asset=self.animation();data=clips.document(asset);clips.save(self.library,asset,data)
        invalid=copy.deepcopy(data);invalid['clips'][0]['lastFrame']=999
        with self.assertRaises(ValueError):clips.save(self.library,asset,invalid)
        self.assertEqual(clips.load(self.library,asset),data)
        invalid=copy.deepcopy(data);invalid['clips'][0]['settings']['events']=[{'frame':500,'function':'Bad'}]
        with self.assertRaises(ValueError):clips.save(self.library,asset,invalid)
    def test_explicit_save_carries_valid_clips_to_new_revision(self):
        first=self.animation();data=clips.document(first);data['clips'][0]['settings']['mirror']=True;clips.save(self.library,first,data)
        second=self.animation();self.library.mark_superseded(first,second)
        self.assertTrue(clips.load(self.library,second)['clips'][0]['settings']['mirror'])
        self.library.verify(first);self.library.verify(second)
    def test_unsupported_clip_schema_is_not_silently_replaced(self):
        asset=self.animation();path=clips.path_for(self.library,asset);write_json(path,{'schemaVersion':999})
        with self.assertRaises(ValueError):clips.load(self.library,asset)
        self.assertEqual(read_json(path),{'schemaVersion':999})

    def test_named_fbx_preset_roundtrip_and_split_protection(self):
        asset=self.animation();data=clips.document(asset);data['clips'].append(clips.new_clip('Run',20,40))
        data['clips'][0]['takeName']='Take 001';before=copy.deepcopy(data)
        preset=clips.builtin_presets()['根运动行走 / 跑步'];preset['fbxSettings']['globalScale']=0.01
        clips.save_preset(self.library,'项目配置',preset)
        loaded=clips.presets(self.library)['项目配置'];self.assertEqual(loaded,preset)
        changed=clips.apply_preset(data,asset,data['clips'][0]['id'],loaded)
        self.assertEqual(data,before)
        self.assertEqual(changed['clips'][1],before['clips'][1])
        for key in ('id','name','firstFrame','lastFrame','notes','takeName'):
            self.assertEqual(changed['clips'][0][key],before['clips'][0][key])
        self.assertEqual(changed['fbxSettings']['globalScale'],0.01)
        self.assertTrue(changed['clips'][0]['settings']['loopTime'])

    def test_preset_invalid_event_is_atomic(self):
        asset=self.animation();data=clips.document(asset);preset=clips.builtin_presets()['待机循环']
        preset['clipSettings']['events']=[{'frame':999,'function':'Footstep'}];before=copy.deepcopy(data)
        with self.assertRaises(ValueError):clips.apply_preset(data,asset,data['clips'][0]['id'],preset)
        self.assertEqual(data,before)
        preset['clipSettings']['firstFrame']=100
        with self.assertRaises(ValueError):clips.save_preset(self.library,'Bad',preset)

    def test_fbx_config_survives_animation_save(self):
        old=self.animation();data=clips.document(old);data['fbxSettings']['globalScale']=0.1
        clips.save(self.library,old,data);new=self.animation();self.library.mark_superseded(old,new)
        self.assertEqual(clips.load(self.library,new)['fbxSettings'],data['fbxSettings'])

    def test_fbx_field_coverage(self):
        from ui import fbx_settings
        schema=fbx_settings.SCHEMA
        self.assertEqual(set(clips.fbx_defaults()),{f['name'] for f in schema['importer']}|{'materialRemaps','extensions'})
        self.assertEqual(set(clips.defaults()),{f['name'] for f in schema['clip']}-fbx_settings.PROTECTED|{'transformMask','extensions'})

if __name__=='__main__':unittest.main()
