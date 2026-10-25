from pathlib import Path
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon,QImage
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,QComboBox,
    QCheckBox,QFormLayout,QDialogButtonBox,QListWidget,QListWidgetItem,QFileDialog,QInputDialog,QMessageBox)
from .library import safe_name,contained


class CaptureDialog(QDialog):
    def __init__(self,panel,kind,update=None):
        super().__init__(panel)
        self.setWindowTitle('更新角色 T-pose' if update else '从 Max 导入角色' if kind=='model' else '从 Max 导入动画' if kind=='animation' else '保存当前帧 Pose')
        self.resize(470,310);form=QFormLayout(self)
        self.name=QLineEdit(update or '')
        self.name.setReadOnly(bool(update));form.addRow('角色名' if kind=='model' else '名称',self.name)
        self.category=QComboBox();self.category.addItem('未分类','')
        for category in panel.library.categories():self.category.addItem(category,category)
        self.rig=QComboBox();self.rig.addItems(['Generic','Biped','CAT'])
        self.textures=QCheckBox('同时复制贴图（可选）');self.avatar=QCheckBox('从当前视口生成头像');self.avatar.setChecked(True)
        if kind=='model':
            form.addRow('分类',self.category);form.addRow('骨骼类型',self.rig);form.addRow(self.textures);form.addRow(self.avatar)
            label=QLabel('先摆好 T-pose，再选中全部角色内容。\n模型、骨骼、控制器、辅助节点都必须选全。')
            if update:
                info=panel.library.character_info(update);self.rig.setCurrentText(info.get('rig','Generic'));self.category.setCurrentIndex(max(0,self.category.findData(info.get('category',''))))
        else:
            label=QLabel('动画读取当前 Max 场景的起止帧与 FPS，保存完整场景。' if kind=='animation' else '读取当前帧的角色姿态与可记录的控制器数值。')
        label.setWordWrap(True);form.addRow(label)
        self.notes=QLineEdit();form.addRow('备注',self.notes)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);form.addRow(buttons)

    def accept(self):
        try:safe_name(self.name.text())
        except ValueError as exc:QMessageBox.warning(self,'名称无效',str(exc));return
        super().accept()


class CharacterDialog(QDialog):
    def __init__(self,panel):
        super().__init__(panel);self.panel=panel
        self.setWindowTitle('角色库');self.resize(850,620)
        layout=QVBoxLayout(self);row=QHBoxLayout()
        self.search=QLineEdit();self.search.setPlaceholderText('搜索角色…');self.search.textChanged.connect(self.refresh)
        self.category=QComboBox();self.category.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.search,1);row.addWidget(self.category);row.addWidget(self.button('＋ 分类',self.add_category));layout.addLayout(row)
        self.cards=QListWidget();self.cards.setViewMode(QListWidget.ViewMode.IconMode);self.cards.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.cards.setMovement(QListWidget.Movement.Static);self.cards.setIconSize(QSize(110,110));self.cards.setGridSize(QSize(170,160));self.cards.setWordWrap(True)
        self.cards.itemDoubleClicked.connect(lambda *_:self.panel.guard(self.choose));layout.addWidget(self.cards,1)
        row=QHBoxLayout()
        for title,fn in [('从 Max 导入角色',lambda:panel.capture('model')),('更新 T-pose',self.update),('导出角色到 Max',self.export),('更换头像',self.avatar),('设置分类',self.set_category)]:row.addWidget(self.button(title,fn))
        layout.addLayout(row)
        row=QHBoxLayout();row.addWidget(QLabel('双击头像选择角色；更新 T-pose 保留已有动画和 Pose。'));row.addStretch();row.addWidget(self.button('选择角色',self.choose));layout.addLayout(row)
        self.reload_categories()

    def button(self,title,fn):
        b=QPushButton(title);b.clicked.connect(lambda _:self.panel.guard(fn));return b

    def selected(self):
        item=self.cards.currentItem()
        if not item:raise ValueError('请先选择角色。')
        return item.data(Qt.ItemDataRole.UserRole)

    def reload_categories(self):
        value=self.category.currentData();self.category.blockSignals(True);self.category.clear();self.category.addItem('全部分类',None);self.category.addItem('未分类','')
        for name in self.panel.library.categories():self.category.addItem(name,name)
        self.category.setCurrentIndex(max(0,self.category.findData(value)));self.category.blockSignals(False);self.refresh()

    def refresh(self,*_):
        current=self.cards.currentItem();selected=current.data(Qt.ItemDataRole.UserRole) if current else self.panel.active_character
        self.cards.clear();library=self.panel.library
        for name in library.characters():
            info=library.character_info(name)
            if self.search.text().casefold() not in name.casefold():continue
            if self.category.currentData() is not None and info['category']!=self.category.currentData():continue
            icon=self.panel.context.resource('.lxtool/icon.png')
            if info.get('avatar'):
                path=contained(library.root/'characters'/name,info['avatar'])
                if path.is_file():icon=path
            item=QListWidgetItem(QIcon(str(icon)),name+'\n'+(info['category'] or '未分类'))
            item.setData(Qt.ItemDataRole.UserRole,name);item.setToolTip('已有 T-pose' if info['tpose'] else '旧版空角色，请更新 T-pose')
            self.cards.addItem(item)
            if selected==name:self.cards.setCurrentItem(item)

    def choose(self):
        self.panel.choose_character(self.selected());self.accept()

    def update(self):self.panel.capture('model',update=self.selected())

    def export(self):
        asset=self.panel.library.character_info(self.selected())['tpose']
        if not asset:raise ValueError('角色没有 T-pose，请先更新。')
        self.panel.send_to_max(asset)

    def add_category(self):
        name,ok=QInputDialog.getText(self,'新建分类','分类名称')
        if ok:self.panel.library.add_category(name);self.reload_categories()

    def set_category(self):
        name=self.selected();items=['未分类',*self.panel.library.categories()]
        value,ok=QInputDialog.getItem(self,'设置分类','分类',items,0,False)
        if ok:self.panel.library.update_character_info(name,category='' if value=='未分类' else value);self.refresh()

    def avatar(self):
        name=self.selected();path,_=QFileDialog.getOpenFileName(self,'选择头像','','图片 (*.png *.jpg *.jpeg *.webp)')
        if not path:return
        image=QImage(path)
        if image.isNull():raise ValueError('头像不是有效图片。')
        output=self.panel.context.data_root/'avatar-upload.png';output.parent.mkdir(parents=True,exist_ok=True)
        if not image.scaled(256,256,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation).save(str(output)):raise ValueError('头像转换失败。')
        self.panel.library.set_avatar(name,output);self.refresh();self.panel.update_character_header()
