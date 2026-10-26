import copy
import uuid
from PySide6.QtCore import Qt,Signal,QTimer
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTreeWidget,QTreeWidgetItem,
    QComboBox,QInputDialog,QMessageBox,QTabWidget,QAbstractItemView,QHeaderView,QToolButton,QMenu)
from . import clips
from .fbx_settings import SettingsForm
from .widgets import ColumnsDelegate

class ClipEditor(QWidget):
    message=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.setObjectName('ClipWorkspace')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        self.library=self.asset=self.data=None;self.current_id=None;self.loading=False
        layout=QVBoxLayout(self);layout.setContentsMargins(14,12,14,12);layout.setSpacing(10)
        row=QHBoxLayout();self.title=QLabel('Clip 拆分');self.title.setStyleSheet('font-size:18px;font-weight:600');row.addWidget(self.title,1)
        add=QPushButton('＋ Clip');add.clicked.connect(lambda:self.guard(self.add_clip));row.addWidget(add)
        more=QToolButton();more.setText('⋯');more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup);menu=QMenu(more)
        for title,fn in [('复制当前 Clip',self.duplicate),('移除当前 Clip',self.remove)]:menu.addAction(title,lambda fn=fn:self.guard(fn))
        more.setMenu(menu);row.addWidget(more);layout.addLayout(row)
        self.source=QLabel('选择左侧动画，开始拆分和配置。');layout.addWidget(self.source)
        self.table=QTreeWidget();self.table.setHeaderLabels(['Clip 名称','起始帧','结束帧','Loop Time','备注','源 Take'])
        self.table.setRootIsDecorated(False);self.table.setMinimumHeight(145);self.table.setMaximumHeight(210)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked|QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.setItemDelegate(ColumnsDelegate({0,1,2,4,5},{1,2},self.table))
        for col,width in enumerate([140,75,75,85,140,95]):self.table.setColumnWidth(col,width)
        self.table.header().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.table.header().setSectionResizeMode(4,QHeaderView.ResizeMode.Stretch)
        self.table.currentItemChanged.connect(self.select_clip);self.table.itemChanged.connect(self.edit_cell);layout.addWidget(self.table)
        self.tabs=QTabWidget();self.clip_settings=SettingsForm('clip');self.importer=SettingsForm('importer')
        self.tabs.addTab(self.clip_settings,'Clip 独立配置');self.tabs.addTab(self.importer,'FBX 配置');layout.addWidget(self.tabs,1)
        self.loop=self.clip_settings.controls['loopTime'];self.loop.toggled.connect(self.loop_changed)
        self.extra=self.clip_settings.controls['extensions']
        row=QHBoxLayout();row.addWidget(QLabel('目标编辑器'));self.target=QComboBox();self.target.addItems(['2022.3','2022.3.62t13']);row.addWidget(self.target)
        row.addSpacing(12);row.addWidget(QLabel('预设'));self.preset=QComboBox();row.addWidget(self.preset,1)
        apply=QPushButton('应用');apply.clicked.connect(lambda:self.guard(self.apply_selected_preset));row.addWidget(apply)
        store=QPushButton('另存预设');store.clicked.connect(lambda:self.guard(self.store_preset));row.addWidget(store);layout.addLayout(row)
        row=QHBoxLayout();label=QLabel('预设不改变 Clip 分段 · 切换动画自动保存');row.addWidget(label,1)
        save=QPushButton('保存配置');save.clicked.connect(lambda:self.guard(self.flush));row.addWidget(save);layout.addLayout(row)
        self.setEnabled(False)

    def guard(self,fn):
        try:fn()
        except Exception as exc:self.message.emit(str(exc))

    def apply_selected_preset(self):
        if not self.current():return
        self.commit_current()
        candidate=clips.apply_preset(self.data,self.asset,self.current_id,clips.presets(self.library)[self.preset.currentText()])
        clips.save(self.library,self.asset,candidate);self.data=candidate;self.render_table(self.current_id)
        self.message.emit('已应用配置预设；所有 Clip 名称、分段和备注保持不变。')

    def store_preset(self):
        if not self.current():return
        self.commit_current()
        name,ok=QInputDialog.getText(self,'保存 Unity 配置预设','预设名称（保存 FBX 与当前 Clip 配置，不包含分段）')
        if not ok or not name.strip():return
        name=name.strip()
        if name in clips.presets(self.library) and name not in clips.builtin_presets():
            if QMessageBox.question(self,'覆盖预设','覆盖同名预设：'+name+'？')!=QMessageBox.StandardButton.Yes:return
        clips.save_preset(self.library,name,{'fbxSettings':self.data['fbxSettings'],'clipSettings':self.current()['settings']})
        self.preset.clear();self.preset.addItems(clips.presets(self.library));self.preset.setCurrentText(name)
        self.message.emit('配置预设已保存，可用于其他动画的 Clip。')

    def current(self):
        return next((c for c in self.data['clips'] if c['id']==self.current_id),None) if self.data else None

    def commit_current(self):
        if self.data is None:return
        candidate=copy.deepcopy(self.data)
        current=next((c for c in candidate['clips'] if c['id']==self.current_id),None)
        if current:current['settings']=self.clip_settings.values()
        candidate['fbxSettings']=self.importer.values();candidate['targetEditor']=self.target.currentText()
        clips.validate(candidate,self.asset);self.data=candidate

    def flush(self):
        if self.data is None:return
        self.commit_current();clips.save(self.library,self.asset,self.data)
        self.message.emit('配置已保存。')

    def set_asset(self,library,asset):
        self.library,self.asset=library,asset;self.current_id=None;self.data=None
        self.loading=True;self.table.clear();self.loading=False
        active=bool(asset and asset['kind']=='animation');self.setEnabled(active)
        self.setProperty('empty',not active);self.style().unpolish(self);self.style().polish(self)
        if not active:
            self.title.setText('Clip 拆分');self.source.setText('选择左侧动画，开始拆分和配置。')
            self.clip_settings.set_values(clips.defaults());self.importer.set_values(clips.fbx_defaults());return
        self.data=clips.load(library,asset)
        self.preset.clear();self.preset.addItems(clips.presets(library))
        self.title.setText(asset['name']+' · Clip 拆分')
        source=self.data['source'];self.source.setText(f"{source['firstFrame']:g} — {source['lastFrame']:g} 帧 · {source['fps']:g} FPS · 双击单元格编辑")
        self.render_table(self.data['clips'][0]['id'] if self.data['clips'] else None)

    def render_table(self,selected):
        self.loading=True;self.table.clear();target=None
        for clip in self.data['clips']:
            item=QTreeWidgetItem([clip['name'],f"{clip['firstFrame']:g}",f"{clip['lastFrame']:g}",'',clip.get('notes',''),clip.get('takeName','')])
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsEditable|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(3,Qt.CheckState.Checked if clip['settings'].get('loopTime') else Qt.CheckState.Unchecked)
            item.setData(0,Qt.ItemDataRole.UserRole,clip['id']);self.table.addTopLevelItem(item)
            item.setToolTip(5,'源 Take 是 FBX 中原始动画轨道组的名称；通常留空，由导入器读取。')
            if clip['id']==selected:target=item
        if target:self.table.setCurrentItem(target)
        self.current_id=selected;self.loading=False;self.show_fields()

    def select_clip(self,item,old):
        if self.loading:return
        try:self.flush()
        except Exception as exc:
            self.message.emit(str(exc));self.loading=True;self.table.setCurrentItem(old);self.loading=False;return
        self.current_id=item.data(0,Qt.ItemDataRole.UserRole) if item else None;self.show_fields()

    def edit_cell(self,item,column):
        if self.loading or not self.data:return
        try:
            self.commit_current();candidate=copy.deepcopy(self.data)
            clip=next(c for c in candidate['clips'] if c['id']==item.data(0,Qt.ItemDataRole.UserRole))
            if column in (1,2):clip['firstFrame' if column==1 else 'lastFrame']=float(item.text(column))
            elif column==3:clip['settings']['loopTime']=item.checkState(3)==Qt.CheckState.Checked
            else:clip[{0:'name',4:'notes',5:'takeName'}[column]]=item.text(column).strip()
            clips.save(self.library,self.asset,candidate);self.data=candidate;self.show_fields()
            self.message.emit('Clip 已保存。')
        except Exception as exc:
            self.message.emit('修改未保存：'+str(exc));QTimer.singleShot(0,lambda:self.render_table(self.current_id))

    def loop_changed(self):
        if self.loading or not self.current():return
        try:
            self.flush();self.loading=True
            item=self.table.currentItem()
            if item:item.setCheckState(3,Qt.CheckState.Checked if self.loop.isChecked() else Qt.CheckState.Unchecked)
        except Exception as exc:self.message.emit(str(exc));self.show_fields()
        finally:self.loading=False

    def show_fields(self):
        self.loading=True
        try:
            clip=self.current();self.clip_settings.setEnabled(clip is not None)
            self.clip_settings.set_values(clip['settings'] if clip else clips.defaults())
            self.target.setCurrentText(self.data.get('targetEditor','2022.3'))
            self.importer.set_values(self.data.get('fbxSettings',clips.fbx_defaults()))
        finally:self.loading=False

    def current_scroll(self):
        form=self.clip_settings if self.tabs.currentIndex()==0 else self.importer
        return form.currentWidget()

    def unique_name(self,name):
        names={c['name'].casefold() for c in self.data['clips']};i=1;result=name
        while result.casefold() in names:result=f'{name}_{i:02d}';i+=1
        return result

    def add_clip(self):
        self.commit_current();source=self.data['source']
        clip=clips.new_clip(self.unique_name('Clip'),source['firstFrame'],source['lastFrame']);self.data['clips'].append(clip)
        clips.save(self.library,self.asset,self.data);self.render_table(clip['id'])

    def duplicate(self):
        self.commit_current()
        if not self.current():return
        clip=copy.deepcopy(self.current());clip['id']=uuid.uuid4().hex;clip['name']=self.unique_name(clip['name']+'_copy')
        self.data['clips'].append(clip);clips.save(self.library,self.asset,self.data);self.render_table(clip['id'])

    def remove(self):
        if not self.current():return
        self.data['clips']=[c for c in self.data['clips'] if c['id']!=self.current_id]
        clips.save(self.library,self.asset,self.data)
        self.render_table(self.data['clips'][0]['id'] if self.data['clips'] else None)
