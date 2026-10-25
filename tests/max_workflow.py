"""Run with 3dsmaxbatch, never in a user's editing scene."""
from pathlib import Path
import runpy,json,traceback,uuid,hashlib
from pymxs import runtime as rt
import pymxs
root=Path(__file__).resolve().parents[1]
output=root/'local-data'/('workflow-'+uuid.uuid4().hex[:8]);output.mkdir(parents=True)
report={'ok':False,'output':str(output)}
try:
    bridge=runpy.run_path(str(root/'max/bridge.py'))
    rt.resetMaxFile(rt.Name('noPrompt'))
    parent=rt.Dummy(name='RoleRoot');mesh=rt.Box(name='RoleMesh');mesh.parent=parent
    control=rt.Circle(name='RoleControl')
    definition=rt.execute('attributes LXTestAttributes (parameters main (finger type:#float default:0 animatable:true))')
    rt.custAttributes.add(control,definition)
    rt.frameRate=24;rt.animationRange=rt.interval(2,12)
    with pymxs.animate(True):
        with pymxs.attime(2):control.pos=rt.point3(0,0,0);control.finger=0.0
        with pymxs.attime(12):control.pos=rt.point3(10,0,0);control.finger=100.0
    rt.sliderTime=7;rt.select([parent,mesh,control])
    model=output/'model';model.mkdir()
    captured=bridge['export_asset']({'kind':'model','rig':'Generic','strictSelection':True,'includeTextures':False,'captureAvatar':True,'directory':str(model)})
    signature=captured['metadata']['signature'];assert len(signature)==3
    assert not (model/'textures').exists()
    report['character']=captured
    # Optional textures must survive model and animation reload without pointing into the library.
    bitmap=rt.bitmap(2,2,color=rt.color(180,80,40));bitmap.filename=str(output/'original.png');rt.save(bitmap);rt.close(bitmap)
    material=rt.StandardMaterial();material.diffuseMap=rt.Bitmaptexture(filename=str(output/'original.png'));mesh.material=material
    textured=output/'textured';textured.mkdir()
    bridge['export_asset']({'kind':'model','rig':'Generic','strictSelection':True,'includeTextures':True,'directory':str(textured)})
    assert len(list((textured/'textures').iterdir()))==1
    rt.clearSelection()
    pose=output/'pose';pose.mkdir()
    import builtins,time
    session=builtins._lx_animation_bridge
    bridge['write_json'](session.root/'workflow.request.json',{'action':'export','expires':time.time()+60,
        'args':{'kind':'pose','rig':'Generic','expected':signature,'directory':str(pose)}})
    session.tick()
    assert json.loads((session.root/'workflow.result.json').read_text('utf-8'))['ok']
    assert json.loads((session.root/'info.json').read_text('utf-8'))['protocol']==2
    data=json.loads((pose/'pose.json').read_text('utf-8'));assert any(n.get('tracks') for n in data['nodes'])
    rt.sliderTime=10
    bridge['apply_pose'](pose/'pose.json')
    assert abs(float(control.finger)-50)<0.01,control.finger
    assert abs(float(control.pos.x)-5)<0.01
    assert float(rt.sliderTime)==10,float(rt.sliderTime)
    assert rt.getKeyIndex(rt.getPropertyController(control,'finger'),rt.sliderTime)>0
    report['pose']='No selection; custom control and position restored at current frame 10 with key'
    animation=output/'animation';animation.mkdir()
    result=bridge['export_asset']({'kind':'animation','rig':'Generic','sceneRange':True,'includeTextures':True,'expected':signature,'directory':str(animation)})
    assert result['metadata']['start']==2 and result['metadata']['end']==12 and result['metadata']['fps']==24
    before=hashlib.sha256((animation/'source.max').read_bytes()).hexdigest()
    extra=rt.Box(name='UnexpectedObject');failed=output/'rejected';failed.mkdir()
    try:bridge['export_asset']({'kind':'animation','rig':'Generic','expected':signature,'directory':str(failed)})
    except ValueError as exc:assert 'UnexpectedObject' in str(exc)
    else:raise AssertionError('Extra object accepted')
    assert not list(failed.iterdir())
    rt.delete(extra);rt.delete(control)
    try:bridge['export_asset']({'kind':'pose','rig':'Generic','expected':signature,'directory':str(failed)})
    except ValueError as exc:assert 'RoleControl' in str(exc)
    else:raise AssertionError('Missing control accepted')
    assert not list(failed.iterdir())
    rt.Box(name='MustDisappear')
    loaded=bridge['import_asset']({'kind':'animation','rig':'Generic','path':str(animation/'asset.fbx')})
    assert rt.getNodeByName('MustDisappear') is None
    assert rt.getNodeByName('RoleControl') is not None
    rt.Box(name='OnlyInWorkingCopy');rt.saveMaxFile(str(Path(str(rt.maxFilePath))/str(rt.maxFileName)),quiet=True)
    assert hashlib.sha256((animation/'source.max').read_bytes()).hexdigest()==before
    assert Path(loaded['working']).parent.name=='working-scenes'
    animation_map=rt.getNodeByName('RoleMesh').material.diffuseMap
    assert Path(str(animation_map.filename)).is_file()
    assert Path(str(animation_map.filename)).is_relative_to(Path(loaded['working']).parent)
    bridge['import_asset']({'kind':'model','rig':'Generic','path':str(textured/'asset.fbx')})
    assert Path(str(rt.getNodeByName('RoleMesh').material.diffuseMap.filename)).is_file()
    bridge['import_asset']({'kind':'model','rig':'Generic','path':str(model/'asset.fbx')})
    assert bridge['scene_signature'](list(rt.objects))==signature
    with pymxs.attime(7):assert abs(float(rt.getNodeByName('RoleControl').finger)-50)<0.01
    report.update(ok=True,animation=result,integrity='extra/missing rejected without output',isolation='Max save changes working scene only')
except Exception:report['error']=traceback.format_exc()
finally:
    (root/'local-data/workflow-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(report,ensure_ascii=False))
