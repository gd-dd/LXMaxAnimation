"""Prepare verified library assets and queue their import into a Unity project."""

from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

from . import clips
from .library import contained, read_json, safe_name, write_json


CATEGORIES = {'model': 'Model', 'animation': 'Animations', 'pose': 'Poses', 'tpose': 'TPose'}
MANIFEST = 'ProjectSettings/LXMaxAnimationImports.json'
RUNTIME = 'Library/LXMaxAnimation'
QUEUE_NAME = 'queue-v2'
RECEIVER = 'Assets/LXMaxAnimation/Editor/LXMaxAnimationReceiver.cs'
SCAN_EXCLUDED = {'.git', '.vs', 'assets', 'library', 'logs', 'obj', 'packages',
                 'projectsettings', 'temp', 'usersettings', 'node_modules'}


def project_version(project):
    project = Path(project).resolve()
    version_file = project / 'ProjectSettings/ProjectVersion.txt'
    if not (project / 'Assets').is_dir() or not version_file.is_file():
        raise ValueError('请选择包含 Assets 和 ProjectSettings/ProjectVersion.txt 的项目。')
    version = re.search(r'^m_EditorVersion:\s*(\S+)', version_file.read_text('utf-8-sig'), re.M)
    if not version or not re.fullmatch(r'[\w.-]+', version[1]):
        raise ValueError('无法确定此 Unity 项目的编辑器版本。')
    return version[1]


def scan_projects(directory):
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError('请选择有效的项目扫描目录。')
    found = []
    for folder, dirs, _ in os.walk(root, topdown=True, followlinks=False):
        project = Path(folder)
        try:
            version = project_version(project)
        except (OSError, ValueError):
            dirs[:] = [name for name in dirs if name.casefold() not in SCAN_EXCLUDED
                       and not (project / name).is_symlink()
                       and not (hasattr(Path, 'is_junction') and (project / name).is_junction())]
            continue
        found.append((project, version))
        dirs.clear()
    return sorted(found, key=lambda row: (row[0].name.casefold(), str(row[0]).casefold()))


def find_editor(version):
    roots = []
    hub_config = Path(os.environ.get('APPDATA', '')) / 'UnityHub/secondaryInstallPath.json'
    try:
        value = read_json(hub_config)
        if isinstance(value, str) and Path(value).is_absolute():
            roots.append(Path(value))
    except (OSError, ValueError):
        pass
    for base in filter(None, (os.environ.get('ProgramFiles'), os.environ.get('ProgramW6432'))):
        roots.append(Path(base) / 'Unity/Hub/Editor')
    for drive in ('E:/', 'D:/'):
        roots.extend((Path(drive) / 'Ruanjian/UnityEditor', Path(drive) / 'Ruanjian/TuanjieEditor'))
    for root in roots:
        for name in ('Unity.exe', 'Tuanjie.exe'):
            candidate = root / version / 'Editor' / name
            if candidate.is_file():
                return candidate.resolve()
    return None


def editor_version(executable):
    if os.name != 'nt':
        return Path(executable).parent.parent.name
    import ctypes
    from ctypes import wintypes
    dll = ctypes.WinDLL('version')
    dll.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
    dll.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    dll.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    dll.GetFileVersionInfoW.restype = wintypes.BOOL
    dll.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                                  ctypes.POINTER(wintypes.UINT)]
    dll.VerQueryValueW.restype = wintypes.BOOL
    size = dll.GetFileVersionInfoSizeW(str(executable), None)
    if not size:
        return None
    data = ctypes.create_string_buffer(size)
    pointer = ctypes.c_void_p()
    length = wintypes.UINT()
    if not dll.GetFileVersionInfoW(str(executable), 0, size, data):
        return None
    if not dll.VerQueryValueW(data, r'\VarFileInfo\Translation', ctypes.byref(pointer), ctypes.byref(length)):
        return None
    pairs = ctypes.cast(pointer, ctypes.POINTER(wintypes.WORD))
    translations = [(pairs[i], pairs[i + 1]) for i in range(0, length.value // 2 - 1, 2)]
    for language, page in translations:
        key = fr'\StringFileInfo\{language:04x}{page:04x}\ProductVersion'
        if dll.VerQueryValueW(data, key, ctypes.byref(pointer), ctypes.byref(length)) and pointer.value:
            return ctypes.wstring_at(pointer).split('_', 1)[0].strip()
    return None


def import_manifest(project):
    path = contained(project, MANIFEST)
    if not path.exists():
        return {'schema': 1, 'roles': {}, 'assets': {}}
    data = read_json(path)
    if not isinstance(data, dict) or data.get('schema') != 1:
        raise ValueError('项目中的 LXMaxAnimation 导入记录格式不受支持。')
    if not all(isinstance(data.get(key), dict) for key in ('roles', 'assets')):
        raise ValueError('项目中的 LXMaxAnimation 导入记录已损坏。')
    return data


def project_asset(project, relative):
    parts = Path(relative).parts
    if (len(parts) != 5 or parts[:2] != ('Assets', 'Charactor')
            or parts[3] not in CATEGORIES.values() or Path(parts[4]).suffix.casefold() != '.fbx'
            or any(safe_name(part) != part for part in parts)):
        raise ValueError('导入路径必须位于 Assets/Charactor 的角色分类目录。')
    path = contained(project, relative)
    if path != Path(project).resolve().joinpath(*parts):
        raise ValueError('导入路径包含目录链接。')
    return path


def role_folder(project, catalog, character, character_id):
    if character_id in catalog['roles']:
        return safe_name(catalog['roles'][character_id])
    base = safe_name(character)
    taken = {str(value).casefold() for value in catalog['roles'].values()}
    if base.casefold() in taken or (project / 'Assets/Charactor' / base).exists():
        base = base[:63] + '--' + character_id[:8]
        if base.casefold() in taken or (project / 'Assets/Charactor' / base).exists():
            raise ValueError('当前角色的 Unity 目录与已有目录冲突。')
    catalog['roles'][character_id] = base
    return base


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def settings_pairs(data):
    return [{'name': name, 'json': json.dumps(value, ensure_ascii=False, allow_nan=False)}
            for name, value in data.items()]


def clip_data(library, asset, kind):
    metadata = asset.get('metadata', {})
    if kind in ('pose', 'tpose'):
        frame = float(metadata.get('frame', 0) or 0)
        return [], [{'id': asset['id'], 'name': asset['name'], 'firstFrame': frame,
                     'lastFrame': frame, 'takeName': '', 'settings': []}]
    if kind != 'animation' or (not clips.path_for(library, asset).is_file()
                               and any(metadata.get(key) is None for key in ('start', 'end'))):
        return [], []
    document = clips.load(library, asset)
    rows = []
    for clip in document['clips']:
        settings = dict(clip['settings'])
        take_name = settings.pop('takeName', '') or clip.get('takeName', '')
        rows.append({key: clip[key] for key in ('id', 'name', 'firstFrame', 'lastFrame')} |
                    {'takeName': take_name, 'settings': settings_pairs(settings)})
    return settings_pairs(document.get('fbxSettings', {})), rows


def atomic_copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    leaf = destination.parent / ('.lx-' + uuid.uuid4().hex + '.tmp')
    try:
        shutil.copy2(source, leaf)
        os.replace(leaf, destination)
    finally:
        leaf.unlink(missing_ok=True)


def export_plan(library, asset, kind, staging, key):
    main = library.verify(asset)
    folder = main.parent if main.name == 'source.max' else Path(asset['_directory'])
    full_scene = folder / 'source.max'
    if full_scene.is_file() and 'source.max' in asset['files']:
        source = full_scene
        pose_payload = None
    elif main.suffix.lower() == '.fbx' and kind in ('model', 'animation'):
        return None, main
    elif kind in ('pose', 'tpose'):
        reference = library.character_info(asset['character']).get('reference')
        if not reference or 'source.max' not in reference['files']:
            raise ValueError(f'「{asset["name"]}」需要该角色的完整 Max 场景才能导出单帧 FBX。')
        library.verify(reference)
        source = contained(reference['_directory'], 'source.max')
        folder = Path(reference['_directory'])
        pose_payload = library.verify(asset, frames=True)
    else:
        raise ValueError(f'「{asset["name"]}」缺少可导出的 Max 或 FBX 文件。')
    textures = []
    texture_file = folder / 'textures.json'
    if texture_file.is_file():
        textures = [dict(row, file=str(contained(folder, row['file'])))
                    for row in read_json(texture_file).get('textures', [])]
    output = staging / (key + '.fbx')
    frame = asset.get('metadata', {}).get('frame')
    job = dict(schema=1, source=str(source), output=str(output), result=str(staging / (key + '.json')),
               kind=kind, frame=frame, textures=textures)
    if pose_payload:
        job['posePayload'] = str(pose_payload)
    return job, output


def max_export(executable, script, staging, jobs):
    if not executable:
        raise ValueError('需要 3ds Max 批处理组件。请先在工具中选择本机 Max 程序。')
    executable = Path(executable).resolve().with_name('3dsmaxbatch.exe')
    if not executable.is_file():
        raise ValueError('所选 3ds Max 安装中没有 3dsmaxbatch.exe。')
    req = staging / 'max-request.json'
    write_json(req, {'schema': 1, 'jobs': jobs})
    env = dict(os.environ, LX_UNITY_FBX_REQUEST=str(req), PYTHONDONTWRITEBYTECODE='1')
    for key in ('QT_QPA_PLATFORM', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'PYTHONHOME', 'PYTHONPATH'):
        env.pop(key, None)
    for key in ('APPDATA', 'LOCALAPPDATA', 'USERPROFILE', 'TEMP', 'TMP',
                'ADSK_3DSMAX_USERSETTINGS_DIR', 'ADSK_3DSMAX_APPDATA_DIR',
                'ADSK_3DSMAX_AUTOBACKUP_DIR', 'ADSK_3DSMAX_USERTOOLS_DIR'):
        folder = staging / 'profile' / key
        folder.mkdir(parents=True, exist_ok=True)
        env[key] = str(folder)
    ini = staging / '3dsmax.ini'
    ini.write_text('[Directories]\nProjectFolder=' + str(staging) + '\nAutoBackup=' + env['TEMP'] + '\n', 'utf-8')
    log = staging / 'max-export.log'
    with log.open('wb') as stream:
        process = subprocess.run([str(executable), str(script), '-i', str(ini), '-v', '3',
                                  '-listenerlog', str(staging / 'max-listener.log')],
                                 cwd=staging, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                 timeout=1200, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    results = {}
    for job in jobs:
        result_file = Path(job['result'])
        if not result_file.is_file():
            raise ValueError(f'Max 未返回导出结果（退出代码 {process.returncode}）。日志：{log}')
        result = read_json(result_file)
        if not result.get('ok') or not Path(job['output']).is_file():
            raise ValueError(f'Max FBX 导出失败：{result.get("message", "未生成 FBX")}。日志：{log}')
        results[job['output']] = result
    return results


@contextmanager
def project_lock(runtime):
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / 'publisher.lock').open('ab+') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise ValueError('此 Unity 项目有另一项 LXMaxAnimation 导入正在准备。') from error
                raise
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def enqueue(runtime, requests):
    queue = runtime / QUEUE_NAME
    queue.mkdir(parents=True, exist_ok=True)
    return [write_request(queue, payload) for payload in requests]


def write_request(queue, payload):
    identifier = uuid.uuid4().hex
    write_json(queue / (identifier + '.request.json'), dict(payload, schema=2, id=identifier))
    return queue / (identifier + '.result.json')


def install_receiver(project, receiver):
    path = contained(project, RECEIVER)
    source = Path(receiver)
    if not path.is_file() or path.read_bytes() != source.read_bytes():
        if path.is_file():
            backup = contained(project, RUNTIME) / 'receiver-backups' / (digest(path) + '.cs')
            if not backup.is_file():
                atomic_copy(path, backup)
        atomic_copy(source, path)


def prepare_import(library, project, entries, receiver, script, max_executable, work_root, *, model_rig='Generic'):
    """Export all selected files before changing any project FBX."""
    project = Path(project).resolve()
    project_version(project)
    runtime = contained(project, RUNTIME)
    if not entries:
        raise ValueError('请勾选要导入的资产。')
    if any((runtime / QUEUE_NAME).glob('*.request.json')):
        raise ValueError('此项目还有未完成的导入。请打开 Unity，或先点「重新导入项目资产」处理队列。')
    work_root = Path(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='lx-unity-', dir=work_root))
    outputs, jobs = [], []
    for index, (asset, kind) in enumerate(entries):
        settings, selected_clips = clip_data(library, asset, kind)
        job, output = export_plan(library, asset, kind, staging, str(index))
        if job:
            jobs.append(job)
        outputs.append((asset, kind, output, settings, selected_clips))
    results = max_export(max_executable, script, staging, jobs) if jobs else {}
    requests = []
    with project_lock(runtime):
        if any((runtime / QUEUE_NAME).glob('*.request.json')):
            raise ValueError('此项目还有未完成的导入。请打开 Unity，或先点「重新导入项目资产」处理队列。')
        catalog = import_manifest(project)
        plan = {}
        for asset, kind, output, settings, selected_clips in outputs:
            character = asset['character']
            role_id = library.character_id(character)
            role = role_folder(project, catalog, character, role_id)
            name = role if kind == 'model' else safe_name(asset['name'])
            relative = f'Assets/Charactor/{role}/{CATEGORIES[kind]}/{name}.fbx'
            target = project_asset(project, relative)
            if target in plan:
                raise ValueError('选中的版本会写入同一个 FBX。每个资产请选择一个版本。')
            recorded = catalog['assets'].get(relative)
            if (target.exists() or target.with_suffix('.fbx.meta').exists()) and not recorded:
                raise ValueError(f'目标已有未由 LXMaxAnimation 管理的文件：{relative}')
            if any(item.casefold() == relative.casefold() and item != relative for item in catalog['assets']):
                raise ValueError(f'项目已有仅大小写不同的 FBX：{relative}')
            export = results.get(str(output), {})
            meta = asset.get('metadata', {})
            source_start = export.get('start', meta.get('start', 0)) or 0
            if kind in ('pose', 'tpose'):
                for clip in selected_clips:
                    clip.update(firstFrame=source_start, lastFrame=export.get('end', source_start))
            rig = model_rig if kind == 'model' else 'Generic'
            if kind in ('pose', 'tpose'):
                model = next((item for item in catalog['assets'].values()
                              if item.get('kind') == 'model' and item.get('roleId') == role_id), {})
                rig = model.get('rig', 'Generic')
            request = dict(path=relative, kind=kind, rig=rig, sourceStart=source_start,
                           sourceFps=export.get('fps', meta.get('fps', 30)) or 30, sha256=digest(output),
                           fbxSettings=settings, clips=selected_clips)
            plan[target] = output
            catalog['assets'][relative] = dict(request, roleId=role_id, character=character,
                                               revision=asset['revision'], assetId=asset['id'])
            requests.append(request)
        install_receiver(project, receiver)
        record = contained(project, MANIFEST)
        old_catalog = record.read_bytes() if record.is_file() else None
        backups = staging / 'backups'
        backups.mkdir()
        published = []
        try:
            for index, (target, output) in enumerate(plan.items()):
                backup = backups / str(index) if target.is_file() else None
                if backup:
                    shutil.copy2(target, backup)
                atomic_copy(output, target)
                published.append((target, backup))
            write_json(record, catalog)
        except Exception:
            for target, backup in reversed(published):
                if backup:
                    atomic_copy(backup, target)
                else:
                    target.unlink(missing_ok=True)
            if old_catalog is not None and (not record.exists() or record.read_bytes() != old_catalog):
                recovered = backups / 'manifest.json'
                recovered.write_bytes(old_catalog)
                atomic_copy(recovered, record)
            raise
        tickets = enqueue(runtime, requests)
    return tickets, staging


def prepare_reimport(project, receiver):
    project = Path(project).resolve()
    project_version(project)
    runtime = contained(project, RUNTIME)
    with project_lock(runtime):
        catalog = import_manifest(project)
        pending = list((runtime / QUEUE_NAME).glob('*.request.json'))
        if pending:
            install_receiver(project, receiver)
            return [file.with_name(file.name.replace('.request.json', '.result.json')) for file in pending]
        requests = []
        for relative, payload in sorted(catalog['assets'].items()):
            path = project_asset(project, relative)
            if not path.is_file():
                raise ValueError(f'找不到已导入的文件：{relative}。可以从资产库重新覆盖。')
            requests.append(dict(payload, path=relative, sha256=digest(path)))
        if not requests:
            raise ValueError('该项目还没有由 LXMaxAnimation 导入的资产。')
        install_receiver(project, receiver)
        return enqueue(runtime, requests)


def process_imports(project, tickets, editor):
    project = Path(project).resolve()
    if all(ticket.is_file() for ticket in tickets) or (project / 'Temp/UnityLockfile').exists():
        return 'queued'
    required_version = project_version(project)
    editor = Path(editor) if editor else find_editor(required_version)
    if not editor or not editor.is_file() or editor.name.casefold() not in ('unity.exe', 'tuanjie.exe'):
        return 'editor_missing'
    actual_version = editor_version(editor)
    if actual_version != required_version:
        raise ValueError(f'导入已排队。项目需要 {required_version}，所选编辑器版本为 {actual_version or "未知"}。')
    log = contained(project, RUNTIME) / ('unity-' + uuid.uuid4().hex[:8] + '.log')
    subprocess.run([str(editor.resolve()), '-batchmode', '-nographics', '-projectPath', str(project),
                    '-executeMethod', 'LXMaxAnimation.Receiver.RunBatch', '-quit', '-logFile', str(log)],
                   cwd=project, timeout=1800, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if not all(ticket.is_file() for ticket in tickets):
        raise ValueError(f'Unity 未返回全部导入回执。重新打开项目可继续处理队列。日志：{log}')
    return 'finished'
