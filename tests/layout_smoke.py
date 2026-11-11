"""Offscreen layout and draft acceptance; uses only an isolated E: fixture.

Run with LXTools' Python and -B. No scene connection, screen input or user library
is used. Screenshots are actual Qt renders, not mockups.
"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get('LX_ANIMATION_LAYOUT_OUTPUT',
    'E:/project/LXTools/acceptance/animation-ui-2026-11-12/layout'))
if OUTPUT.resolve().drive.upper() != 'E:':
    raise RuntimeError('Layout output must stay on E:')
OUTPUT.mkdir(parents=True, exist_ok=True)
for name in ('TEMP', 'TMP', 'APPDATA', 'LOCALAPPDATA', 'USERPROFILE'):
    folder = OUTPUT / name
    folder.mkdir(exist_ok=True)
    os.environ[name] = str(folder)
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QPoint, QRect
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QToolButton
from unittest.mock import patch
from ui.panel import create_panel
from ui.library import Library, write_json
from ui import clips


def main():
    app = QApplication([])
    # The offscreen plugin can otherwise choose a Latin-only fallback after the
    # E: profile redirect. Read the existing OS font; never install or copy it.
    font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        assert font_id >= 0, 'Could not read the existing Chinese font'
        font = app.font(); font.setFamily(QFontDatabase.applicationFontFamilies(font_id)[0]); app.setFont(font)
    report = {'ok': False, 'checks': [], 'geometry': [], 'errors': [],
              'screenInput': False, 'maxTouched': False, 'userAssetsTouched': False,
              'fontFamily': app.font().family(), 'fontPointSize': app.font().pointSizeF(),
              'qtScaleFactor': os.environ.get('QT_SCALE_FACTOR', '1'),
              'devicePixelRatio': app.devicePixelRatio()}
    def check(name, fn):
        try:
            fn()
            report['checks'].append(name)
        except Exception:
            report['errors'].append({'check': name, 'traceback': traceback.format_exc()})

    with tempfile.TemporaryDirectory(prefix='fixture-', dir=OUTPUT) as folder:
        base = Path(folder)
        library = Library(base / 'library'); library.initialize()
        library.add_category('测试角色分类')
        source = base / 'source'; source.mkdir()
        (source / 'asset.fbx').write_bytes(b'Isolated UI fixture, not an FBX host test')
        write_json(source / 'tpose.json', {'schema': 1})
        role = '角色名称很长用于验证省略与完整提示_' * 3
        other_role = '切换返回测试角色'
        name = '动作名称很长用于验证省略与完整提示_' * 3
        metadata = {'rig': 'Generic', 'fps': 30, 'start': 0, 'end': 120,
                    'signature': [{'name': 'root'}]}
        for character in (role, other_role):
            library.import_character(character, source, 'asset.fbx', metadata, '测试角色分类')
        animation = library.publish(role, name, 'animation', source, 'asset.fbx',
                                    notes='长备注_' * 35, metadata=metadata)
        library.publish(role, 'Idle', 'animation', source, 'asset.fbx', metadata=metadata)
        library.publish(other_role, 'Other', 'animation', source, 'asset.fbx', metadata=metadata)
        document = clips.document(animation)
        document['clips'].append(clips.new_clip('第二段动作', 20, 60))
        clips.save(library, animation, document)
        clip_id = document['clips'][1]['id']

        class Context:
            package_root = ROOT
            data_root = base / 'data'
            def __init__(self):
                self.settings = {'library': str(library.root), 'character': role}
            def resource(self, path): return ROOT / path
            def load_settings(self): return copy.deepcopy(self.settings)
            def save_settings(self, settings): self.settings = copy.deepcopy(settings)
        context = Context()
        shell = QWidget(); box = QVBoxLayout(shell)
        panel = create_panel(context, shell); box.addWidget(panel)
        shell.resize(1280, 800); shell.show(); app.processEvents()

        def find_asset(identifier):
            return next(panel.assets.topLevelItem(i) for i in range(panel.assets.topLevelItemCount())
                        if panel.assets.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)['id'] == identifier)
        panel.assets.setCurrentItem(find_asset(animation['id'])); app.processEvents()
        panel.editor.table.setCurrentItem(panel.editor.table.topLevelItem(1)); app.processEvents()

        def visible_inside(widget):
            assert widget.isVisibleTo(shell), widget.objectName() or widget.text()
            rect = QRect(widget.mapTo(shell, QPoint(0, 0)), widget.size())
            assert QRect(QPoint(0, 0), shell.size()).contains(rect), (widget, rect, shell.size())

        def geometry_case(width, height, advanced):
            shell.resize(width, height); app.processEvents()
            assert shell.size().toTuple() == (width, height), (
                'window forced larger', (width, height), shell.size().toTuple(), panel.minimumSizeHint().toTuple())
            if width == 700:
                assert panel.narrow_tabs.isVisible()
                panel.narrow_tabs.setCurrentIndex(0); app.processEvents()
                visible_inside(panel.assets); visible_inside(panel.search)
                assert panel.left.isVisible() and not panel.right.isVisible()
                panel.narrow_tabs.setCurrentIndex(1); app.processEvents()
                assert panel.right.isVisible() and not panel.left.isVisible()
            else:
                assert not panel.narrow_tabs.isVisible()
                assert panel.left.isVisible() and panel.right.isVisible()
                visible_inside(panel.assets)
            panel.editor.advanced_toggle.setChecked(advanced); app.processEvents()
            assert shell.size().toTuple() == (width, height), ('advanced forced larger', shell.size().toTuple())
            for widget in (panel.connect_button, panel.apply_button, panel.save_button,
                           panel.editor.advanced_toggle, panel.editor.save_config):
                visible_inside(widget)
            if advanced:
                assert not panel.editor.table.isVisible()
                for widget in (panel.editor.target, panel.editor.preset, panel.editor.tabs): visible_inside(widget)
                assert panel.editor.current_scroll().viewport().height() >= 50
            else:
                visible_inside(panel.editor.table)
            report['geometry'].append({'requested': [width, height], 'actual': list(shell.size().toTuple()),
                                       'advanced': advanced, 'panel': list(panel.size().toTuple()),
                                       'editor': list(panel.editor.size().toTuple())})
            assert panel.grab().save(str(OUTPUT / f'panel-{width}-{height}-advanced-{advanced}.png'))

        for width, height in ((700, 650), (960, 700), (1280, 800)):
            for advanced in (False, True):
                check(f'geometry-{width}-{height}-advanced-{advanced}',
                      lambda w=width, h=height, a=advanced: geometry_case(w, h, a))

        def long_names():
            assert panel.character_title.toolTip() == role
            assert panel.selection_label.toolTip() == name
            item = find_asset(animation['id'])
            assert item.toolTip(0) == name and item.toolTip(3) == '长备注_' * 35
            assert panel.editor.title.toolTip() == '当前 Clip：第二段动作'
        check('long-names-have-full-tooltips', long_names)

        def selection_roundtrip():
            assert panel.editor.current_id == clip_id
            panel.refresh_assets(); app.processEvents()
            assert panel.selected_asset()['id'] == animation['id'] and panel.editor.current_id == clip_id
            panel.search.setText('not-existing-filter'); app.processEvents()
            assert panel.assets.topLevelItemCount() == 0
            panel.search.clear(); app.processEvents()
            assert panel.selected_asset()['id'] == animation['id'] and panel.editor.current_id == clip_id
            panel.choose_character(other_role); app.processEvents()
            panel.choose_character(role); app.processEvents()
            assert panel.selected_asset()['id'] == animation['id'] and panel.editor.current_id == clip_id
        check('clip-and-asset-selection-roundtrip', selection_roundtrip)

        event_text = '[\n  {"functionName": "DraftEvent"}\n'  # Intentionally incomplete JSON.
        human_text = '{\n  "human": [\n'  # Another independent invalid draft.
        def draft_roundtrip():
            editor = panel.editor
            editor.advanced_toggle.setChecked(True)
            editor.clip_settings.controls['events'].setPlainText(event_text)
            editor.importer.controls['humanDescription'].setPlainText(human_text)
            editor.importer.controls['globalScale'].setValue(0.123)
            editor.tabs.setCurrentIndex(1); editor.importer.setCurrentIndex(1); app.processEvents()
            editor.advanced_toggle.setChecked(False); editor.advanced_toggle.setChecked(True); app.processEvents()
            assert editor.clip_settings.controls['events'].toPlainText() == event_text
            assert editor.importer.controls['humanDescription'].toPlainText() == human_text
            assert editor.importer.controls['globalScale'].value() == 0.123
            assert editor.tabs.currentIndex() == 1 and editor.importer.currentIndex() == 1
            item = editor.table.currentItem(); item.setText(2, '999'); app.processEvents(); app.processEvents()
            assert editor.table.currentItem().text(2) == '60', 'Invalid table edit was not reverted'
            assert editor.clip_settings.controls['events'].toPlainText() == event_text, 'Table error discarded event draft'
            assert editor.importer.controls['humanDescription'].toPlainText() == human_text, 'Table error discarded rig draft'
            assert editor.importer.controls['globalScale'].value() == 0.123
        check('advanced-toggle-and-table-error-preserve-raw-drafts', draft_roundtrip)

        def reopen_draft():
            nonlocal panel
            panel.shutdown(); box.removeWidget(panel); panel.hide(); panel.deleteLater(); app.processEvents()
            draft_path = context.data_root / 'clip-drafts.json'
            assert draft_path.is_file() and json.loads(draft_path.read_text('utf-8')), 'No persisted invalid draft'
            panel = create_panel(context, shell); box.addWidget(panel); app.processEvents()
            assert panel.active_character == role and panel.selected_asset()['id'] == animation['id']
            assert panel.editor.current_id == clip_id
            assert panel.editor.clip_settings.controls['events'].toPlainText() == event_text
            assert panel.editor.importer.controls['humanDescription'].toPlainText() == human_text
            assert panel.editor.importer.controls['globalScale'].value() == 0.123
            assert panel.editor.advanced_toggle.isChecked()
            assert panel.editor.tabs.currentIndex() == 1 and panel.editor.importer.currentIndex() == 1
            panel.grab().save(str(OUTPUT / 'draft-restored.png'))
        check('close-reopen-restores-complete-invalid-draft', reopen_draft)
        panel.shutdown(); shell.close(); app.processEvents()

        # Include the platform sidebar, header, inherited stylesheet and native
        # loader. A bare QWidget has materially more space than the real host.
        sys.path.insert(0, 'E:/project/LXTools/LXTools/src')
        from desktop import Window, STYLE
        from core import ToolStore
        app.setStyle('Fusion');app.setStyleSheet(STYLE)
        host_profile=base/'host-profile';host_data=host_profile/'tool-data/repo-1433389279'
        write_json(host_data/'panel-settings.json',{'library':str(library.root),'character':role,
                   'selectedAssets':{role:animation['id']}})
        manifest=json.loads((ROOT/'.lxtool/manifest.json').read_text('utf-8'))
        tool=dict(manifest,id='repo-1433389279',repository='gd-dd/LXMaxAnimation',root=str(ROOT),
                  panelData=json.loads((ROOT/'.lxtool/panel.json').read_text('utf-8')))
        window=Window(ToolStore(host_profile),base/'host-tools',autoload=False)
        window.panel_title.setText('LXMaxAnimation · 0.0.4')
        window.workspace.display(tool);window.pages.setCurrentWidget(window.tool_panel)
        window.show();app.processEvents()
        native=window.workspace.native_panel.widget
        report['hostGeometry']=[]
        def host_geometry(width,height):
            window.resize(width,height);app.processEvents()
            assert window.size().toTuple()==(width,height)
            if native.narrow_tabs.isVisible():native.narrow_tabs.setCurrentIndex(1)
            for advanced in (False,True):
                native.editor.advanced_toggle.setChecked(advanced);app.processEvents()
                for widget in (native.connect_button,native.apply_button,native.save_button,native.editor.advanced_toggle,native.editor.save_config):
                    assert widget.isVisibleTo(window)
                    assert window.rect().contains(QRect(widget.mapTo(window,QPoint()),widget.size()))
                viewport=None
                if advanced:
                    assert not native.editor.table.isVisible()
                    viewport=native.editor.current_scroll().viewport().height()
                    assert viewport>=100,('host advanced viewport too small',width,height,viewport)
                else:
                    assert native.editor.table.isVisibleTo(window) and native.editor.table.viewport().height()>=70
                report['hostGeometry'].append({'requested':[width,height],'panel':list(native.size().toTuple()),
                                              'advanced':advanced,'settingsViewportHeight':viewport})
                assert window.grab().save(str(OUTPUT/f'host-{width}-{height}-advanced-{advanced}.png'))
        for width,height in ((1040,720),(1280,720),(1440,900)):
            check(f'real-source-native-host-{width}-{height}',lambda w=width,h=height:host_geometry(w,h))
        window.close();app.processEvents()

    report['ok'] = not report['errors']
    (OUTPUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    with patch('ui.panel.host.sessions', return_value=[]), patch('ui.panel.host.available_windows', return_value=[]):
        raise SystemExit(main())
