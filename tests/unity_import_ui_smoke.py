"""Exercise the Unity import dialog against two disposable projects without opening editors."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from asset_sync_ui_smoke import OUTPUT, PACKAGE, click, inspect_modal
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from ui import unity_export
from ui.library import Library, read_json, write_json
from ui.panel import create_panel
from ui.unity_dialog import UnityImportDialog


def project(path, version):
    (path / 'Assets').mkdir(parents=True)
    (path / 'ProjectSettings').mkdir()
    (path / 'ProjectSettings/ProjectVersion.txt').write_text(
        f'm_EditorVersion: {version}\n', encoding='utf8')
    return path


def exercise(base):
    library = Library(base / 'library')
    library.initialize()
    library.create_character('角色')
    source = base / 'source'
    source.mkdir()
    (source / 'source.max').write_bytes(b'Private fixture; exported through a simulated Max process')
    meta = dict(start=0, end=30, frame=12, fps=30)
    old_walk = library.publish('角色', '行走', 'animation', source, 'source.max', metadata=meta)
    library.publish('角色', '行走', 'animation', source, 'source.max', metadata=meta)
    idle = library.publish('角色', '待机', 'animation', source, 'source.max', metadata=meta)
    tpose = library.publish('角色', '标准姿势', 'model', source, 'source.max', metadata=meta)
    library.create_asset('角色', '空占位', 'animation')

    root = base / 'projects'
    first = project(root / 'Alpha', '2022.3.62f1')
    version = '2022.3.62t13'
    target = project(root / 'Team/Beta', version)
    project(root / 'Library/Ignored', version)
    unity_executable = str(base / 'Tuanjie.exe')
    max_executable = base / '3dsmax.exe'

    class Context:
        package_root = PACKAGE
        data_root = base / 'data'
        workspace_state = {}

        def resource(self, path):
            return PACKAGE / path

        def load_settings(self):
            return {'library': str(library.root), 'character': '角色',
                    'unityEditors': {version: unity_executable}}

        def save_settings(self, data):
            self.saved = data.copy()

    context = Context()
    shell = QWidget()
    shell.resize(760, 720)
    layout = QVBoxLayout(shell)
    panel = create_panel(context, shell)
    layout.addWidget(panel)
    shell.show()
    QApplication.processEvents()
    panel.refresh_assets(select_id=old_walk['id'])
    assert panel.narrow_tabs.isVisible() and panel.width() < 820
    assert panel.unity_button.isVisible()
    assert panel.rect().contains(panel.unity_button.mapTo(panel, panel.unity_button.rect().center()))

    exported = []
    processed = []
    delayed = []

    def fixture_export(executable, script, staging, jobs):
        assert executable == max_executable and script == PACKAGE / 'max/export_unity.py'
        exported.append([job['kind'] for job in jobs])
        for job in jobs:
            Path(job['output']).write_bytes(b'FBX fixture: ' + job['kind'].encode())
        return {job['output']: {'start': 12, 'end': 12, 'fps': 30}
                if job['kind'] == 'tpose' else {'start': 0, 'end': 30, 'fps': 30} for job in jobs}

    def fixture_process(proj, tickets, editor):
        assert proj == target and editor == unity_executable
        rows = []
        for ticket in tickets:
            request = ticket.with_name(ticket.name.replace('.result.json', '.request.json'))
            payload = read_json(request)
            assert (proj / payload['path']).is_file()
            rows.append((ticket, request, dict(ok=True, path=payload['path'], warnings=[])))
        processed.append([receipt['path'] for _, _, receipt in rows])
        if len(processed) == 4:
            delayed.extend(rows)
            return 'queued'
        for ticket, request, receipt in rows:
            write_json(ticket, receipt)
            request.unlink()
        return 'processed'

    def rows(dialog):
        return {dialog.assets.item(i).data(Qt.ItemDataRole.UserRole)[0]['name']: dialog.assets.item(i)
                for i in range(dialog.assets.count())}

    state = 0

    def inspect(dialog):
        nonlocal state
        assert isinstance(dialog, UnityImportDialog)
        if state == 0:
            assert not dialog.model.isEnabled() and not dialog.selected.isEnabled() and not dialog.reimport.isEnabled()
            assert set(rows(dialog)) == {'待机', '行走', '标准姿势'}
            assert [(asset['id'], kind) for asset, kind in dialog.checked_assets()] == [(old_walk['id'], 'animation')]
            dialog.directory.setText(str(root))
            state = 1
            click(dialog.refresh)
        elif state == 1 and not dialog.working:
            assert dialog.projects.count() == 2 and '找到 2 个项目' in dialog.status.text(), dialog.status.text()
            dialog.projects.setCurrentIndex(dialog.projects.findData(str(target)))
            assert dialog.target.text() == str(target / 'Assets/Charactor')
            assert context.saved['unityProject'] == str(target)
            dialog.model_rig.setCurrentIndex(dialog.model_rig.findData('Humanoid'))
            state = 2
            click(dialog.model)
        elif state == 2 and not dialog.working:
            assert 'Unity 已导入 1/1 项' in dialog.status.text(), dialog.status.text()
            assert context.saved['unityModelRig'] == 'Humanoid'
            state = 3
            click(dialog.selected)
        elif state == 3 and not dialog.working:
            assert 'Unity 已导入 1/1 项' in dialog.status.text(), dialog.status.text()
            click(dialog.clear_all)
            assert not dialog.selected.isEnabled()
            for item in rows(dialog).values():
                item.setCheckState(Qt.CheckState.Checked)
            assert {(asset['id'], kind) for asset, kind in dialog.checked_assets()} == {
                (old_walk['id'], 'animation'), (idle['id'], 'animation'), (tpose['id'], 'tpose')}
            state = 4
            click(dialog.selected)
        elif state == 4 and not dialog.working:
            assert 'Unity 已导入 3/3 项' in dialog.status.text(), dialog.status.text()
            state = 5
            click(dialog.reimport)
        elif state == 5 and not dialog.working:
            assert delayed and '导入已排队' in dialog.status.text(), dialog.status.text()
            for index, (ticket, request, receipt) in enumerate(delayed):
                if index == 0:
                    receipt.update(ok=False, message='测试导入失败')
                write_json(ticket, receipt)
                request.unlink()
            state = 6
        elif state == 6 and not dialog.tickets:
            assert 'Unity 已导入 3/4 项' in dialog.status.text(), dialog.status.text()
            assert '测试导入失败' in dialog.status.text()
            click(dialog.close_button)
            return True
        return False

    try:
        with (patch.object(unity_export, 'max_export', side_effect=fixture_export),
              patch.object(unity_export, 'process_imports', side_effect=fixture_process),
              patch.object(unity_export, 'prepare_import', wraps=unity_export.prepare_import) as imports,
              patch.object(unity_export, 'prepare_reimport', wraps=unity_export.prepare_reimport) as reimport,
              patch('ui.unity_dialog.host.preferred_max', return_value=max_executable)):
            inspect_modal(QApplication.activeModalWidget, inspect, lambda: click(panel.unity_button))
            assert [row.args[1] for row in imports.call_args_list] == [target, target, target]
            assert [(asset['id'], kind) for asset, kind in imports.call_args_list[0].args[2]] == [(tpose['id'], 'model')]
            assert [(asset['id'], kind) for asset, kind in imports.call_args_list[1].args[2]] == [(old_walk['id'], 'animation')]
            reimport.assert_called_once_with(target, PACKAGE / 'unity/LXMaxAnimationReceiver.cs')
        assert exported == [['model'], ['animation'], ['animation', 'animation', 'tpose']]
        assert [len(batch) for batch in processed] == [1, 1, 3, 4]
        assert {Path(path).parent.name for path in processed[-1]} == {'Model', 'Animations', 'TPose'}
        assert len(list((target / 'Assets/Charactor').rglob('*.fbx'))) == 4
        assert not (first / 'Assets/Charactor').exists()
        assert panel.status.text() == 'Unity 已导入 3/4 项。'
    finally:
        panel.shutdown()
        shell.close()


if __name__ == '__main__':
    app = QApplication([])
    with TemporaryDirectory(dir=OUTPUT) as temp:
        exercise(Path(temp))
    print('Unity import UI passed: narrow entry, project scan, single/multiple assets, and asynchronous receipts')
