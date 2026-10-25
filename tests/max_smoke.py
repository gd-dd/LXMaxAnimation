"""Run only in an isolated 3dsmaxbatch process; creates a synthetic scene."""
from pathlib import Path
import json
import runpy
import traceback
import uuid
from pymxs import runtime as rt
import pymxs

root=Path(__file__).resolve().parents[1]
output=root/'local-data'/('max-smoke-'+uuid.uuid4().hex[:8]);output.mkdir(parents=True)
report={'ok':False,'output':str(output)}
try:
    bridge=runpy.run_path(str(root/'max/bridge.py'))
    rt.resetMaxFile(rt.Name('noPrompt'))
    parent=rt.Dummy(name='LX_TestRoot')
    child=rt.Box(name='LX_TestChild');child.parent=parent;child.position=rt.point3(0,0,10)
    rt.select(parent)
    with pymxs.animate(True):
        with pymxs.attime(0):parent.position=rt.point3(0,0,0)
        with pymxs.attime(10):parent.position=rt.point3(20,0,0)
    rt.sliderTime=5
    pose=output/'pose';pose.mkdir()
    bridge['export_asset']({'kind':'pose','directory':str(pose)})
    rt.sliderTime=20
    bridge['apply_pose'](pose/'pose.json')
    assert abs(float(parent.position.x)-10)<0.01, str(parent.position)
    assert int(rt.sliderTime)==20
    report['pose']='saved frame 5, applied frame 20; root x=10'
    rt.sliderTime=0
    model=output/'model';model.mkdir()
    report['model']=bridge['export_asset']({'kind':'model','directory':str(model),'start':0,'end':10})
    anim=output/'animation';anim.mkdir()
    report['animation']=bridge['export_asset']({'kind':'animation','directory':str(anim),'start':0,'end':10})
    (anim/'asset.json').write_text(json.dumps({'metadata':report['animation']['metadata']}),encoding='utf-8')
    rt.deleteKeys(parent.controller,rt.Name('allKeys'))
    parent.position=rt.point3(0,0,0)
    report['import_animation']=bridge['import_asset']({'kind':'animation','path':str(anim/'asset.fbx')})
    with pymxs.attime(10):assert abs(float(parent.position.x)-20)<0.01,str(parent.position)
    rt.resetMaxFile(rt.Name('noPrompt'))
    report['import_model']=bridge['import_asset']({'kind':'model','path':str(model/'asset.fbx')})
    assert len(list(rt.objects))>=2
    report['ok']=True
except Exception:
    report['error']=traceback.format_exc()
finally:
    (root/'local-data/max-smoke-result.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
