"""Max-side adapter. All scene operations run on Max's GUI thread."""
import json
import os
from pathlib import Path
import time
import uuid
import shutil
import hashlib
import builtins
from pymxs import runtime as rt
import pymxs
try:
    from PySide6.QtCore import QTimer
except ImportError:
    from PySide2.QtCore import QTimer


def write_json(path, data):
    path = Path(path)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temp,path)


def selected_hierarchy(names=None, include_skin=False):
    found = {}
    def visit(node):
        handle = int(rt.getHandleByAnim(node))
        if handle in found:return
        found[handle]=node
        for child in node.children:visit(child)
    if names:
        scene={}
        for node in rt.objects:scene.setdefault(str(node.name),[]).append(node)
        for name in names:
            if len(scene.get(name,[]))!=1:raise ValueError('当前场景角色节点缺失或重名：'+name)
            visit(scene[name][0])
    else:
        for node in rt.selection:visit(node)
    if include_skin:
        bone_names={str(node.name) for node in found.values()}
        for node in rt.geometry:
            for modifier in node.modifiers:
                if str(rt.classOf(modifier))=='Skin':
                    used={str(rt.skinOps.GetBoneName(modifier,i,0)) for i in range(1,int(rt.skinOps.GetNumberBones(modifier))+1)}
                    if used & bone_names:
                        if used-bone_names:raise ValueError('蒙皮模型引用了选择范围外的骨骼，请选择完整角色：'+str(node.name))
                        visit(node)
    if not found:raise ValueError('请先选择角色根节点或完整角色。')
    names = [str(n.name) for n in found.values()]
    if len(names) != len(set(n.casefold() for n in names)):
        raise ValueError('选择集中存在重名节点，请先修正骨骼命名。')
    return list(found.values())


def rows(matrix):
    return [[float(matrix[row][i]) for i in range(3)] for row in range(4)]


def scene_signature(nodes):
    result=[];seen=set()
    for node in nodes:
        name=str(node.name)
        if name.casefold() in seen:raise ValueError('场景存在重名对象：'+name)
        seen.add(name.casefold())
        result.append({'name':name,'parent':str(node.parent.name) if node.parent else None,
                       'class':str(rt.classOf(node)),
                       'modifiers':[str(rt.classOf(m)) for m in node.modifiers],
                       'customAttributes':int(rt.custAttributes.count(node))})
    return sorted(result,key=lambda item:item['name'])


def validate_scene(nodes,expected):
    actual=scene_signature(nodes);current={item['name']:item for item in actual};target={item['name']:item for item in expected}
    extra=sorted(set(current)-set(target));missing=sorted(set(target)-set(current))
    changed=sorted(name for name in set(current)&set(target) if current[name]!=target[name])
    errors=[]
    if extra:errors.append('多出对象：'+', '.join(extra))
    if missing:errors.append('缺少对象：'+', '.join(missing))
    if changed:errors.append('类型 / 层级 / 修改器结构不一致：'+', '.join(changed))
    if errors:raise ValueError('保存失败，当前场景与角色不一致。\n'+'\n'.join(errors))
    return actual


def selected_role():
    nodes=list(rt.selection)
    if not nodes:raise ValueError('请选中全部角色内容，包括模型、骨骼、独立控制器和辅助节点。')
    scene_signature(nodes);names={str(n.name) for n in nodes}
    for node in nodes:
        if node.parent and str(node.parent.name) not in names:raise ValueError('角色选择不完整，缺少父节点：'+str(node.parent.name))
        for modifier in node.modifiers:
            if str(rt.classOf(modifier))=='Skin':
                used={str(rt.skinOps.GetBoneName(modifier,i,0)) for i in range(1,int(rt.skinOps.GetNumberBones(modifier))+1)}
                if used-names:raise ValueError('角色选择不完整，缺少蒙皮骨骼：'+', '.join(sorted(used-names)))
    return nodes


def matrix(value):
    if len(value)!=4 or any(len(row)!=3 for row in value):raise ValueError('Invalid transform matrix')
    return rt.matrix3(*(rt.point3(*row) for row in value))


def rig_root(nodes, rig):
    roots={}
    for node in nodes:
        if rig=='CAT':
            root=node if str(rt.classOf(node))=='CATParent' else (node.controller.CATParent if rt.isProperty(node.controller,'CATParent') else None)
        elif rig=='Biped':
            root=node
            if 'biped' not in str(rt.classOf(node)).lower():continue
            while root.parent and 'biped' in str(rt.classOf(root.parent)).lower():root=root.parent
        else:return None
        if root:roots[int(rt.getHandleByAnim(root))]=root
    if len(roots)!=1:raise ValueError('请选择且仅选择一个 '+rig+' 角色（根节点或骨骼）。')
    return next(iter(roots.values()))


def export_pose(nodes, destination, rig='Generic'):
    data={'schema':1,'frame':float(rt.sliderTime),'rig':rig,'nodes':[],'signature':scene_signature(nodes)}
    for node in nodes:
        parent=node.parent
        local=node.transform * rt.inverse(parent.transform) if parent else node.transform
        data['nodes'].append({'name':str(node.name),'parent':str(parent.name) if parent else None,'local':rows(local),'tracks':capture_tracks(node)})
    write_json(destination,data)


def capture_tracks(node):
    tracks=[]
    def visit(obj,path,labels,depth):
        if depth>12:return
        try:count=int(obj.numSubs)
        except Exception:return
        for i in range(1,count+1):
            sub=rt.getSubAnim(obj,i);label=str(rt.getSubAnimName(obj,i))
            if 'material' in label.lower():continue
            current=path+[i];names=labels+[label]
            try:
                ctrl=sub.controller;cls=str(rt.classOf(ctrl)) if ctrl else ''
                # Procedural and constraint outputs are driven by their controls;
                # write only key-based scalar tracks, preserving their controllers.
                if cls.lower() in ('bezier_float','linear_float','tcb_float','boolean_controller'):
                    value=sub.value
                    if isinstance(value,(float,int,bool)):
                        tracks.append({'path':current,'labels':names,'controller':cls,'value':value})
            except Exception:pass
            visit(sub,current,names,depth+1)
    visit(node,[],[],0)
    for index in range(1,int(rt.custAttributes.count(node))+1):
        before=len(tracks)
        visit(rt.custAttributes.get(node,index),[],[],0)
        for track in tracks[before:]:track['attribute']=index
    return tracks


def resolve_track(node,record):
    sub=rt.custAttributes.get(node,record['attribute']) if record.get('attribute') else node
    for index,label in zip(record['path'],record['labels']):
        if str(rt.getSubAnimName(sub,index))!=label:raise ValueError('控制器轨道结构不匹配：'+str(node.name))
        sub=rt.getSubAnim(sub,index)
    if str(rt.classOf(sub.controller))!=record['controller']:raise ValueError('控制器类型不匹配：'+str(node.name))
    return sub


def apply_pose(path, rig='Generic'):
    data=json.loads(Path(path).read_text('utf-8'))
    if data.get('schema')!=1 or not data.get('nodes'):raise ValueError('Invalid pose file')
    if data.get('rig','Generic')!=rig:raise ValueError('选择的骨骼类型与 Pose 不一致。')
    if data.get('signature'):validate_scene(list(rt.objects),data['signature'])
    scene={}
    for node in rt.objects:scene.setdefault(str(node.name),[]).append(node)
    records={record['name']:record for record in data['nodes']}
    if len(records)!=len(data['nodes']):raise ValueError('Pose contains duplicate names')
    for name,record in records.items():
        if len(scene.get(name,[]))!=1:raise ValueError('节点缺失或重名：'+name)
        node=scene[name][0]
        if (str(node.parent.name) if node.parent else None)!=record['parent']:
            raise ValueError('父子层级不匹配：'+name)
        matrix(record['local'])
        for track in record.get('tracks',[]):resolve_track(node,track)
        is_biped='biped' in str(rt.classOf(node)).lower()
        if is_biped and rig!='Biped':raise ValueError('目标是 Biped，请选择 Biped 模式。')
        if rt.isProperty(node.controller,'CATParent') and rig!='CAT':raise ValueError('目标是 CAT，请选择 CAT 模式。')
    ordered=[]; visiting=set()
    def add(name):
        if name in ordered:return
        if name in visiting:raise ValueError('Pose contains a hierarchy cycle')
        visiting.add(name)
        parent=records[name]['parent']
        if parent in records:add(parent)
        ordered.append(name)
    for name in records:add(name)
    with pymxs.undo(True,'LXMaxAnimation Pose'),pymxs.animate(True):
        if rig=='CAT':
            cat=rig_root([scene[name][0] for name in records],rig)
            if int(cat.NumLayers)<1:cat.AppendLayer('LX Pose',rt.Name('Absolute'))
            cat.CATMode=1
        for name in ordered:
            node=scene[name][0]; local=matrix(records[name]['local'])
            world=local * node.parent.transform if node.parent else local
            if 'biped' in str(rt.classOf(node)).lower():
                rt.biped.setTransform(node,rt.Name('rotation'),world.rotationPart,True)
                rt.biped.setTransform(node,rt.Name('pos'),world.translationPart,True)
            else:
                node.transform=world
                if rig!='CAT':rt.addNewKey(node.controller,rt.sliderTime)
        for name in ordered:
            for track in records[name].get('tracks',[]):
                sub=resolve_track(scene[name][0],track);sub.value=track['value']
                rt.addNewKey(sub.controller,rt.sliderTime)
    return {'ok':True,'message':f'Pose 已应用到当前帧：{len(ordered)} 个节点。'}


def param(export,name,value=None):
    fn=rt.FBXExporterSetParam if export else rt.FBXImporterSetParam
    result=fn(name) if value is None else fn(name,value)
    if str(result).lower()=='unsupplied':raise ValueError('FBX 插件不支持参数：'+name)


def export_asset(args):
    kind=args['kind']
    if args.get('expected') is not None:
        nodes=list(rt.objects);validate_scene(nodes,args['expected'])
    elif kind=='model' and args.get('strictSelection'):
        nodes=selected_role()
    else:nodes=selected_hierarchy(args.get('nodes'), include_skin=kind=='model')
    if kind=='animation' and args.get('sceneRange',False):
        args=dict(args,start=float(rt.animationRange.start),end=float(rt.animationRange.end))
    rig=args.get('rig','Generic')
    if rig not in ('Generic','Biped','CAT'):raise ValueError('Unknown rig type')
    root=rig_root(nodes,rig)
    if rig=='CAT' and not (args.get('strictSelection') or args.get('expected') is not None):
        for node in root.CATRigNodes:
            if node not in nodes:nodes.append(node)
    elif rig=='Biped' and not (args.get('strictSelection') or args.get('expected') is not None):
        def include(node):
            if node not in nodes:nodes.append(node)
            for child in node.children:include(child)
        include(root)
    folder=Path(args['directory']).resolve()
    # Export destinations are fresh local staging folders, never existing scenes.
    if not folder.is_dir() or any(folder.iterdir()):raise ValueError('导出临时目录必须存在且为空。')
    warnings=[]
    if kind=='model' and args.get('captureAvatar',False):
        try:
            bitmap=rt.gw.getViewportDib()
            bitmap.filename=str(folder/'avatar.png')
            rt.save(bitmap);rt.close(bitmap)
        except Exception as exc:warnings.append('视口截图失败，可手动设置头像：'+str(exc))
    if kind=='pose':
        if rig=='CAT' and not root.SavePose(str(folder/'pose.pse')):raise RuntimeError('CAT Pose 保存失败。')
        export_pose(nodes,folder/'pose.json',rig)
        return {'ok':True,'main':'pose.json','metadata':{'rig':rig,'frame':float(rt.sliderTime),'nodes':[str(n.name) for n in nodes],'signature':scene_signature(nodes)}}
    if kind not in ('model','animation'):raise ValueError('Unknown asset kind')
    old_selection=list(rt.selection); old_time=rt.sliderTime
    textures=[]; missing=[]
    try:
        rt.select(nodes)
        # Native scene data preserves the complete rig and controllers.
        if kind=='animation':
            if not rt.saveMaxFile(str(folder/'source.max'),useNewFile=False,clearNeedSaveFlag=False,quiet=True):raise RuntimeError('完整 Max 场景保存失败。')
        else:
            if not rt.saveNodes(nodes,str(folder/'source.max'),quiet=True):raise RuntimeError('角色场景保存失败。')
        if kind=='animation' and rig=='Biped':
            rt.biped.saveBipFileSegment(root.controller,str(folder/'animation.bip'),int(args['start']),int(args['end']),rt.Name('keyPerFrame'))
        if kind=='animation' and rig=='CAT':
            if int(root.NumLayers)<1:raise ValueError('CAT 没有动画层。请在 Animation 模式创建动画后保存。')
            if not root.SaveClip(str(folder/'animation.clp'),int(args['start']),int(args['end']),1,int(root.NumLayers)):
                raise RuntimeError('CAT Clip 保存失败。')
        rt.pluginManager.loadClass(rt.FBXEXP)
        param(True,'PushSettings')
        try:
            param(True,'ResetExport')
            param(True,'Animation',kind=='animation')
            param(True,'Skin',True)
            param(True,'Cameras',False);param(True,'Lights',False)
            param(True,'EmbedTextures',args.get('includeTextures',False))
            if kind=='animation':
                start,end=int(args['start']),int(args['end'])
                if start>end:raise ValueError('Invalid animation range')
                param(True,'BakeAnimation',True)
                param(True,'BakeFrameStart',start);param(True,'BakeFrameEnd',end);param(True,'BakeFrameStep',1)
            rt.exportFile(str(folder/'asset.fbx'),rt.Name('noPrompt'),selectedOnly=True,using=rt.FBXEXP)
        finally:param(True,'PopSettings')
        bitmaps={}
        if args.get('includeTextures',False):
            for node in nodes:
                for bitmap in rt.getClassInstances(rt.Bitmaptexture,target=node):
                    bitmaps[int(rt.getHandleByAnim(bitmap))]=bitmap
        for bitmap in bitmaps.values():
            original=str(bitmap.filename)
            file=Path(original)
            if not file.is_file():
                resolved=str(rt.mapPaths.getFullFilePath(original))
                file=Path(resolved)
            if not file.is_file():missing.append(original);continue
            suffix=hashlib.sha256(str(file.resolve()).encode()).hexdigest()[:8]
            dest=folder/'textures'/(file.stem+'-'+suffix+file.suffix)
            dest.parent.mkdir(exist_ok=True);shutil.copy2(file,dest)
            textures.append({'source':original,'file':dest.relative_to(folder).as_posix()})
        write_json(folder/'textures.json',{'textures':textures,'missing':missing})
        if kind=='model':
            export_pose(nodes,folder/'tpose.json',rig)
            if rig=='CAT' and not root.SavePose(str(folder/'pose.pse')):raise RuntimeError('CAT T-pose 保存失败。')
        if missing:warnings.append('以下贴图缺失，未复制：'+', '.join(missing))
        if not (folder/'asset.fbx').is_file() or (folder/'asset.fbx').stat().st_size==0:raise RuntimeError('FBX 导出未生成文件。')
        return {'ok':True,'main':'asset.fbx','warnings':warnings,'metadata':{'rig':rig,'fps':int(rt.frameRate),'start':args.get('start'),'end':args.get('end'),'nodes':[str(n.name) for n in nodes],'signature':scene_signature(nodes),'frame':float(old_time),'scene':str(rt.maxFilePath)+str(rt.maxFileName),'includeTextures':bool(args.get('includeTextures',False)),'warnings':warnings}}
    finally:
        rt.sliderTime=old_time
        rt.select(old_selection)


def import_asset(args):
    path=Path(args['path'])
    rig=args.get('rig','Generic')
    if not path.is_file():raise ValueError('资产文件不存在。')
    if args['kind']=='pose':return apply_pose(path,rig)
    if path.suffix.lower()!='.fbx':raise ValueError('Expected FBX')
    if args['kind'] in ('animation','model') and (path.parent/'source.max').is_file():
        source=path.parent/'source.max'
        if not source.is_file():raise ValueError('此动画没有 Max 场景快照，请从 Max 重新导入。')
        # Open a working copy so Ctrl+S cannot overwrite an immutable library revision.
        working_root=Path(os.environ['LOCALAPPDATA'])/'LXMaxAnimation/working-scenes';working_root.mkdir(parents=True,exist_ok=True)
        working=working_root/(uuid.uuid4().hex+'.max');shutil.copy2(source,working)
        if not rt.loadMaxFile(str(working),quiet=True):raise RuntimeError('动画场景加载失败。')
        textures=path.parent/'textures.json'
        if textures.is_file():
            mapping={}
            for item in json.loads(textures.read_text('utf-8'))['textures']:
                original=(path.parent/item['file']).resolve()
                if not original.is_relative_to(path.parent.resolve()) or not original.is_file():raise ValueError('贴图路径无效。')
                target=working_root/working.stem/original.name;target.parent.mkdir(exist_ok=True)
                shutil.copy2(original,target);mapping[item['source']]=str(target)
            for bitmap in rt.getClassInstances(rt.Bitmaptexture):
                if str(bitmap.filename) in mapping:bitmap.filename=mapping[str(bitmap.filename)]
            rt.saveMaxFile(str(working),quiet=True)
        return {'ok':True,'working':str(working),'message':'已打开角色工作场景；编辑与保存只影响工作副本。' if args['kind']=='model' else '已替换当前 Max 场景；编辑与保存只影响工作副本。'}
    raise ValueError('此资产没有原生 Max 场景，请从 Max 重新导入。')


class Bridge:
    def __init__(self):
        self.root=Path(os.environ['LOCALAPPDATA'])/'LXMaxAnimation/sessions'/(str(os.getpid())+'-'+uuid.uuid4().hex[:8])
        self.root.mkdir(parents=True)
        import ctypes
        from ctypes import wintypes as W
        kernel=ctypes.WinDLL('kernel32')
        kernel.GetCurrentProcess.restype=W.HANDLE
        kernel.GetProcessTimes.argtypes=[W.HANDLE,ctypes.POINTER(W.FILETIME),ctypes.POINTER(W.FILETIME),ctypes.POINTER(W.FILETIME),ctypes.POINTER(W.FILETIME)]
        created,exited,cpu,user=(W.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(kernel.GetCurrentProcess(),ctypes.byref(created),ctypes.byref(exited),ctypes.byref(cpu),ctypes.byref(user)):raise RuntimeError('Cannot read Max process identity')
        self.birth=str((created.dwHighDateTime<<32)|created.dwLowDateTime)
        self.busy=False
        self.timer=QTimer();self.timer.setInterval(750);self.timer.timeout.connect(self.tick);self.timer.start()
        self.tick()
    def stop(self):
        self.timer.stop();(self.root/'info.json').unlink(missing_ok=True)
    def tick(self):
        if self.busy:return
        self.busy=True
        try:
            write_json(self.root/'info.json',{'protocol':2,'pid':os.getpid(),'birth':self.birth,'scene':str(rt.maxFilePath)+str(rt.maxFileName),'version':str(rt.maxVersion()[0]),'frame':float(rt.sliderTime),'start':float(rt.animationRange.start),'end':float(rt.animationRange.end),'fps':int(rt.frameRate),'selection':[str(n.name) for n in rt.selection]})
            for path in self.root.glob('*.request.json'):
                working=path.with_suffix('.working');path.rename(working)
                try:
                    data=json.loads(working.read_text('utf-8'))
                    if data['expires']<time.time():raise ValueError('请求已过期，未执行。')
                    action=data['action']
                    if action=='export':result=export_asset(data['args'])
                    elif action=='import':result=import_asset(data['args'])
                    else:raise ValueError('Unknown action')
                except Exception as exc:result={'ok':False,'message':str(exc)}
                write_json(path.with_name(path.name.replace('.request.json','.result.json')),result)
                working.unlink()
        finally:self.busy=False


if hasattr(builtins,'_lx_animation_bridge'):builtins._lx_animation_bridge.stop()
builtins._lx_animation_bridge=Bridge()
print('LXMaxAnimation connected. PID',os.getpid())
