import os
os.environ.setdefault('QT_QPA_PLATFORM','windows')
import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout
from PySide6.QtCore import Qt
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
    panel.editor.add_clip();panel.editor.name.setText('Walk_Loop');panel.editor.first.setValue(20);panel.editor.last.setValue(80);panel.editor.loop.setChecked(True);panel.editor.flush()
    data=clips.load(library,animation);assert len(data['clips'])==2
    assert data['clips'][1]['settings']['loopTime'] and not data['clips'][0]['settings']['loopTime']
    panel.editor.last.setValue(999)
    try:panel.editor.flush()
    except ValueError:pass
    else:raise AssertionError('Invalid clip range accepted')
    assert clips.load(library,animation)==data
    panel.editor.last.setValue(80)
    before=[(c['id'],c['name'],c['firstFrame'],c['lastFrame']) for c in data['clips']]
    panel.editor.preset.setCurrentText('根运动行走 / 跑步');panel.editor.apply_selected_preset()
    after=clips.load(library,animation)
    assert before==[(c['id'],c['name'],c['firstFrame'],c['lastFrame']) for c in after['clips']]
    assert not after['clips'][1]['settings']['lockRootPositionXZ']
    panel.editor.importer.controls['globalScale'].setValue(0.01);panel.editor.flush()
    assert clips.load(library,animation)['fbxSettings']['globalScale']==0.01
    panel.open_gallery();app.processEvents();assert panel.gallery.cards.count()==2
    panel.gallery.category.setCurrentIndex(panel.gallery.category.findData('主角'));assert panel.gallery.cards.count()==1
    panel.gallery.grab().save(str(root/'local-data/characters.png'));panel.gallery.hide()
    panel.grab().save(str(root/'local-data/panel-workflow.png'))
    panel.shutdown();panel.shutdown();shell.close()
print('UI passed: embedded widget, sorting/search, role category gallery, independent clip settings, validation and persistence')
