import copy
import json
import uuid
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTreeWidget,QTreeWidgetItem,
    QFormLayout,QLineEdit,QDoubleSpinBox,QCheckBox,QComboBox,QGroupBox,QPlainTextEdit,QScrollArea,QInputDialog,QMessageBox)
from . import clips
from .fbx_settings import SettingsForm, SCHEMA


class ClipEditor(QWidget):
    message = Signal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.library=self.asset=self.data=None
        self.current_id=None;self.loading=False
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.title=QLabel('选择一个动画来拆分 Clip');self.title.setStyleSheet('font-size:19px;font-weight:600');layout.addWidget(self.title)
        self.source=QLabel('源帧范围与 FPS 会从 Max 场景读取。');layout.addWidget(self.source)
        self.table=QTreeWidget();self.table.setHeaderLabels(['Clip 名称','起始帧','结束帧','时长']);self.table.setRootIsDecorated(False)
        self.table.setMinimumHeight(130);self.table.setMaximumHeight(210);self.table.currentItemChanged.connect(self.select_clip);layout.addWidget(self.table)
        row=QHBoxLayout()
        for title,fn in [('＋ Clip',self.add_clip),('复制 Clip',self.duplicate),('移除 Clip',self.remove),('保存配置',self.flush)]:
            b=QPushButton(title);b.clicked.connect(lambda _,fn=fn:self.guard(fn));row.addWidget(b)
        layout.addLayout(row)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.body=QWidget();formbody=QVBoxLayout(self.body);scroll.setWidget(self.body);layout.addWidget(scroll,1)
        group=QGroupBox('当前 Clip');form=QFormLayout(group)
        self.name=QLineEdit();self.first=QDoubleSpinBox();self.last=QDoubleSpinBox();self.notes=QLineEdit()
        for spin in (self.first,self.last):spin.setRange(-1000000,1000000);spin.setDecimals(3)
        form.addRow('名称',self.name);span=QHBoxLayout();span.addWidget(self.first);span.addWidget(QLabel('—'));span.addWidget(self.last);form.addRow('帧范围',span);form.addRow('备注',self.notes);formbody.addWidget(group)
        self.take=QLineEdit();self.take.setPlaceholderText('留空时由后续导入器读取源 Take');form.addRow('源 Take',self.take)
        self.target=QComboBox();self.target.addItems(['2022.3','2022.3.62t13']);form.addRow('目标编辑器',self.target)
        group=QGroupBox('Unity 配置预设 · 不修改 Clip 分段');preset_row=QHBoxLayout(group)
        self.preset=QComboBox();preset_row.addWidget(self.preset,1)
        for title,fn in [('应用 FBX / 当前 Clip',self.apply_selected_preset),('命名保存预设',self.store_preset)]:
            button=QPushButton(title);button.clicked.connect(lambda _,fn=fn:self.guard(fn));preset_row.addWidget(button)
        formbody.addWidget(group)
        info=QLabel('FBX 配置：Unity 2022.3 / 团结 '+SCHEMA['version']+' 字段集。\n文件级设置作用于整个 FBX；Clip 设置各自独立。对象引用填项目路径或 GUID，复杂结构用 JSON。')
        info.setWordWrap(True);formbody.addWidget(info)
        self.importer=SettingsForm('importer');self.importer.setMinimumHeight(360);formbody.addWidget(self.importer)
        self.clip_settings=SettingsForm('clip');self.clip_settings.setMinimumHeight(360);formbody.addWidget(self.clip_settings)
        self.loop=self.clip_settings.controls['loopTime']
        self.extra=self.clip_settings.controls['extensions']
        formbody.addStretch()
        self.footer=QLabel('');self.footer.setWordWrap(True);layout.addWidget(self.footer)
        self.setEnabled(False)

    def guard(self,fn):
        try:fn()
        except Exception as exc:self.message.emit(str(exc))

    def apply_selected_preset(self):
        if not self.current():return
        self.commit_current()
        candidate=clips.apply_preset(self.data,self.asset,self.current_id,clips.presets(self.library)[self.preset.currentText()])
        clips.save(self.library,self.asset,candidate);self.data=candidate;self.show_fields()
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
        clip=self.current()
        if not clip:return
        candidate=copy.deepcopy(clip)
        candidate.update(name=self.name.text().strip(),firstFrame=self.first.value(),lastFrame=self.last.value(),notes=self.notes.text(),takeName=self.take.text())
        settings=self.clip_settings.values()
        candidate['settings']=settings
        data=copy.deepcopy(self.data)
        data['fbxSettings']=self.importer.values()
        data['targetEditor']=self.target.currentText()
        data['clips']=[candidate if c['id']==candidate['id'] else c for c in data['clips']]
        clips.validate(data,self.asset)
        self.data=data

    def flush(self):
        if self.data is None:return
        self.commit_current();clips.save(self.library,self.asset,self.data);self.render_table(self.current_id)
        self.message.emit('Clip 配置已保存。')

    def set_asset(self,library,asset):
        self.library,self.asset=library,asset;self.current_id=None;self.data=None
        self.loading=True;self.table.clear();self.loading=False
        if not asset or asset['kind']!='animation':
            self.setEnabled(False);self.title.setText('选择动画来拆分 Clip');self.source.setText('T-pose 与单帧 Pose 无需拆分。');return
        self.data=clips.load(library,asset);self.setEnabled(True)
        self.preset.clear();self.preset.addItems(clips.presets(library))
        self.title.setText(asset['name']+' · Clip 拆分')
        source=self.data['source'];self.source.setText(f"源动画 {source['firstFrame']:g} — {source['lastFrame']:g} 帧 · {source['fps']:g} FPS")
        self.footer.setText('保存到该动画版本下的 clips.json；切换动画时自动保存。')
        self.render_table(self.data['clips'][0]['id'] if self.data['clips'] else None)

    def render_table(self,selected):
        self.loading=True;self.table.clear();target=None
        for clip in self.data['clips']:
            seconds=(clip['lastFrame']-clip['firstFrame'])/self.data['source']['fps']
            item=QTreeWidgetItem([clip['name'],f"{clip['firstFrame']:g}",f"{clip['lastFrame']:g}",f'{seconds:.3f} s'])
            item.setData(0,Qt.ItemDataRole.UserRole,clip['id']);self.table.addTopLevelItem(item)
            if clip['id']==selected:target=item
        if target:self.table.setCurrentItem(target)
        self.loading=False;self.current_id=selected;self.show_fields()

    def select_clip(self,item,old):
        if self.loading:return
        try:
            self.commit_current()
            clips.save(self.library,self.asset,self.data)
        except Exception as exc:
            self.message.emit(str(exc));self.loading=True;self.table.setCurrentItem(old);self.loading=False;return
        self.current_id=item.data(0,Qt.ItemDataRole.UserRole) if item else None
        self.show_fields()

    def show_fields(self):
        clip=self.current();self.body.setEnabled(clip is not None)
        if not clip:return
        self.name.setText(clip['name']);self.first.setValue(clip['firstFrame']);self.last.setValue(clip['lastFrame']);self.notes.setText(clip.get('notes',''))
        self.clip_settings.set_values(clip['settings'])
        self.take.setText(clip.get('takeName',''));self.target.setCurrentText(self.data.get('targetEditor','2022.3'))
        self.importer.set_values(self.data.get('fbxSettings',clips.fbx_defaults()))

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
