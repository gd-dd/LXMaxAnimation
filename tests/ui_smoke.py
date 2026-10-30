import os
os.environ.setdefault('QT_QPA_PLATFORM','windows')
import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit,QScrollArea
from ui.panel import create_panel
from ui.library import Library,write_json
from ui import clips
root=Path(__file__).resolve().parents[1]
app=QApplication([])
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
    panel.editor.tabs.setCurrentIndex(1);app.processEvents()
    spin=panel.editor.importer.controls['globalScale'];spin.setFocus();value=spin.value()
    scroll=panel.editor.importer.currentWidget();scroll.verticalScrollBar().setValue(0)
    wheel=QWheelEvent(QPointF(spin.rect().center()),QPointF(spin.mapToGlobal(spin.rect().center())),QPoint(),QPoint(0,-120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
    app.sendEvent(spin,wheel);app.processEvents()
    assert spin.value()==value and scroll.verticalScrollBar().value()>0
    combo=panel.editor.target;index=combo.currentIndex();combo.setFocus();app.sendEvent(combo,wheel);assert combo.currentIndex()==index
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
    # Inline metadata editing persists; double-click cancels delayed editing and only loads.
    asset_item=panel.assets.currentItem();asset_item.setText(3,'新的备注')
    assert library.list_assets('测试角色','新的备注')[0][0]['id']==animation['id']
    loaded=[];panel.send_to_max=lambda asset:loaded.append(asset['id'])
    rect=panel.assets.visualItemRect(asset_item);point=QPoint(rect.left()+20,rect.center().y())
    QTest.mouseClick(panel.assets.viewport(),Qt.MouseButton.LeftButton,pos=point)
    QTest.qWait(QApplication.doubleClickInterval()+150)
    assert panel.assets.findChild(QLineEdit) is not None
    rename=panel.assets.findChild(QLineEdit)
    QTest.keyClick(rename,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier);QTest.keyClicks(rename,'Walk_Run');QTest.keyClick(rename,Qt.Key.Key_Return);app.processEvents()
    assert library.list_assets('测试角色','Walk_Run')[0][0]['id']==animation['id']
    QTest.mouseDClick(panel.assets.viewport(),Qt.MouseButton.LeftButton,pos=point)
    QTest.qWait(QApplication.doubleClickInterval()+150)
    assert loaded==[animation['id']]
    panel.assets.clearSelection();panel.assets.setCurrentItem(None);app.processEvents();assert not panel.editor.isEnabled()
    panel.grab().save(str(root/'local-data/panel-empty.png'))
    panel.assets.setCurrentItem(asset_item);app.processEvents();assert panel.editor.isEnabled()
    panel.editor.tabs.setCurrentIndex(0)
    panel.open_gallery();app.processEvents();assert panel.gallery.cards.count()==2
    panel.gallery.category.setCurrentIndex(panel.gallery.category.findData('主角'));assert panel.gallery.cards.count()==1
    panel.gallery.grab().save(str(root/'local-data/characters.png'));panel.gallery.hide()
    panel.grab().save(str(root/'local-data/panel-workflow.png'))
    from unittest.mock import patch,Mock
    fake_exe=base/'3dsmax.exe';fake_exe.touch();process=Mock(pid=87654);process.poll.return_value=None
    panel.disconnect()
    with patch('ui.panel.host.available_windows',return_value=[]),patch('ui.panel.host.sessions',return_value=[]),patch('ui.panel.host.preferred_max',return_value=None),patch('ui.panel.QFileDialog.getOpenFileName',return_value=(str(fake_exe),'')) as picker,patch('ui.panel.host.launch_max',return_value=process) as launch:
        panel.start_max();panel.start_max()
        assert picker.call_count==1 and launch.call_count==1
        assert panel.settings['maxExecutable']==str(fake_exe)
        ready={'protocol':2,'directory':'test-session','pid':87654}
        with patch('ui.panel.host.sessions',return_value=[dict(ready,pid=12345)]):
            panel.poll();assert panel.active_session is None
        with patch('ui.panel.host.sessions',return_value=[ready]):
            panel.poll();assert panel.active_session=='test-session'
            panel.disconnect();panel.poll();assert panel.active_session is None
            panel.start_max();assert panel.active_session=='test-session' and launch.call_count==1
    panel.shutdown();panel.shutdown();shell.close()
print('UI passed: embedded widget, sorting/search, role category gallery, independent clip settings, validation and persistence')
