"""Isolated batch integration checks for native Biped and CAT formats."""
from pathlib import Path
import runpy,json,traceback,uuid
from pymxs import runtime as rt
import pymxs
root=Path(__file__).resolve().parents[1]
output=root/'local-data'/('rigs-'+uuid.uuid4().hex[:8]);output.mkdir(parents=True)
bridge=runpy.run_path(str(root/'max/bridge.py'))
report={}
for rig in ['Biped','CAT']:
    try:
        rt.resetMaxFile(rt.Name('noPrompt'))
        if rig=='Biped':
            node=rt.biped.createNew(100,0,rt.point3(0,0,0))
            node.controller.figureMode=False
            with pymxs.animate(True):
                with pymxs.attime(0):rt.biped.setTransform(node,rt.Name('pos'),rt.point3(0,0,50),True)
                with pymxs.attime(10):rt.biped.setTransform(node,rt.Name('pos'),rt.point3(20,0,50),True)
        else:
            node=rt.CATParent()
            node.AddHub()
            node.AppendLayer('Base',rt.Name('Absolute'))
            node.CATMode=1
            hub=node.RootHub.node
            with pymxs.animate(True):
                with pymxs.attime(0):hub.position=rt.point3(0,0,50)
                with pymxs.attime(10):hub.position=rt.point3(20,0,50)
        rt.select(list(rt.objects));rt.sliderTime=5
        signature=bridge['scene_signature'](list(rt.objects))
        rt.clearSelection()
        target=node if rig=='Biped' else hub
        expected=[float(target.transform[3][i]) for i in range(3)]
        pose=output/(rig+'-pose');pose.mkdir()
        saved=bridge['export_asset']({'kind':'pose','rig':rig,'directory':str(pose),'expected':signature})
        rt.sliderTime=20
        loaded=bridge['apply_pose'](pose/'pose.json',rig)
        actual=[float(target.transform[3][i]) for i in range(3)]
        assert max(abs(a-b) for a,b in zip(expected,actual))<0.1,(rig,expected,actual)
        assert float(rt.sliderTime)==20
        assert bridge['scene_signature'](list(rt.objects))==signature
        anim=output/(rig+'-anim');anim.mkdir()
        rt.clearSelection()
        exported=bridge['export_asset']({'kind':'animation','rig':rig,'directory':str(anim),'start':0,'end':10,'expected':signature})
        rt.select(node)
        imported=bridge['import_asset']({'kind':'animation','rig':rig,'path':str(anim/'asset.fbx')})
        report[rig]={'ok':True,'pose':loaded,'animation':imported}
    except Exception:report[rig]={'ok':False,'error':traceback.format_exc()}
(root/'local-data/max-rigs-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
