"""LXTool embedded character and animation workspace; no standalone application."""
from datetime import datetime
from pathlib import Path
import os
import shutil
import time
from PySide6.QtCore import Qt,QTimer,QThread,Signal,QSize
from PySide6.QtGui import QPixmap,QColor
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,QLineEdit,QTreeWidget,QTreeWidgetItem,
    QComboBox,QFileDialog,QSplitter,QHeaderView,QTabBar,QSizePolicy,QLayout,QDialog,QDialogButtonBox,QFormLayout,QMessageBox,QInputDialog,QToolButton,QMenu,QApplication,QFrame,QBoxLayout)
from .library import Library,KINDS,frame_payload,read_json,contained
from . import integrations as host
from . import max_connection
from .clip_editor import ClipEditor
from .dialogs import AssetDetailsDialog,CharacterDialog,CreateAssetDialog,LibrarySyncDialog
from .widgets import WheelRouter,AssetTree,ElidedLabel
from .asset_git_status import asset_git_state,asset_paths,asset_status
from .asset_git_push import push_asset
from .git_access import access_state,describe_git_error


class Job(QThread):
    done=Signal(object,str)
    def __init__(self,fn,parent):super().__init__(parent);self.fn=fn
    def run(self):
        try:self.done.emit(self.fn(),'')
        except Exception as exc:self.done.emit(None,str(exc))


class Panel(QWidget):
    def __init__(self,context,parent=None):
        super().__init__(parent)
        self.context=context
        self.settings=context.load_settings()
        self.registration_error=''
        self.attach=None
        try:
            if QApplication.platformName()!='offscreen':
                self.attach=max_connection.AutoAttach('max-animation',context)
            max_connection.register('max-animation',context)
        except (OSError,ValueError) as error:
            self.registration_error=str(error)
        self.waiting_target=None
        self.library=None;self.active_character=None;self.active_session=self.settings.get('session');self.pending=None;self.launching=None
        self.jobs=[];self.closed=False;self.gallery=None;self.restoring=False
        self.setObjectName('LXAnimation')
        self.setStyleSheet("""
            QWidget#LXAnimation {background:#f5f7f2;color:#2c382c;}
            QWidget#ClipWorkspace {background:#ffffff;border-radius:9px;}
            QWidget#ClipWorkspace[empty="true"] {background:#ffffff;}
            QWidget#SettingsBody {background:#ffffff;}
            QWidget:disabled {color:#9ca595;}
            QLineEdit,QComboBox,QDoubleSpinBox,QSpinBox,QPlainTextEdit {
                background:#fcfdf9;color:#33442c;border:1px solid #d5dfca;border-radius:8px;padding:7px 11px;
                selection-background-color:#dcebc6;selection-color:#2c421d;}
            QLineEdit:hover,QComboBox:hover,QDoubleSpinBox:hover,QSpinBox:hover,QPlainTextEdit:hover {border-color:#aabc91;}
            QLineEdit:focus,QComboBox:focus,QDoubleSpinBox:focus,QSpinBox:focus,QPlainTextEdit:focus {background:#fff;border:1px solid #86a857;}
            QLineEdit,QComboBox,QDoubleSpinBox,QSpinBox {min-height:20px;}
            QComboBox {padding-right:36px;}
            QComboBox::drop-down {subcontrol-origin:padding;subcontrol-position:top right;width:30px;
                border:0;border-left:1px solid #e0e7d6;border-top-right-radius:7px;border-bottom-right-radius:7px;background:#eef4e5;}
            QComboBox::drop-down:hover {background:#e0edce;}
            QComboBox::down-arrow {image:url("__ICONS__/chevron-down.svg");width:12px;height:12px;}
            QComboBox QAbstractItemView {background:#fcfdf9;color:#33442c;border:1px solid #b8cba0;
                padding:5px;outline:0;selection-background-color:#e2edcf;selection-color:#304620;}
            QComboBox QAbstractItemView::item {min-height:28px;padding:4px 9px;}
            QDoubleSpinBox,QSpinBox {padding-right:31px;}
            QDoubleSpinBox::up-button,QSpinBox::up-button {subcontrol-origin:border;subcontrol-position:top right;
                width:27px;border:0;border-left:1px solid #e0e7d6;border-top-right-radius:7px;background:#eef4e5;}
            QDoubleSpinBox::down-button,QSpinBox::down-button {subcontrol-origin:border;subcontrol-position:bottom right;
                width:27px;border:0;border-left:1px solid #e0e7d6;border-bottom-right-radius:7px;background:#eef4e5;}
            QDoubleSpinBox::up-button:hover,QSpinBox::up-button:hover,QDoubleSpinBox::down-button:hover,QSpinBox::down-button:hover {background:#e0edce;}
            QDoubleSpinBox::up-arrow,QSpinBox::up-arrow {image:url("__ICONS__/chevron-up.svg");width:10px;height:10px;}
            QDoubleSpinBox::down-arrow,QSpinBox::down-arrow {image:url("__ICONS__/chevron-down.svg");width:10px;height:10px;}
            QLineEdit:disabled,QComboBox:disabled,QDoubleSpinBox:disabled,QSpinBox:disabled,QPlainTextEdit:disabled {background:#fff;color:#9ca595;}
            QPushButton,QToolButton {padding:7px 10px;border:1px solid #ccd9bf;border-radius:6px;background:#edf3e5;color:#35512b;}
            QPushButton:hover,QToolButton:hover {background:#dcebc9;border-color:#a7bd8f;}
            QPushButton:disabled,QToolButton:disabled {background:#edf3e5;color:#9ca595;border-color:#ccd9bf;}
            QTreeWidget {background:#fff;alternate-background-color:#f5f8f1;border:1px solid #d7e0d0;border-radius:7px;}
            QTreeWidget::item {padding:6px;}
            QTreeWidget::item:selected {background:#dcecc9;color:#243e1c;}
            QTreeWidget:disabled {background:#fff;color:#9ca595;}
            QHeaderView::section:disabled {color:#9ca595;}
            QTabBar::tab:disabled {color:#9ca595;}
            QTabBar::tab:selected:disabled {background:#fff;color:#9ca595;}
            QHeaderView::section {background:#edf2e7;border:0;border-bottom:1px solid #d6e0cc;border-right:2px solid #81986b;padding:7px;color:#516346;}
            QTabWidget::pane {border:1px solid #dce4d4;border-radius:5px;background:#fff;}
            QTabBar::tab {padding:8px 13px;background:#edf2e8;color:#617154;border:0;}
            QTabBar::tab:selected {background:#fff;color:#385623;border-bottom:3px solid #92b85b;}
            QSplitter::handle:horizontal {background:#bbcba9;border-radius:3px;margin:8px 1px;}
            QSplitter::handle:horizontal:hover {background:#88a862;}
            QScrollArea {border:0;background:transparent;}
            QScrollBar:vertical {width:10px;background:#f0f3eb;}
            QScrollBar::handle:vertical {background:#b5c5a5;border-radius:4px;min-height:24px;}
        """.replace('__ICONS__',(Path(__file__).parent/'icons').as_posix()))
        outer=QVBoxLayout(self);outer.setContentsMargins(10,8,10,8);outer.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.setMinimumSize(360,300)
        row=QHBoxLayout();self.avatar=QLabel();self.avatar.setFixedSize(38,38);row.addWidget(self.avatar)
        self.character_title=ElidedLabel('选择一个角色');self.character_title.setStyleSheet('font-size:18px;font-weight:650');row.addWidget(self.character_title,1)
        row.addWidget(self.button('角色库',self.open_gallery))
        self.connect_button=self.button('连接 Max',self.start_max);row.addWidget(self.connect_button)
        more=QToolButton();more.setText('更多');more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup);menu=QMenu(more)
        for title,fn in [('切换 Max 窗口',self.connect_max),('断开连接',self.disconnect),('更换 Max 程序',self.choose_max_program)]:menu.addAction(title,lambda fn=fn:self.guard(fn))
        more.setMenu(menu);row.addWidget(more)
        self.register_character=self.button('创建角色',lambda:self.create_asset(new_character=True))
        row.addWidget(self.register_character)
        outer.addLayout(row)
        connection_row=QHBoxLayout()
        self.connection=ElidedLabel('尚未连接 Max')
        connection_row.addWidget(self.connection,1)
        self.editing_asset=self.settings.get('editingAsset')
        self.editing_label=ElidedLabel('当前编辑：未绑定资产')
        self.editing_label.setStyleSheet("color:#526747;font-weight:600;")
        connection_row.addWidget(self.editing_label,1)
        outer.addLayout(connection_row)
        outer.addWidget(self.library_controls())
        self.narrow_tabs=QTabBar();self.narrow_tabs.addTab('资产浏览');self.narrow_tabs.addTab('资产 / Clip 编辑');self.narrow_tabs.setExpanding(True)
        self.narrow_tabs.currentChanged.connect(self.update_workspace);outer.addWidget(self.narrow_tabs);self.narrow_tabs.hide()
        self.split=QSplitter();self.split.setHandleWidth(8);outer.addWidget(self.split,1)
        self.left=left=QWidget();left.setMinimumWidth(220);leftbox=QVBoxLayout(left);leftbox.setContentsMargins(0,4,4,0)
        self.search=QLineEdit();self.search.setPlaceholderText('搜索动画 / Pose / 备注');self.search.textChanged.connect(lambda:self.guard(self.refresh_assets));leftbox.addWidget(self.search)
        row=QHBoxLayout();self.kind=QComboBox();self.kind.addItem('全部资产','');[self.kind.addItem(v,k) for k,v in KINDS.items()]
        self.kind.currentIndexChanged.connect(lambda:self.guard(self.refresh_assets));row.addWidget(self.kind,1)
        self.version_choice=QComboBox()
        self.version_choice.setAccessibleName('资产版本')
        self.version_choice.setPlaceholderText('版本')
        self.version_choice.setToolTip('切换所选资产的版本')
        self.version_choice.currentIndexChanged.connect(self.asset_version_changed)
        self.version_choice.setMaximumWidth(110)
        row.addWidget(self.version_choice)
        leftbox.addLayout(row)
        self.assets=AssetTree();self.assets.setAlternatingRowColors(True);self.assets.setHeaderLabels(['名称','类型','版本','状态','备注']);self.assets.setRootIsDecorated(False);self.assets.setSortingEnabled(True);self.assets.sortItems(0,Qt.SortOrder.AscendingOrder)
        self.assets.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.assets.header().setCascadingSectionResizes(False)
        self.assets.header().setStretchLastSection(True)
        self.assets.header().setToolTip("拖动表头分隔线，调整分隔线左侧的列")
        self.assets.setColumnWidth(0,104)
        self.assets.setColumnWidth(1,60);self.assets.setColumnWidth(2,48);self.assets.setColumnWidth(3,104)
        self.assets.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.assets.customContextMenuRequested.connect(self.asset_menu)
        self.assets.currentItemChanged.connect(self.asset_changed)
        self.assets.itemChanged.connect(self.asset_metadata_changed);leftbox.addWidget(self.assets,1)
        management=QHBoxLayout()
        self.create_asset_button=self.button('创建资产',self.create_asset)
        management.addWidget(self.create_asset_button)
        self.push_asset_button=self.button('推送此动画',self.push_selected_animation)
        self.push_asset_button.setVisible(False)
        management.addWidget(self.push_asset_button)
        leftbox.addLayout(management)
        self.split.addWidget(left)
        self.right=right=QWidget();right.setMinimumWidth(340);rightbox=QVBoxLayout(right);rightbox.setContentsMargins(4,4,0,0)
        self.selection_label=ElidedLabel('未选择资产');self.selection_label.setStyleSheet('font-size:15px;font-weight:650')
        selection=QHBoxLayout();selection.addWidget(self.selection_label,3)
        self.asset_summary=ElidedLabel('从资产列表选择一项');selection.addWidget(self.asset_summary,2)
        self.selected_asset_status=ElidedLabel()
        self.selected_asset_status.setMinimumWidth(76)
        self.selected_asset_status.setStyleSheet('color:#50723d;font-weight:600;')
        selection.addWidget(self.selected_asset_status,1)
        rightbox.addLayout(selection)
        row=QHBoxLayout()
        self.save_button=self.button('保存修改',self.save_changes)
        self.apply_button=self.button('覆盖场景',lambda:self.send_to_max(self.selected_asset()))
        self.key_asset=self.button('覆盖帧',self.key_selected_asset)
        for button in (self.save_button,self.apply_button,self.key_asset):
            row.addWidget(button,1)
        self.save_button.setStyleSheet("QPushButton:enabled {background:#dcebc9;border-color:#b8cba0;font-weight:600;}")
        rightbox.addLayout(row)
        self.delete_asset_button=QToolButton()
        self.delete_asset_button.setText('删除资产…')
        self.delete_asset_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        delete_menu=QMenu(self.delete_asset_button)
        delete_menu.addAction('删除所选版本',lambda:self.guard(lambda:self.delete_asset(False)))
        delete_menu.addAction('删除全部版本',lambda:self.guard(lambda:self.delete_asset(True)))
        self.delete_asset_button.setMenu(delete_menu)
        management.addWidget(self.delete_asset_button)
        self.asset_scan=QTimer(self)
        self.asset_scan.setSingleShot(True)
        self.asset_scan.timeout.connect(lambda:self.guard(self.scan_asset_status))
        self.editor=ClipEditor()
        self.editor.message.connect(self.set_status)
        self.editor.written.connect(self.schedule_asset_scan)
        rightbox.addWidget(self.editor,1)
        self.split.addWidget(right);self.split.setSizes([300,700]);self.split.setStretchFactor(0,1);self.split.setStretchFactor(1,2);self.split.setChildrenCollapsible(False)
        self.status=ElidedLabel('先创建角色和资产，再连接 Max 保存修改。');outer.addWidget(self.status)
        draft_path=context.data_root/'clip-drafts.json'
        if draft_path.is_file():self.guard(lambda:setattr(self.editor,'recovery',read_json(draft_path)))
        self.editor.restore_view(self.settings.get('editorView',{}))
        self.remembered_assets=self.settings.get('selectedAssets',{})
        self.search.setText(self.settings.get('assetSearch',''));self.kind.setCurrentIndex(max(0,self.kind.findData(self.settings.get('assetKind',''))))
        self.wheel_router=WheelRouter(self,self.editor.current_scroll)
        path=self.settings.get('library') or str(context.data_root/'library')
        self.guard(lambda:self.load_library(path))
        self.active_session=self.settings.get('session')
        self.auto_reconnect=True
        if self.registration_error:self.set_status('Max 启动接入设置未能写入：'+self.registration_error)
        self.timer=QTimer(self);self.timer.setInterval(750);self.timer.timeout.connect(self.poll);self.timer.start();self.poll();self.update_workspace()

    def minimumSizeHint(self):return QSize(360,300)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'narrow_tabs'):self.update_workspace()

    def update_workspace(self,*_):
        narrow=self.width()<820
        self.narrow_tabs.setVisible(narrow)
        self.left.setVisible(not narrow or self.narrow_tabs.currentIndex()==0)
        self.right.setVisible(not narrow or self.narrow_tabs.currentIndex()==1)
        self.update_library_layout()

    def button(self,title,fn):
        b=QPushButton(title);b.clicked.connect(lambda _:self.guard(fn));return b
    def guard(self,fn):
        try:return fn()
        except Exception as exc:self.set_status('操作失败：'+describe_git_error(exc))
    def set_status(self,text):
        if not self.closed:self.status.setText(str(text))
    def busy(self):return self.pending is not None or self.launching is not None or any(j.isRunning() for j in self.jobs)
    def idle(self):
        if self.busy():raise ValueError('当前任务尚未完成，请等待。')
    def persist(self):
        self.settings.update(character=self.active_character,session=self.active_session,editorView=self.editor.view_state(),selectedAssets=self.remembered_assets,editingAsset=self.editing_asset,assetSearch=self.search.text(),assetKind=self.kind.currentData())
        if self.library:self.settings['library']=str(self.library.root)
        self.context.save_settings(self.settings)
    def run_job(self,fn,label,done=None):
        if any(j.isRunning() for j in self.jobs):raise ValueError('文件操作进行中，请等待。')
        self.set_status(label);job=Job(fn,self);self.jobs.append(job)
        def completed(value,error):
            if self.closed:return
            if error:self.set_status('操作失败：'+describe_git_error(error))
            elif done:self.guard(lambda:done(value))
            else:self.set_status(str(value))
        job.done.connect(completed);job.start()
    def require_library(self):
        if not self.library:raise ValueError('请先设置资产库。')
        return self.library
    def selected_session(self):
        matches=[s for s in host.sessions() if s['directory']==self.active_session]
        if not matches:raise ValueError('请连接一个 Max 窗口。')
        if matches[0].get('assetWorkspace')!=1:raise ValueError('Max 正在等待自动连接。')
        return matches[0]
    def character_info(self):
        self.require_library()
        if not self.active_character:raise ValueError('请先从角色库导入并选择角色。')
        info=self.library.character_info(self.active_character)
        if not info['reference']:raise ValueError('此角色缺少可用场景，请先在角色库保存 T-pose。')
        return info
    def selected_asset(self):
        item=self.assets.currentItem()
        if not item:raise ValueError('请先选择一项资产。')
        return self.version_choice.currentData() or item.data(0,Qt.ItemDataRole.UserRole)
    def load_library(self,path):
        self.editor.flush();self.library=Library(path,lambda:host.git_identity(Path(path).resolve()));self.library.initialize()
        self.asset_sync_data=None if (self.library.root/'.git').exists() else {}
        names=self.library.characters();previous=self.settings.get('character')
        self.active_character=previous if previous in names else (names[0] if names else None)
        self.editor.set_asset(None,None);self.update_character_header();self.refresh_assets(flush=False);self.persist()
        self.library_state=None
        self.library_last_cloud=None
        self.library_feedback=''
        self.update_library_controls()
        if (self.library.root/'.git').exists():
            self.library_action('local')
    def update_character_header(self):
        icon=self.context.resource('.lxtool/icon.png');self.character_title.setText(self.active_character or '选择一个角色')
        if self.active_character:
            info=self.library.character_info(self.active_character)
            if info.get('avatar'):
                target=contained(self.library.root/'characters'/self.active_character,info['avatar'])
                if target.is_file():icon=target
        self.avatar.setPixmap(QPixmap(str(icon)).scaled(38,38,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
    def choose_character(self,name):
        self.idle();self.editor.flush();self.active_character=name;self.editor.set_asset(None,None)
        self.update_character_header();self.refresh_assets(flush=False);self.persist()
    def delete_character(self,name):
        self.idle()
        self.editor.flush()
        self.library.delete_character(name)
        self.remembered_assets.pop(name,None)
        if self.active_character==name:
            self.active_character=None
            self.editor.set_asset(None,None)
            self.update_character_header()
            self.refresh_assets(flush=False)
        self.persist()
        if self.gallery:self.gallery.refresh()
        self.set_status(f'已删除角色「{name}」，可从库内回收目录找回文件。')

    def open_gallery(self):
        self.require_library()
        if self.gallery is None:
            self.gallery=CharacterDialog(self)
        self.gallery.reload_categories();self.gallery.show();self.gallery.raise_();self.gallery.activateWindow()
    def refresh_assets(self,*_,flush=True,select_id=None):
        if not self.library:return
        if flush:self.editor.flush()
        selected_revision=select_id or (self.selected_asset()['id'] if self.assets.currentItem() else None)
        select_id=selected_revision or self.remembered_assets.get(self.active_character)
        self.restoring=True;self.assets.setSortingEnabled(False);self.assets.clear()
        data,errors=self.library.list_assets(self.active_character) if self.active_character else ([],[])
        groups={}
        for asset in data:
            if self.kind.currentData() and asset['kind']!=self.kind.currentData():continue
            groups.setdefault((asset['kind'],asset['name']),[]).append(asset)
        chosen=None;chosen_version=None
        for (kind,name),versions in groups.items():
            latest=versions[0]
            if not any(self.search.text().casefold() in (name+' '+a.get('notes','')).casefold() for a in versions):
                continue
            for number,version in enumerate(reversed(versions),1):
                version['_displayVersion']=number
            item=QTreeWidgetItem([name,KINDS[kind],str(len(versions)),'',latest.get('notes','')])
            item.setToolTip(0,name);item.setToolTip(4,latest.get('notes',''))
            self.mark_asset_item(item,versions)
            item.setData(0,Qt.ItemDataRole.UserRole,latest)
            item.setData(0,Qt.ItemDataRole.UserRole+1,versions)
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsEditable)
            self.assets.addTopLevelItem(item)
            # Keep the current group, while explicit capture can select its new revision.
            if any(a['id']==select_id for a in versions):
                chosen=item
                chosen_version=next((a for a in versions if a['id']==selected_revision),None)
        self.assets.setSortingEnabled(True)
        if chosen:self.assets.setCurrentItem(chosen)
        self.restoring=False
        self.load_asset_versions(chosen,chosen_version)
        if errors:self.set_status('索引异常：'+'; '.join(errors))
    def mark_asset_item(self,item,versions):
        try:
            state=asset_status(self.asset_sync_data,asset_paths(self.library.root,versions))
        except ValueError as error:
            state={'text':'路径异常','detail':str(error),'code':'conflict'}
        color={'latest':'#4b7438','behind':'#956026','modified':'#365b94','ahead':'#365b94',
               'conflict':'#a3303b','diverged':'#a3303b'}.get(state['code'],'#657465')
        item.setText(3,state['text'])
        item.setForeground(3,QColor(color))
        item.setToolTip(3,state['detail'])

    def update_asset_marks(self):
        was_restoring=self.restoring
        self.restoring=True
        try:
            for index in range(self.assets.topLevelItemCount()):
                item=self.assets.topLevelItem(index)
                self.mark_asset_item(item,item.data(0,Qt.ItemDataRole.UserRole+1) or ())
        finally:
            self.restoring=was_restoring
        self.update_version_marks()

    def update_version_marks(self):
        if not self.library:
            return
        for index in range(self.version_choice.count()):
            asset=self.version_choice.itemData(index)
            try:
                state=asset_status(self.asset_sync_data,asset_paths(self.library.root,[asset],exact=True),
                                   historical=index!=0)
            except ValueError:
                continue
            self.version_choice.setItemData(index,state['detail'],Qt.ItemDataRole.ToolTipRole)
        selected=self.version_choice.currentData()
        if selected:
            try:
                state=asset_status(self.asset_sync_data,asset_paths(self.library.root,[selected],exact=True),
                                   historical=self.version_choice.currentIndex()!=0)
                self.selected_asset_status.setText(state['text'])
                self.selected_asset_status.setToolTip(state['detail'])
            except ValueError:
                self.selected_asset_status.clear()
        else:
            self.selected_asset_status.clear()

    def schedule_asset_scan(self):
        if self.library and (self.library.root/'.git').exists():
            self.asset_scan.start(420)

    def scan_asset_status(self):
        if self.closed or not self.library:
            return
        workspace=getattr(self.context,'workspace_state',{})
        if self.busy() or self.library_working or workspace.get('lxgit_working_root')==str(self.library.root):
            self.asset_scan.start(1000)
            return
        self.library_action('asset_status')

    def push_selected_animation(self):
        item=self.assets.currentItem()
        if item:
            self.push_animation_item(item)

    def push_animation_item(self,item):
        asset=item.data(0,Qt.ItemDataRole.UserRole)
        if asset['kind']!='animation':
            return
        self.library_action('push_asset',asset=asset)

    def asset_menu(self,position):
        item=self.assets.itemAt(position)
        if not item:
            return
        menu=QMenu(self.assets)
        menu.addAction('详情信息…',lambda:self.guard(lambda:self.open_asset_details(item)))
        asset=item.data(0,Qt.ItemDataRole.UserRole)
        if asset['kind']=='animation' and (self.library_state or {}).get('remote'):
            menu.addAction('推送此动画…',lambda:self.guard(lambda:self.push_animation_item(item)))
        menu.addAction('打开资产目录',lambda:self.guard(lambda:self.reveal_asset(
            self.selected_asset() if item is self.assets.currentItem() else item.data(0,Qt.ItemDataRole.UserRole))))
        menu.exec(self.assets.viewport().mapToGlobal(position))

    def reveal_asset(self,asset,version=False):
        group, folder = self.library.asset_location(asset)
        os.startfile(str(folder if version else group))

    def open_asset_details(self,item):
        self.idle()
        try:self.editor.flush()
        except ValueError:self.editor.keep_draft()
        asset=self.selected_asset() if item is self.assets.currentItem() else item.data(0,Qt.ItemDataRole.UserRole)
        dialog=AssetDetailsDialog(self,asset)
        dialog.exec()
        if dialog.changed:
            selected=dialog.selected()['id'] if dialog.versions.currentItem() else None
            self.remembered_assets.pop(self.active_character,None)
            self.refresh_assets(flush=False,select_id=selected)
            self.persist()
            if self.gallery:self.gallery.refresh()
            self.schedule_asset_scan()

    def asset_changed(self,item,old):
        if self.restoring:return
        try:self.editor.flush()
        except Exception as exc:
            self.set_status(str(exc));self.restoring=True;self.assets.setCurrentItem(old);self.restoring=False;return
        self.load_asset_versions(item)
        if item and self.narrow_tabs.isVisible():self.narrow_tabs.setCurrentIndex(1)

    def load_asset_versions(self,item,selected=None):
        versions=item.data(0,Qt.ItemDataRole.UserRole+1) if item else []
        self.version_choice.blockSignals(True)
        try:
            self.version_choice.clear()
            for index,asset in enumerate(versions):
                suffix=' · 最新' if index==0 else ' · 旧版本'
                self.version_choice.addItem(f"v{asset['_displayVersion']:03d}{suffix}",asset)
                self.version_choice.setItemData(index,asset['revision'],Qt.ItemDataRole.ToolTipRole)
            if versions:self.version_choice.setCurrentIndex(0)
            if selected:
                index=next(i for i,asset in enumerate(versions) if asset['id']==selected['id'])
                self.version_choice.setCurrentIndex(index)
            self.version_choice.setEnabled(bool(versions))
        finally:
            self.version_choice.blockSignals(False)
        asset=self.version_choice.currentData()
        self.editor.set_asset(self.library,asset)
        self.update_selection_controls(asset)

    def asset_version_changed(self,index):
        asset=self.version_choice.itemData(index)
        if not asset:return
        try:self.editor.flush()
        except Exception as error:
            self.set_status(str(error))
            old=self.editor.asset
            for i in range(self.version_choice.count()):
                if old and self.version_choice.itemData(i)['id']==old['id']:
                    self.version_choice.blockSignals(True)
                    self.version_choice.setCurrentIndex(i)
                    self.version_choice.blockSignals(False)
                    break
            return
        self.editor.set_asset(self.library,asset)
        self.update_selection_controls(asset)

    def select_max(self,window):
        live=max_connection.process_identity(window['pid'])
        if not live or live['birth']!=window['birth']:
            raise ValueError('该 Max 已退出，请重新选择。')
        self.waiting_target=(window['pid'],str(window['birth']))
        self.remember_max_target(window)
        self.active_session=None
        self.auto_reconnect=True
        self.persist()
        self.poll()

    def connect_max(self):
        self.idle()
        available=host.available_windows()
        if not available:self.start_max();return
        if len(available)==1:self.select_max(available[0]);return
        dialog=QDialog(self);dialog.setWindowTitle('选择 Max 窗口')
        layout=QVBoxLayout(dialog);combo=QComboBox()
        for window in available:
            status='已连接' if window['session'] and window['session'].get('assetWorkspace')==1 else '等待自动连接'
            combo.addItem(f"PID {window['pid']} · {window['title']} · {status}",window)
        layout.addWidget(combo)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec():self.select_max(combo.currentData())

    def disconnect(self):
        self.idle()
        self.active_session=None
        self.waiting_target=None
        self.auto_reconnect=False
        self.persist()
        self.poll()

    def create_asset(self,new_character=False):
        self.idle()
        library=self.require_library()
        if not new_character and not self.active_character:
            raise ValueError('请先创建角色。')
        dialog=CreateAssetDialog(self,new_character)
        if not dialog.exec():
            return
        self.editor.flush()
        character=dialog.character.text().strip() if new_character else self.active_character
        asset=library.create_asset(character,dialog.name.text(),dialog.kind.currentData(),new_character)
        self.active_character=character
        self.editor.set_asset(None,None)
        self.kind.setCurrentIndex(0)
        self.search.clear()
        self.update_character_header()
        self.refresh_assets(flush=False,select_id=asset['id'])
        if self.gallery:self.gallery.accept()
        if self.narrow_tabs.isVisible():self.narrow_tabs.setCurrentIndex(1)
        self.persist()
        self.set_status('已创建空资产，可在 Max 准备场景后保存修改。')
        self.schedule_asset_scan()

    def save_changes(self):
        self.idle()
        selected=self.selected_asset()
        self.editor.flush()
        session=self.selected_session()
        if session.get('assetWorkspace')!=1:
            raise ValueError('正在等待 Max 自动升级连接。')
        editing=self.bound_asset(session)
        dialog=QDialog(self)
        dialog.setWindowTitle('保存修改')
        dialog.setMinimumWidth(380)
        form=QFormLayout(dialog)
        form.addRow('目标资产',QLabel(selected['character']+' / '+selected['name']))
        if editing and editing['id']!=selected['id']:
            form.addRow('当前编辑',QLabel(editing['character']+' / '+editing['name']))
        kind=QComboBox()
        for value,title in [('animation','动画 · 整个时间轴'),('pose','Pose · 当前帧'),('model','T-pose · 当前帧')]:
            kind.addItem(title,value)
        kind.setCurrentIndex(kind.findData(selected['kind']))
        form.addRow('保存类型',kind)
        rig=QComboBox()
        rig.addItems(['Generic','Biped','CAT'])
        info=self.library.character_info(selected['character'])
        rig.setCurrentText(selected['metadata'].get('rig',info.get('rig','Generic')))
        form.addRow('骨架类型',rig)
        hint=QLabel('保存完整 Max 场景和可找到的贴图，生成新版本。')
        hint.setWordWrap(True);form.addRow(hint)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('保存新版本')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);form.addRow(buttons)
        if not dialog.exec():
            return
        stage=self.library.stage()
        try:
            result=host.request(session,'saveWorkspaceAsset',directory=str(stage),kind=kind.currentData(),
                                rig=rig.currentText(),expectedScene=session.get('scene',''))
        except Exception:
            stage.rmdir()
            raise
        self.pending=dict(result=str(result),time=time.time(),stage=stage,type='export',
                          kind=kind.currentData(),character=selected['character'],replace=selected,
                          session=session['directory'],scene=session.get('scene',''))
        self.set_status('正在保存 Max 场景…')

    @staticmethod
    def scene_matches(first,second):
        return bool(first and second and os.path.normcase(os.path.normpath(first))==os.path.normcase(os.path.normpath(second)))

    def bound_asset(self,session):
        asset=self.editing_asset
        if (asset and self.library and asset.get('library')==str(self.library.root)
                and asset.get('session')==session['directory']
                and self.scene_matches(asset.get('scene'),session.get('scene'))
                and (not asset.get('directory') or Path(asset['directory'],'asset.json').is_file())):
            return asset
        return None

    def bind_asset(self,asset,session,scene):
        self.editing_asset=dict(id=asset['id'],name=asset['name'],kind=asset['kind'],character=asset['character'],
                                session=session,scene=scene,library=str(self.library.root),directory=asset['_directory'])
        self.editing_label.setText('当前编辑：'+asset['character']+' / '+asset['name'])
        self.persist()

    def delete_asset(self,all_versions):
        self.idle()
        asset=self.selected_asset()
        subject='全部版本' if all_versions else f"版本 v{asset['_displayVersion']:03d}"
        if QMessageBox.question(self,'删除资产',f'将「{asset["name"]}」的{subject}移入回收目录？')!=QMessageBox.StandardButton.Yes:
            return
        versions=self.assets.currentItem().data(0,Qt.ItemDataRole.UserRole+1)
        next_id=None if all_versions else next((entry['id'] for entry in versions if entry['id']!=asset['id']),None)
        count=self.library.delete_asset(asset,all_versions)
        self.remembered_assets.pop(self.active_character,None)
        self.refresh_assets(flush=False,select_id=next_id)
        self.persist()
        if self.gallery:self.gallery.refresh()
        self.set_status(f'已将 {count} 个资产版本移入回收目录。')
        self.schedule_asset_scan()

    def key_selected_asset(self):
        self.send_to_max(self.selected_asset(),frames=True)

    def send_to_max(self,asset,*,frames=False):
        self.idle()
        session=self.selected_session()
        library=self.library
        if asset.get('placeholder'):raise ValueError('请先为此空资产保存修改。')
        metadata=asset.get('metadata',{})
        options={}
        if frames:
            if not frame_payload(asset):
                raise ValueError('此版本没有可覆盖到帧的数据。')
            if session.get('frameApply')!=2:
                raise ValueError('此 Max 窗口仍在使用旧版连接组件。新版组件自动加载完成后再点「覆盖帧」。')
            options['sourceFps']=metadata.get('fps')
        else:
            self.editor.flush()
            if 'source.max' not in asset['files']:raise ValueError('此旧版本没有完整 Max 场景，可使用「覆盖帧」。')
            scene=Path(session.get('scene') or '未命名场景').name
            prompt=f'用「{asset["name"]}」覆盖 Max（PID {session["pid"]}）中的「{scene}」？未保存的修改可能丢失。'
            if QMessageBox.question(self,'覆盖场景',prompt)!=QMessageBox.StandardButton.Yes:
                return
            if asset['kind'] in ('pose','model'):
                options['captureFrame']=metadata.get('frame')
        def ready(path):
            result=host.request(session,'applyAssetFrames' if frames else 'coverScene',path=str(path),
                                kind=asset['kind'],rig=metadata.get('rig','Generic'),
                                expectedScene=session.get('scene',''),**options)
            self.pending=dict(result=str(result),time=time.time(),type='import',session=session['directory'],
                              coveredAsset=None if frames else asset)
            self.set_status('正在应用帧到 Max…' if frames else '正在覆盖场景…')
        self.run_job(lambda:library.verify(asset,frames=frames),
                     '正在校验帧数据…' if frames else '正在校验资产文件…',ready)

    def update_selection_controls(self,asset):
        ready=bool(asset and not asset.get('placeholder'))
        self.save_button.setEnabled(asset is not None)
        self.apply_button.setEnabled(ready and 'source.max' in asset['files'])
        payload=frame_payload(asset)
        self.key_asset.setEnabled(bool(payload))
        hints={'animation':'一次性追加到 Max 时间轴末尾，保留现有模型和动画。',
               'pose':'一次性把 Pose 打键到 Max 当前帧。',
               'model':'一次性把 T-pose 打键到 Max 当前帧。'}
        self.key_asset.setToolTip(hints[asset['kind']] if payload else
                                  '此版本没有可覆盖到帧的数据。' if ready else '')
        self.apply_button.setToolTip('此版本没有完整 Max 场景。' if ready and not self.apply_button.isEnabled() else '')
        self.create_asset_button.setEnabled(bool(self.active_character))
        self.delete_asset_button.setEnabled(asset is not None)
        if asset:self.remembered_assets[self.active_character]=asset['id']
        self.selection_label.setText(asset['name'] if asset else '未选择资产')
        if asset and asset.get('placeholder'):
            self.asset_summary.setText(KINDS[asset['kind']]+' · 空资产，等待保存修改')
        elif asset:
            meta=asset.get('metadata',{});kind=KINDS[asset['kind']]
            frames=(f"{meta.get('start','—')} — {meta.get('end','—')} 帧" if asset['kind']=='animation'
                    else f"第 {meta.get('frame','—')} 帧")
            detail=f"{kind} · {frames}"
            self.asset_summary.setText(detail+(' · '+asset.get('notes','') if asset.get('notes') else ''))
        else:self.asset_summary.setText('从资产列表选择一项')
        self.selection_label.setToolTip(asset['name'] if asset else '')
        self.update_version_marks()
        self.update_push_asset_button()

    def update_push_asset_button(self):
        selected=self.version_choice.currentData()
        eligible=bool(selected and selected['kind']=='animation' and (self.library_state or {}).get('remote'))
        self.push_asset_button.setVisible(eligible)
        self.push_asset_button.setEnabled(eligible and not self.library_working
                                         and self.library_state.get('branch')=='main'
                                         and not self.library_state.get('blocked'))
        self.push_asset_button.setToolTip('推送这条动画的所有本地版本、场景和配置。')

    def asset_metadata_changed(self,item,column):
        if self.restoring or column not in (0,4):return
        asset=item.data(0,Qt.ItemDataRole.UserRole)
        if not asset:return
        try:
            self.idle();self.editor.flush()
            from .library import safe_name,write_json
            key='name' if column==0 else 'notes';value=safe_name(item.text(column)) if column==0 else item.text(column)
            versions=item.data(0,Qt.ItemDataRole.UserRole+1) if key=='name' else [asset]
            if key=='name' and value!=asset['name']:
                existing,_=self.library.list_assets(asset['character'],kind=asset['kind'])
                if any(entry['name'].casefold()==value.casefold() and entry['name']!=asset['name'] for entry in existing):
                    raise ValueError('已有同名资产。')
            updates=[]
            for version in versions:
                path=contained(self.library.root,Path(version['_directory']).relative_to(self.library.root))/'asset.json'
                updates.append((path,read_json(path)))
            written=[]
            try:
                for path,original in updates:
                    write_json(path,self.library.stamp(dict(original,**{key:value})))
                    written.append((path,original))
            except OSError:
                for path,original in reversed(written):
                    write_json(path,original)
                raise
            for version in versions:version[key]=value
            self.restoring=True
            try:
                item.setData(0,Qt.ItemDataRole.UserRole,asset)
                if key=='name':
                    item.setData(0,Qt.ItemDataRole.UserRole+1,versions)
                else:
                    lineage=item.data(0,Qt.ItemDataRole.UserRole+1)
                    lineage[0]=asset
                    item.setData(0,Qt.ItemDataRole.UserRole+1,lineage)
            finally:
                self.restoring=False
            if item==self.assets.currentItem():
                self.load_asset_versions(item,self.selected_asset())
            self.set_status('资产信息已保存。')
            self.schedule_asset_scan()
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
        self.idle();available=[session for session in host.sessions() if session.get('assetWorkspace')==1]
        saved=self.active_session or self.settings.get('session')
        selected=(host.preferred_session(available,saved)
                  if saved or self.attach is None or self.attach.windows_count<=1 else None)
        if selected:
            self.remember_max_target(selected);self.active_session=selected['directory'];self.auto_reconnect=False;self.persist();self.poll()
            self.set_status('已连接 Max，无需重复启动。');return
        if host.available_windows():self.connect_max();return
        path=host.preferred_max(self.settings.get('maxExecutable',''))
        if not path:path=self.choose_max_program()
        if not path:return
        process=host.launch_max(path,self.context.resource('max/bootstrap.ms'))
        self.settings['maxExecutable']=str(path);self.active_session=None;self.waiting_target=None
        self.auto_reconnect=False
        self.launching={'process':process,'pid':process.pid,'time':time.time()};self.persist()
        self.set_status('正在启动 Max，就绪后会自动连接该窗口…')

    def library_controls(self):
        self.library_state=None
        self.asset_sync_data=None
        self.library_working=False
        self.library_feedback=''
        self.library_last_cloud=None
        section=QFrame()
        section.setStyleSheet('QFrame#librarySync {background:#f5f8ef;border:1px solid #d6e2c9;border-radius:7px;}')
        section.setObjectName('librarySync')
        layout=QBoxLayout(QBoxLayout.Direction.LeftToRight,section)
        self.library_bar_layout=layout
        layout.setContentsMargins(8,4,8,4)
        layout.setSpacing(6)
        header=QHBoxLayout()
        header.setSpacing(4)
        title=QLabel('共享资产库')
        title.setStyleSheet('font-weight:650;color:#3c5334;')
        header.addWidget(title)
        self.library_summary=ElidedLabel('正在读取本地库')
        header.addWidget(self.library_summary,1)
        self.library_refresh=self.button('刷新',lambda:self.library_action('refresh'))
        self.library_refresh.setToolTip('重新读取本地资产与 Git 状态，并检查云端更新')
        header.addWidget(self.library_refresh)
        self.library_details=self.button('详情',self.open_library_sync)
        header.addWidget(self.library_details)
        self.library_account=self.button('账号',self.open_git_access)
        self.library_account.setToolTip('查看 Git 提交身份与 GitHub 账号权限')
        header.addWidget(self.library_account)
        workspace=getattr(self.context,'workspace_state',{})
        self.library_git=self.button('LXGit',self.open_library_in_git)
        self.library_git.setToolTip('在 LXGit 中打开同一个本地资产库')
        self.library_git.setVisible(callable(workspace.get('open_tool')))
        header.addWidget(self.library_git)
        layout.addLayout(header,1)
        row=QHBoxLayout()
        row.setSpacing(4)
        self.library_pull=self.button('拉取更新',lambda:self.library_action('pull'))
        self.library_push=self.button('提交推送',lambda:self.library_action('push'))
        self.library_overwrite=self.button('云端覆盖',lambda:self.library_action('overwrite'))
        self.library_restore=self.button('还原…',lambda:self.library_action('history'))
        for button in (self.library_pull,self.library_push,self.library_overwrite,self.library_restore):
            row.addWidget(button,1)
        self.library_setup=self.button('连接共享库…',self.library_settings)
        row.addWidget(self.library_setup,1)
        layout.addLayout(row)
        return section

    def update_library_layout(self):
        linked=bool((self.library_state or {}).get('remote'))
        stacked=linked and self.width()<650
        self.library_bar_layout.setDirection(QBoxLayout.Direction.TopToBottom if stacked
                                             else QBoxLayout.Direction.LeftToRight)

    def update_library_controls(self):
        data=self.library_state or {}
        linked=bool(data.get('remote'))
        root=self.library.root if self.library else None
        is_git=bool(root and (root/'.git').exists())
        ready=not self.library_working and data.get('branch')=='main' and not data.get('blocked')
        dirty,ahead,behind=len(data.get('dirty',[])),data.get('ahead',0),data.get('behind',0)
        if self.library_working:
            summary=self.library_feedback
        elif data.get('blocked'):
            summary='Git 操作待处理 · 打开 LXGit 查看'
        elif data.get('branch') not in (None,'main'):
            summary=f"当前分支 {data['branch'] or '游离'} · 同步使用 main"
        elif linked:
            cloud=f'云端更新 {behind}' if data.get('checked') else '云端未检查'
            summary=f'本地改动 {dirty} · 待推送 {ahead} · {cloud}'
        else:
            summary='本地库 · 尚未连接云端' if self.library_state or not is_git else '本地库 · 请刷新 Git 状态'
        self.library_summary.setText(summary)
        self.update_library_layout()
        extra=self.library_feedback
        if self.library_last_cloud:
            extra=f'{extra}\n云端检查 {self.library_last_cloud}'.strip()
        self.library_summary.setToolTip('\n'.join((summary,str(root or ''),extra)).strip())
        self.library_refresh.setEnabled(bool(root and not self.library_working))
        self.library_details.setEnabled(bool(root and not self.library_working))
        self.library_account.setEnabled(is_git and not self.library_working)
        self.update_push_asset_button()
        self.library_git.setEnabled(is_git and not self.library_working)
        self.library_setup.setVisible(not linked)
        self.library_setup.setEnabled(bool(root and not self.library_working))
        for button in (self.library_pull,self.library_push,self.library_overwrite):
            button.setVisible(linked)
        self.library_restore.setVisible(is_git)
        self.library_pull.setEnabled(bool(ready and linked and not dirty and not ahead))
        self.library_push.setEnabled(bool(ready and linked))
        self.library_overwrite.setEnabled(bool(ready and linked and data.get('has_head')))
        self.library_restore.setEnabled(bool(ready and data.get('has_head')))
        self.library_pull.setToolTip('快速更新到云端版本。工作区需干净，且没有待推送的提交。')
        self.library_overwrite.setToolTip('使用云端 main 覆盖本地资产库。先备份本地提交及工作区。')
        self.library_restore.setToolTip('还原未提交改动，或选择历史提交创建反向提交')

    def library_action(self,operation,commit=None,asset=None):
        self.idle()
        library=self.require_library()
        root=library.root
        changes={'pull','push','push_asset','overwrite','restore','revert'}
        workspace=getattr(self.context,'workspace_state',{})
        if workspace.get('lxgit_working_root')==str(root):
            raise ValueError('LXGit 正在操作此资产库，完成后再刷新。')
        if operation not in ('local','asset_status'):
            self.editor.flush()
        confirmations={
            'push':('提交推送','提交并推送本地资产库的改动？其他成员拉取后会收到新增、修改和删除。'),
            'overwrite':('云端覆盖本地库','用云端 main 覆盖本地资产库？本地提交和未提交的改动会先备份，可在 LXGit 找回。当前 Max 场景保持原位。'),
            'restore':('还原未提交改动','将本地库还原到最近的本地提交？未提交的改动会先存入 LXGit 储藏。'),
            'revert':('反向提交','撤销所选提交的改动并创建一条本地反向提交？确认后可另行推送给团队。'),
        }
        if operation=='push_asset':
            confirmations[operation]=('推送此动画',f'提交并推送「{asset["name"]}」的本地改动和版本？')
        if operation in confirmations:
            title,question=confirmations[operation]
            if QMessageBox.question(self,title,question,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
                return
        labels={'asset_status':'正在读取动画文件状态…','push_asset':'正在推送所选动画…','local':'正在读取本地状态…','refresh':'正在刷新本地和云端状态…','history':'正在读取可还原的提交…',
                'pull':'正在拉取云端更新…','push':'正在提交并推送…','overwrite':'正在备份并覆盖本地库…',
                'restore':'正在备份并还原本地改动…','revert':'正在创建反向提交…'}
        label=labels[operation]
        if operation in changes:
            workspace['animation_working_root']=str(root)
        self.library_working=True
        self.library_feedback=label
        self.update_library_controls()
        locks_editor=operation in changes or operation=='refresh'
        if locks_editor:
            self.split.setEnabled(False)
            self.register_character.setEnabled(False)
        def work():
            message=''
            success=True
            try:
                if operation=='push_asset':
                    message=push_asset(root,asset)
                elif operation in changes:
                    message=host.sync_git(root,operation,commit=commit)
                data=host.library_sync_state(root,check_cloud=operation=='refresh')
            except Exception as error:
                message='操作失败：'+describe_git_error(error)
                success=False
                try:data=host.library_sync_state(root)
                except Exception:data=None
            try:
                asset_data=asset_git_state(root,data) if data is not None else None
            except Exception as error:
                asset_data=None
                if not message:
                    message='无法读取动画文件状态：'+describe_git_error(error)
            try:
                history=host.library_commits(root) if operation=='history' and data and data.get('has_head') else []
            except Exception as error:
                history=[]
                success=False
                message='操作失败：'+describe_git_error(error)
            finally:
                if operation in changes and workspace.get('animation_working_root')==str(root):
                    workspace.pop('animation_working_root',None)
            return data,message,history,success,asset_data
        def ready(result):
            data,message,history,ok,self.asset_sync_data=result
            self.library_working=False
            if locks_editor:
                self.split.setEnabled(True)
                self.register_character.setEnabled(True)
            self.library_state=data
            self.library_feedback=message or ('刷新完成。' if operation=='refresh' else '')
            if ok and operation in ('refresh','pull','push','push_asset','overwrite') and data and data.get('remote'):
                self.library_last_cloud=datetime.now().strftime('%m-%d %H:%M')
            self.update_library_controls()
            if operation in changes or operation=='refresh':
                self.reload_library_assets()
            else:
                self.update_asset_marks()
            if ok and message and operation in changes:
                self.settings['lastLibrarySync']=dict(library=str(root),time=datetime.now().strftime('%m-%d %H:%M'),message=message)
                self.persist()
            self.set_status(self.library_feedback or '共享资产库状态已读取。')
            if operation=='history' and ok:
                QTimer.singleShot(0,lambda:self.guard(lambda:self.choose_library_revert(data,history)) if not self.closed else None)
        try:
            self.run_job(work,label,ready)
        except Exception:
            workspace.pop('animation_working_root',None)
            self.library_working=False
            if locks_editor:
                self.split.setEnabled(True)
                self.register_character.setEnabled(True)
            self.update_library_controls()
            raise

    def choose_library_revert(self,data,history):
        dialog=QDialog(self)
        dialog.setWindowTitle('还原资产库')
        dialog.resize(560,220)
        layout=QVBoxLayout(dialog)
        text=QLabel('还原未提交的改动，或选择一条历史提交，创建一条反向提交。')
        text.setWordWrap(True);layout.addWidget(text)
        restore=self.button('还原未提交改动…',lambda:dialog.done(2))
        restore.setEnabled(bool(data['dirty']))
        layout.addWidget(restore)
        layout.addWidget(QLabel('历史提交'))
        picker=QComboBox()
        for sha,date,author,subject in history:
            picker.addItem(f'{date} · {author} · {subject} · {sha[:8]}',sha)
        layout.addWidget(picker)
        row=QHBoxLayout()
        row.addStretch()
        row.addWidget(self.button('关闭',dialog.reject))
        revert=self.button('创建反向提交…',dialog.accept)
        revert.setEnabled(bool(history) and not data['dirty'])
        row.addWidget(revert)
        layout.addLayout(row)
        selection=dialog.exec()
        if selection==2:self.library_action('restore')
        if selection==QDialog.DialogCode.Accepted:self.library_action('revert',picker.currentData())

    def open_git_access(self):
        self.idle()
        root=self.require_library().root
        dialog=QDialog(self)
        dialog.setWindowTitle('Git 账号与权限')
        dialog.resize(560,330)
        layout=QVBoxLayout(dialog)
        info=QLabel('正在读取本地 Git 设置…')
        info.setTextFormat(Qt.TextFormat.PlainText)
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info.setWordWrap(True)
        layout.addWidget(info,1)
        row=QHBoxLayout()
        def read_access(verify):
            self.idle()
            check.setEnabled(False);identity.setEnabled(False);close.setEnabled(False);lxgit.setEnabled(False)
            info.setText('正在核验 GitHub 账号与仓库权限…' if verify else '正在读取本地 Git 设置…')
            def worker():
                try:return access_state(root,verify=verify),None
                except Exception as error:return None,describe_git_error(error)
            def ready(value):
                state,error=value
                if state:
                    show=lambda value:('有权限' if value is True else '无权限' if value is False else '待核验')
                    identity_text=' · '.join(filter(None,(state.get('identity_name'),state.get('identity_email'))))
                    lines=[f"提交者  {identity_text or '尚未设置姓名和邮箱'}",
                           f"GitHub 账号  {state.get('account') or '待核验'}",
                           f"凭据助手  {'已配置' if state.get('helper_configured') else '未配置'}",
                           f"远端  {state.get('remote') or '尚未连接'}",
                           f"仓库权限  读取 {show(state.get('read_access'))} · 写入 {show(state.get('write_access'))}",
                           state.get('message','')]
                    if state.get('push_remote') not in ('',None,state.get('remote')):
                        lines.insert(4,f"推送地址  {state['push_remote']}")
                    info.setText(chr(10).join(lines))
                else:
                    info.setText(error)
                check.setEnabled(True);identity.setEnabled(True);close.setEnabled(True);lxgit.setEnabled(True)
            self.run_job(worker,'正在读取 Git 账号信息…',ready)
        def edit_identity():
            name,ok=QInputDialog.getText(dialog,'设置提交者','显示姓名')
            if not ok or not name.strip():return
            email,ok=QInputDialog.getText(dialog,'设置提交者','提交者邮箱')
            if not ok:return
            if '@' not in email or not email.strip():
                info.setText('请填写有效的提交者邮箱。')
                return
            host.git_run(root,'config','--local','user.name',name.strip(),timeout=8)
            host.git_run(root,'config','--local','user.email',email.strip(),timeout=8)
            read_access(False)
        check=self.button('核验 GitHub 权限',lambda:read_access(True))
        identity=self.button('设置提交者…',edit_identity)
        def manage():
            dialog.accept()
            self.open_library_in_git()
        lxgit=self.button('在 LXGit 管理账号',manage)
        close=self.button('关闭',dialog.reject)
        for button in (check,identity,lxgit,close):
            row.addWidget(button)
        layout.addLayout(row)
        note=QLabel('工具架账号用于商店。共享资产库使用 Git 凭据，提交者姓名和邮箱用于版本记录。')
        note.setWordWrap(True)
        layout.addWidget(note)
        QTimer.singleShot(0,lambda:self.guard(lambda:read_access(False)) if dialog.isVisible() else None)
        dialog.exec()

    def open_library_sync(self):
        self.idle()
        LibrarySyncDialog(self).exec()

    def open_library_in_git(self):
        self.idle()
        root=self.require_library().root
        marker=root/'.git'
        if not (marker.is_dir() or marker.is_file()):
            raise ValueError('请先在共享库设置中连接本地 Git 资产库。')
        self.editor.flush()
        target=self.context.workspace_state['open_tool']('repo-1432888469')
        select=getattr(target,'open_animation_library',None)
        if callable(select):
            select()
        elif target is not None:
            self.set_status('请将 LXGit 更新到支持动画资产库联动的版本。')

    def refresh_linked_library(self):
        self.library_action('refresh')

    def reload_library_assets(self):
        library=self.require_library()
        names=library.characters()
        if self.active_character not in names:
            self.active_character=names[0] if names else None
            self.editor.set_asset(None,None)
        binding=self.editing_asset or {}
        if binding.get('library')==str(library.root) and binding.get('directory'):
            marker=Path(binding['directory'])/'asset.json'
            if not marker.is_file() or read_json(marker).get('id')!=binding.get('id'):
                self.editing_asset=None
        self.update_character_header()
        self.refresh_assets(flush=False)
        if self.gallery:self.gallery.reload_categories()
        self.persist()

    def library_settings(self):
        self.idle();self.editor.flush();dialog=QDialog(self);dialog.setWindowTitle('共享库设置');dialog.resize(650,200);form=QFormLayout(dialog)
        row=QHBoxLayout();path=QLineEdit(str(self.library.root) if self.library else '');row.addWidget(path,1)
        def browse():
            value=QFileDialog.getExistingDirectory(dialog,'选择资产库',path.text())
            if value:path.setText(value)
        row.addWidget(self.button('选择目录',browse));form.addRow('本地目录',row)
        remote=QLineEdit(self.settings.get('remote',''));form.addRow('共享仓库',remote)
        form.addRow(QLabel('团队成员使用同一个仓库，各自在本机选择空目录连接。仓库访问权限由 GitHub 管理。'))
        def apply():
            self.settings['remote']=remote.text().strip();self.load_library(path.text());dialog.accept()
        form.addRow(self.button('应用目录',apply));row=QHBoxLayout()
        def connect_existing():
            if Path(path.text()).resolve()!=self.library.root:raise ValueError('请先应用目录。')
            address=host.shared_url(remote.text().strip())
            library=self.library
            dialog.accept()
            def ready(message):
                self.settings['remote']=address
                self.persist()
                QTimer.singleShot(0,lambda:self.guard(lambda:self.library_action('local')))
            self.run_job(lambda:host.init_git(library.root,address),'正在为当前库设置共享仓库…',ready)
        def join_shared():
            target=Path(path.text().strip())
            address=host.shared_url(remote.text().strip())
            if not path.text().strip():raise ValueError('请选择共享资产库目录。')
            dialog.accept()
            def ready(folder):
                self.settings['remote']=address
                self.load_library(folder)
                self.set_status('已连接共享资产库。')
            self.run_job(lambda:host.clone_shared_library(target,address),'正在连接共享资产库…',ready)
        row.addWidget(self.button('连接共享库',join_shared))
        row.addWidget(self.button('为当前库设置仓库',connect_existing))
        form.addRow(row);dialog.exec()
    def remember_max_target(self, session):
        state=getattr(self.context,'workspace_state',None)
        if state is not None and session.get('birth') and session.get('pid'):
            state['max_target']=(int(session['pid']),str(session['birth']))

    def max_connection_status(self):
        return self.connection_state

    def poll(self):
        if self.closed:return
        available=[session for session in host.sessions() if session.get('assetWorkspace')==1]
        if self.attach:
            self.attach.poll({(s['pid'],str(s.get('birth'))) for s in available
                              if s.get('bridgeDigest')==self.attach.bridge_digest})
        if self.auto_reconnect and not self.launching:
            state=getattr(self.context,'workspace_state',{})
            target=self.waiting_target or (state.get('max_target') if not self.active_session else None)
            if target:
                selected=next((item for item in available if (item['pid'],str(item.get('birth','')))==target),None)
            elif self.active_session or self.attach is None or self.attach.windows_count<=1:
                selected=host.preferred_session(available,self.active_session)
            else:
                selected=None
            if selected:
                self.remember_max_target(selected)
                self.waiting_target=None
                self.active_session=selected['directory']
                self.auto_reconnect=False
                self.persist()
        if self.launching:
            started=next((s for s in available if s['pid']==self.launching['pid']),None)
            if started:
                self.remember_max_target(started);self.active_session=started['directory'];self.launching=None;self.persist();self.set_status('Max 已启动并连接。')
            elif self.launching['process'].poll() is not None or time.time()-self.launching['time']>240:
                self.launching=None;self.set_status('Max 启动后暂未就绪。完成 Max 的启动提示后可从菜单选择窗口。')
        matches=[s for s in available if s['directory']==self.active_session]
        if matches:
            self.connection_state='Max 已连接'
            session=matches[0];self.connection.setText(f"● Max · PID {session['pid']} · {Path(session.get('scene') or '未命名场景').name}  |  {session.get('start','?')} — {session.get('end','?')} 帧 · {session.get('fps','?')} FPS · 当前 {session.get('frame','?')}")
        else:
            waiting=self.launching or self.waiting_target or (self.attach and self.attach.connecting)
            self.connection_state='Max 连接中' if waiting else ('Max 已断开' if self.active_session else 'Max 未连接')
            self.connection.setText('○ 请选择 Max 窗口' if not waiting and not self.active_session and len(available)>1 else '○ '+self.connection_state)
            self.connection.setToolTip('等待目标 Max 空闲。' if waiting else '')
        bound=self.bound_asset(matches[0]) if matches else None
        self.editing_label.setText('当前编辑：'+bound['character']+' / '+bound['name'] if bound else '当前编辑：未绑定资产')
        pending=self.pending
        if not pending:return
        path=Path(pending['result'])
        if path.exists():
            self.pending=None
            def consume():
                result=read_json(path)
                if not result.get('ok'):raise ValueError(result.get('message','Max 操作失败'))
                if pending['type']=='import':
                    if pending['coveredAsset']:
                        self.bind_asset(pending['coveredAsset'],pending['session'],result['working'])
                    self.set_status(result.get('message','完成。'))
                    return
                library=self.library
                def publish():
                    asset=library.save_asset_revision(pending['replace'],pending['kind'],pending['stage'],
                                                      result['main'],result['metadata'])
                    if asset.get('saveWarning'):
                        result.setdefault('warnings',[]).append(asset['saveWarning'])
                    shutil.rmtree(pending['stage']);return asset
                def finished(asset):
                    self.active_character=pending['character'];self.editor.set_asset(None,None)
                    if self.kind.currentData() not in (None,'',asset['kind']):self.kind.setCurrentIndex(0)
                    self.update_character_header();self.refresh_assets(flush=False,select_id=asset['id']);self.persist()
                    self.bind_asset(asset,pending['session'],pending['scene'])
                    if self.gallery:self.gallery.reload_categories()
                    self.schedule_asset_scan()
                    self.set_status('已更新库。'+(' · '+'; '.join(result.get('warnings',[])) if result.get('warnings') else ''))
                self.run_job(publish,'正在归档 Max 场景与配置…',finished)
            self.guard(consume)
        elif time.time()-pending['time']>180:self.set_status('Max 尚未返回结果，仍在等待；不会重复提交或切换窗口。')
    def shutdown(self):
        if self.closed:return
        if self.attach:self.attach.close();self.attach=None
        if not self.library_working:
            try:self.editor.flush()
            except Exception:self.editor.keep_draft()
        from .library import write_json
        write_json(self.context.data_root/'clip-drafts.json',self.editor.recovery)
        self.closed=True;self.timer.stop();self.asset_scan.stop();self.wheel_router.stop()
        self.persist()
        if self.gallery:self.gallery.close()
        for job in self.jobs:
            if job.isRunning():job.setParent(None);_finishing.append(job);job.finished.connect(lambda j=job:_release(j))

_finishing=[]
def _release(job):
    if job in _finishing:_finishing.remove(job)
    job.deleteLater()

def create_panel(context,parent):return Panel(context,parent)
