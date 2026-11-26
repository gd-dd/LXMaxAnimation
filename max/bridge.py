"""Max-side adapter. All scene operations run on Max's GUI thread."""
import json
import math
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


def rig_roots(nodes, rig):
    roots={}
    for node in nodes:
        if rig=='CAT':
            root=node if str(rt.classOf(node))=='CATParent' else (node.controller.CATParent if rt.isProperty(node.controller,'CATParent') else None)
        elif rig=='Biped':
            root=node
            if 'biped' not in str(rt.classOf(node)).lower():continue
            while root.parent and 'biped' in str(rt.classOf(root.parent)).lower():root=root.parent
        if root:roots[int(rt.getHandleByAnim(root))]=root
    return list(roots.values())


def rig_root(nodes, rig):
    if rig not in ('Biped','CAT'):return None
    roots=rig_roots(nodes,rig)
    if len(roots)!=1:raise ValueError('请选择且仅选择一个 '+rig+' 角色（根节点或骨骼）。')
    return roots[0]


def pose_records(nodes):
    records=[]
    for node in nodes:
        parent=node.parent
        local=node.transform * rt.inverse(parent.transform) if parent else node.transform
        records.append({'name':str(node.name),'parent':str(parent.name) if parent else None,'local':rows(local),'tracks':capture_tracks(node)})
    return records


def export_pose(nodes,destination,rig='Generic'):
    write_json(destination,dict(schema=1,frame=float(rt.sliderTime),rig=rig,nodes=pose_records(nodes),
                                signature=scene_signature(nodes)))


def export_animation_keys(nodes,folder,rig,start,end):
    first=math.ceil(float(start))
    last=math.floor(float(end))
    if not nodes or last<first or (last-first+1)*len(nodes)>100000:
        return '动画场景已保存；此次范围过大或为空，未生成可打键轨道。'
    try:
        signature=scene_signature(nodes)
    except ValueError:
        return '动画场景已保存；对象名称重复，未生成可打键轨道。'
    frames=[]
    for frame in range(first,last+1):
        with pymxs.attime(frame):
            frames.append(pose_records(nodes))
    write_json(folder/'animation-keys.json',dict(schema=1,rig=rig,signature=signature,frames=frames))
    return ''



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


def prepare_pose(data,rig):
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
    return scene,ordered


def write_pose(scene,ordered,records,rig,frame,key):
    for name in ordered:
        node=scene[name][0]
        local=matrix(records[name]['local'])
        world=local * node.parent.transform if node.parent else local
        if 'biped' in str(rt.classOf(node)).lower():
            rt.biped.setTransform(node,rt.Name('rotation'),world.rotationPart,key)
            rt.biped.setTransform(node,rt.Name('pos'),world.translationPart,key)
        else:
            node.transform=world
            if key and rig!='CAT':rt.addNewKey(node.controller,frame)
    for name in ordered:
        for track in records[name].get('tracks',[]):
            sub=resolve_track(scene[name][0],track)
            sub.value=track['value']
            if key:rt.addNewKey(sub.controller,frame)


def apply_frames(data,frames,rig,key):
    scene,ordered=prepare_pose(data,rig)
    failure=None
    with pymxs.undo(True,'LXMaxAnimation Keyframes' if key else 'LXMaxAnimation Pose'),pymxs.animate(key):
        try:
            if key and rig=='CAT':
                cat=rig_root([scene[name][0] for name in ordered],rig)
                if int(cat.NumLayers)<1:cat.AppendLayer('LX Pose',rt.Name('Absolute'))
                cat.CATMode=1
            for frame,values in frames:
                records={record['name']:record for record in values}
                if len(records)!=len(values) or set(records)!=set(ordered):
                    raise ValueError('帧数据中的对象清单不一致。')
                with pymxs.attime(frame):
                    write_pose(scene,ordered,records,rig,frame,key)
        except BaseException as error:
            failure=error
            raise
    if failure is not None:
        raise failure


def apply_pose(path,rig='Generic',key=True):
    data=json.loads(Path(path).read_text('utf-8'))
    apply_frames(data,[(float(rt.sliderTime),data.get('nodes',[]))],rig,key)
    return {'ok':True,'message':'已打键到当前帧。' if key else '已读取 Pose。'}


def apply_animation(path,rig,start,end):
    data=json.loads(Path(path).read_text('utf8'))
    frames=data.get('frames',[])
    steps=len(frames)-1
    start,end=float(start),float(end)
    if not frames or not math.isfinite(start) or not math.isfinite(end) or end<start or (steps and end==start):
        raise ValueError('请选择有效的目标帧段。')
    targets=[(start+(end-start)*index/max(steps,1),values) for index,values in enumerate(frames)]
    apply_frames(dict(data,nodes=frames[0]),targets,rig,True)
    return {'ok':True,'message':f'已将动画打键到 {start:g}–{end:g} 帧。'}


def native_frame_type(cls):
    if 'biped' in cls:
        return 'Biped'
    if cls in ('catparent','catbone','hubobject'):
        return 'CAT'
    return None


def frame_node_type(node):
    cls=str(rt.classOf(node)).casefold()
    native=native_frame_type(cls)
    if native:
        return native
    if rt.isProperty(node.controller,'CATParent'):
        return 'CAT'
    if cls in ('bone','bonegeometry'):
        return 'bone'
    return str(rt.superClassOf(node)).casefold()


def frame_receivers(records,signature,rig):
    scene={}
    for node in rt.objects:
        scene.setdefault(str(node.name).casefold(),[]).append(node)
    source={item['name']:item for item in signature}
    required_rigs={native_frame_type(item['class'].casefold()) for name,item in source.items()
                   if name in records and item['class'].casefold()!='catparent'}-{None}
    matched_rigs=set()
    geometry=None
    matched,skipped={},[]
    for name,record in records.items():
        candidates=scene.get(name.casefold(),())
        if len(candidates)!=1:
            skipped.append(f'{name}（{"缺少" if not candidates else "重名"}）')
            continue
        node=candidates[0]
        parent=str(node.parent.name).casefold() if node.parent else None
        expected_parent=record['parent'].casefold() if record['parent'] is not None else None
        if parent!=expected_parent or (parent is not None and len(scene.get(parent,()))!=1):
            skipped.append(f'{name}（父节点不匹配）')
            continue
        kind=frame_node_type(node)
        original=source.get(name,{})
        # Older complete scenes used a single export label even for mixed rigs.
        # Trust a matching per-node class before falling back to a legacy label.
        if kind in ('Biped','CAT') and not original and kind!=rig:
            skipped.append(f'{name}（骨架类型不匹配）')
            continue
        cls=str(rt.classOf(node)).casefold()
        source_class=original.get('class',cls).casefold()
        compatible=cls==source_class
        if not compatible and kind=='geometryclass':
            if geometry is None:
                geometry={str(value).casefold() for value in rt.GeometryClass.classes}
                geometry.difference_update(('bone','bonegeometry'))
            compatible=source_class in geometry and 'biped' not in source_class and not source_class.startswith('cat')
        if not compatible:
            skipped.append(f'{name}（节点类型不匹配）')
            continue
        controller_class=str(rt.classOf(node.controller)).casefold()
        if kind=='Biped' and controller_class=='footsteps':
            skipped.append(f'{name}（Biped 步迹）')
            continue
        if kind=='geometryclass':
            deforms={'skin','physique','skin_wrap','skin_morph'}
            modifiers={str(rt.classOf(modifier)).casefold() for modifier in node.modifiers}
            if deforms & (modifiers|{value.casefold() for value in original.get('modifiers',())}):
                skipped.append(f'{name}（蒙皮模型）')
                continue
        if kind not in ('Biped','CAT') and controller_class!='prs':
            skipped.append(f'{name}（变换控制器不支持）')
            continue
        matched[name]=(node,kind)
        if kind in required_rigs and cls!='catparent':
            matched_rigs.add(kind)
    missing_rigs=required_rigs-matched_rigs
    if missing_rigs:
        names='、'.join(sorted(missing_rigs))
        raise ValueError(f'当前场景没有与资产匹配的 {names} 骨架。请打开使用同一套骨架的角色场景。')
    # Max transforms are relative to their parent. Write parents before children.
    ordered={}
    def add(name):
        if name in ordered:
            return
        parent=records[name]['parent']
        if parent in matched:
            add(parent)
        ordered[name]=matched[name]
    for name in matched:
        add(name)
    return ordered,skipped


def animation_track_id(track):
    return (track.get('attribute'),tuple(track['path']),tuple(track['labels']),track['controller'])


def find_animation_track(node,kind,track):
    # Traverse the actual transform controller, never the material or modifier branch.
    # Legacy custom attributes were captured on the base object. Only rig nodes may
    # reapply these values, since on a mesh they can drive changes to the model.
    if track.get('attribute'):
        if kind not in ('helper','helperclass','shape','shapeclass','bone','Biped','CAT'):
            return None
    else:
        try:
            first=rt.getSubAnim(node,track['path'][0])
            if first.controller!=node.controller and first.value!=node.controller:
                return None
        except Exception:
            return None
    try:
        return resolve_track(node,track)
    except (RuntimeError,ValueError,AttributeError,IndexError):
        return None


def frame_apply_plan(frames,signature,rig):
    records={record['name']:record for record in frames[0]}
    if not records or len({name.casefold() for name in records})!=len(frames[0]):
        raise ValueError('帧数据没有对象，或包含重名对象。')
    targets,skipped=frame_receivers(records,signature,rig)
    if not targets:
        raise ValueError('没有匹配的可打键节点。'+'、'.join(skipped[:4]))
    track_cache={}
    plan=[]
    for sample in frames:
        values={record['name']:record for record in sample}
        if len(values)!=len(sample) or values.keys()!=records.keys():
            raise ValueError('动画帧中的对象清单不一致。')
        transforms=[]
        for name,(node,kind) in targets.items():
            record=values[name]
            if record['parent']!=records[name]['parent']:
                raise ValueError('动画帧中的父子层级不一致：'+name)
            local=record['local']
            if len(local)!=4 or any(len(row)!=3 or not all(math.isfinite(value) for value in row) for row in local):
                raise ValueError('无效的变换数据：'+name)
            tracks=[]
            for track in record.get('tracks',()):
                identifier=(name,animation_track_id(track))
                if identifier not in track_cache:
                    track_cache[identifier]=find_animation_track(node,kind,track)
                sub=track_cache[identifier]
                if sub is not None:
                    value=track['value']
                    if not math.isfinite(value):
                        raise ValueError('无效的控制器数据：'+name)
                    tracks.append((sub,value))
            transforms.append((node,kind,local,tracks))
        plan.append(transforms)
    return targets,skipped,track_cache,plan


def frame_append_boundary(targets,track_cache,end):
    controllers=[node.controller for node,_ in targets.values()]
    controllers.extend(sub.controller for sub in track_cache.values() if sub is not None)
    for controller in controllers:
        span=rt.getTimeRange(controller,rt.Name('children'))
        if span is not None:
            end=max(end,float(span.end))
    return end


def write_frame_animation(sample,frame):
    for node,kind,local,tracks in sample:
        world=matrix(local)
        if node.parent:
            world=world*node.parent.transform
        if kind=='Biped':
            rt.biped.setTransform(node,rt.Name('rotation'),world.rotationPart,True)
            rt.biped.setTransform(node,rt.Name('pos'),world.translationPart,True)
        else:
            node.transform=world
            if kind!='CAT':
                rt.addNewKey(node.controller,frame)
    for _,_,_,tracks in sample:
        for sub,value in tracks:
            sub.value=value
            rt.addNewKey(sub.controller,frame)


def hold_frame_animation(targets,track_cache,boundary):
    with pymxs.attime(boundary):
        # Keep evaluated values through the old end, even for a track whose
        # last key was well before the end of the time range.
        track_values=[(sub,sub.value) for sub in track_cache.values() if sub is not None]
        rig_transforms=[(node,kind,node.transform) for node,kind in targets.values() if kind in ('Biped','CAT')]
        for node,kind in targets.values():
            if kind not in ('Biped','CAT'):
                rt.addNewKey(node.controller,boundary)
        for node,kind,world in rig_transforms:
            if kind=='Biped':
                rt.biped.setTransform(node,rt.Name('rotation'),world.rotationPart,True)
                rt.biped.setTransform(node,rt.Name('pos'),world.translationPart,True)
            else:
                node.transform=world
        for sub,value in track_values:
            if not rt.getKeyIndex(sub.controller,boundary):
                sub.value=value
                rt.addNewKey(sub.controller,boundary)


def apply_asset_frames(args):
    kind=args['kind']
    if kind not in ('animation','pose','model'):
        raise ValueError('不支持此资产类型的帧操作。')
    path=Path(args['path'])
    if path.suffix.lower()!='.json' or not path.is_file():
        raise ValueError('此版本没有可应用的独立帧数据。')
    data=json.loads(path.read_text('utf-8-sig'))
    rig=data.get('rig',args.get('rig','Generic'))
    if data.get('schema')!=1 or rig not in ('Generic','Biped','CAT'):
        raise ValueError('帧数据格式或骨架类型不匹配。')
    frames=data.get('frames') if kind=='animation' else [data.get('nodes')]
    if not frames or not frames[0]:
        raise ValueError('此版本没有可应用的帧数据。')
    targets,skipped,track_cache,plan=frame_apply_plan(frames,data.get('signature') or (),rig)
    old_range=rt.animationRange
    current=float(rt.sliderTime)
    boundary=float(old_range.end)
    if kind=='animation':
        boundary=frame_append_boundary(targets,track_cache,boundary)
        fps=float(rt.frameRate)
        source_fps=float(fps if args.get('sourceFps') is None else args['sourceFps'])
        if not math.isfinite(source_fps) or source_fps<=0:
            raise ValueError('源动画帧率无效。')
        step=fps/source_fps
        start=math.floor(boundary)+1
        positions=[start+index*step for index in range(len(frames))]
    else:
        start=current
        positions=[current]
    end=positions[-1]
    cat_nodes=[node for node,node_kind in targets.values() if node_kind=='CAT']
    cats=rig_roots(cat_nodes,'CAT')
    for biped in rig_roots((node for node,node_kind in targets.values() if node_kind=='Biped'),'Biped'):
        if rt.isProperty(biped.controller,'figureMode') and biped.controller.figureMode:
            raise ValueError('请退出 Biped 体型模式后再覆盖帧：'+str(biped.name))
    failure=None
    with pymxs.undo(True,'LXMaxAnimation 覆盖帧'),pymxs.animate(True):
        try:
            for cat in cats:
                if int(cat.NumLayers)<1:
                    cat.AppendLayer('LX Pose',rt.Name('Absolute'))
                cat.CATMode=1
            if kind=='animation':
                rt.animationRange=rt.interval(old_range.start,math.ceil(end))
                hold_frame_animation(targets,track_cache,boundary)
            for time_value,sample in zip(positions,plan):
                with pymxs.attime(time_value):
                    write_frame_animation(sample,time_value)
        except BaseException as error:
            failure=error
            raise
        finally:
            if float(rt.sliderTime)!=current:
                rt.sliderTime=current
    if failure is not None:
        if kind=='animation':
            rt.animationRange=old_range
        raise failure
    label='T-pose' if kind=='model' else 'Pose'
    message=f'动画已追加到 {start:g}–{end:g} 帧。' if kind=='animation' else f'{label} 已应用到当前帧（{start:g}）。'
    native_nodes={rig_type:sum(node_kind==rig_type for _,node_kind in targets.values())
                  for rig_type in ('Biped','CAT')}
    native_summary='、'.join(f'{rig_type} {total} 个' for rig_type,total in native_nodes.items() if total)
    message+=f'已打键 {len(targets)} 个对象'+(f'（{native_summary}）' if native_summary else '')+'。'
    if skipped:
        message+=f'跳过 {len(skipped)} 个对象：'+'、'.join(skipped[:4])+('…' if len(skipped)>4 else '。')
    return dict(ok=True,message=message,start=start,end=end,appliedNodes=len(targets),
                nativeRigNodes=native_nodes,skippedNodes=skipped,
                skippedTracks=sum(sub is None for sub in track_cache.values()))


def param(export,name,value=None):
    fn=rt.FBXExporterSetParam if export else rt.FBXImporterSetParam
    result=fn(name) if value is None else fn(name,value)
    if str(result).lower()=='unsupplied':raise ValueError('FBX 插件不支持参数：'+name)


def export_character_scene(args):
    folder = Path(args['directory']).resolve()
    if not folder.is_dir() or any(folder.iterdir()):
        raise ValueError('导出临时目录必须存在且为空。')
    if args['kind'] not in ('model','animation','pose'):
        raise ValueError('请选择有效的资产类型。')
    scene = folder / 'source.max'
    if not rt.saveMaxFile(str(scene),useNewFile=False,clearNeedSaveFlag=False,quiet=True):
        raise RuntimeError('完整 Max 场景保存失败。')
    textures, missing, warnings = [], [], []
    for asset in rt.getMAXFileAssetMetadata(str(scene)):
        if str(asset.type).lstrip('#').casefold() != 'bitmap':
            continue
        original = str(asset.filename)
        resolved = Path(str(asset.resolvedFilename) or original)
        if not resolved.is_file():
            resolved = Path(str(rt.mapPaths.getFullFilePath(original)))
        if not resolved.is_file():
            missing.append(original)
            continue
        suffix = hashlib.sha256(str(resolved.resolve()).encode()).hexdigest()[:12]
        destination = folder / 'textures' / (resolved.stem+'-'+suffix+resolved.suffix)
        destination.parent.mkdir(exist_ok=True)
        if not destination.exists():
            shutil.copy2(resolved,destination)
        textures.append({'source':original,'assetId':str(asset.assetId),'file':destination.relative_to(folder).as_posix()})
    write_json(folder/'textures.json',{'textures':textures,'missing':missing})
    if missing:
        warnings.append('以下贴图缺失，已保留原路径：'+', '.join(dict.fromkeys(missing)))
    if args.get('captureAvatar'):
        try:
            bitmap=rt.gw.getViewportDib()
            try:
                bitmap.filename=str(folder/'avatar.png')
                rt.save(bitmap)
            finally:
                rt.close(bitmap)
        except Exception as exc:
            warnings.append('视口截图失败，可手动设置头像：'+str(exc))
    nodes=list(rt.objects)
    try:
        signature=scene_signature(nodes)
    except ValueError:
        signature=None
        warnings.append('场景有重名对象，原生场景已完整保存。按对象匹配的 Pose 或动画操作需要唯一名称。')
    rig=args.get('rig','Generic')
    if signature and args['kind'] in ('model','pose'):
        sidecar='tpose.json' if args['kind']=='model' else 'pose.json'
        try:
            export_pose(nodes,folder/sidecar,rig)
        except ValueError as exc:
            warnings.append('已保存完整场景，当前姿势无法用于覆盖帧：'+str(exc))
    if args['kind']=='animation':
        warning=export_animation_keys(nodes,folder,rig,rt.animationRange.start,rt.animationRange.end)
        if warning:warnings.append(warning)
    frame=float(rt.sliderTime)
    start,end=(float(rt.animationRange.start),float(rt.animationRange.end)) if args['kind']=='animation' else (frame,frame)
    metadata=dict(rig=rig,fps=int(rt.frameRate),start=start,end=end,frame=frame,nodes=[str(n.name) for n in nodes],
                  signature=signature,scene=str(rt.maxFilePath)+str(rt.maxFileName),includeTextures=True,
                  fullCharacterScene=True,warnings=warnings)
    return dict(ok=True,main='source.max',warnings=warnings,metadata=metadata)


def export_asset(args):
    if args.get('fullCharacterScene'):
        return export_character_scene(args)

    kind=args['kind']
    scoped=args.get('selectedRoleOnly',False)
    if scoped and (kind not in ('animation','pose') or args.get('expected') is None):
        raise ValueError('仅已登记角色的 Pose 或动画可按角色选区保存。')
    if args.get('expected') is not None:
        nodes=selected_role() if scoped else list(rt.objects)
        validate_scene(nodes,args['expected'])
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
        if kind=='animation' and not scoped:
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
        if kind=='animation':
            warning=export_animation_keys(nodes,folder,rig,args['start'],args['end'])
            if warning:warnings.append(warning)
        if missing:warnings.append('以下贴图缺失，未复制：'+', '.join(missing))
        if not (folder/'asset.fbx').is_file() or (folder/'asset.fbx').stat().st_size==0:raise RuntimeError('FBX 导出未生成文件。')
        return {'ok':True,'main':'asset.fbx','warnings':warnings,'metadata':{'rig':rig,'fps':int(rt.frameRate),'start':args.get('start'),'end':args.get('end'),'nodes':[str(n.name) for n in nodes],'signature':scene_signature(nodes),'frame':float(old_time),'scene':str(rt.maxFilePath)+str(rt.maxFileName),'includeTextures':bool(args.get('includeTextures',False)),'warnings':warnings}}
    finally:
        rt.sliderTime=old_time
        rt.select(old_selection)


def import_asset(args):
    rig=args.get('rig','Generic')
    operation=args.get('operation')
    if operation=='keyCurrent':
        nodes=list(rt.objects)
        validate_scene(nodes,args['signature'])
        data=dict(schema=1,rig=rig,signature=args['signature'],nodes=pose_records(nodes))
        apply_frames(data,[(float(rt.sliderTime),data['nodes'])],rig,True)
        return {'ok':True,'message':'已为当前姿势打键。'}
    path=Path(args['path'])
    if not path.is_file():raise ValueError('资产文件不存在。')
    if operation=='keyAnimation':
        return apply_animation(path.parent/'animation-keys.json',rig,args['start'],args['end'])
    if operation=='keyTpose':
        tpose=path.parent/'tpose.json'
        if not tpose.is_file():raise ValueError('此版本没有可打键的 T-pose，请打开场景后重新保存 T-pose。')
        return apply_pose(tpose,rig)
    if args['kind']=='pose' and operation!='coverScene':
        pose=path.parent/'pose.json' if path.suffix.lower()=='.max' else path
        if not pose.is_file():raise ValueError('此版本没有可用于覆盖帧的 Pose。')
        return apply_pose(pose,rig,args.get('key',True))
    source=path if path.suffix.lower()=='.max' else path.parent/'source.max'
    if (args['kind'] in ('animation','model') or operation=='coverScene') and source.is_file():
        # Open a working copy so Ctrl+S cannot overwrite an immutable library revision.
        working_root=local_data()/'LXMaxAnimation/working-scenes';working_root.mkdir(parents=True,exist_ok=True)
        working=working_root/(uuid.uuid4().hex+'.max');shutil.copy2(source,working)
        textures=path.parent/'textures.json'
        mapping={};asset_paths={}
        if textures.is_file():
            for item in json.loads(textures.read_text('utf-8'))['textures']:
                original=(path.parent/item['file']).resolve()
                if not original.is_relative_to(path.parent.resolve()) or not original.is_file():raise ValueError('贴图路径无效。')
                target=working_root/working.stem/original.name;target.parent.mkdir(exist_ok=True)
                shutil.copy2(original,target)
                mapping[item['source']]=str(target)
                if item.get('assetId'):
                    asset_paths[item['assetId']]=str(target)
        if asset_paths:
            assets=rt.getMAXFileAssetMetadata(str(working))
            for asset in assets:
                target=asset_paths.get(str(asset.assetId))
                if target:
                    asset.filename=target
            rt.setMAXFileAssetMetadata(str(working),assets)
        if not rt.loadMaxFile(str(working),quiet=True):raise RuntimeError('Max 场景加载失败。')
        changed=False
        for bitmap in rt.getClassInstances(rt.Bitmaptexture) if mapping else ():
            if str(bitmap.filename) in mapping:
                bitmap.filename=mapping[str(bitmap.filename)]
                changed=True
        if operation=='coverScene' and args.get('captureFrame') is not None:
            rt.sliderTime=float(args['captureFrame'])
        if changed:
            rt.saveMaxFile(str(working),quiet=True)
        return {'ok':True,'working':str(working),'message':'已打开角色工作场景；编辑与保存只影响工作副本。' if args['kind']=='model' else '已替换当前 Max 场景；编辑与保存只影响工作副本。'}
    raise ValueError('此资产没有原生 Max 场景，请从 Max 重新导入。')


def execute_request(action,args):
    if 'expectedScene' in args:
        current=str(rt.maxFilePath)+str(rt.maxFileName)
        expected=args['expectedScene']
        if os.path.normcase(os.path.normpath(current))!=os.path.normcase(os.path.normpath(expected)):
            raise ValueError('Max 当前场景已切换，操作未执行。请重新选择。')
    if action=='export':return export_asset(args)
    if action=='saveWorkspaceAsset':
        result=export_character_scene(args)
        result['metadata']['workspaceAsset']=True
        return result
    if action=='coverScene':return import_asset(dict(args,operation='coverScene'))
    if action=='applyAssetFrames':return apply_asset_frames(args)
    if action in ('import','keyAsset'):return import_asset(args)
    raise ValueError('Unknown action')


def local_data():
    try:
        shared=rt.LXMaxAutoConnectRoot
    except AttributeError:
        shared=None
    if isinstance(shared,str) and Path(shared).is_absolute():
        return Path(shared).parent
    return Path(os.environ['LOCALAPPDATA'])


class Bridge:
    def __init__(self, previous=None):
        sessions=local_data()/'LXMaxAnimation/sessions'
        self.root=(previous.root if previous is not None and previous.root.parent==sessions
                   else sessions/(str(os.getpid())+'-'+uuid.uuid4().hex[:8]))
        self.root.mkdir(parents=True,exist_ok=True)
        source=Path(__file__).resolve()
        self.package=str(source.parents[1])
        self.digest=hashlib.sha256(source.read_bytes()).hexdigest()

        import ctypes
        from ctypes import wintypes as W
        kernel=ctypes.WinDLL('kernel32')
        kernel.GetCurrentProcess.restype=W.HANDLE
        kernel.GetProcessTimes.argtypes=[W.HANDLE,ctypes.POINTER(W.FILETIME),ctypes.POINTER(W.FILETIME),ctypes.POINTER(W.FILETIME),ctypes.POINTER(W.FILETIME)]
        created,exited,cpu,user=(W.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(kernel.GetCurrentProcess(),ctypes.byref(created),ctypes.byref(exited),ctypes.byref(cpu),ctypes.byref(user)):raise RuntimeError('Cannot read Max process identity')
        self.birth=str((created.dwHighDateTime<<32)|created.dwLowDateTime)
        self.busy=False
        self.timer=QTimer();self.timer.setInterval(750);self.timer.timeout.connect(self.tick)
    def start(self):
        self.tick()
        self.timer.start()
    def stop(self):
        self.timer.stop();(self.root/'info.json').unlink(missing_ok=True)
    def tick(self):
        if self.busy:return
        self.busy=True
        rt.LXMaxAnimationCanReload=False
        try:
            write_json(self.root/'info.json',{'protocol':2,'fullCharacterScene':1,'keyAssetOperations':1,'assetWorkspace':1,'frameApply':2,'package':self.package,'bridgeDigest':self.digest,'pid':os.getpid(),'birth':self.birth,'scene':str(rt.maxFilePath)+str(rt.maxFileName),'version':str(rt.maxVersion()[0]),'frame':float(rt.sliderTime),'start':float(rt.animationRange.start),'end':float(rt.animationRange.end),'fps':int(rt.frameRate),'selection':[str(n.name) for n in rt.selection]})
            for path in self.root.glob('*.request.json'):
                working=path.with_suffix('.working');path.rename(working)
                try:
                    data=json.loads(working.read_text('utf-8'))
                    if data['expires']<time.time():raise ValueError('请求已过期，未执行。')
                    result=execute_request(data['action'],data['args'])
                except Exception as exc:result={'ok':False,'message':str(exc)}
                write_json(path.with_name(path.name.replace('.request.json','.result.json')),result)
                working.unlink()
        finally:
            self.busy=False
            rt.LXMaxAnimationCanReload=not any(self.root.glob('*.request.json'))


def start_bridge():
    rt.execute('global LXMaxAnimationCanReload; global LXMaxAnimationBootstrapDigest')
    previous=getattr(builtins,'_lx_animation_bridge',None)
    replacement=Bridge(previous)
    if previous is not None:
        previous.stop()
    try:
        replacement.start()
    except Exception:
        replacement.stop()
        if previous is not None:
            previous.timer.start()
            previous.tick()
        raise
    builtins._lx_animation_bridge=replacement
    rt.LXMaxAnimationBootstrapDigest=replacement.digest
    print('LXMaxAnimation connected. PID',os.getpid())


if globals().get('_START_CONNECTION', True):
    start_bridge()
