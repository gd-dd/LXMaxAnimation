"""Run with path to LXTools source as argv[1]; tests its real isolated loader."""
import json,sys,tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication,QWidget
sys.path.insert(0,sys.argv[1])
from native_panels import NativePanelHandle
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'.lxtool/manifest.json').read_text('utf-8'))
tool={**manifest,'id':'repo-999999999','root':str(root),'panelData':json.loads((root/'.lxtool/panel.json').read_text('utf-8'))}
app=QApplication([]);parent=QWidget();parent.resize(900,600);parent.show()
with tempfile.TemporaryDirectory() as temp:
    for _ in range(2):
        handle=NativePanelHandle(tool,temp,parent)
        assert QApplication.instance() is app
        assert handle.widget.parentWidget() is parent
        assert not handle.widget.isWindow()
        assert hasattr(handle.widget, "editor") and hasattr(handle.widget, "open_gallery")
        handle.widget.show();app.processEvents()
        assert handle.shutdown() is None
        app.processEvents()
print('LXTools native loader passed: embedded child widget, shared application, verified imports, reopen and shutdown')
