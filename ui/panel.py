"""LX native API 1 entry point."""
from pathlib import Path
import shutil
import time
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QTreeWidget, QTreeWidgetItem, QComboBox, QFileDialog,
    QInputDialog, QSplitter, QFormLayout, QGroupBox, QMessageBox, QSpinBox, QHeaderView, QScrollArea)
from .library import Library, KINDS, read_json
from . import integrations as host


class Job(QThread):
    done = Signal(object, str)
    def __init__(self, callback, parent):
        super().__init__(parent)
        self.callback = callback
    def run(self):
        try:
            self.done.emit(self.callback(), '')
        except Exception as exc:
            self.done.emit(None, str(exc))


class Panel(QWidget):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.settings = context.load_settings()
        self.library = None
        self.jobs = []
        self.pending = {}
        self.closed = False
        self.setObjectName('LXAnimation')
        self.setStyleSheet('QWidget#LXAnimation {background:#f5f7f1;color:#26382c;} QGroupBox {border:1px solid #dce4d3;border-radius:10px;margin-top:16px;padding-top:12px;} QGroupBox::title {subcontrol-origin:margin;left:12px;} QPushButton {padding:8px 13px;border:1px solid #bdcfa8;border-radius:6px;background:#eaf1df;color:#304c27;} QPushButton:hover {background:#d5e7bc;} QLineEdit,QComboBox,QSpinBox {padding:6px;border:1px solid #d3ddcb;border-radius:5px;background:white;} QTreeWidget,QListWidget {background:white;border:1px solid #dce4d3;border-radius:8px;} QTreeWidget::item {padding:8px;}')
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0,0,0,0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget(scroll)
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        shell.addWidget(scroll)
        header = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(QPixmap(str(context.resource('.lxtool/icon.png'))).scaled(72,72,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        header.addWidget(icon)
        titles = QVBoxLayout()
        title = QLabel('LXMaxAnimation'); title.setStyleSheet('font-size:25px;font-weight:700;')
        titles.addWidget(title); titles.addWidget(QLabel('角色资产 · 动画库 · Max ⇄ Unity'))
        header.addLayout(titles,1); layout.addLayout(header)
        row = QHBoxLayout()
        self.root = QLineEdit(self.settings.get('library','')); self.root.setReadOnly(True); self.root.setPlaceholderText('选择本地动画资产库 / Git 克隆目录')
        row.addWidget(self.root,1); row.addWidget(self.button('选择资产库',self.choose_library)); layout.addLayout(row)
        split = QSplitter(); layout.addWidget(split,1)
        left = QWidget(); leftbox = QVBoxLayout(left); leftbox.addWidget(QLabel('角色'))
        self.characters = QListWidget(); self.characters.currentTextChanged.connect(self.refresh_assets); leftbox.addWidget(self.characters)
        leftbox.addWidget(self.button('＋ 新建角色',self.add_character)); split.addWidget(left)
        right = QWidget(); rightbox = QVBoxLayout(right)
        filters = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText('搜索动画、Pose、备注…'); self.search.textChanged.connect(self.refresh_assets)
        self.kind = QComboBox(); self.kind.addItem('全部资产',''); [self.kind.addItem(v,k) for k,v in KINDS.items()]; self.kind.currentIndexChanged.connect(self.refresh_assets)
        filters.addWidget(self.search,1); filters.addWidget(self.kind); filters.addWidget(self.button('刷新',self.refresh_assets)); rightbox.addLayout(filters)
        self.assets = QTreeWidget(); self.assets.setHeaderLabels(['名称','类型','版本 / UTC','备注']); self.assets.setRootIsDecorated(False)
        self.assets.header().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.assets.itemDoubleClicked.connect(lambda *_:self.guard(self.import_max)); rightbox.addWidget(self.assets,1)
        buttons = QHBoxLayout()
        buttons.addWidget(self.button('登记已有 FBX',self.import_file)); buttons.addWidget(self.button('导入 Max',self.import_max)); buttons.addWidget(self.button('一键导入 Unity',self.import_unity)); rightbox.addLayout(buttons)
        split.addWidget(right); split.setSizes([180,760])
        maxbox = QGroupBox('3ds Max · 当前场景'); maxlayout = QVBoxLayout(maxbox)
        row = QHBoxLayout(); self.session = QComboBox(); row.addWidget(self.session,1)
        self.max_rig = QComboBox(); self.max_rig.addItem('普通骨骼','Generic'); self.max_rig.addItem('Biped','Biped'); self.max_rig.addItem('CAT','CAT'); row.addWidget(self.max_rig)
        row.addWidget(self.button('连接说明',self.connection_help)); row.addWidget(self.button('刷新连接',self.refresh_sessions)); maxlayout.addLayout(row)
        row = QHBoxLayout(); self.asset_name = QLineEdit(); self.asset_name.setPlaceholderText('保存名称，例如 Walk / Idle / 开心')
        self.save_kind = QComboBox(); [self.save_kind.addItem(v,k) for k,v in KINDS.items()]
        self.start = QSpinBox(); self.end = QSpinBox()
        for spin in (self.start,self.end):spin.setRange(-100000,100000)
        self.end.setValue(100)
        row.addWidget(self.asset_name,1); row.addWidget(self.save_kind); row.addWidget(QLabel('起止帧')); row.addWidget(self.start); row.addWidget(self.end)
        row.addWidget(self.button('保存当前选择',self.export_max)); maxlayout.addLayout(row)
        maxlayout.addWidget(QLabel('选中角色根节点或完整角色；模型 / T-pose 取当前帧，Pose 导入到当前帧。双击列表导入所选 Max。'))
        layout.addWidget(maxbox)
        options = QGroupBox('Unity 与 GitHub'); form = QFormLayout(options)
        row = QHBoxLayout(); self.unity = QLineEdit(self.settings.get('unity','')); row.addWidget(self.unity,1); row.addWidget(self.button('选择项目',self.choose_unity))
        self.rig = QComboBox(); self.rig.addItems(['Generic','Humanoid']); row.addWidget(self.rig); form.addRow('Unity 项目',row)
        row = QHBoxLayout(); self.remote = QLineEdit(self.settings.get('remote','')); self.remote.setPlaceholderText('https://github.com/账号/LXMaxAnimationLibrary.git'); row.addWidget(self.remote,1)
        row.addWidget(self.button('初始化 Git LFS',self.init_git)); row.addWidget(self.button('拉取',lambda:self.sync('pull'))); row.addWidget(self.button('保存并推送',lambda:self.sync('push'))); form.addRow('资产仓库',row)
        layout.addWidget(options)
        self.status = QLabel('选择资产库开始。'); self.status.setWordWrap(True); self.status.setTextFormat(Qt.TextFormat.PlainText); self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); layout.addWidget(self.status)
        self.timer = QTimer(self); self.timer.setInterval(1000); self.timer.timeout.connect(self.poll); self.timer.start()
        if self.root.text(): self.load_library(self.root.text())
        self.refresh_sessions()

    def button(self, name, callback):
        button = QPushButton(name)
        button.clicked.connect(lambda checked=False:self.guard(callback))
        return button

    def guard(self, callback):
        try:return callback()
        except Exception as exc:self.status.setText('操作失败：' + str(exc))

    def persist(self):
        self.settings.update(library=self.root.text(),unity=self.unity.text(),remote=self.remote.text())
        self.context.save_settings(self.settings)

    def run_job(self, callback, message, completed=None):
        if any(job.isRunning() for job in self.jobs):
            raise ValueError('正在执行文件 / Git 操作，请等待完成。')
        self.status.setText(message)
        job = Job(callback,self); self.jobs.append(job)
        def done(value,error):
            if self.closed:return
            if error:self.status.setText('操作失败：'+error)
            else:
                self.status.setText(str(value) if isinstance(value,str) else '操作完成。')
                if completed:self.guard(lambda:completed(value))
        job.done.connect(done); job.start()

    def require_library(self):
        if not self.library:raise ValueError('请先选择资产库。')
        return self.library

    def character(self):
        self.require_library()
        item = self.characters.currentItem()
        if not item:raise ValueError('请先选择或创建角色。')
        return item.text()

    def selected_asset(self):
        self.require_library()
        item = self.assets.currentItem()
        if not item:raise ValueError('请先选择一项资产。')
        return item.data(0,Qt.ItemDataRole.UserRole)

    def selected_session(self):
        session = self.session.currentData()
        if not session:raise ValueError('未连接 Max，请查看连接说明。')
        return session

    def choose_library(self):
        if self.pending or any(j.isRunning() for j in self.jobs):raise ValueError('操作进行中，请完成后切换资产库。')
        path = QFileDialog.getExistingDirectory(self,'选择 / 新建资产库',self.root.text())
        if path:self.load_library(path)

    def load_library(self, path):
        library = Library(path); library.initialize(); self.library = library
        self.root.setText(str(library.root)); self.persist()
        self.characters.clear(); self.characters.addItems(library.characters())
        if self.characters.count():self.characters.setCurrentRow(0)
        self.refresh_assets(); self.status.setText('资产库已就绪。')

    def add_character(self):
        library = self.require_library()
        name,ok = QInputDialog.getText(self,'新建角色','角色名')
        if ok:
            library.create_character(name); self.characters.addItem(name.strip()); self.characters.setCurrentRow(self.characters.count()-1)

    def refresh_assets(self,*_):
        if not self.library:return
        self.assets.clear()
        character = self.characters.currentItem()
        if not character:return
        assets,errors = self.library.list_assets(character.text(),self.search.text(),self.kind.currentData())
        for asset in assets:
            item = QTreeWidgetItem([asset['name'],KINDS[asset['kind']],asset['revision'],asset.get('notes','')])
            item.setData(0,Qt.ItemDataRole.UserRole,asset); self.assets.addTopLevelItem(item)
        self.status.setText(f'{len(assets)} 项资产。' + (' 索引错误：'+'; '.join(errors) if errors else ''))

    def refresh_sessions(self):
        current = self.session.currentData(); self.session.clear()
        for session in host.sessions():
            self.session.addItem(f"Max {session.get('version','')} · PID {session['pid']} · {session.get('scene','未命名')}",session)
            if current and current['directory'] == session['directory']:self.session.setCurrentIndex(self.session.count()-1)

    def connection_help(self):
        script = self.context.resource('max/bootstrap.ms')
        QMessageBox.information(self,'连接当前 Max',f'在需要操作的 3ds Max 中，选择 Scripting → Run Script，运行：\n\n{script}\n\n连接仅作用于该实例；关闭此面板不会关闭 Max。')

    def import_file(self):
        character = self.character()
        path,_ = QFileDialog.getOpenFileName(self,'登记 FBX','','FBX (*.fbx)')
        if not path:return
        kind,ok = QInputDialog.getItem(self,'资产类型','登记为',['动画','模型 / T-pose'],0,False)
        if not ok:return
        library=self.library
        self.run_job(lambda:library.import_fbx(character,Path(path).stem,'animation' if kind=='动画' else 'model',path),'正在登记 FBX…',lambda _:self.refresh_assets())

    def import_max(self):
        if self.pending:raise ValueError('已有宿主任务等待回执，请等待完成。')
        asset = self.selected_asset(); session = self.selected_session(); library = self.library
        def ready(path):
            result = host.request(session,'import',path=str(path),kind=asset['kind'],rig=self.max_rig.currentData())
            self.pending[str(result)] = {'type':'import','time':time.time()}
            self.status.setText('已提交给 Max，等待执行结果…')
        self.run_job(lambda:library.verify(asset),'正在校验资产…',ready)

    def export_max(self):
        if self.pending or any(j.isRunning() for j in self.jobs):raise ValueError('已有任务进行中，请等待完成。')
        from .library import safe_name
        character = self.character(); session = self.selected_session()
        name=safe_name(self.asset_name.text()); kind=self.save_kind.currentData()
        if self.start.value()>self.end.value():raise ValueError('起始帧不能大于结束帧。')
        stage = self.library.stage()
        result=host.request(session,'export',directory=str(stage),kind=kind,rig=self.max_rig.currentData(),start=self.start.value(),end=self.end.value())
        self.pending[str(result)]={'type':'export','time':time.time(),'stage':stage,'character':character,'name':name,'kind':kind}
        self.status.setText('Max 正在保存选择集…')

    def choose_unity(self):
        path=QFileDialog.getExistingDirectory(self,'选择 Unity / 团结项目',self.unity.text())
        if path:self.unity.setText(path); self.persist()

    def import_unity(self):
        if self.pending:raise ValueError('已有宿主任务等待回执，请等待完成。')
        asset=self.selected_asset(); library=self.library; project=self.unity.text(); rig=self.rig.currentText()
        if not project:raise ValueError('请先选择 Unity 项目。')
        receiver=self.context.resource('unity/LXMaxAnimationReceiver.cs'); self.persist()
        def ready(result):
            self.pending[str(result)]={'type':'unity','time':time.time()}
            self.status.setText('资产和接收器已送入项目，等待 Unity 编辑器导入回执（请打开该项目）。')
        self.run_job(lambda:host.send_unity(library,asset,project,receiver,rig),'正在复制资产至 Unity…',ready)

    def init_git(self):
        library=self.require_library(); remote=self.remote.text().strip(); self.persist()
        self.run_job(lambda:host.init_git(library.root,remote),'正在初始化 Git LFS…')

    def sync(self,operation):
        if self.pending:raise ValueError('请等待宿主保存完成后再同步。')
        library=self.require_library()
        self.run_job(lambda:host.sync_git(library.root,operation),'正在同步 GitHub…',lambda _:self.load_library(str(library.root)))

    def poll(self):
        for file,pending in list(self.pending.items()):
            path=Path(file)
            if path.exists():
                del self.pending[file]
                def consume():
                    result=read_json(path)
                    if not result.get('ok'):raise RuntimeError(result.get('message','宿主操作失败'))
                    if pending['type']=='export':
                        library=self.library
                        def publish():
                            asset=library.publish(pending['character'],pending['name'],pending['kind'],pending['stage'],result['main'],metadata=result.get('metadata',{}))
                            shutil.rmtree(pending['stage'])
                            return asset
                        self.run_job(publish,'正在校验并归档…',lambda _:self.refresh_assets())
                    else:self.status.setText(result.get('message','完成。'))
                self.guard(consume)
            elif time.time()-pending['time']>180:
                del self.pending[file]
                self.status.setText('未收到宿主回执。请检查 Max / Unity；不要立即重复操作，原任务可能仍在执行。临时文件已保留。')

    def shutdown(self):
        if self.closed:return
        self.closed=True; self.timer.stop()
        # Keep running jobs alive independently until bounded I/O finishes.
        for job in self.jobs:
            if job.isRunning():
                job.setParent(None)
                _finishing_jobs.append(job)
                job.finished.connect(lambda j=job:_release_job(j))


_finishing_jobs=[]
def _release_job(job):
    if job in _finishing_jobs:_finishing_jobs.remove(job)
    job.deleteLater()

def create_panel(context,parent):
    return Panel(context,parent)
