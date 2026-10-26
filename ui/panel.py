"""LXTool embedded character and animation workspace; no standalone application."""
from pathlib import Path
import shutil
import time
from PySide6.QtCore import Qt,QTimer,QThread,Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,QTreeWidget,QTreeWidgetItem,
    QComboBox,QFileDialog,QSplitter,QHeaderView,QDialog,QDialogButtonBox,QFormLayout,QMessageBox,QInputDialog,QToolButton,QMenu,QApplication)
from .library import Library,KINDS,read_json,contained
from . import integrations as host
from .clip_editor import ClipEditor
from .dialogs import CharacterDialog,CaptureDialog
from .widgets import WheelRouter,AssetTree


class Job(QThread):
    done=Signal(object,str)
    def __init__(self,fn,parent):super().__init__(parent);self.fn=fn
    def run(self):
        try:self.done.emit(self.fn(),'')
        except Exception as exc:self.done.emit(None,str(exc))


class Panel(QWidget):
    def __init__(self,context,parent=None):
        super().__init__(parent);self.context=context;self.settings=context.load_settings()
        self.library=None;self.active_character=None;self.active_session=self.settings.get('session');self.pending=None;self.launching=None
        self.jobs=[];self.closed=False;self.gallery=None;self.restoring=False
        self.setObjectName('LXAnimation')
        self.setStyleSheet("""
            QWidget#LXAnimation {background:#f5f7f2;color:#2c382c;}
            QWidget#ClipWorkspace {background:#ffffff;border-radius:9px;}
            QWidget#ClipWorkspace[empty="true"] {background:#e8ece6;}
            QWidget:disabled {color:#9aa297;}
            QLineEdit,QComboBox,QDoubleSpinBox,QSpinBox,QPlainTextEdit {background:#fff;border:1px solid #d6dfcf;border-radius:5px;padding:5px;}
            QLineEdit:disabled,QComboBox:disabled,QDoubleSpinBox:disabled,QSpinBox:disabled,QPlainTextEdit:disabled {background:#edf0ea;color:#a0a69b;}
            QPushButton,QToolButton {padding:7px 10px;border:1px solid #ccd9bf;border-radius:6px;background:#edf3e5;color:#35512b;}
            QPushButton:hover,QToolButton:hover {background:#dcebc9;border-color:#a7bd8f;}
            QPushButton:disabled,QToolButton:disabled {background:#e8ece4;color:#a4ad9d;border-color:#dce1d8;}
            QTreeWidget {background:#fff;alternate-background-color:#f5f8f1;border:1px solid #d7e0d0;border-radius:7px;}
            QTreeWidget::item {padding:6px;}
            QTreeWidget::item:selected {background:#dcecc9;color:#243e1c;}
            QTreeWidget:disabled {background:#edf0ea;color:#9aa297;}
            QHeaderView::section {background:#edf2e7;border:0;border-bottom:1px solid #d6e0cc;padding:7px;color:#516346;}
            QTabWidget::pane {border:1px solid #dce4d4;border-radius:5px;background:#fff;}
            QTabBar::tab {padding:8px 13px;background:#edf2e8;color:#617154;border:0;}
            QTabBar::tab:selected {background:#fff;color:#385623;border-bottom:3px solid #92b85b;}
            QSplitter::handle:horizontal {background:#bbcba9;border-radius:3px;margin:8px 1px;}
            QSplitter::handle:horizontal:hover {background:#88a862;}
            QScrollArea {border:0;background:transparent;}
            QScrollBar:vertical {width:10px;background:#f0f3eb;}
            QScrollBar::handle:vertical {background:#b5c5a5;border-radius:4px;min-height:24px;}
        """)
        outer=QVBoxLayout(self);outer.setContentsMargins(14,10,14,10)
        row=QHBoxLayout();self.avatar=QLabel();self.avatar.setFixedSize(58,58);row.addWidget(self.avatar)
        title=QVBoxLayout();self.character_title=QLabel('选择一个角色');self.character_title.setStyleSheet('font-size:22px;font-weight:650');title.addWidget(self.character_title)
        title.addWidget(QLabel('角色 · 动画 · Pose · Clip'));row.addLayout(title,1)
        row.addWidget(self.button('角色库',self.open_gallery));row.addWidget(self.button('资产库 / 同步',self.library_settings));outer.addLayout(row)
        row=QHBoxLayout();self.connection=QLabel('尚未连接 Max');self.connection.setWordWrap(True);row.addWidget(self.connection,1)
        self.connect_button=self.button('一键连接 Max',self.start_max);row.addWidget(self.connect_button)
        more=QToolButton();more.setText('连接 ▾');more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup);menu=QMenu(more)
        for title,fn in [('切换 Max 窗口',self.connect_max),('断开连接',self.disconnect),('更换 Max 程序',self.choose_max_program)]:menu.addAction(title,lambda fn=fn:self.guard(fn))
        more.setMenu(menu);row.addWidget(more);outer.addLayout(row)
        split=QSplitter();split.setHandleWidth(8);outer.addWidget(split,1)
        left=QWidget();leftbox=QVBoxLayout(left);leftbox.setContentsMargins(0,8,8,0)
        row=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('搜索动画 / Pose / 备注');self.search.textChanged.connect(lambda:self.guard(self.refresh_assets))
        self.kind=QComboBox();self.kind.addItem('全部','');[self.kind.addItem(v,k) for k,v in KINDS.items()];self.kind.currentIndexChanged.connect(lambda:self.guard(self.refresh_assets))
        row.addWidget(self.search,1);row.addWidget(self.kind);leftbox.addLayout(row)
        self.assets=AssetTree();self.assets.setAlternatingRowColors(True);self.assets.setHeaderLabels(['名称','类型','版本','备注']);self.assets.setRootIsDecorated(False);self.assets.setSortingEnabled(True);self.assets.sortItems(0,Qt.SortOrder.AscendingOrder)
        self.assets.header().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch);self.assets.header().setSectionResizeMode(3,QHeaderView.ResizeMode.Stretch)
        self.assets.setColumnWidth(1,95);self.assets.setColumnWidth(2,65)
        self.assets.currentItemChanged.connect(self.asset_changed);self.assets.itemDoubleClicked.connect(lambda *_:self.guard(lambda:self.send_to_max(self.selected_asset())))
        self.assets.itemChanged.connect(self.asset_metadata_changed)
        leftbox.addWidget(self.assets,1)
        row=QHBoxLayout();create=QToolButton();create.setText('＋ 从 Max 导入');create.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup);menu=QMenu(create)
        menu.addAction('动画',lambda:self.guard(lambda:self.capture('animation')));menu.addAction('单帧 Pose',lambda:self.guard(lambda:self.capture('pose')));menu.addSeparator();menu.addAction('刷新列表',lambda:self.guard(self.refresh_assets));create.setMenu(menu);row.addWidget(create)
        self.selection_label=QLabel('未选择资产');row.addWidget(self.selection_label,1)
        self.save_button=self.button('从 Max 保存',self.overwrite);self.save_button.setEnabled(False);row.addWidget(self.save_button);leftbox.addLayout(row)
        hint=QLabel('双击加载到 Max · 选中后再单击名称 / 备注编辑\n仅“从 Max 保存”写回库；不自动备份当前场景。');hint.setWordWrap(True);leftbox.addWidget(hint)
        split.addWidget(left)
        right=QWidget();rightbox=QVBoxLayout(right);rightbox.setContentsMargins(8,8,0,0)
        self.editor=ClipEditor();self.editor.message.connect(self.set_status);rightbox.addWidget(self.editor,1)
        footer=QHBoxLayout();footer.addWidget(QLabel('Unity 导出与后处理接口：后续接入'),1);button=QPushButton('导出到 Unity · 暂未接入');button.setEnabled(False);footer.addWidget(button);rightbox.addLayout(footer)
        split.addWidget(right);split.setSizes([490,560]);split.setChildrenCollapsible(False)
        self.status=QLabel('先连接 Max，再从角色库导入 T-pose。');self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText);self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);outer.addWidget(self.status)
        self.wheel_router=WheelRouter(self,self.editor.current_scroll)
        path=self.settings.get('library') or str(context.data_root/'library')
        self.guard(lambda:self.load_library(path))
        self.active_session=self.settings.get('session')
        self.auto_reconnect=True
        self.timer=QTimer(self);self.timer.setInterval(750);self.timer.timeout.connect(self.poll);self.timer.start();self.poll()

    def button(self,title,fn):
        b=QPushButton(title);b.clicked.connect(lambda _:self.guard(fn));return b
    def guard(self,fn):
        try:return fn()
        except Exception as exc:self.set_status('操作失败：'+str(exc))
    def set_status(self,text):
        if not self.closed:self.status.setText(str(text))
    def busy(self):return self.pending is not None or self.launching is not None or any(j.isRunning() for j in self.jobs)
    def idle(self):
        if self.busy():raise ValueError('当前任务尚未完成，请等待。')
    def persist(self):
        self.settings.update(character=self.active_character,session=self.active_session)
        if self.library:self.settings['library']=str(self.library.root)
        self.context.save_settings(self.settings)
    def run_job(self,fn,label,done=None):
        if any(j.isRunning() for j in self.jobs):raise ValueError('文件操作进行中，请等待。')
        self.set_status(label);job=Job(fn,self);self.jobs.append(job)
        def completed(value,error):
            if self.closed:return
            if error:self.set_status('操作失败：'+error)
            elif done:self.guard(lambda:done(value))
            else:self.set_status(str(value))
        job.done.connect(completed);job.start()
    def require_library(self):
        if not self.library:raise ValueError('请先设置资产库。')
        return self.library
    def selected_session(self):
        matches=[s for s in host.sessions() if s['directory']==self.active_session]
        if not matches:raise ValueError('请连接一个 Max 窗口。')
        if matches[0].get('protocol',1)<2:raise ValueError('Max 连接脚本需要更新，请重新运行本工具的连接脚本。')
        return matches[0]
    def character_info(self):
        self.require_library()
        if not self.active_character:raise ValueError('请先从角色库导入并选择角色。')
        info=self.library.character_info(self.active_character)
        if not info['tpose']:raise ValueError('此旧版角色没有 T-pose，请在角色库更新。')
        return info
    def selected_asset(self):
        item=self.assets.currentItem()
        if not item:raise ValueError('请先选择一项资产。')
        return item.data(0,Qt.ItemDataRole.UserRole)
    def load_library(self,path):
        self.editor.flush();self.library=Library(path);self.library.initialize()
        names=self.library.characters();previous=self.settings.get('character')
        self.active_character=previous if previous in names else (names[0] if names else None)
        self.editor.set_asset(None,None);self.update_character_header();self.refresh_assets(flush=False);self.persist()
    def update_character_header(self):
        icon=self.context.resource('.lxtool/icon.png');self.character_title.setText(self.active_character or '选择一个角色')
        if self.active_character:
            info=self.library.character_info(self.active_character)
            if info.get('avatar'):
                target=contained(self.library.root/'characters'/self.active_character,info['avatar'])
                if target.is_file():icon=target
        self.avatar.setPixmap(QPixmap(str(icon)).scaled(58,58,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
    def choose_character(self,name):
        self.idle();self.editor.flush();self.active_character=name;self.editor.set_asset(None,None)
        self.update_character_header();self.refresh_assets(flush=False);self.persist()
    def open_gallery(self):
        self.require_library()
        if self.gallery is None:
            self.gallery=CharacterDialog(self)
        self.gallery.reload_categories();self.gallery.show();self.gallery.raise_();self.gallery.activateWindow()
    def refresh_assets(self,*_,flush=True,select_id=None):
        if not self.library:return
        if flush:self.editor.flush()
        if not select_id and self.assets.currentItem():select_id=self.selected_asset()['id']
        self.restoring=True;self.assets.setSortingEnabled(False);self.assets.clear()
        data,errors=self.library.list_assets(self.active_character) if self.active_character else ([],[])
        versions={}
        for asset in sorted(data,key=lambda a:a['created']):
            key=(asset['kind'],asset['name']);versions[key]=versions.get(key,0)+1;asset['_displayVersion']=versions[key]
        chosen=None
        for asset in data:
            if self.kind.currentData() and asset['kind']!=self.kind.currentData():continue
            if self.search.text().casefold() not in (asset['name']+' '+asset.get('notes','')).casefold():continue
            item=QTreeWidgetItem([asset['name'],KINDS[asset['kind']],f"v{asset['_displayVersion']:03d}",asset.get('notes','')]);item.setToolTip(2,asset['revision']);item.setData(0,Qt.ItemDataRole.UserRole,asset)
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsEditable)
            self.assets.addTopLevelItem(item)
            if asset['id']==select_id:chosen=item
        self.assets.setSortingEnabled(True)
        if chosen:self.assets.setCurrentItem(chosen)
        self.restoring=False
        asset=chosen.data(0,Qt.ItemDataRole.UserRole) if chosen else None
        self.editor.set_asset(self.library,asset);self.update_selection_controls(asset)
        if errors:self.set_status('索引异常：'+'; '.join(errors))
    def asset_changed(self,item,old):
        if self.restoring:return
        try:self.editor.flush()
        except Exception as exc:
            self.set_status(str(exc));self.restoring=True;self.assets.setCurrentItem(old);self.restoring=False;return
        asset=item.data(0,Qt.ItemDataRole.UserRole) if item else None
        self.guard(lambda:self.editor.set_asset(self.library,asset));self.update_selection_controls(asset)
    def connect_max(self):
        self.idle();available=host.sessions()
        available=[s for s in available if s.get('protocol',1)>=2]
        if not available:self.start_max();return
        if len(available)==1:
            self.active_session=available[0]['directory'];self.auto_reconnect=False;self.persist();self.poll();return
        dialog=QDialog(self);dialog.setWindowTitle('选择唯一连接的 Max 窗口');layout=QVBoxLayout(dialog);combo=QComboBox()
        for session in available:combo.addItem(f"PID {session['pid']} · {session.get('scene') or '未命名场景'}",session['directory'])
        layout.addWidget(combo);buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec():self.active_session=combo.currentData();self.auto_reconnect=False;self.persist();self.poll()
    def disconnect(self):self.idle();self.active_session=None;self.auto_reconnect=False;self.persist();self.poll()
    def connection_help(self):
        script=self.context.resource('max/bootstrap.ms')
        QMessageBox.information(self,'连接 Max',f'在需要连接的 Max 窗口中，通过 Scripting → Run Script 运行：\n\n{script}\n\n随后点击“连接 Max”选择该窗口。一次只绑定一个窗口。')
    def capture(self,kind,update=None,replace=None):
        self.idle();library=self.require_library();session=self.selected_session();self.editor.flush()
        info=self.character_info() if kind!='model' else None
        dialog=CaptureDialog(self,kind,update)
        if replace:dialog.name.setText(replace['name']);dialog.notes.setText(replace.get('notes',''))
        if not replace and not dialog.exec():return
        name=dialog.name.text().strip();character=name if kind=='model' else self.active_character
        if kind=='model' and not update and any(c.casefold()==name.casefold() for c in library.characters()):raise ValueError('角色已存在，请使用更新 T-pose。')
        stage=library.stage()
        args={'directory':str(stage),'kind':kind,'rig':dialog.rig.currentText() if kind=='model' else info.get('rig','Generic'),
              'sceneRange':True,'includeTextures':dialog.textures.isChecked(),'captureAvatar':kind=='model' and dialog.avatar.isChecked()}
        if info:
            args['includeTextures']=bool(info['tpose']['metadata'].get('includeTextures',False))
            expected=info['tpose']['metadata'].get('signature')
            if not expected:raise ValueError('角色缺少完整场景清单，请先在角色库更新 T-pose。')
            args['expected']=expected
        else:args['strictSelection']=True
        result=host.request(session,'export',**args)
        self.pending={'result':str(result),'time':time.time(),'stage':stage,'kind':kind,'name':name,'character':character,'category':dialog.category.currentData() or '',
                      'update':bool(update),'notes':dialog.notes.text(),'replace':replace,'session':session['directory'],'type':'export'}
        self.set_status('正在读取所连接 Max 的当前场景…')
    def overwrite(self):
        asset=self.selected_asset()
        if asset['kind']=='model':self.capture('model',update=self.active_character)
        else:self.capture(asset['kind'],replace=asset)
    def send_to_max(self,asset):
        self.idle();self.editor.flush();session=self.selected_session();library=self.library
        def ready(path):
            result=host.request(session,'import',path=str(path),kind=asset['kind'],rig=asset.get('metadata',{}).get('rig','Generic'))
            self.pending={'result':str(result),'time':time.time(),'type':'import','session':session['directory']}
            self.set_status('正在替换 Max 当前场景…' if asset['kind']=='animation' else '正在向 Max 应用资产…')
        self.run_job(lambda:library.verify(asset),'正在校验库文件…',ready)
    def update_selection_controls(self,asset):
        self.save_button.setEnabled(asset is not None)
        self.selection_label.setText(asset['name'] if asset else '未选择资产')
        self.selection_label.setToolTip(asset['name'] if asset else '')

    def asset_metadata_changed(self,item,column):
        if self.restoring or column not in (0,3):return
        asset=item.data(0,Qt.ItemDataRole.UserRole)
        if not asset:return
        try:
            self.idle();self.editor.flush()
            from .library import safe_name,write_json
            key='name' if column==0 else 'notes';value=safe_name(item.text(column)) if column==0 else item.text(column)
            path=contained(self.library.root,Path(asset['_directory']).relative_to(self.library.root))/'asset.json'
            data=read_json(path);data[key]=value;write_json(path,data)
            asset[key]=value;self.restoring=True;item.setData(0,Qt.ItemDataRole.UserRole,asset);self.restoring=False
            self.update_selection_controls(asset)
            if self.editor.asset and self.editor.asset['id']==asset['id']:
                self.editor.asset[key]=value;self.editor.title.setText(asset['name']+' · Clip 拆分')
            self.set_status('资产信息已保存。')
        except Exception as exc:
            self.restoring=True;item.setText(column,asset['name' if column==0 else 'notes']);self.restoring=False
            self.set_status('修改未保存：'+str(exc))

    def choose_max_program(self):
        path,_=QFileDialog.getOpenFileName(self,'选择 3ds Max 程序',self.settings.get('maxExecutable',''),'3ds Max (3dsmax.exe)')
        if path:
            if Path(path).name.lower()!='3dsmax.exe':raise ValueError('请选择 3dsmax.exe。')
            self.settings['maxExecutable']=path;self.persist()
        return path

    def start_max(self):
        if self.launching:
            self.set_status('Max 正在启动，就绪后会自动连接，请稍候。');return
        self.idle();available=host.sessions()
        selected=host.preferred_session(available,self.active_session or self.settings.get('session'))
        if selected:
            self.active_session=selected['directory'];self.auto_reconnect=False;self.persist();self.poll()
            self.set_status('已连接 Max，无需重复启动。');return
        if any(s.get('protocol',1)>=2 for s in available):self.connect_max();return
        path=host.preferred_max(self.settings.get('maxExecutable',''))
        if not path:path=self.choose_max_program()
        if not path:return
        process=host.launch_max(path,self.context.resource('max/bootstrap.ms'))
        self.settings['maxExecutable']=str(path);self.active_session=None
        self.auto_reconnect=False
        self.launching={'process':process,'pid':process.pid,'time':time.time()};self.persist()
        self.set_status('正在启动 Max，连接脚本就绪后自动绑定该窗口…')

    def library_settings(self):
        self.idle();self.editor.flush();dialog=QDialog(self);dialog.setWindowTitle('资产库与同步');dialog.resize(650,200);form=QFormLayout(dialog)
        row=QHBoxLayout();path=QLineEdit(str(self.library.root) if self.library else '');row.addWidget(path,1)
        def browse():
            value=QFileDialog.getExistingDirectory(dialog,'选择资产库',path.text())
            if value:path.setText(value)
        row.addWidget(self.button('选择目录',browse));form.addRow('本地目录',row)
        remote=QLineEdit(self.settings.get('remote',''));form.addRow('GitHub 仓库',remote)
        def apply():
            self.settings['remote']=remote.text().strip();self.load_library(path.text());dialog.accept()
        form.addRow(self.button('应用目录',apply));row=QHBoxLayout()
        def sync(operation):
            if Path(path.text()).resolve()!=self.library.root:raise ValueError('请先应用目录。')
            self.settings['remote']=remote.text().strip();self.persist();dialog.accept();library=self.library
            fn=(lambda:host.init_git(library.root,self.settings['remote'])) if operation=='init' else (lambda:host.sync_git(library.root,operation))
            self.run_job(fn,'正在同步资产库…',lambda message:(self.refresh_assets(),self.set_status(message)))
        for title,operation in [('初始化 Git LFS','init'),('拉取','pull'),('保存并推送','push')]:row.addWidget(self.button(title,lambda operation=operation:sync(operation)))
        form.addRow(row);dialog.exec()
    def poll(self):
        if self.closed:return
        available=host.sessions()
        if self.auto_reconnect and not self.launching:
            selected=host.preferred_session(available,self.active_session)
            if selected:
                self.active_session=selected['directory'];self.auto_reconnect=False;self.persist()
        if self.launching:
            started=next((s for s in available if s['pid']==self.launching['pid'] and s.get('protocol',1)>=2),None)
            if started:
                self.active_session=started['directory'];self.launching=None;self.persist();self.set_status('Max 已启动并连接。')
            elif self.launching['process'].poll() is not None or time.time()-self.launching['time']>240:
                self.launching=None;self.set_status('Max 未返回连接，请检查启动界面，再从“连接”菜单选择窗口。')
        matches=[s for s in available if s['directory']==self.active_session]
        if matches:
            session=matches[0];self.connection.setText(f"● Max · PID {session['pid']} · {Path(session.get('scene') or '未命名场景').name}  |  {session.get('start','?')} — {session.get('end','?')} 帧 · {session.get('fps','?')} FPS · 当前 {session.get('frame','?')}")
        else:self.connection.setText('◌ 正在启动 Max…' if self.launching else ('○ Max 未连接' if not self.active_session else '○ Max 连接已断开'))
        pending=self.pending
        if not pending:return
        path=Path(pending['result'])
        if path.exists():
            self.pending=None
            def consume():
                result=read_json(path)
                if not result.get('ok'):raise ValueError(result.get('message','Max 操作失败'))
                if pending['type']=='import':self.set_status(result.get('message','完成。'));return
                library=self.library
                def publish():
                    if pending['kind']=='model':asset=library.import_character(pending['character'],pending['stage'],result['main'],result['metadata'],pending['category'],pending['update'])
                    else:asset=library.publish(pending['character'],pending['name'],pending['kind'],pending['stage'],result['main'],pending['notes'],result['metadata'])
                    if pending['replace']:
                        warning=library.mark_superseded(pending['replace'],asset)
                        if warning:result.setdefault('warnings',[]).append(warning)
                    shutil.rmtree(pending['stage']);return asset
                def finished(asset):
                    self.active_character=pending['character'];self.editor.set_asset(None,None);self.update_character_header();self.refresh_assets(flush=False,select_id=asset['id']);self.persist()
                    if self.gallery:self.gallery.reload_categories()
                    self.set_status('已更新库。'+(' · '+'; '.join(result.get('warnings',[])) if result.get('warnings') else ''))
                self.run_job(publish,'正在归档 Max 场景与配置…',finished)
            self.guard(consume)
        elif time.time()-pending['time']>180:self.set_status('Max 尚未返回结果，仍在等待；不会重复提交或切换窗口。')
    def shutdown(self):
        if self.closed:return
        try:self.editor.flush()
        except Exception:
            if self.editor.data:
                from .library import write_json
                write_json(self.context.data_root/'clip-recovery.json',{'assetId':self.editor.asset['id'],'lastValid':self.editor.data,'extraText':self.editor.extra.toPlainText()})
        self.closed=True;self.timer.stop();self.wheel_router.stop()
        if self.gallery:self.gallery.close()
        for job in self.jobs:
            if job.isRunning():job.setParent(None);_finishing.append(job);job.finished.connect(lambda j=job:_release(j))

_finishing=[]
def _release(job):
    if job in _finishing:_finishing.remove(job)
    job.deleteLater()

def create_panel(context,parent):return Panel(context,parent)
