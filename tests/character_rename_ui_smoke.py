"""Rename through the character picker and verify the running panel retains its selection."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from asset_sync_ui_smoke import OUTPUT, PACKAGE, click, until
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget
from ui.library import Library
from ui.panel import create_panel


def exercise(base, app):
    library = Library(base / 'library')
    library.initialize()
    library.create_character('更名前')
    source = base / 'source'
    source.mkdir()
    (source / 'scene.max').write_bytes(b'Fixture only')
    meta = dict(fps=30, start=0, end=12)
    old = library.publish('更名前', '行走', 'animation', source, 'scene.max', metadata=meta)
    latest = library.publish('更名前', '行走', 'animation', source, 'scene.max', metadata=meta)
    role_id = library.character_id('更名前')

    class Context:
        package_root = PACKAGE
        data_root = base / 'data'
        workspace_state = {}

        def resource(self, path):
            return PACKAGE / path

        def load_settings(self):
            return {'library': str(library.root), 'character': '更名前'}

        def save_settings(self, data):
            self.settings = data.copy()

    context = Context()
    shell = QWidget()
    shell.resize(1200, 800)
    layout = QVBoxLayout(shell)
    panel = create_panel(context, shell)
    layout.addWidget(panel)
    shell.show()
    app.processEvents()
    try:
        panel.refresh_assets(select_id=old['id'])
        panel.bind_asset(latest, str(base / 'max-session'), str(base / 'max-scene.max'))
        assert panel.selected_asset()['id'] == old['id']
        panel.open_gallery()
        dialog = panel.gallery
        dialog.search.setText('更名前')
        assert dialog.cards.currentItem().data(Qt.ItemDataRole.UserRole) == '更名前'
        rename = next(button for button in dialog.findChildren(QPushButton) if button.text()=='重命名…')
        with patch('ui.dialogs.QInputDialog.getText', return_value=('更名后', True)):
            click(rename)
        until(lambda: panel.active_character == '更名后', panel.status.text())
        assert panel.character_title.text() == '更名后'
        assert panel.selected_asset()['id'] == old['id']
        assert panel.editing_asset['id'] == latest['id']
        assert panel.editing_asset['character'] == '更名后'
        assert panel.editor.asset['character'] == '更名后'
        assert panel.remembered_assets['更名后'] == old['id']
        assert '更名前' not in panel.remembered_assets
        assert context.settings['character'] == '更名后'
        assert not dialog.search.text()
        assert dialog.cards.currentItem().data(Qt.ItemDataRole.UserRole) == '更名后'
        assert library.character_id('更名后') == role_id
        asset = panel.selected_asset()
        with patch('ui.panel.os.startfile', create=True) as reveal:
            panel.reveal_asset(asset, True)
        destination = Path(reveal.call_args.args[0])
        assert destination.is_dir() and destination.is_relative_to(library.root/'characters'/'更名后')
    finally:
        panel.shutdown()
        shell.close()


if __name__=='__main__':
    app = QApplication([])
    with TemporaryDirectory(dir=OUTPUT) as temp:
        exercise(Path(temp), app)
    print('Character rename UI passed: picker, historical version, Max binding, and Explorer path')
