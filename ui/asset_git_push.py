"""Publish one animation family without adding other worktree or index changes."""
import json
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from .integrations import git_run, require_sync_branch
from .library import Library, read_json, safe_name

UPSTREAM = 'refs/remotes/origin/main'
BRANCH = 'refs/heads/main'
LITERAL = ('--literal-pathspecs',)
PATH_INPUT = ('--pathspec-from-file=-', '--pathspec-file-nul')


def _null_items(text):
    return [item for item in text.split('\0') if item]


def _null_input(paths):
    return ''.join(path+'\0' for path in paths)


def _covers(path, roots):
    return any(path==root or path.startswith(root+'/') for root in roots)


def _ref(root, name):
    return git_run(root,'for-each-ref','--format=%(objectname)',name,timeout=8)


def _cloud_commit(root):
    git_run(root,'fetch','--prune','origin',timeout=90)
    target = _ref(root, UPSTREAM)
    if not target:
        if git_run(root,'ls-remote','--heads','origin',timeout=60):
            raise ValueError('共享仓库有其他分支但没有 main，请先检查共享库设置。')
        return ''
    try:
        marker = json.loads(git_run(root,'show',target+':library.json',timeout=8).lstrip('\ufeff'))
    except (RuntimeError,ValueError) as error:
        raise ValueError('云端 main 缺少有效的 LXMaxAnimation 资产库。') from error
    if not isinstance(marker,dict) or marker.get('schema')!=1:
        raise ValueError('云端 main 的资产库格式不受支持。')
    return target


def _tree_files(root, revision, path):
    if not revision:
        return []
    return _null_items(git_run(root,*LITERAL,'ls-tree','-r','-z','--name-only',revision,
                               '--',path,timeout=15,strip=False))


def _animation_scope(root, asset, local, cloud):
    if asset.get('kind')!='animation':
        raise ValueError('请选择一个动画资产。')
    library = Library(root)
    library.asset_location(asset)
    character = safe_name(asset['character'])
    name = safe_name(asset['name'])
    parent = f'characters/{character}/animation'
    versions, errors = library.list_assets(character,kind='animation')
    if errors:
        raise ValueError('动画索引存在异常，请重新读取资产库后重试。')
    wanted = {library.asset_location(entry)[0].relative_to(root).as_posix()
              for entry in versions if entry['name']==name}
    if not wanted:
        raise ValueError('所选动画已不存在，请刷新动画列表。')
    foreign = set()
    for revision in dict.fromkeys((local,cloud)):
        for path in _tree_files(root,revision,parent):
            parts = PurePosixPath(path).parts
            if parts[-1]!='asset.json':
                continue
            if len(parts)==5:
                group = '/'.join(parts[:-1])
            elif len(parts)==7 and parts[4]=='versions':
                group = '/'.join(parts[:4])
                if parts[3]!=name and group not in wanted:
                    continue
            else:
                continue
            try:
                record=json.loads(git_run(root,'show',revision+':'+path,timeout=8).lstrip('\ufeff'))
            except (RuntimeError,ValueError) as error:
                raise ValueError('共享库中存在无法读取的动画版本记录。') from error
            if (isinstance(record,dict) and record.get('schema')==1 and
                    record.get('character')==character and record.get('kind')=='animation' and
                    record.get('name')==name):
                wanted.add(group)
            else:
                foreign.add(group)
    for entry in versions:
        if entry['name']!=name:
            foreign.add(library.asset_location(entry)[0].relative_to(root).as_posix())
    if (any(_covers(other,wanted) for other in foreign) or
            any(_covers(path,foreign) for path in wanted)):
        raise ValueError('动画目录与其他资产共用，请先在 LXGit 核对目录。')
    # A new character or empty repository needs its root records to load the published animation.
    # Changes to existing shared settings/character records belong to the whole-library action.
    required=['library.json',f'characters/{character}/character.json']
    foundations=[*required,'.gitattributes','.gitignore']
    for filename in foundations:
        if cloud and _tree_files(root,cloud,filename):
            continue
        marker = root/filename
        if filename in required and not marker.is_file():
            raise ValueError('缺少共享库或角色的基础记录，请修复后再推送。')
        if marker.is_file():
            if marker.resolve()!=marker:
                raise ValueError('基础记录路径包含链接，请修复后再推送。')
            if filename in required:
                record=read_json(marker)
                if (not isinstance(record,dict) or record.get('schema')!=1 or
                        filename.endswith('/character.json') and record.get('name')!=character):
                    raise ValueError('共享库或角色的基础记录无效，请修复后再推送。')
            wanted.add(filename)
    return tuple(sorted(wanted))


def _check_history(root, local, cloud, scope):
    if cloud:
        if not local:
            raise ValueError('云端有更新。请先拉取共享库，再推送此动画。')
        try:
            git_run(root,'merge-base','--is-ancestor',cloud,local,timeout=8)
        except RuntimeError as error:
            raise ValueError('云端有更新或已分叉。请在 LXGit 整理本地改动并拉取，再推送此动画。') from error
    if not local or local==cloud:
        return
    history=cloud+'..'+local if cloud else local
    if git_run(root,'rev-list','--max-count=1','--merges',history,timeout=15):
        raise ValueError('本地有未推送的合并提交，请先在 LXGit 核对提交范围。')
    changed = _null_items(git_run(root,'log','--format=','--name-only','--no-renames','-z',
                                  history,timeout=20,strip=False))
    if any(not _covers(path,scope) for path in changed):
        raise ValueError('本地提交还包含其他资产。请在 LXGit 先拆分或推送这些提交，再单独推送此动画。')


def _verify_staged(root, local, scope, env):
    baseline=[local] if local else []
    raw=git_run(root,'diff','--cached','--raw','--no-abbrev','--no-renames','-z',*baseline,
                timeout=30,strip=False,extra_env=env)
    fields=iter(_null_items(raw))
    blobs={}
    for fields_row,path in zip(fields,fields):
        mode=fields_row.split()[1]
        if not _covers(path,scope):
            raise ValueError('待推送内容包含其他资产，操作已停止。')
        if mode not in ('000000','100644','100755'):
            raise ValueError('动画目录包含链接或子仓库，请整理后再推送。')
        if mode!='000000':
            blobs[path]=fields_row.split()[3]
    if blobs:
        attributes=_null_items(git_run(root,'check-attr','--cached','-z','--stdin','filter',
                                        input=_null_input(blobs),timeout=20,strip=False,extra_env=env))
        entries=iter(attributes)
        for path,_,value in zip(entries,entries,entries):
            if value!='lfs':
                continue
            blob=blobs[path]
            size=int(git_run(root,'cat-file','-s',blob,timeout=8))
            pointer=git_run(root,'cat-file','blob',blob,timeout=8) if size<=1024 else ''
            if not pointer.startswith('version https://git-lfs.github.com/spec/v1\n'):
                raise ValueError('动画文件未转换为 Git LFS 指针，请在 LXGit 检查 Git LFS 设置。')
    return bool(raw)


def push_asset(root, asset, message=''):
    """Push the named animation and its versions, cleaning only its index entries."""
    root=Path(root).resolve()
    require_sync_branch(root)
    fetch_url=git_run(root,'remote','get-url','origin',timeout=8)
    push_urls=git_run(root,'remote','get-url','--push','--all','origin',timeout=8).splitlines()
    if push_urls!=[fetch_url]:
        raise ValueError('单独推送需要同一个读取和推送地址。请在 LXGit 核对 origin 地址。')
    git_run(root,'lfs','version',timeout=8)
    git_dir=Path(git_run(root,'rev-parse','--absolute-git-dir',timeout=8))
    # Skip hashing other artists' binary work while taking a snapshot of selected paths.
    git_run(root,'var','GIT_AUTHOR_IDENT',timeout=8)
    git_run(root,'var','GIT_COMMITTER_IDENT',timeout=8)
    local=_ref(root,BRANCH)
    cloud=_cloud_commit(root)
    scope=_animation_scope(root,asset,local,cloud)
    _check_history(root,local,cloud,scope)
    message=message.strip() or '更新动画：'+safe_name(asset['name'])
    with tempfile.TemporaryDirectory(prefix='lx-asset-',dir=git_dir) as staging:
        env={'GIT_INDEX_FILE':str(Path(staging)/'index')}
        git_run(root,'read-tree',*([local] if local else ['--empty']),extra_env=env)
        tracked=_null_items(git_run(root,'ls-files','-z',timeout=15,strip=False,extra_env=env))
        selected=[path for path in scope if (root/path).exists()
                  or any(_covers(file,(path,)) for file in tracked)]
        if selected:
            git_run(root,*LITERAL,'add','-A',*PATH_INPUT,input=_null_input(selected),extra_env=env)
        revision=local
        if _verify_staged(root,local,scope,env):
            tree=git_run(root,'write-tree',extra_env=env)
            signing=git_run(root,'config','--bool','--default','false','commit.gpgSign',timeout=8)=='true'
            revision=git_run(root,'commit-tree',tree,*(['-p',local] if local else []),
                             *(['-S'] if signing else []),'-m',message)
    if not revision or revision==cloud:
        return '所选动画没有待推送的改动。'
    if _ref(root,BRANCH)!=local:
        raise ValueError('本地分支在操作期间已变化，未推送。请刷新后重试。')
    # Push only the verified commit. A normal push refuses remote non-fast-forward updates.
    git_run(root,'push','--no-follow-tags','--recurse-submodules=no','origin',revision+':'+BRANCH)
    if revision!=local:
        try:
            require_sync_branch(root)
            git_run(root,'update-ref','-m','LXMaxAnimation asset push',BRANCH,revision,
                    local or '0'*len(revision),timeout=10)
            git_run(root,*LITERAL,'reset','-q','--no-refresh',revision,*PATH_INPUT,
                    input=_null_input(selected),timeout=15)
        except (RuntimeError,ValueError,OSError,subprocess.TimeoutExpired) as error:
            raise ValueError(f'动画已推送到云端（{revision[:10]}），本地索引未同步。请刷新后在 LXGit 核对当前分支。') from error
    return '已推送所选动画。'
