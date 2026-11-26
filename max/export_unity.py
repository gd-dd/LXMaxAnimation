"""Export a saved asset in a dedicated 3ds Max Batch process."""
import builtins
import json
import math
import os
from pathlib import Path
import runpy

import pymxs
from pymxs import runtime as rt


REQUEST_ENV = 'LX_UNITY_FBX_REQUEST'
MODES = {'model', 'animation', 'pose', 'tpose'}


def exporter(name, *values):
    reply = rt.FBXExporterSetParam(name, *values)
    if str(reply).lstrip('#').casefold() == 'unsupplied':
        raise RuntimeError('Max FBX 导出器不支持参数：' + name)


def archive_paths(entries):
    by_name = {}
    for entry in entries:
        key = os.path.normcase(os.path.normpath(entry['source']))
        file = Path(entry['file'])
        if not file.is_absolute() or not file.is_file():
            raise ValueError('归档贴图不存在：' + file.name)
        file = file.resolve()
        if key in by_name and by_name[key] != file:
            raise ValueError('同一原始路径对应多张归档贴图：' + file.name)
        by_name[key] = file
    return by_name


def link_bitmaps(mappings):
    missing = []
    for bitmap in rt.getClassInstances(rt.Bitmaptexture):
        original = str(bitmap.filename)
        if not original:
            continue
        key = os.path.normcase(os.path.normpath(original))
        file = mappings.get(key)
        if file is None:
            file = Path(original)
            if not file.is_absolute() or not file.is_file():
                file = Path(str(rt.mapPaths.getFullFilePath(original)))
        if file.is_absolute() and file.is_file():
            bitmap.filename = str(file)
        else:
            missing.append(original)
    return list(dict.fromkeys(missing))


def frame_range(mode, frame):
    if mode in ('pose', 'tpose'):
        captured = float(rt.sliderTime) if frame is None else float(frame)
        if not math.isfinite(captured):
            raise ValueError('采集帧无效。')
        # Evaluate the original subframe even though FBX takes use whole frames.
        rt.sliderTime = captured
        start = math.floor(captured)
        return start, start+1
    if mode == 'animation':
        start = math.ceil(float(rt.animationRange.start))
        end = math.floor(float(rt.animationRange.end))
        if end < start:
            raise ValueError('动画时间轴中没有可导出的整帧。')
        return start, end
    return None, None


def hold_single_frame(mode, pose_file, start, end):
    bridge = runpy.run_path(str(Path(__file__).with_name('bridge.py')), init_globals={'_START_CONNECTION': False})
    nodes = list(rt.objects)
    bipeds = bridge['rig_roots'](nodes, 'Biped')
    cats = bridge['rig_roots'](nodes, 'CAT')

    def enable_animation():
        for biped in bipeds:
            if biped.controller.figureMode:
                biped.controller.figureMode = False
        for cat in cats:
            if int(cat.NumLayers) < 1:
                cat.AppendLayer('LX Unity Pose', rt.Name('Absolute'))
            cat.CATMode = 1

    with pymxs.attime(rt.sliderTime):
        if pose_file:
            enable_animation()
            bridge['apply_asset_frames'](dict(path=pose_file, kind='pose' if mode=='pose' else 'model'))
        sample = bridge['pose_records'](nodes)
    _, _, _, plan = bridge['frame_apply_plan']([sample], bridge['scene_signature'](nodes), 'Generic')
    scene_range = rt.animationRange
    if start<float(scene_range.start) or end>float(scene_range.end):
        rt.animationRange=rt.interval(min(start,float(scene_range.start)),max(end,float(scene_range.end)))
    enable_animation()
    # A zero-duration FBX take imports without any Unity transform curves.
    # Hold the exact same evaluated pose at both boundaries of one frame.
    with pymxs.animate(True):
        for frame in (start,end):
            with pymxs.attime(frame):
                bridge['write_frame_animation'](plan[0],frame)


def export_unity_fbx(request, output):
    mode = request.get('kind')
    if request.get('schema') != 1 or mode not in MODES:
        raise ValueError('无效的 Unity FBX 导出请求。')
    source = Path(request['source'])
    if not source.is_absolute() or source.suffix.casefold() != '.max' or not source.is_file():
        raise ValueError('缺少有效的完整 Max 场景。')
    archive = archive_paths(request.get('textures', ()))
    if not rt.loadMaxFile(str(source), quiet=True):
        raise RuntimeError('Max 无法打开资产源场景。请检查 Max 版本和所需插件。')
    nodes = list(rt.objects)
    if not nodes:
        raise ValueError('Max 场景中没有可导出的对象。')
    missing = link_bitmaps(archive)
    start, end = frame_range(mode, request.get('frame'))
    pose_take = mode in ('pose', 'tpose')
    if pose_take:
        hold_single_frame(mode, request.get('posePayload'), start, end)
        # Biped's procedural Footsteps object is a viewport aid, not part of
        # the held skeleton. Its evaluated path can still move at the next frame.
        nodes = [node for node in nodes if str(rt.classOf(node.controller)).casefold() != 'footsteps']
        rt.select(nodes)
    elif request.get('posePayload'):
        raise ValueError('旧版姿势数据只适用于 Pose 或 T-pose。')
    fps = int(rt.frameRate)
    rt.pluginManager.loadClass(rt.FBXEXP)
    exporter('PushSettings')
    try:
        exporter('ResetExport')
        for key, value in (
            ('ASCII', False), ('Skin', True), ('Shape', True), ('Cameras', False),
            ('Lights', False), ('EmbedTextures', True), ('Animation', start is not None),
            ('ShowWarnings', False),
        ):
            exporter(key, value)
        exporter('SplitAnimationIntoTakes', '-c')
        if pose_take:
            exporter('SplitAnimationIntoTakes','T-pose' if mode=='tpose' else 'Pose',start,end)
        if start is not None:
            for key, value in (
                ('BakeAnimation', True), ('BakeResampleAnimation', True),
                ('BakeFrameStart', start), ('BakeFrameEnd', end), ('BakeFrameStep', 1),
            ):
                exporter(key, value)
        exported = rt.exportFile(str(output), rt.Name('noPrompt'), selectedOnly=pose_take, using=rt.FBXEXP)
        if not exported or not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError('Max FBX 导出失败，未生成可导入文件。')
    finally:
        exporter('SplitAnimationIntoTakes', '-c')
        exporter('PopSettings')
    warnings = ['以下贴图未找到：' + '、'.join(missing)] if missing else []
    return dict(ok=True, message='已导出 Unity FBX。', output=str(output), start=start,
                end=end, fps=fps, nodes=len(nodes), warnings=warnings)


def fresh_file(value, request_file, extension):
    path = Path(value)
    if not path.is_absolute() or path.suffix.casefold() != extension:
        raise ValueError('无效的 Max 导出临时文件路径。')
    path = path.resolve()
    if not path.is_relative_to(request_file.parent) or not path.parent.is_dir() or path.exists():
        raise ValueError('Max 导出输出必须是本次临时目录中的新文件。')
    return path


def run_job(request, request_file):
    result = fresh_file(request['result'], request_file, '.json')
    try:
        output = fresh_file(request['output'], request_file, '.fbx')
        receipt = export_unity_fbx(request, output)
    except Exception as error:
        receipt = dict(ok=False, message=str(error))
    draft = result.with_name(result.name + '.tmp')
    draft.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(draft, result)


def main():
    request_file = Path(os.environ[REQUEST_ENV]).resolve()
    request = json.loads(request_file.read_text('utf-8-sig'))
    if not rt.maxOps.isInNonInteractiveMode():
        raise RuntimeError('Unity FBX 导出必须在独立的 3ds Max Batch 进程中运行。')
    # A 3ds Max startup script can load the interactive bridge in the same
    # process. The batch process must never advertise itself as an editor.
    rt.execute('global LXMaxAutoConnectTimer; if LXMaxAutoConnectTimer != undefined do LXMaxAutoConnectTimer.Stop()')
    connection = getattr(builtins, '_lx_animation_bridge', None)
    if connection:
        connection.stop()
    jobs = request.get('jobs')
    try:
        if jobs is None:
            run_job(request, request_file)
        else:
            if request.get('schema') != 1 or not isinstance(jobs, list) or not jobs:
                raise ValueError('无效的 Unity FBX 批量导出请求。')
            for job in jobs:
                try:
                    run_job({**job, 'schema': 1}, request_file)
                except Exception as error:
                    print('无法写入 Max FBX 导出报告：'+str(error))
    finally:
        rt.resetMaxFile(rt.Name('noPrompt'))


if __name__ == '__main__':
    main()
