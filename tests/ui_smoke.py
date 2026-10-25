import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
from pathlib import Path
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from ui.panel import create_panel
from ui.library import Library
root=Path(__file__).resolve().parents[1]
class Context:
    package_root=root
    def resource(self,path):return root/path
    def load_settings(self):return {}
    def save_settings(self,value):pass
app=QApplication([])
with tempfile.TemporaryDirectory() as temp:
    library=Library(Path(temp)/'library');library.initialize();library.create_character('测试角色')
    source=Path(temp)/'Walk.fbx';source.write_bytes(b'UI fixture')
    library.import_fbx('测试角色','Walk','animation',source)
    panel=create_panel(Context(),None);panel.resize(1200,920);panel.load_library(str(library.root));panel.show();app.processEvents()
    assert panel.assets.topLevelItemCount()==1
    panel.search.setText('missing');assert panel.assets.topLevelItemCount()==0
    panel.search.clear();assert panel.assets.topLevelItemCount()==1
    assert panel.max_rig.count()==3
    panel.grab().save(str(root/'local-data/panel.png'))
    panel.shutdown();panel.shutdown();panel.close()
print('UI smoke passed: rendering, character list, filtering, 3 rig modes, idempotent shutdown')
