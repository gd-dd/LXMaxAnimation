from pathlib import Path
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon,QImage
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,QComboBox,
    QCheckBox,QFormLayout,QDialogButtonBox,QListWidget,QListWidgetItem,QFileDialog,QInputDialog,QMessageBox,QToolButton,QMenu)
from .library import safe_name,contained


class CreateAssetDialog(QDialog):
    def __init__(self,panel,new_character=False):
        super().__init__(panel)
        self.setWindowTitle('创建角色与首个资产' if new_character else '创建资产')
        self.setMinimumWidth(365)
        form=QFormLayout(self)
        self.character=QLineEdit()
        if new_character:
            form.addRow('角色名称',self.character)
        self.kind=QComboBox()
        for key,label in [('animation','动画'),('pose','Pose'),('model','T-pose')]:
            self.kind.addItem(label,key)
        self.name=QLineEdit()
        form.addRow('资产名称',self.name)
        form.addRow('资产类型',self.kind)
        hint=QLabel('先创建空资产，再用「保存修改」存入 Max 场景。')
        hint.setWordWrap(True)
        form.addRow(hint)
        self.new_character=new_character
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('创建')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);form.addRow(buttons)

    def accept(self):
        try:
            if self.new_character:safe_name(self.character.text())
            safe_name(self.name.text())
        except ValueError as error:
            QMessageBox.warning(self,'名称无效',str(error))
            return
        super().accept()


class CharacterDialog(QDialog):
    def __init__(self,panel):
        super().__init__(panel);self.panel=panel
        self.setWindowTitle('角色库');self.resize(850,620)
        layout=QVBoxLayout(self);row=QHBoxLayout()
        self.search=QLineEdit();self.search.setPlaceholderText('搜索角色…');self.search.textChanged.connect(self.refresh)
        self.category=QComboBox();self.category.currentIndexChanged.connect(self.refresh)
        self.category.setMinimumContentsLength(6);self.category.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.search,1);row.addWidget(self.category);layout.addLayout(row)
        self.cards=QListWidget();self.cards.setViewMode(QListWidget.ViewMode.IconMode);self.cards.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.cards.setMovement(QListWidget.Movement.Static);self.cards.setIconSize(QSize(110,110));self.cards.setGridSize(QSize(170,160));self.cards.setWordWrap(True)
        self.cards.itemDoubleClicked.connect(lambda *_:self.panel.guard(self.choose));layout.addWidget(self.cards,1)
        row=QHBoxLayout()
        row.addWidget(self.button('创建角色',lambda:panel.create_asset(new_character=True)))
        row.addWidget(self.button('删除角色',self.delete_role))
        more=QToolButton();more.setText('角色管理');more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup);menu=QMenu(more)
        for title,fn in [('更换头像',self.avatar),('设置分类',self.set_category),('新建分类',self.add_category)]:menu.addAction(title,lambda fn=fn:self.panel.guard(fn))
        more.setMenu(menu);row.addWidget(more);row.addStretch();row.addWidget(self.button('选择角色',self.choose))
        layout.addLayout(row)
        hint=QLabel('双击头像选择角色，然后在资产列表管理内容。');hint.setWordWrap(True);layout.addWidget(hint)
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
            item.setData(Qt.ItemDataRole.UserRole,name);item.setToolTip(name+'\n'+('已有 T-pose' if info['tpose'] else ('已有角色场景，可补存 T-pose' if info['reference'] else '暂无角色场景')))
            self.cards.addItem(item)
            if selected==name:self.cards.setCurrentItem(item)

    def choose(self):
        self.panel.choose_character(self.selected());self.accept()

    def delete_role(self):
        name=self.selected()
        self.panel.idle()
        prompt=f'将角色「{name}」及其动画、Pose 和历史版本移出角色库，文件保留在库内回收目录。确定继续？'
        if QMessageBox.question(self,'删除角色',prompt)!=QMessageBox.StandardButton.Yes:
            return
        self.panel.delete_character(name)

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
