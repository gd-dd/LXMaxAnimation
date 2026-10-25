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


def selected_hierarchy():
    found = {}
    def visit(node):
        handle = int(rt.getHandleByAnim(node))
        if handle in found:return
        found[handle]=node
        for child in node.children:visit(child)
    for node in rt.selection:visit(node)
    if not found:raise ValueError('请先选择角色根节点或完整角色。')
    names = [str(n.name) for n in found.values()]
    if len(names) != len(set(n.casefold() for n in names)):
        raise ValueError('选择集中存在重名节点，请先修正骨骼命名。')
    return list(found.values())


def rows(matrix):
    return [[float(matrix[row][i]) for i in range(3)] for row in range(4)]


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
    data={'schema':1,'frame':float(rt.sliderTime),'rig':rig,'nodes':[]}
    for node in nodes:
        parent=node.parent
        local=node.transform * rt.inverse(parent.transform) if parent else node.transform
        data['nodes'].append({'name':str(node.name),'parent':str(parent.name) if parent else None,'local':rows(local)})
    write_json(destination,data)


def apply_pose(path, rig='Generic'):
    data=json.loads(Path(path).read_text('utf-8'))
    if data.get('schema')!=1 or not data.get('nodes'):raise ValueError('Invalid pose file')
    if data.get('rig','Generic')!=rig:raise ValueError('选择的骨骼类型与 Pose 不一致。')
    if rig=='CAT':
        root=rig_root(selected_hierarchy(),rig)
        native=Path(path).parent/'pose.pse'
        if not native.is_file():raise ValueError('CAT 原生 Pose 文件缺失。')
        with pymxs.undo(True,'LXMaxAnimation CAT Pose'):
            root.CATMode=1
            root.LoadPose(str(native),rt.sliderTime)
        return {'ok':True,'message':'CAT Pose 已加载到当前帧的独立层。'}
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
        is_biped='biped' in str(rt.classOf(node)).lower()
        if is_biped and rig!='Biped':raise ValueError('目标是 Biped，请选择 Biped 模式。')
        if rt.isProperty(node.controller,'CATParent'):raise ValueError('目标是 CAT，请选择 CAT 模式。')
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
        for name in ordered:
            node=scene[name][0]; local=matrix(records[name]['local'])
            world=local * node.parent.transform if node.parent else local
            if 'biped' in str(rt.classOf(node)).lower():
                rt.biped.setTransform(node,rt.Name('rotation'),world.rotationPart,True)
                rt.biped.setTransform(node,rt.Name('pos'),world.translationPart,True)
            else:node.transform=world
    return {'ok':True,'message':f'Pose 已应用到当前帧：{len(ordered)} 个节点。'}


def param(export,name,value=None):
    fn=rt.FBXExporterSetParam if export else rt.FBXImporterSetParam
    result=fn(name) if value is None else fn(name,value)
    if str(result).lower()=='unsupplied':raise ValueError('FBX 插件不支持参数：'+name)


def export_asset(args):
    nodes=selected_hierarchy(); kind=args['kind']
    rig=args.get('rig','Generic')
    if rig not in ('Generic','Biped','CAT'):raise ValueError('Unknown rig type')
    root=rig_root(nodes,rig)
    if rig=='CAT':
        for node in root.CATRigNodes:
            if node not in nodes:nodes.append(node)
    elif rig=='Biped':
        def include(node):
            if node not in nodes:nodes.append(node)
            for child in node.children:include(child)
        include(root)
    folder=Path(args['directory']).resolve()
    # Export destinations are fresh local staging folders, never existing scenes.
    if not folder.is_dir() or any(folder.iterdir()):raise ValueError('导出临时目录必须存在且为空。')
    if kind=='pose':
        if rig=='CAT' and not root.SavePose(str(folder/'pose.pse')):raise RuntimeError('CAT Pose 保存失败。')
        export_pose(nodes,folder/'pose.json',rig)
        return {'ok':True,'main':'pose.json','metadata':{'rig':rig,'frame':float(rt.sliderTime),'nodes':len(nodes)}}
    if kind not in ('model','animation'):raise ValueError('Unknown asset kind')
    old_selection=list(rt.selection); old_time=rt.sliderTime
    textures=[]; missing=[]
    try:
        rt.select(nodes)
        # Native selection keeps the rig/controllers for later manual scene recovery.
        rt.saveNodes(nodes,str(folder/'source.max'),quiet=True)
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
            param(True,'EmbedTextures',kind=='model')
            if kind=='animation':
                start,end=int(args['start']),int(args['end'])
                if start>end:raise ValueError('Invalid animation range')
                param(True,'BakeAnimation',True)
                param(True,'BakeFrameStart',start);param(True,'BakeFrameEnd',end);param(True,'BakeFrameStep',1)
            rt.exportFile(str(folder/'asset.fbx'),rt.Name('noPrompt'),selectedOnly=True,using=rt.FBXEXP)
        finally:param(True,'PopSettings')
        if kind=='model':
            bitmaps={}
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
            export_pose(nodes,folder/'tpose.json',rig)
            if rig=='CAT' and not root.SavePose(str(folder/'pose.pse')):raise RuntimeError('CAT T-pose 保存失败。')
        if missing:raise ValueError('贴图缺失，尚未归档：'+', '.join(missing))
        if not (folder/'asset.fbx').is_file() or (folder/'asset.fbx').stat().st_size==0:raise RuntimeError('FBX 导出未生成文件。')
        return {'ok':True,'main':'asset.fbx','metadata':{'rig':rig,'fps':int(rt.frameRate),'start':args.get('start'),'end':args.get('end'),'nodes':[str(n.name) for n in nodes],'frame':float(old_time)}}
    finally:
        rt.sliderTime=old_time
        rt.select(old_selection)


def import_asset(args):
    path=Path(args['path'])
    rig=args.get('rig','Generic')
    if not path.is_file():raise ValueError('资产文件不存在。')
    if args['kind']=='pose':return apply_pose(path,rig)
    if path.suffix.lower()!='.fbx':raise ValueError('Expected FBX')
    if args['kind']=='animation' and rig in ('Biped','CAT'):
        root=rig_root(selected_hierarchy(),rig)
        native=path.parent/('animation.bip' if rig=='Biped' else 'animation.clp')
        if not native.is_file():raise ValueError('此条目缺少 '+rig+' 原生动画，请在正确骨骼模式下重新保存。')
        with pymxs.undo(True,'LXMaxAnimation '+rig):
            if rig=='Biped':rt.biped.loadBipFile(root.controller,str(native))
            else:
                root.CATMode=1
                root.LoadClip(str(native),rt.sliderTime)
        return {'ok':True,'message':rig+' 原生动画已导入。'}
    if args['kind']=='model' and (path.parent/'source.max').is_file():
        source=path.parent/'source.max'
        names=[str(x) for x in rt.getMAXFileObjectNames(str(source))]
        existing={str(n.name) for n in rt.objects}
        if existing.intersection(names):raise ValueError('场景已有同名角色节点，请换空场景或先重命名现有角色。')
        if not rt.mergeMAXFile(str(source),rt.Name('noRedraw'),rt.Name('select')):raise RuntimeError('Max 模型合并失败。')
        textures=path.parent/'textures.json'
        if textures.is_file():
            mapping={x['source']:str(path.parent/x['file']) for x in json.loads(textures.read_text('utf-8'))['textures']}
            for node in rt.selection:
                for bitmap in rt.getClassInstances(rt.Bitmaptexture,target=node):
                    if str(bitmap.filename) in mapping:bitmap.filename=mapping[str(bitmap.filename)]
        tpose=path.parent/'tpose.json'
        if tpose.is_file():
            saved_rig=json.loads(tpose.read_text('utf-8')).get('rig','Generic')
            apply_pose(tpose,saved_rig)
        return {'ok':True,'message':'原生模型、贴图和骨骼已合并到当前场景。'}
    rt.pluginManager.loadClass(rt.FBXIMP)
    param(False,'PushSettings')
    try:
        param(False,'ResetImport')
        param(False,'Mode',rt.Name('exmerge' if args['kind']=='animation' else 'create'))
        param(False,'Animation',args['kind']=='animation')
        param(False,'Cameras',False);param(False,'Lights',False)
        param(False,'KeepFrameRate',True)
        if args['kind']=='animation':
            meta=path.parent/'asset.json'
            names=json.loads(meta.read_text('utf-8')).get('metadata',{}).get('nodes',[]) if meta.exists() else []
            if not names:raise ValueError('外部 FBX 无节点映射，请先在 Max 手动导入检查，再从工具保存动画以便安全回灌。')
            existing=[str(n.name) for n in rt.objects]
            bad=[name for name in names if existing.count(name)!=1]
            if bad:raise ValueError('目标场景节点缺失或重名：'+', '.join(bad))
        with pymxs.undo(True,'LXMaxAnimation FBX'):
            rt.importFile(str(path),rt.Name('noPrompt'),using=rt.FBXIMP)
        return {'ok':True,'message':'FBX 已导入当前 Max 场景。'}
    finally:param(False,'PopSettings')


class Bridge:
    def __init__(self):
        self.root=Path(os.environ['LOCALAPPDATA'])/'LXMaxAnimation/sessions'/(str(os.getpid())+'-'+uuid.uuid4().hex[:8])
        self.root.mkdir(parents=True)
        self.busy=False
        self.timer=QTimer();self.timer.setInterval(750);self.timer.timeout.connect(self.tick);self.timer.start()
        self.tick()
    def stop(self):
        self.timer.stop();(self.root/'info.json').unlink(missing_ok=True)
    def tick(self):
        if self.busy:return
        self.busy=True
        try:
            write_json(self.root/'info.json',{'pid':os.getpid(),'scene':str(rt.maxFilePath)+str(rt.maxFileName),'version':str(rt.maxVersion()[0])})
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
