"""Choose a Unity project and send a character or a batch of assets."""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QProgressBar, QPushButton, QVBoxLayout)

from . import integrations as host
from . import unity_export
from .library import KINDS, read_json
from .widgets import ElidedLabel


class UnityImportDialog(QDialog):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.library = panel.require_library()
        self.character = panel.active_character
        self.tickets = []
        self.working = False
        self.project_editors = panel.settings.get('unityEditors', {}).copy()
        self.setWindowTitle('导入 Unity')
        self.resize(690, 520)
        body = QVBoxLayout(self)

        paths = QHBoxLayout()
        self.directory = QLineEdit(panel.settings.get('unityScanDirectory', ''))
        self.directory.setPlaceholderText('Unity 项目所在目录')
        self.directory.returnPressed.connect(self.scan)
        self.directory.setAccessibleName('项目扫描目录')
        paths.addWidget(self.directory, 1)
        self.browse = self.add_button(paths, '浏览…', self.choose_directory)
        self.refresh = self.add_button(paths, '扫描项目', self.scan)
        body.addLayout(paths)

        target = QHBoxLayout()
        self.projects = QComboBox()
        self.projects.setAccessibleName('目标 Unity 项目')
        self.projects.setMinimumContentsLength(18)
        self.projects.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.projects.currentIndexChanged.connect(self.update_target)
        target.addWidget(self.projects, 1)
        self.editor_button = self.add_button(target, '编辑器…', self.choose_editor)
        body.addLayout(target)
        self.target = ElidedLabel()
        body.addWidget(self.target)

        select = QHBoxLayout()
        select.addWidget(QLabel('导入资产'), 1)
        self.select_all = self.add_button(select, '全选', lambda: self.set_checks(True))
        self.clear_all = self.add_button(select, '清空', lambda: self.set_checks(False))
        body.addLayout(select)
        self.assets = QListWidget()
        self.assets.setAlternatingRowColors(True)
        self.assets.itemChanged.connect(self.update_actions)
        body.addWidget(self.assets, 1)
        self.populate_assets()

        actions = QHBoxLayout()
        self.model = self.add_button(actions, '导入 / 覆盖角色', lambda: self.start_import('model'))
        self.model_rig = QComboBox()
        self.model_rig.setAccessibleName('角色导入骨架类型')
        self.model_rig.setToolTip('角色模型的 Unity 骨架类型')
        self.model_rig.addItem('通用骨架', 'Generic')
        self.model_rig.addItem('人形骨架', 'Humanoid')
        self.model_rig.setCurrentIndex(max(0, self.model_rig.findData(panel.settings.get('unityModelRig'))))
        actions.addWidget(self.model_rig)
        self.selected = self.add_button(actions, '导入 / 覆盖勾选', lambda: self.start_import('selected'))
        self.reimport = self.add_button(actions, '重新导入项目资产', lambda: self.start_import('reimport'))
        actions.addStretch(1)
        self.close_button = self.add_button(actions, '关闭', self.reject)
        body.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        body.addWidget(self.progress)
        self.status = ElidedLabel()
        body.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.setInterval(750)
        self.timer.timeout.connect(self.read_receipts)
        self.timer.start()
        self.update_target()
        if self.directory.text():
            QTimer.singleShot(0, lambda: self.guard(self.scan))

    def add_button(self, layout, title, action):
        button = QPushButton(title)
        button.clicked.connect(lambda: self.guard(action))
        layout.addWidget(button)
        return button

    def guard(self, action):
        try:
            action()
        except (OSError, RuntimeError, ValueError) as error:
            self.status.setText(str(error))

    def reject(self):
        if not self.working:
            super().reject()

    def closeEvent(self, event):
        if self.working:
            event.ignore()
        else:
            super().closeEvent(event)

    def populate_assets(self):
        if not self.character:
            return
        assets, errors = self.library.list_assets(self.character)
        if errors:
            raise ValueError('角色资产索引存在异常，请先刷新资产库。')
        selected = self.panel.version_choice.currentData()
        grouped = {}
        for asset in assets:
            if not asset.get('placeholder'):
                grouped.setdefault((asset['kind'], asset['name']), []).append(asset)
        for (kind, name), versions in sorted(grouped.items(), key=lambda row: (row[0][0], row[0][1].casefold())):
            asset = versions[0]
            version = len(versions)
            if selected and selected['id'] in {value['id'] for value in versions}:
                index = next(i for i, value in enumerate(versions) if value['id'] == selected['id'])
                asset, version = versions[index], len(versions) - index
            row = QListWidgetItem(f'{name}   ·   {"T-pose" if kind == "model" else KINDS[kind]}   ·   v{version:03d}')
            row.setData(Qt.ItemDataRole.UserRole, (asset, 'tpose' if kind == 'model' else kind))
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(Qt.CheckState.Checked if selected and asset['id'] == selected['id'] else Qt.CheckState.Unchecked)
            self.assets.addItem(row)

    def checked_assets(self):
        return [self.assets.item(index).data(Qt.ItemDataRole.UserRole)
                for index in range(self.assets.count())
                if self.assets.item(index).checkState() == Qt.CheckState.Checked]

    def set_checks(self, checked):
        self.assets.blockSignals(True)
        try:
            for index in range(self.assets.count()):
                self.assets.item(index).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        finally:
            self.assets.blockSignals(False)
        self.update_actions()

    def choose_directory(self):
        folder = QFileDialog.getExistingDirectory(self, '选择 Unity 项目或其上级目录', self.directory.text())
        if folder:
            self.directory.setText(folder)
            self.scan()

    def scan(self):
        if self.working or not self.directory.text().strip():
            return
        path = self.directory.text().strip()
        previous = self.projects.currentData() or self.panel.settings.get('unityProject', '')
        def ready(projects):
            self.projects.clear()
            for project, version in projects:
                self.projects.addItem(f'{project.name}   ·   {version}', str(project))
                self.projects.setItemData(self.projects.count() - 1, str(project), Qt.ItemDataRole.ToolTipRole)
            if projects:
                self.projects.setCurrentIndex(max(0, self.projects.findData(previous)))
            self.panel.settings['unityScanDirectory'] = path
            self.update_target()
            self.status.setText(f'找到 {len(projects)} 个项目。' if projects else '此目录下未找到 Unity 项目。')
        self.run(lambda: unity_export.scan_projects(path), '正在扫描 Unity 项目…', ready)

    def selected_project(self):
        path = self.projects.currentData()
        return Path(path) if path else None

    def update_target(self):
        project = self.selected_project()
        if project:
            self.panel.settings['unityProject'] = str(project)
            self.panel.persist()
        self.target.setText(str(project / 'Assets/Charactor') if project else '扫描后选择目标项目')
        self.update_actions()

    def update_actions(self):
        if not hasattr(self, 'model'):
            return
        ready = not self.working
        has_project = bool(self.selected_project())
        for control in (self.directory, self.browse, self.refresh, self.projects, self.select_all,
                        self.clear_all, self.assets, self.close_button):
            control.setEnabled(ready)
        self.editor_button.setEnabled(ready and has_project)
        self.model.setEnabled(ready and has_project and bool(self.character))
        self.model_rig.setEnabled(self.model.isEnabled())
        self.selected.setEnabled(ready and has_project and bool(self.checked_assets()))
        self.reimport.setEnabled(ready and has_project)
        self.progress.setVisible(self.working)

    def choose_editor(self):
        project = self.selected_project()
        version = unity_export.project_version(project)
        current = self.project_editors.get(version, '') or str(unity_export.find_editor(version) or '')
        path, _ = QFileDialog.getOpenFileName(self, f'选择 {version} 编辑器', current,
                                             'Unity / 团结 (Unity.exe Tuanjie.exe)')
        if path:
            self.project_editors[version] = path
            self.panel.settings['unityEditors'] = self.project_editors
            self.panel.persist()

    def run(self, action, message, done):
        self.panel.idle()
        self.working = True
        self.update_actions()
        self.status.setText(message)
        def worker():
            try:
                return action(), None
            except Exception as error:
                return None, str(error)
        def complete(result):
            self.working = False
            self.update_actions()
            value, error = result
            if error:
                self.status.setText(error)
            else:
                self.guard(lambda: done(value))
        try:
            self.panel.run_job(worker, message, complete)
        except Exception:
            self.working = False
            self.update_actions()
            raise

    def start_import(self, mode):
        project = self.selected_project()
        version = unity_export.project_version(project)
        editor = self.project_editors.get(version)
        receiver = self.panel.context.resource('unity/LXMaxAnimationReceiver.cs')
        script = self.panel.context.resource('max/export_unity.py')
        entries = self.checked_assets()
        model_rig = self.model_rig.currentData()
        root = str(self.library.root)
        workspace = getattr(self.panel.context, 'workspace_state', {})
        if mode!='reimport' and workspace.get('lxgit_working_root')==root:
            raise ValueError('LXGit 正在操作此资产库，请稍后重试。')
        if mode == 'model':
            info = self.library.character_info(self.character)
            selected = self.panel.version_choice.currentData()
            model = selected if selected and selected['kind'] == 'model' and not selected.get('placeholder') else info['reference']
            if not model:
                raise ValueError('此角色没有可导入的 Max 场景或模型 FBX。')
            entries = [(model, 'model')]
        if mode != 'reimport':
            self.panel.editor.flush()
        if mode == 'model':
            self.panel.settings['unityModelRig'] = model_rig
            self.panel.persist()
        max_executable = host.preferred_max(self.panel.settings.get('maxExecutable', '')) if mode != 'reimport' else None
        work_root = self.panel.context.data_root / 'unity-export'

        def prepare():
            if mode == 'reimport':
                tickets = unity_export.prepare_reimport(project, receiver)
            else:
                try:
                    tickets, _ = unity_export.prepare_import(self.library, project, entries, receiver, script,
                                                            max_executable, work_root, model_rig=model_rig)
                finally:
                    if workspace.get('animation_working_root')==root:
                        workspace.pop('animation_working_root',None)
            try:
                return tickets, unity_export.process_imports(project, tickets, editor), None
            except Exception as error:
                return tickets, None, str(error)

        def published(result):
            tickets, status, error = result
            self.tickets = tickets
            if self.read_receipts():
                return
            if error:
                self.status.setText(error)
            elif status == 'editor_missing':
                self.status.setText('导入已排队。打开此项目，或选择对应的 Unity 编辑器后重新导入项目资产。')
            else:
                self.status.setText('导入已排队。项目打开时会自动处理。')

        if mode!='reimport':
            workspace['animation_working_root']=root
        try:
            self.run(prepare, '正在导出 FBX 并提交 Unity 导入…' if mode != 'reimport' else '正在重新导入项目资产…', published)
        except Exception:
            if mode!='reimport':
                workspace.pop('animation_working_root',None)
            raise

    def read_receipts(self):
        if not self.tickets or not all(path.is_file() for path in self.tickets):
            return False
        try:
            rows = [read_json(path) for path in self.tickets]
        except (OSError, ValueError):
            return False
        failures = [row.get('path', '') + '  ' + row.get('message', '') for row in rows if not row.get('ok')]
        warnings = [warning for row in rows for warning in row.get('warnings') or []]
        self.tickets = []
        status = f'Unity 已导入 {len(rows) - len(failures)}/{len(rows)} 项。'
        self.status.setText('  '.join((status, *failures, *warnings)))
        self.panel.set_status(status)
        return True
