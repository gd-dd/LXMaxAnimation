"""Describe a local asset against the Git working tree and fetched cloud main."""
from pathlib import Path

from .integrations import git_run, working_changes


_CONFLICT = {'DD', 'AU', 'UD', 'UA', 'DU', 'AA', 'UU'}


def _file_set(output):
    return {path for path in output.split('\0') if path}


def _working_paths(root):
    raw = working_changes(root)
    parts = iter(raw[:-1].split('\0') if raw.endswith('\0') else raw.split('\0'))
    dirty, tracked, conflict = set(), set(), set()
    for item in parts:
        if not item:
            continue
        code, name = item[:2], item[3:]
        names = {name}
        if 'R' in code or 'C' in code:
            previous = next(parts)
            if 'R' in code:
                names.add(previous)
        dirty.update(names)
        if code != '??':
            tracked.update(names)
        if code in _CONFLICT:
            conflict.update(names)
    return dirty, tracked, conflict


def _revision(root, ref):
    try:
        return git_run(root, 'rev-parse', '--verify', '--quiet', ref, timeout=8) or None
    except RuntimeError as error:
        if str(error).strip():
            raise
        return None


def _base(root, head, cloud):
    try:
        return git_run(root, 'merge-base', head, cloud, timeout=8) or None
    except RuntimeError as error:
        if str(error).strip():
            raise
        return None


def _tree_changes(root, first, second):
    if first == second:
        return set()
    return _file_set(git_run(root, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames',
                            '--name-only', '-z', first, second, '--', 'characters/',
                            timeout=20, strip=False))


def _tree_paths(root, revision):
    return _file_set(git_run(root, 'ls-tree', '-r', '--name-only', '-z', revision,
                            '--', 'characters/', timeout=20, strip=False))


def _scopes(paths):
    """Index group and revision dirs so row rendering never walks a Git tree."""
    scopes = set()
    for path in paths:
        parts = path.split('/')
        if len(parts) < 5 or parts[0] != 'characters':
            continue
        scopes.add('/'.join(parts[:4]))
        if len(parts) >= 7 and parts[4] == 'versions':
            scopes.add('/'.join(parts[:6]))
    return scopes


def asset_git_state(root, library_state=None):
    """Read local changes and compare with the pinned, already fetched cloud main."""
    root = Path(root)
    if not (root / '.git').exists():
        return dict(ready=False, connected=False, checked=False, cloud_oid=None, head_oid=None)
    if library_state and 'remote' in library_state:
        connected = bool(library_state['remote'])
    else:
        connected = 'origin' in git_run(root, 'remote', timeout=8).splitlines()
    head = _revision(root, 'HEAD')
    cloud = _revision(root, 'refs/remotes/origin/main') if connected else None
    checked = bool(cloud or connected and (library_state or {}).get('checked'))
    dirty, tracked, conflicts = _working_paths(root)
    outgoing, incoming, different, cloud_files = set(), set(), set(), set()
    if cloud:
        cloud_files = _tree_paths(root, cloud)
    if head and cloud:
        different = _tree_changes(root, head, cloud)
        if different:
            base = _base(root, head, cloud)
            if base is None:
                # With unrelated history, any unequal path needs manual review.
                outgoing = incoming = different
            elif base == head:
                incoming = different
            elif base == cloud:
                outgoing = different
            else:
                outgoing = _tree_changes(root, base, head) & different
                incoming = _tree_changes(root, base, cloud) & different
    elif cloud:
        incoming = different = cloud_files
    elif head and checked:
        outgoing = different = _tree_paths(root, head)
    return dict(ready=True, connected=connected,
                checked=checked,
                cloud_oid=cloud, head_oid=head, dirty=_scopes(dirty), tracked_dirty=_scopes(tracked),
                conflicts=_scopes(conflicts), outgoing=_scopes(outgoing),
                incoming=_scopes(incoming), different=_scopes(different),
                cloud_files=_scopes(path for path in cloud_files if path.endswith('/asset.json')))


def asset_paths(root, versions, *, exact=False):
    """Return repository-relative paths that cover only the supplied asset versions."""
    if isinstance(versions, dict):
        versions = (versions,)
    root = Path(root).resolve()
    paths = set()
    for asset in versions:
        folder = Path(asset['_directory']).relative_to(root)
        parts = folder.parts
        if (not parts or parts[0] != 'characters' or len(parts) not in (4, 6)
                or '..' in parts or asset.get('character', parts[1]) != parts[1]
                or asset.get('kind', parts[2]) != parts[2]):
            raise ValueError('资产目录不在当前角色的版本路径内。')
        if len(parts) == 6:
            if parts[4] != 'versions':
                raise ValueError('资产版本路径无效。')
            if not exact:
                folder = folder.parent.parent
        paths.add(folder.as_posix())
    return tuple(sorted(paths))


def asset_status(state, paths, *, historical=False):
    """Return display text and independent change flags for one asset or revision."""
    paths = {paths} if isinstance(paths, str) else set(paths)
    state_ready = state is not None
    state = state or {}
    dirty = bool(paths & state.get('dirty', set()))
    tracked_dirty = bool(paths & state.get('tracked_dirty', set()))
    conflict = bool(paths & state.get('conflicts', set()))
    ahead = bool(paths & state.get('outgoing', set()))
    behind = bool(paths & state.get('incoming', set()))
    cloud_has_asset = bool(paths & state.get('cloud_files', set()))
    cloud = state.get('cloud_oid')
    pending_check = bool(state.get('connected') and not state.get('checked'))
    if not state_ready:
        return dict(text='待刷新', code='unknown', detail='刷新共享资产库以检查文件状态。',
                    dirty=False, ahead=False, behind=False, conflict=False, in_cloud=False,
                    untracked=False, refresh_required=True)

    labels = []
    if historical:
        labels.append('旧版本')
    if conflict:
        labels.append('有冲突')
        code = 'conflict'
    else:
        if dirty:
            labels.append('已修改' if tracked_dirty else '未跟踪')
        if ahead and behind:
            labels.append('双端有更新')
            code = 'diverged'
        elif behind:
            if '旧版本' not in labels:
                labels.append('旧版本')
            code = 'behind'
        elif ahead and state.get('connected'):
            labels.append('待推送')
            code = 'ahead'
        else:
            code = 'historical' if historical else 'latest'
        if dirty:
            code = 'modified'
    if pending_check:
        labels.append('云端待检查')
        if code in ('latest','historical'):
            code = 'unknown'
    elif not state.get('connected') or not cloud_has_asset and not behind:
        if not labels:
            labels.append('仅本地')
            code = 'local'
        elif state.get('connected') and not cloud_has_asset and not ahead and code != 'conflict':
            labels.append('仅本地')
    if not labels:
        labels = ['最新']

    explanations = []
    if historical:
        explanations.append('当前选择的是此资产的历史版本。')
    if conflict:
        explanations.append('此资产包含尚未解决的 Git 冲突。')
    if dirty:
        explanations.append('有本地文件改动尚未提交。' if tracked_dirty else '存在未由 Git 跟踪的新文件。')
    if ahead:
        explanations.append('此资产有仅存在于本地提交中的内容。')
    if behind:
        explanations.append('云端有此资产的新改动。' if cloud_has_asset else '云端已经删除此资产或版本。')
    if cloud:
        explanations.append(f'比较基准是已获取的云端 main（{cloud[:8]}）。点击「刷新」可重新检查。')
    elif pending_check:
        explanations.append('尚未获取云端版本。点击「刷新」检查。')
    elif state.get('connected'):
        explanations.append('共享仓库尚未有可比较的 main 版本。')
    else:
        explanations.append('当前库尚未连接云端。')
    return dict(text=' · '.join(labels), detail='\n'.join(explanations), code=code,
                dirty=dirty, ahead=ahead, behind=behind, conflict=conflict, in_cloud=cloud_has_asset,
                untracked=dirty and not tracked_dirty, refresh_required=pending_check)
