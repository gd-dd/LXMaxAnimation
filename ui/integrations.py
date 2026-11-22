"""Explicit host requests and Git operations; never starts a host on import."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid
import tempfile
import re
from urllib.request import getproxies
from .library import write_json, read_json, contained, digest
from . import max_connection

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
    return remembered if saved else (ready[0] if len(ready)==1 else None)


def session_root():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'LXMaxAnimation' / 'sessions'


def sessions():
    result = []
    for file in session_root().glob('*/info.json'):
        try:
            data = read_json(file)
            identity=max_connection.process_identity(data.get('pid',0))
            if identity and str(data.get('birth',''))==identity['birth'] and time.time() - file.stat().st_mtime < 8:
                data['directory'] = str(file.parent)
                result.append(data)
        except (OSError, ValueError):
            pass
    return result


def available_windows():
    connected=sessions()
    result=[]
    for window in max_connection.windows():
        session=next((s for s in connected if s['pid']==window['pid'] and str(s.get('birth'))==window['birth']),None)
        result.append(dict(window,session=session))
    return result


def request(session, action, **args):
    folder = contained(session_root(), Path(session['directory']).relative_to(session_root()))
    live=next((s for s in sessions() if s['directory']==str(folder) and s['pid']==session['pid'] and s.get('birth')==session.get('birth')),None)
    if not live or time.time() - (folder / 'info.json').stat().st_mtime > 8:
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


def git_program():
    found=shutil.which('git')
    if found:
        return found
    for base in ('ProgramFiles','LOCALAPPDATA'):
        if os.environ.get(base):
            prefix=Path(os.environ[base])
            if base=='LOCALAPPDATA':prefix=prefix/'Programs'
            path=prefix/'Git/cmd/git.exe'
            if path.is_file():
                return str(path)
    package=Path(__file__).resolve().parents[1]
    if package.parent.name=='versions' and package.parent.parent.name.endswith('--1433389279'):
        runtime=package.parents[2]/'LXGit--1432888469/runtime/git'
        for marker in sorted(runtime.glob('*/lxgit-ready.json'),reverse=True):
            try:
                git=marker.parent/'cmd/git.exe'
                if git.resolve()==git and digest(git)==read_json(marker)['files']['cmd/git.exe']:
                    return str(git)
            except (OSError,ValueError,KeyError,TypeError):
                continue
    raise ValueError('找不到 Git。请先在 LXGit 中准备 Git，或安装 Git for Windows。')


def git_run(root, *args, timeout=300):
    env={**os.environ, 'GIT_TERMINAL_PROMPT':'0'}
    program=git_program()
    portable=Path(program).parent.parent
    if (portable/'lxgit-ready.json').is_file():
        env['PATH']=os.pathsep.join(str(portable/folder) for folder in ('cmd','ucrt64/bin','usr/bin'))+os.pathsep+env.get('PATH','')
    # Git does not automatically read Windows Internet Settings; honor the
    # user's active system proxy without changing global Git configuration.
    for scheme,proxy in getproxies().items():
        if scheme in ('http','https') and proxy:
            env.setdefault(scheme.upper()+'_PROXY',proxy)
    result = subprocess.run([program, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                            env=env)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def git_identity(root):
    if (root/'.git').exists():
        try:
            return git_run(root,'config','--get','user.name',timeout=4) or None
        except (ValueError,RuntimeError,OSError,subprocess.TimeoutExpired):
            pass
    user=os.environ.get('USERNAME') or os.environ.get('USER')
    return user+'（本机）' if user else None


def asset_history(root, asset):
    if not (root/'.git').exists():
        return []
    folder=contained(root,Path(asset['_directory']).relative_to(root))
    log=git_run(root,'log','--max-count=100','--format=%H%x00%an%x00%aI%x00%cn%x00%cI%x00%s',
                '--',folder.relative_to(root).as_posix(),timeout=8)
    return [line.split('\0',5) for line in log.splitlines() if line.count('\0')==5]


def shared_url(remote):
    if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?',remote):
        raise ValueError('请填写不含凭据的 GitHub 仓库 HTTPS 地址。')
    return remote.rstrip('/')


def clone_shared_library(target, remote):
    remote=shared_url(remote)
    target=Path(target).resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError('请选择一个空目录存放共享资产库。')
    target.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.lx-library-',dir=target.parent))
    try:
        git_run(target.parent,'clone','--branch','main','--single-branch','--',remote,str(stage))
        if read_json(stage/'library.json').get('schema')!=1:
            raise ValueError('指定仓库不是可用的 LXMaxAnimation 资产库。')
        git_run(stage,'lfs','install','--local')
        git_run(stage,'lfs','pull')
        if target.exists():
            target.rmdir()
        stage.rename(target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return target


def init_git(root, remote=''):
    root = Path(root)
    if not (root / 'library.json').is_file():
        raise ValueError('只能初始化 LXMaxAnimation 资产库。')
    if not (root / '.git').exists():
        git_run(root, 'init', '-b', 'main')
    git_run(root, 'lfs', 'install', '--local')
    if remote:
        remote=shared_url(remote)
        remotes = git_run(root, 'remote').splitlines()
        if 'origin' in remotes:
            if git_run(root, 'remote', 'get-url', 'origin').rstrip('/') != remote.rstrip('/'):
                raise ValueError('现有 origin 与填写地址不同；请在 Git 客户端核对。')
        else:
            git_run(root, 'remote', 'add', 'origin', remote)
    return 'Git LFS 已初始化。'


def sync_git(root, operation, remote=''):
    root = Path(root)
    if not (root / '.git').exists():
        raise ValueError('请先初始化 Git。')
    if remote and git_run(root,'remote','get-url','origin').rstrip('/').casefold().removesuffix('.git')!=shared_url(remote).casefold().removesuffix('.git'):
        raise ValueError('填写的共享仓库与当前目录的 origin 不同。请连接另一个空目录。')
    if operation == 'pull':
        if git_run(root, 'status', '--porcelain'):
            raise ValueError('本地有未提交内容，请先保存并推送，或在 Git 客户端处理后拉取。')
        git_run(root, 'pull', '--ff-only', 'origin', 'main')
        git_run(root, 'lfs', 'pull')
        return '拉取完成。'
    if operation != 'push':
        raise ValueError('未知 Git 操作。')
    if any((root/'.git'/name).exists() for name in ('rebase-merge','rebase-apply','MERGE_HEAD','CHERRY_PICK_HEAD')):
        raise ValueError('请先在 Git 客户端完成正在进行的合并或变基。')
    git_run(root, 'lfs', 'version')
    staged=git_run(root,'diff','--cached','--name-only').splitlines()
    if any(name not in ('library.json','.gitattributes','.gitignore') and not name.startswith('characters/') for name in staged):
        raise ValueError('Git 暂存区含资产库之外的文件，请先在 Git 客户端处理。')
    # Stage only the asset library, never arbitrary user files or credentials.
    paths = [p for p in ['library.json', '.gitattributes', '.gitignore', 'characters'] if (root / p).exists()]
    git_run(root, 'add', '--', *paths)
    if git_run(root, 'diff', '--cached', '--name-only'):
        git_run(root, 'commit', '-m', 'Save animation library assets')
    git_run(root, 'fetch', 'origin')
    if git_run(root,'branch','-r','--list','origin/main'):
        try:
            git_run(root,'rebase','origin/main')
        except RuntimeError as exc:
            try:
                git_run(root,'rebase','--abort')
            except RuntimeError:
                raise exc
            raise ValueError('共享库有冲突，本地提交已保留。请在 Git 客户端处理冲突后重试。') from exc
    git_run(root, 'push', '-u', 'origin', 'main')
    return '已推送到 GitHub。'
