"""Versioned sidecar contract, deliberately independent of a Unity connection."""
import copy
import math
import uuid
from pathlib import Path
from .library import read_json, write_json, safe_name, contained
from . import fbx_settings

def fbx_defaults():return fbx_settings.defaults('importer')

SCHEMA = 'lx-animation-clips'

def builtin_presets():
    result = {}
    for name, loop, motion in [('待机循环', True, False), ('原地行走 / 跑步', True, False),
                               ('根运动行走 / 跑步', True, True), ('一次性动作', False, False),
                               ('根运动一次性动作', False, True)]:
        settings = defaults()
        settings.update(loopTime=loop, loopPose=loop)
        for key in ('lockRootRotation', 'lockRootHeightY', 'lockRootPositionXZ'):
            settings[key] = not motion
        result[name] = {'fbxSettings':fbx_defaults(),'clipSettings':settings}
    return result

def presets(library):
    path = library.root / 'unity-presets.json'
    custom = read_json(path) if path.exists() else {'schemaVersion': 1, 'presets': {}}
    if custom.get('schemaVersion') != 1 or not isinstance(custom.get('presets'), dict):
        raise ValueError('不支持的预设文件格式。')
    return copy.deepcopy({**builtin_presets(), **custom['presets']})

def save_preset(library, name, settings):
    import json
    name = safe_name(name)
    if name in builtin_presets():raise ValueError('默认预设只读，请使用其他名称。')
    if not isinstance(settings, dict):raise ValueError('预设配置必须是对象。')
    fbx_settings.validate(settings.get('fbxSettings'),'importer')
    fbx_settings.validate(settings.get('clipSettings'),'clip')
    if fbx_settings.PROTECTED.intersection(settings['clipSettings']):raise ValueError('预设不能包含 Clip 分段或来源字段。')
    json.dumps(settings, allow_nan=False)
    path = library.root / 'unity-presets.json'
    presets(library)  # Refuse to replace an unknown schema.
    data = read_json(path) if path.exists() else {'schemaVersion': 1, 'presets': {}}
    data['presets'][name] = copy.deepcopy(settings)
    write_json(path, data)

def apply_preset(data, asset, clip_id, settings):
    candidate = copy.deepcopy(data)
    if fbx_settings.PROTECTED.intersection(settings['clipSettings']):raise ValueError('预设包含分段字段，已拒绝应用。')
    clip = next(c for c in candidate['clips'] if c['id'] == clip_id)
    clip['settings'] = copy.deepcopy(settings['clipSettings'])
    candidate['fbxSettings'] = copy.deepcopy(settings['fbxSettings'])
    return validate(candidate, asset)

def defaults():
    return fbx_settings.defaults('clip')

def new_clip(name, first, last):
    return {'id': uuid.uuid4().hex, 'name': name, 'firstFrame': float(first), 'lastFrame': float(last),
            'settings': defaults(), 'notes': ''}

def document(asset):
    metadata = asset.get('metadata', {})
    first = metadata.get('start')
    last = metadata.get('end')
    if first is None or last is None:
        raise ValueError('此动画缺少场景帧范围，请从 Max 重新导入。')
    return {'schema': SCHEMA, 'schemaVersion': 1, 'assetId': asset['id'], 'revision': asset['revision'],
            'source': {'main': asset['main'], 'fps': metadata.get('fps', 30), 'firstFrame': first, 'lastFrame': last},
            'clips': [new_clip(asset['name'], first, last)], 'extensions': {},
            'fbxSettings':fbx_defaults(),'targetEditor':'2022.3','fieldSet':fbx_settings.SCHEMA['version']}

def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

def validate(data, asset):
    if data.get('schema') != SCHEMA or data.get('schemaVersion') != 1:
        raise ValueError('不支持的 Clip 配置格式。')
    base = document(asset)
    if not finite(base['source']['fps']) or base['source']['fps'] <= 0:
        raise ValueError('源动画 FPS 必须大于零。')
    if data.get('assetId') != asset['id'] or data.get('revision') != asset['revision'] or data.get('source') != base['source']:
        raise ValueError('Clip 配置与动画源版本不匹配。')
    names, ids = set(), set()
    fbx_settings.validate(data.get('fbxSettings',{}),'importer')
    if not isinstance(data.get('clips'), list):
        raise ValueError('clips 必须是数组。')
    for clip in data['clips']:
        name = safe_name(clip['name'])
        if name.casefold() in names or not clip.get('id') or clip['id'] in ids:
            raise ValueError('Clip 名称或 ID 重复。')
        names.add(name.casefold()); ids.add(clip['id'])
        a, b = clip['firstFrame'], clip['lastFrame']
        if not finite(a) or not finite(b) or not base['source']['firstFrame'] <= a <= b <= base['source']['lastFrame']:
            raise ValueError(f'Clip {name} 的范围必须位于源动画范围内，且起始帧不能大于结束帧。')
        settings = clip.get('settings')
        if not isinstance(settings, dict):
            raise ValueError('每个 Clip 必须有独立 settings 对象。')
        fbx_settings.validate(settings,'clip')
        for event in settings.get('events', []):
            if not finite(event.get('frame')) or not a <= event['frame'] <= b or not event.get('function'):
                raise ValueError('事件需有 function 和处于 Clip 范围内的 frame。')
    # Forbid NaN/Infinity anywhere, including extension fields.
    import json
    json.dumps(data, allow_nan=False)
    return data

def path_for(library, asset):
    folder = contained(library.root, Path(asset['_directory']).relative_to(library.root))
    return folder / 'clips.json'

def load(library, asset):
    path = path_for(library, asset)
    return copy.deepcopy(validate(read_json(path), asset) if path.exists() else document(asset))

def save(library, asset, data):
    validate(data, asset)
    write_json(path_for(library, asset), data)
