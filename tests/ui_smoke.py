import os
os.environ.setdefault('QT_QPA_PLATFORM','windows')
import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtGui import QWheelEvent,QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit,QScrollArea,QDialog,QPlainTextEdit
from ui.panel import create_panel
from ui.library import Library,write_json
from ui import clips
root=Path(__file__).resolve().parents[1]
output=Path(os.environ.get('LX_ANIMATION_QA_OUTPUT',str(root/'local-data')));output.mkdir(parents=True,exist_ok=True)
app=QApplication([])
font_path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/msyh.ttc'
if font_path.is_file():
    font_id=QFontDatabase.addApplicationFont(str(font_path))
    assert font_id>=0,'Could not read existing Chinese font'
    font=app.font();font.setFamily(QFontDatabase.applicationFontFamilies(font_id)[0]);app.setFont(font)
with tempfile.TemporaryDirectory() as temp:
    base=Path(temp);library=Library(base/'library');library.initialize();library.add_category('主角')
    source=base/'source';source.mkdir();(source/'asset.fbx').write_bytes(b'UI test fixture');write_json(source/'tpose.json',{'schema':1})
    metadata={'rig':'Generic','fps':30,'start':0,'end':120,'signature':[{'name':'root'}]}
    library.import_character('测试角色',source,'asset.fbx',metadata,'主角')
    library.import_character('另一个角色',source,'asset.fbx',metadata)
    animation=library.publish('测试角色','Walk','animation',source,'asset.fbx',notes='行走循环',metadata=metadata)
    library.publish('测试角色','Idle','animation',source,'asset.fbx',notes='待机',metadata=metadata)
    class Context:
        package_root=root;data_root=base/'data'
        def resource(self,path):return root/path
        def load_settings(self):return {'library':str(library.root),'character':'测试角色'}
        def save_settings(self,value):pass
    shell=QWidget();shell.resize(1300,920);layout=QVBoxLayout(shell)
    panel=create_panel(Context(),shell);layout.addWidget(panel);shell.show();app.processEvents()
    assert not panel.isWindow()
    assert panel.assets.topLevelItemCount()==3
    panel.search.setText('missing');assert panel.assets.topLevelItemCount()==0
    panel.search.clear();assert panel.assets.topLevelItemCount()==3
    panel.assets.sortItems(0,Qt.SortOrder.DescendingOrder)
    assert panel.assets.topLevelItem(0).text(0)=='Walk'
    panel.assets.setCurrentItem(panel.assets.topLevelItem(0));app.processEvents()
    panel.editor.add_clip();app.processEvents();row=panel.editor.table.currentItem()
    clip_rect=panel.editor.table.visualItemRect(row)
    QTest.mouseClick(panel.editor.table.viewport(),Qt.MouseButton.LeftButton,pos=QPoint(clip_rect.left()+20,clip_rect.center().y()))
    QTest.mouseDClick(panel.editor.table.viewport(),Qt.MouseButton.LeftButton,pos=QPoint(clip_rect.left()+20,clip_rect.center().y()))
    app.processEvents();assert panel.editor.table.findChild(QLineEdit) is not None
    QTest.keyClick(panel.editor.table.findChild(QLineEdit),Qt.Key.Key_Escape)
    row.setText(0,'Walk_Loop');row.setText(1,'20');row.setText(2,'80');row.setCheckState(3,Qt.CheckState.Checked)
    data=clips.load(library,animation);assert len(data['clips'])==2
    assert data['clips'][1]['settings']['loopTime'] and not data['clips'][0]['settings']['loopTime']
    assert panel.editor.loop.isChecked()
    panel.editor.loop.setChecked(False);assert row.checkState(3)==Qt.CheckState.Unchecked
    panel.editor.loop.setChecked(True);assert row.checkState(3)==Qt.CheckState.Checked
    row.setText(2,'999');app.processEvents()
    assert clips.load(library,animation)==data
    assert panel.editor.table.currentItem().text(2)=='80'
    # Wheel over a focused value must scroll the active page, never alter the value.
    panel.editor.advanced_toggle.setChecked(True);panel.editor.tabs.setCurrentIndex(1);app.processEvents()
    spin=panel.editor.importer.controls['globalScale'];spin.setFocus();value=spin.value()
    scroll=panel.editor.importer.currentWidget();scroll.verticalScrollBar().setValue(0)
    wheel=QWheelEvent(QPointF(spin.rect().center()),QPointF(spin.mapToGlobal(spin.rect().center())),QPoint(),QPoint(0,-120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
    app.sendEvent(spin,wheel);app.processEvents()
    assert spin.value()==value and scroll.verticalScrollBar().value()>0
    combo=panel.editor.target;index=combo.currentIndex();combo.setFocus();app.sendEvent(combo,wheel);assert combo.currentIndex()==index
    # Normal full-text viewers keep their own scrolling; only expanding JSON uses the page scrollbar.
    viewer=QDialog(panel);viewer.resize(350,160);viewer_box=QVBoxLayout(viewer)
    text=QPlainTextEdit('\n'.join(str(i) for i in range(100)));viewer_box.addWidget(text);viewer.show();app.processEvents()
    app.sendEvent(text.viewport(),wheel);app.processEvents();assert text.verticalScrollBar().value()>0
    viewer.close()
    # No page scrollbar is nested inside another page scrollbar.
    for area in panel.editor.findChildren(QScrollArea):
        parent=area.parentWidget()
        while parent:
            assert not isinstance(parent,QScrollArea)
            parent=parent.parentWidget()
    before=[(c['id'],c['name'],c['firstFrame'],c['lastFrame']) for c in data['clips']]
    panel.editor.preset.setCurrentText('根运动行走 / 跑步');panel.editor.apply_selected_preset()
    after=clips.load(library,animation)
    assert before==[(c['id'],c['name'],c['firstFrame'],c['lastFrame']) for c in after['clips']]
    assert not after['clips'][1]['settings']['lockRootPositionXZ']
    panel.editor.importer.controls['globalScale'].setValue(0.01);panel.editor.flush()
    assert clips.load(library,animation)['fbxSettings']['globalScale']==0.01
    # Inline metadata editing persists; double-click leaves the working scene alone.
    asset_item=panel.assets.currentItem();asset_item.setText(4,'新的备注')
    assert library.list_assets('测试角色','新的备注')[0][0]['id']==animation['id']
    send_to_max=panel.send_to_max
    loaded=[];panel.send_to_max=lambda asset,**options:loaded.append(asset['id'])
    rect=panel.assets.visualItemRect(asset_item);point=QPoint(rect.left()+20,rect.center().y())
    QTest.mouseClick(panel.assets.viewport(),Qt.MouseButton.LeftButton,pos=point)
    QTest.qWait(QApplication.doubleClickInterval()+150)
    assert panel.assets.findChild(QLineEdit) is not None
    rename=panel.assets.findChild(QLineEdit)
    QTest.keyClick(rename,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier);QTest.keyClicks(rename,'Walk_Run');QTest.keyClick(rename,Qt.Key.Key_Return);app.processEvents()
    assert library.list_assets('测试角色','Walk_Run')[0][0]['id']==animation['id']
    QTest.mouseDClick(panel.assets.viewport(),Qt.MouseButton.LeftButton,pos=point)
    QTest.qWait(QApplication.doubleClickInterval()+150)
    assert not loaded
    panel.send_to_max=send_to_max
    second=library.publish(animation['character'],'Walk_Run','animation',source,'asset.fbx',metadata=metadata)
    panel.assets.setCurrentItem(None);panel.refresh_assets(select_id=second['id'])
    assert panel.assets.topLevelItemCount()==3 and panel.version_choice.count()==2
    assert panel.selected_asset()['id']==second['id'] and panel.version_choice.currentIndex()==0
    panel.version_choice.setCurrentIndex(1)
    assert panel.selected_asset()['id']==animation['id']
    asset_item=panel.assets.currentItem()
    panel.assets.clearSelection();panel.assets.setCurrentItem(None);app.processEvents();assert not panel.editor.isEnabled()
    panel.grab().save(str(output/'panel-empty.png'))
    panel.assets.setCurrentItem(asset_item);app.processEvents();assert panel.editor.isEnabled()
    panel.editor.tabs.setCurrentIndex(0)
    panel.open_gallery();app.processEvents();assert panel.gallery.cards.count()==2
    panel.gallery.category.setCurrentIndex(panel.gallery.category.findData('主角'));assert panel.gallery.cards.count()==1
    panel.gallery.grab().save(str(output/'characters.png'));panel.gallery.hide()
    panel.grab().save(str(output/'panel-workflow.png'))
    from unittest.mock import patch,Mock
    fake_exe=base/'3dsmax.exe';fake_exe.touch();process=Mock(pid=87654);process.poll.return_value=None
    panel.disconnect()
    with patch('ui.panel.host.available_windows',return_value=[]),patch('ui.panel.host.sessions',return_value=[]),patch('ui.panel.host.preferred_max',return_value=None),patch('ui.panel.QFileDialog.getOpenFileName',return_value=(str(fake_exe),'')) as picker,patch('ui.panel.host.launch_max',return_value=process) as launch:
        panel.start_max();panel.start_max()
        assert picker.call_count==1 and launch.call_count==1
        assert panel.settings['maxExecutable']==str(fake_exe)
        ready={'protocol':2,'assetWorkspace':1,'directory':'test-session','pid':87654}
        with patch('ui.panel.host.sessions',return_value=[dict(ready,pid=12345)]):
            panel.poll();assert panel.active_session is None
        with patch('ui.panel.host.sessions',return_value=[ready]):
            panel.poll();assert panel.active_session=='test-session'
            panel.disconnect();panel.poll();assert panel.active_session is None
            panel.start_max();assert panel.active_session=='test-session' and launch.call_count==1
    from PySide6.QtWidgets import QMessageBox
    panel.gallery.category.setCurrentIndex(0)
    cards=panel.gallery.cards
    other=next(cards.item(i) for i in range(cards.count())
               if cards.item(i).data(Qt.ItemDataRole.UserRole)=='另一个角色')
    cards.setCurrentItem(other)
    with patch('ui.dialogs.QMessageBox.question',return_value=QMessageBox.StandardButton.No):
        panel.gallery.delete_role()
    assert '另一个角色' in library.characters()
    with patch('ui.dialogs.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
        panel.gallery.delete_role()
    assert '另一个角色' not in library.characters()
    assert len(list((library.root/'.staging/deleted-characters').glob('*/character.json')))==1
    from ui.dialogs import CreateAssetDialog
    def enter_dialog(dialog):
        dialog.character.setText('新角色')
        dialog.name.setText('第一条动画')
        dialog.grab().save(str(output/'create-character.png'))
        return QDialog.DialogCode.Accepted
    with patch.object(CreateAssetDialog,'exec',enter_dialog):
        panel.create_asset(new_character=True)
    selected=panel.selected_asset()
    assert selected['placeholder'] and selected['character']=='新角色'
    assert panel.save_button.isEnabled() and not panel.apply_button.isEnabled() and not panel.key_asset.isEnabled()
    assert not panel.editor.isEnabled()
    assert [panel.save_button.text(),panel.apply_button.text(),panel.key_asset.text()]==['保存修改','覆盖场景','覆盖帧']
    panel.grab().save(str(output/'panel-placeholder.png'))
    (source/'source.max').write_bytes(b'full Max fixture')
    (source/'animation-keys.json').write_text('{}')
    saved=library.save_asset_revision(selected,'animation',source,'source.max',dict(metadata,fullCharacterScene=True))
    assert library.verify(saved).name=='source.max'
    assert library.character_info('新角色')['reference']['id']==saved['id']
    panel.refresh_assets(select_id=saved['id'])
    assert panel.version_choice.count()==1
    assert panel.apply_button.isEnabled() and panel.key_asset.isEnabled()
    write_json(source/'pose.json',{'schema':1})
    old_pose=library.publish('新角色','TPose','pose',source,'pose.json',metadata={'frame':0})
    new_pose=library.publish('新角色','TPose','pose',source,'pose.json',metadata={'frame':0})
    tpose=library.publish('新角色','基准','model',source,'source.max',metadata={'frame':0})
    target=dict(ready,frameApply=2,scene=str(base/'current.max'))
    result=base/'applied.result.json'
    with (patch('ui.panel.host.sessions',return_value=[dict(ready,frameApply=1)]),
          patch('ui.panel.host.request') as request):
        panel.key_asset.click()
        request.assert_not_called()
        assert '旧版连接组件' in panel.status.text()
    for asset,payload in ((saved,'animation-keys.json'),(new_pose,'pose.json'),(tpose,'tpose.json')):
        panel.refresh_assets(select_id=asset['id'])
        panel.bind_asset(saved,target['directory'],target['scene'])
        binding=panel.editing_asset.copy()
        assert panel.key_asset.isEnabled()
        with (patch('ui.panel.host.sessions',return_value=[target]),
              patch('ui.panel.host.request',return_value=result) as request,
              patch.object(panel,'run_job',side_effect=lambda work,label,done:done(work())),
              patch.object(panel.editor,'flush',side_effect=AssertionError('Frame apply must not save configuration')),
              patch.object(QDialog,'exec',side_effect=AssertionError('Frame apply must be a single action'))):
            panel.key_asset.click()
            request.assert_called_once_with(target,'applyAssetFrames',path=str(Path(asset['_directory'])/payload),
                                            kind=asset['kind'],rig='Generic',expectedScene=target['scene'],
                                            sourceFps=asset['metadata'].get('fps'))
            write_json(result,{'ok':True,'message':'帧应用成功。'})
            panel.poll()
            assert panel.pending is None and panel.editing_asset==binding
    result.unlink()
    library.delete_asset(tpose,False)
    panel.refresh_assets(select_id=new_pose['id'],flush=False)
    menu=panel.delete_asset_button.menu()
    assert not panel.editor.isEnabled() and panel.delete_asset_button.isEnabled()
    with patch('ui.panel.QMessageBox.question',return_value=QMessageBox.StandardButton.No):
        menu.actions()[0].trigger()
    assert panel.selected_asset()['id']==new_pose['id']
    with patch('ui.panel.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
        menu.actions()[0].trigger()
        assert panel.selected_asset()['id']==old_pose['id']
        menu.actions()[1].trigger()
        assert not panel.delete_asset_button.isEnabled()
        old_animation=library.publish('新角色','旧动画','animation',source,'asset.fbx')
        panel.refresh_assets(select_id=old_animation['id'],flush=False)
        assert not panel.editor.isEnabled() and panel.delete_asset_button.isEnabled()
        menu.actions()[0].trigger()
    archived=library.root/'.staging/deleted-animations'
    assert len(list(archived.glob('*/*/asset.json')))==1 and not list(archived.glob('*/*/clips.json'))
    assert [entry['id'] for entry in library.list_assets('新角色')[0]]==[saved['id']]
    from ui.dialogs import AssetDetailsDialog
    older=library.publish('新角色','共用表情','pose',source,'pose.json',metadata={'frame':0})
    newer=library.publish('新角色','共用表情','pose',source,'pose.json',metadata={'frame':8})
    panel.refresh_assets(select_id=newer['id'],flush=False)
    actions=[]
    def exercise_details(dialog):
        assert dialog.versions.topLevelItemCount()==2
        assert dialog.selected()['id']==newer['id']
        with patch('ui.panel.os.startfile',create=True) as reveal:
            dialog.reveal.click()
            reveal.assert_called_once_with(newer['_directory'])
        dialog.versions.setCurrentItem(dialog.versions.topLevelItem(1))
        dialog.notes.setPlainText('历史版本保留原表情')
        dialog.save.click()
        assert dialog.selected()['id']==older['id']
        assert dialog.selected()['notes']=='历史版本保留原表情'
        dialog.grab().save(str(output/'asset-details.png'))
        with patch('ui.dialogs.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
            dialog.remove.click()
        assert dialog.versions.topLevelItemCount()==1
        assert dialog.selected()['id']==newer['id']
        actions.append('details')
        return QDialog.DialogCode.Accepted
    class DetailsMenu:
        def __init__(self,parent):pass
        def addAction(self,text,action):
            if text=='详情信息…':self.action=action
            else:
                assert text=='打开资产目录'
                with patch('ui.panel.os.startfile',create=True) as reveal:
                    action()
                    reveal.assert_called_once_with(str(library.asset_location(newer)[0]))
        def exec(self,position):
            self.action()
    with patch.object(AssetDetailsDialog,'exec',exercise_details),patch('ui.panel.QMenu',DetailsMenu):
        area=panel.assets.visualItemRect(panel.assets.currentItem())
        panel.assets.customContextMenuRequested.emit(area.center())
    assert actions==['details'] and panel.selected_asset()['id']==newer['id'], (actions,panel.status.text(),area)
    assert not Path(older['_directory']).exists()
    from ui.dialogs import LibrarySyncDialog
    from ui import integrations
    state=dict(ready=True,remote='https://github.com/example/shared.git',dirty=[('M','characters/角色/animation/待机/asset.json')],
               outgoing=[],incoming=[('A','characters/角色/animation/走路/asset.json')],ahead=0,behind=1,checked=True,
               branch='main',has_head=True,has_cloud=True)
    with (patch.object(panel,'run_job',side_effect=lambda work,label,done:done(work())),
          patch.object(integrations,'library_sync_state',return_value=state) as read_state):
        panel.library_refresh.click()
        read_state.assert_called_once_with(panel.library.root,check_cloud=True)
        assert '云端更新 1' in panel.library_summary.text()
        assert panel.library_push.isEnabled() and not panel.library_pull.isEnabled()
        assert panel.library_overwrite.isEnabled() and panel.library_restore.isEnabled()
        with patch.object(integrations,'sync_git') as sync_git:
            from PySide6.QtWidgets import QMessageBox
            with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No):
                panel.library_overwrite.click()
                sync_git.assert_not_called()
        detail=LibrarySyncDialog(panel)
        assert detail.tables['dirty'].topLevelItemCount()==1 and detail.tables['incoming'].topLevelItemCount()==1
        detail.grab().save(str(output/'shared-sync.png'))
        detail.close()
        read_state.return_value=dict(state,dirty=[])
        panel.library_refresh.click()
        assert panel.library_pull.isEnabled()
        shell.grab().save(str(output/'shared-main.png'))
    panel.shutdown();panel.shutdown();shell.close()
print('UI passed: embedded widget, sorting/search, role category gallery, independent clip settings, validation and persistence')
