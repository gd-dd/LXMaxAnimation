"""Exercise the embedded Qt sync controls against a disposable Git/LFS library."""
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from unittest.mock import patch


PACKAGE = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ['LX_ANIMATION_QA_OUTPUT']).resolve()
if OUTPUT.drive.upper() != 'E:':
    raise RuntimeError('Asset sync UI fixtures must stay on E:')
OUTPUT.mkdir(parents=True, exist_ok=True)
for name in ('TEMP', 'TMP', 'APPDATA', 'LOCALAPPDATA', 'USERPROFILE'):
    folder = OUTPUT / name
    folder.mkdir(exist_ok=True)
    os.environ[name] = str(folder)
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['GIT_CONFIG_GLOBAL'] = str(OUTPUT / 'git-config')
os.environ['GIT_CONFIG_NOSYSTEM'] = '1'
sys.dont_write_bytecode = True
sys.path.insert(0, str(PACKAGE))

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget
from ui.integrations import git_run, init_git, sync_git
from ui.library import Library, read_json, write_json
from ui.panel import create_panel


def until(condition, description):
    deadline = monotonic() + 20
    while monotonic() < deadline:
        if condition():
            return
        QApplication.processEvents()
        sleep(0.02)
    raise AssertionError(description)


def click(widget):
    assert widget.isVisible() and widget.isEnabled(), widget.text()
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)


def inspect_modal(find, inspect, activate):
    """Inspect a real popup in its nested event loop and close it even on failure."""
    completed = []
    errors = []
    deadline = monotonic() + 20
    timer = QTimer()

    def poll():
        try:
            if monotonic() >= deadline:
                raise AssertionError('Timed out waiting for the popup')
            found = find()
            if found is not None and inspect(found):
                completed.append(True)
                timer.stop()
        except Exception as exc:
            errors.append(exc)
            timer.stop()
            widget = find() or QApplication.activeModalWidget() or QApplication.activePopupWidget()
            if widget:
                widget.close()

    timer.timeout.connect(poll)
    timer.start(20)
    try:
        activate()
    finally:
        timer.stop()
    if errors:
        raise errors[0]
    assert completed, 'Expected an actual Qt popup'


def exercise_account(panel):
    calls = []

    def access(library_root, verify):
        assert library_root == panel.library.root
        calls.append(verify)
        return dict(identity_name='测试提交者', identity_email='qa@example.invalid',
                    account='animator-fixture' if verify else '', helper_configured=True,
                    remote='https://github.com/example/animation',
                    read_access=True if verify else None, write_access=False if verify else None,
                    message='请联系仓库管理员确认访问角色。' if verify else '')

    def inspect(dialog):
        assert isinstance(dialog, QDialog) and dialog.windowTitle() == 'Git 账号与权限'
        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        assert {'设置提交者…', '在 LXGit 管理账号', '核验 GitHub 权限', '关闭'} <= buttons.keys()
        if not buttons['核验 GitHub 权限'].isEnabled():
            return False
        labels = '\n'.join(label.text() for label in dialog.findChildren(QLabel))
        if '测试提交者' not in labels:
            return False
        assert 'qa@example.invalid' in labels and '工具架账号用于商店' in labels
        if 'animator-fixture' not in labels:
            assert '待核验' in labels
            click(buttons['核验 GitHub 权限'])
            return False
        assert '读取 有权限' in labels and '写入 无权限' in labels and '仓库管理员' in labels
        assert dialog.grab().save(str(OUTPUT / 'git-account.png'))
        click(buttons['关闭'])
        return True

    with patch('ui.panel.access_state', side_effect=access):
        inspect_modal(QApplication.activeModalWidget, inspect, lambda: click(panel.library_account))
    assert calls == [False, True]


def exercise(base, app):
    remote = base / 'remote.git'
    git_run(base, 'init', '--bare', '-b', 'main', str(remote))
    library = Library(base / 'library')
    library.initialize()
    init_git(library.root)
    git_run(library.root, 'config', '--local', 'user.name', 'QA')
    git_run(library.root, 'config', '--local', 'user.email', 'qa@example.invalid')
    git_run(library.root, 'remote', 'add', 'origin', str(remote))
    library.create_character('测试角色')
    source = base / 'source'
    source.mkdir()
    (source / 'scene.max').write_bytes(b'Isolated UI fixture; no Max host required')
    meta = dict(fps=30, start=0, end=40)
    old = library.publish('测试角色', '行走', 'animation', source, 'scene.max', metadata=meta)
    walk = library.publish('测试角色', '行走', 'animation', source, 'scene.max', metadata=meta)
    run = library.publish('测试角色', '跑步', 'animation', source, 'scene.max', metadata=meta)
    library.publish('测试角色', '站立', 'animation', source, 'scene.max', metadata=meta)
    sync_git(library.root, 'push')

    def edit(asset, note):
        file = Path(asset['_directory']) / 'asset.json'
        write_json(file, dict(read_json(file), notes=note))
        return file.relative_to(library.root).as_posix()

    walk_path = edit(walk, '保留本地变更')
    run_path = edit(run, '只推送这条')
    git_run(library.root, 'add', '--', walk_path)
    staged_walk = git_run(library.root, 'show', ':' + walk_path)
    initial_cloud = git_run(remote, 'rev-parse', 'HEAD')

    class Context:
        package_root = PACKAGE
        data_root = base / 'data'
        workspace_state = {}

        def resource(self, path):
            return PACKAGE / path

        def load_settings(self):
            return {'library': str(library.root), 'character': '测试角色'}

        def save_settings(self, data):
            pass

    shell = QWidget()
    shell.resize(1280, 800)
    layout = QVBoxLayout(shell)
    panel = create_panel(Context(), shell)
    layout.addWidget(panel)
    shell.show()
    app.processEvents()

    def item(name):
        return next(row for row in panel.assets.findItems(name, Qt.MatchFlag.MatchExactly, 0))

    def ready():
        return not panel.library_working and all(not job.isRunning() for job in panel.jobs)

    try:
        until(ready, 'Initial local state did not load')
        click(panel.library_refresh)
        until(ready, 'Refresh did not complete')
        assert panel.assets.headerItem().text(3) == '状态'
        assert item('行走').text(3) == item('跑步').text(3) == '已修改'
        assert item('站立').text(3) == '最新'
        panel.assets.setCurrentItem(item('行走'))
        assert panel.selected_asset()['id'] == walk['id']
        assert panel.selected_asset_status.text() == '已修改'
        assert panel.version_choice.count() == 2
        panel.version_choice.setCurrentIndex(1)
        assert panel.selected_asset()['id'] == old['id']
        assert panel.selected_asset_status.text() == '旧版本'
        assert '历史版本' in panel.selected_asset_status.toolTip()
        assert shell.grab().save(str(OUTPUT / 'animation-status.png'))

        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as cancel:
            click(panel.push_asset_button)
        assert '行走' in cancel.call_args.args[2]
        assert git_run(remote, 'rev-parse', 'HEAD') == initial_cloud

        def context_menu(menu):
            assert isinstance(menu, QMenu)
            actions = {action.text(): action for action in menu.actions()}
            assert {'详情信息…', '打开资产目录', '推送此动画…'} <= actions.keys()
            assert menu.grab().save(str(OUTPUT / 'animation-context-menu.png'))
            menu.close()
            actions['推送此动画…'].trigger()
            return True

        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes) as confirm:
            area = panel.assets.visualItemRect(item('跑步'))
            inspect_modal(QApplication.activePopupWidget, context_menu,
                          lambda: panel.assets.customContextMenuRequested.emit(area.center()))
        assert '跑步' in confirm.call_args.args[2] and '行走' not in confirm.call_args.args[2]
        until(ready, 'Single animation job did not finish')
        assert '已推送' in panel.status.text(), panel.status.text()
        paths = git_run(remote, 'diff', '--name-only', '-z', initial_cloud, 'HEAD', strip=False)
        assert paths == run_path + '\0', paths
        assert '只推送这条' in git_run(remote, 'show', 'HEAD:' + run_path)
        assert git_run(library.root, 'show', ':' + walk_path) == staged_walk
        assert item('跑步').text(3) == '最新'
        assert item('行走').text(3) == '已修改'
        assert panel.selected_asset()['id'] == old['id']
        exercise_account(panel)
    finally:
        panel.shutdown()
        for job in panel.jobs:
            if job.isRunning():
                job.wait(20000)
        shell.close()


if __name__ == '__main__':
    app = QApplication([])
    font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        assert font_id >= 0
        font = app.font()
        font.setFamily(QFontDatabase.applicationFontFamilies(font_id)[0])
        app.setFont(font)
    with TemporaryDirectory(prefix='asset-sync-', dir=OUTPUT) as temporary:
        exercise(Path(temporary), app)
    print('Asset sync UI passed: row and historical status, popup targeting, single animation push, account permissions')
