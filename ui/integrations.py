"""Explicit host requests and Git operations; never starts a host on import."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid
from urllib.request import getproxies
from .library import write_json, read_json, contained

def max_installations():
    """Discover installed hosts without embedding a machine-specific path in the package."""
    candidates=set()
    if os.name=='nt':
        import winreg
        for view in (winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Autodesk\3dsMax',0,winreg.KEY_READ|view) as root:
                    for i in range(winreg.QueryInfoKey(root)[0]):
                        with winreg.OpenKey(root,winreg.EnumKey(root,i)) as key:
                            try:candidates.add(Path(winreg.QueryValueEx(key,'Installdir')[0])/'3dsmax.exe')
                            except OSError:pass
            except OSError:pass
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\3dsmax.exe') as key:
                candidates.add(Path(winreg.QueryValueEx(key,'')[0]))
        except OSError:pass
    base=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Autodesk'
    if base.is_dir():candidates.update(base.glob('3ds Max */3dsmax.exe'))
    return sorted((p for p in candidates if p.is_file()),key=str,reverse=True)

def launch_max(executable,bootstrap):
    executable=Path(executable).resolve();bootstrap=Path(bootstrap).resolve()
    if executable.name.lower()!='3dsmax.exe' or not executable.is_file():raise ValueError('请选择有效的 3dsmax.exe。')
    if not bootstrap.is_file():raise ValueError('连接脚本缺失，请重新安装工具。')
    env=dict(os.environ)
    # Same host isolation as Max Tools: LXTool's Qt/Python runtime must not leak into Max.
    for key in ('QT_QPA_PLATFORM','QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH','PYTHONHOME','PYTHONPATH'):
        env.pop(key,None)
    return subprocess.Popen([str(executable),'-U','MAXScript',str(bootstrap)],cwd=str(executable.parent),env=env)

def preferred_max(saved=''):
    candidates=[saved]
    shared=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'LXMaxTools/max-path.txt'
    try:candidates.append(shared.read_text('utf-8-sig').strip())
    except OSError:pass
    for value in candidates:
        path=Path(value) if value else None
        if path and path.name.lower()=='3dsmax.exe' and path.is_file():return path
    found=max_installations()
    return found[0] if found else None

def preferred_session(available,saved=None):
    ready=[s for s in available if s.get('protocol',1)>=2]
    remembered=next((s for s in ready if s['directory']==saved),None)
    return remembered or (ready[0] if len(ready)==1 else None)


def session_root():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'LXMaxAnimation' / 'sessions'


def sessions():
    result = []
    for file in session_root().glob('*/info.json'):
        try:
            data = read_json(file)
            if time.time() - file.stat().st_mtime < 8:
                data['directory'] = str(file.parent)
                result.append(data)
        except (OSError, ValueError):
            pass
    return result


def request(session, action, **args):
    folder = contained(session_root(), Path(session['directory']).relative_to(session_root()))
    if time.time() - (folder / 'info.json').stat().st_mtime > 8:
        raise ValueError('Max 连接已过期，请重新连接。')
    ident = uuid.uuid4().hex
    write_json(folder / (ident + '.request.json'), {'id': ident, 'action': action, 'args': args, 'expires': time.time() + 120})
    return folder / (ident + '.result.json')


def install_unity(project, receiver):
    project = Path(project).resolve()
    if not (project / 'Assets').is_dir() or not (project / 'ProjectSettings/ProjectVersion.txt').is_file():
        raise ValueError('请选择包含 Assets 和 ProjectSettings 的 Unity / 团结项目根目录。')
    target = project / 'Assets/LXMaxAnimation/Editor/LXMaxAnimationReceiver.cs'
    target.parent.mkdir(parents=True, exist_ok=True)
    source = Path(receiver).read_bytes()
    if target.exists() and target.read_bytes() != source:
        backup = target.with_suffix('.cs.' + uuid.uuid4().hex[:8] + '.backup')
        shutil.copy2(target, backup)
    target.write_bytes(source)
    return project


def send_unity(library, asset, project, receiver, rig='Generic'):
    if asset['kind'] == 'pose':
        raise ValueError('单帧 Pose 用于 Max 当前帧；Unity 请导入模型或动画 FBX。')
    library.verify(asset)
    project = install_unity(project, receiver)
    ident = uuid.uuid4().hex
    relative = f'Assets/LXMaxAnimation/Library/{asset["character"]}/{asset["kind"]}/{asset["name"]}--{asset["revision"]}'
    destination = contained(project, relative)
    if destination.exists():
        raise ValueError('此资产版本已在 Unity 项目中，请在 Unity 内重新导入或保存新版本。')
    # Stage outside Assets so the editor cannot import half-copied FBX/textures.
    stage = project / 'Library/LXMaxAnimation/staging' / ident
    stage.mkdir(parents=True)
    try:
        for rel in asset['files']:
            if Path(rel).suffix.lower() in ('.max','.bip','.clp','.pse') or rel.endswith('.json'):
                continue
            target = contained(stage, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(contained(asset['_directory'], rel), target)
        write_json(stage / 'lx-import.json', {'schema': 1, 'kind': asset['kind'], 'rig': rig})
        destination.parent.mkdir(parents=True, exist_ok=True)
        stage.rename(destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    queue = project / 'Library/LXMaxAnimation/queue'
    write_json(queue / (ident + '.request.json'), {'id': ident, 'path': relative + '/' + asset['main'], 'rig': rig})
    return queue / (ident + '.result.json')


def git_run(root, *args):
    env={**os.environ, 'GIT_TERMINAL_PROMPT':'0'}
    # Git does not automatically read Windows Internet Settings; honor the
    # user's active system proxy without changing global Git configuration.
    for scheme,proxy in getproxies().items():
        if scheme in ('http','https') and proxy:
            env.setdefault(scheme.upper()+'_PROXY',proxy)
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=300, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                            env=env)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def init_git(root, remote=''):
    root = Path(root)
    if not (root / 'library.json').is_file():
        raise ValueError('只能初始化 LXMaxAnimation 资产库。')
    if not (root / '.git').exists():
        git_run(root, 'init', '-b', 'main')
    git_run(root, 'lfs', 'install', '--local')
    if remote:
        if not remote.startswith('https://github.com/') or '@' in remote:
            raise ValueError('仓库地址必须为不含凭据的 https://github.com/账号/仓库.git。')
        remotes = git_run(root, 'remote').splitlines()
        if 'origin' in remotes:
            if git_run(root, 'remote', 'get-url', 'origin').rstrip('/') != remote.rstrip('/'):
                raise ValueError('现有 origin 与填写地址不同；请在 Git 客户端核对。')
        else:
            git_run(root, 'remote', 'add', 'origin', remote)
    return 'Git LFS 已初始化。'


def sync_git(root, operation):
    root = Path(root)
    if not (root / '.git').exists():
        raise ValueError('请先初始化 Git。')
    if operation == 'pull':
        if git_run(root, 'status', '--porcelain'):
            raise ValueError('本地有未提交内容，请先保存并推送，或在 Git 客户端处理后拉取。')
        git_run(root, 'pull', '--ff-only', 'origin', 'main')
        git_run(root, 'lfs', 'pull')
        return '拉取完成。'
    if operation != 'push':
        raise ValueError('未知 Git 操作。')
    git_run(root, 'lfs', 'version')
    staged=git_run(root,'diff','--cached','--name-only').splitlines()
    if any(name not in ('library.json','.gitattributes','.gitignore') and not name.startswith('characters/') for name in staged):
        raise ValueError('Git 暂存区含资产库之外的文件，请先在 Git 客户端处理。')
    # Stage only the asset library, never arbitrary user files or credentials.
    paths = [p for p in ['library.json', '.gitattributes', '.gitignore', 'characters'] if (root / p).exists()]
    git_run(root, 'add', '--', *paths)
    if git_run(root, 'diff', '--cached', '--name-only'):
        git_run(root, 'commit', '-m', 'Save animation library assets')
    git_run(root, 'push', '-u', 'origin', 'main')
    return '已推送到 GitHub。'
