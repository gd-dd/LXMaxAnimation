from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon,QImage
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,QComboBox,
    QCheckBox,QFormLayout,QDialogButtonBox,QListWidget,QListWidgetItem,QFileDialog,QInputDialog,QMessageBox,QToolButton,QMenu,QTreeWidget,QTreeWidgetItem,QPlainTextEdit,QTabWidget,QHeaderView)
from .library import safe_name,contained,KINDS
from . import integrations as host


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
        rename=self.button('重命名…',self.rename_role)
        rename.setEnabled(False)
        self.cards.currentItemChanged.connect(lambda current,_:rename.setEnabled(current is not None))
        row.addWidget(rename)
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

    def rename_role(self):
        name=self.selected()
        self.panel.idle()
        role_name,ok=QInputDialog.getText(self,'重命名角色','角色名称',text=name)
        if not ok:
            return
        self.panel.rename_character(name,role_name,on_done=lambda renamed:self.finish_rename(name,renamed))

    def finish_rename(self,name,renamed):
        if renamed and renamed!=name:
            if self.search.text().casefold() not in renamed.casefold():
                self.search.clear()
            self.refresh()
            for index in range(self.cards.count()):
                if self.cards.item(index).data(Qt.ItemDataRole.UserRole)==renamed:
                    self.cards.setCurrentRow(index)
                    break

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

class AssetDetailsDialog(QDialog):
    def __init__(self,panel,asset):
        super().__init__(panel)
        self.panel=panel
        self.asset=asset
        self.changed=False
        self.drafts={}
        self.history={}
        self.setWindowTitle('详情信息 · '+asset['name'])
        self.resize(760,620)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel(asset['character']+' / '+asset['name']+' · '+KINDS[asset['kind']]))
        self.versions=QTreeWidget()
        self.versions.setRootIsDecorated(False)
        self.versions.setHeaderLabels(['版本','保存时间','保存者'])
        self.versions.setColumnWidth(0,130)
        self.versions.setColumnWidth(1,205)
        self.versions.currentItemChanged.connect(self.show_version)
        layout.addWidget(self.versions,2)
        self.provenance=QLabel()
        self.provenance.setWordWrap(True)
        self.provenance.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.provenance)
        layout.addWidget(QLabel('版本备注'))
        self.notes=QPlainTextEdit()
        self.notes.setFixedHeight(76)
        self.notes.textChanged.connect(self.track_draft)
        layout.addWidget(self.notes)
        row=QHBoxLayout()
        self.save=self.button('保存备注',self.save_notes)
        self.reveal=self.button('打开版本目录',lambda:self.panel.reveal_asset(self.selected(),version=True))
        self.remove=self.button('删除所选版本…',self.delete_version)
        self.remove_all=self.button('删除全部版本…',lambda:self.delete_version(True))
        for button in (self.save,self.reveal,self.remove,self.remove_all):
            row.addWidget(button)
        row.addStretch()
        close=QPushButton('关闭')
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)
        layout.addWidget(QLabel('Git 提交记录'))
        self.commits=QPlainTextEdit()
        self.commits.setReadOnly(True)
        layout.addWidget(self.commits,2)
        self.reload(asset['id'])

    def button(self,text,action):
        button=QPushButton(text,self)
        button.clicked.connect(lambda _:self.panel.guard(action))
        return button

    @staticmethod
    def time(value):
        if not value:
            return '时间未知'
        try:
            return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
        except ValueError:
            return value

    def reload(self,selected=None):
        assets,errors=self.panel.library.list_assets(self.asset['character'],kind=self.asset['kind'])
        entries=[row for row in assets if row['name']==self.asset['name']]
        self.versions.blockSignals(True)
        try:
            self.versions.clear()
            for index,entry in enumerate(entries):
                tag=f'v{len(entries)-index:03d}'+(' · 最新' if not index else '')
                if entry.get('placeholder'):
                    tag+=' · 空'
                item=QTreeWidgetItem([tag,self.time(entry.get('created')),entry.get('createdBy') or '未记录'])
                item.setData(0,Qt.ItemDataRole.UserRole,entry)
                item.setToolTip(0,entry['revision'])
                self.versions.addTopLevelItem(item)
                if entry['id']==selected:
                    self.versions.setCurrentItem(item)
            if entries and self.versions.currentItem() is None:
                self.versions.setCurrentItem(self.versions.topLevelItem(0))
        finally:
            self.versions.blockSignals(False)
        self.origin=entries[-1] if entries else None
        self.show_version(self.versions.currentItem())
        if errors:
            self.panel.set_status('索引异常：'+' · '.join(errors))

    def show_version(self,item,*_):
        asset=item.data(0,Qt.ItemDataRole.UserRole) if item else None
        for widget in (self.notes,self.save,self.reveal,self.remove,self.remove_all):
            widget.setEnabled(asset is not None)
        self.notes.blockSignals(True)
        self.notes.setPlainText(self.drafts.get(asset['id'],asset.get('notes','')) if asset else '')
        self.notes.blockSignals(False)
        if not asset:
            self.provenance.setText('没有可用版本。')
            self.commits.clear()
            return
        try:
            history=self.commits_for(asset)
            if history:
                lines=[]
                for sha,author,author_time,committer,commit_time,message in history:
                    lines.append(f'{sha[:10]}  {message}\n作者 {author} · {self.time(author_time)}\n提交者 {committer} · {self.time(commit_time)}')
                self.commits.setPlainText('\n\n'.join(lines))
            else:
                self.commits.setPlainText('暂无 Git 提交。共享库推送后可在这里查看。')
        except Exception as error:
            history=[]
            self.commits.setPlainText('无法读取 Git 提交记录。'+str(error))
        origin=self.origin
        creator=asset.get('assetCreatedBy') or origin.get('assetCreatedBy') or origin.get('createdBy')
        version_author=asset.get('createdBy') or (history[-1][1] if history else None)
        if not creator:
            if origin['id']==asset['id']:
                creator=version_author
            else:
                try:
                    created_history=self.commits_for(origin)
                    if created_history:creator=created_history[-1][1]
                except (OSError,ValueError,RuntimeError):
                    pass
        created=asset.get('assetCreatedAt') or origin.get('assetCreatedAt') or origin.get('created')
        updated,update_time=asset.get('updatedBy'),asset.get('updatedAt')
        if history:
            author,committed=history[0][1:3]
            try:
                use_git=not update_time or datetime.fromisoformat(committed)>datetime.fromisoformat(update_time)
            except (TypeError,ValueError):
                use_git=not update_time
            if use_git:updated,update_time=author,committed
        update_time=update_time or asset.get('created')
        self.provenance.setText(
            f"资产创建  {creator or '未记录'} · {self.time(created)}\n"
            f"版本保存  {version_author or '未记录'} · {self.time(asset.get('created'))}\n"
            f"最近修改  {updated or '未记录'} · {self.time(update_time)}")

    def commits_for(self,asset):
        if asset['id'] not in self.history:
            self.history[asset['id']]=host.asset_history(self.panel.library.root,asset)
        return self.history[asset['id']]

    def track_draft(self):
        asset=self.selected()
        text=self.notes.toPlainText()
        if text==asset.get('notes',''):
            self.drafts.pop(asset['id'],None)
        else:
            self.drafts[asset['id']]=text

    def done(self,result):
        if self.drafts and QMessageBox.question(self,'版本备注','关闭详情并丢弃尚未保存的备注？')!=QMessageBox.StandardButton.Yes:
            return
        super().done(result)

    def selected(self):
        item=self.versions.currentItem()
        if item is None:
            raise ValueError('请选择一个版本。')
        return item.data(0,Qt.ItemDataRole.UserRole)

    def save_notes(self):
        self.panel.idle()
        asset=self.selected()
        self.panel.library.set_notes(asset,self.notes.toPlainText())
        self.drafts.pop(asset['id'],None)
        self.changed=True
        self.reload(asset['id'])
        self.panel.set_status('版本备注已保存。')

    def delete_version(self,all_versions=False):
        self.panel.idle()
        asset=self.selected()
        subject='全部版本' if all_versions else self.versions.currentItem().text(0)
        if QMessageBox.question(self,'删除资产版本',f'将「{asset["name"]}」的{subject}移入回收目录？')!=QMessageBox.StandardButton.Yes:
            return
        count=self.panel.library.delete_asset(asset,all_versions)
        if all_versions:self.drafts.clear()
        else:self.drafts.pop(asset['id'],None)
        self.changed=True
        self.reload()
        self.panel.set_status(f'已将 {count} 个资产版本移入回收目录。')

class LibrarySyncDialog(QDialog):
    def __init__(self,panel):
        super().__init__(panel)
        self.setWindowTitle('共享资产库详情')
        self.resize(700,490)
        layout=QVBoxLayout(self)
        library=panel.require_library()
        self.state=panel.library_state or {}
        remote=self.state.get('remote')
        source=urlsplit(remote) if remote else None
        address=source.hostname+source.path if source and source.hostname else '已连接共享仓库' if remote else '尚未连接'
        cloud=panel.library_last_cloud or ('最近获取的记录' if self.state.get('checked') else '尚未刷新')
        messages=[f'本地目录  {library.root}',f'云端  {address} · {cloud}']
        last=panel.settings.get('lastLibrarySync',{})
        if last.get('library')==str(library.root):
            messages.append(f"上次操作  {last['time']} · {last['message']}")
        if panel.library_feedback:
            messages.append(panel.library_feedback)
        for text in messages:
            label=QLabel(text)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(label)
        self.tabs=QTabWidget()
        self.tables={}
        for key,title,count,unit in (
                ('dirty','本地改动',len(self.state.get('dirty',[])),'项'),
                ('outgoing','待推送',self.state.get('ahead',0),'个提交'),
                ('incoming','云端更新',self.state.get('behind',0),'个提交')):
            table=QTreeWidget()
            table.setRootIsDecorated(False)
            table.setHeaderLabels(['变更','资产库中的路径'])
            table.header().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
            for code,path in self.state.get(key,[]):
                label={'A':'新增','M':'修改','D':'删除','R':'移动','C':'复制','?':'新增','U':'冲突'}.get(code[:1],code)
                item=QTreeWidgetItem([label,path])
                item.setToolTip(1,path)
                table.addTopLevelItem(item)
            self.tables[key]=table
            self.tabs.addTab(table,f'{title} · {count} {unit}')
        layout.addWidget(self.tabs,1)
        row=QHBoxLayout()
        def goto(action):
            self.accept()
            panel.guard(action)
        row.addWidget(panel.button('共享设置…',lambda:goto(panel.library_settings)))
        row.addWidget(panel.button('刷新',lambda:goto(lambda:panel.library_action('refresh'))))
        row.addStretch()
        row.addWidget(panel.button('关闭',self.reject))
        layout.addLayout(row)
