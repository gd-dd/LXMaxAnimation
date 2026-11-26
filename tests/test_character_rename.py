import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ui.library import Library, read_json, write_json


class CharacterRenameTests(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory()
        self.addCleanup(fixture.cleanup)
        self.base = Path(fixture.name)
        self.root = self.base / 'library'
        self.library = Library(self.root, lambda: {'name': 'Animator', 'email': 'animator@example.invalid'})
        self.library.initialize()
        self.library.create_character('月猫')
        self.source = self.base / 'source'
        self.source.mkdir()
        (self.source / 'source.max').write_bytes(b'isolated Max fixture')
        (self.source / 'textures').mkdir()
        (self.source / 'textures/texture.png').write_bytes(b'isolated texture fixture')

    def role(self, name='月猫'):
        return self.root / 'characters' / name

    def snapshot(self, folder):
        return {leaf.relative_to(folder).as_posix(): leaf.read_bytes()
                for leaf in folder.rglob('*') if leaf.is_file()}

    def populate(self):
        first = self.library.publish('月猫', '行走', 'animation', self.source, 'source.max', notes='原始备注')
        second = self.library.publish('月猫', '行走', 'animation', self.source, 'source.max')
        tpose = self.library.publish('月猫', 'T-pose', 'model', self.source, 'source.max')
        empty = self.library.create_asset('月猫', '手势', 'pose')
        clip = b'{"assetId":"unchanged","source":{"main":"source.max"},"note":"keep original bytes"}\n'
        (Path(second['_directory']) / 'clips.json').write_bytes(clip)
        legacy = self.role() / 'animation' / ('行走--' + first['revision'])
        Path(first['_directory']).rename(legacy)
        self.library.add_category('队友')
        self.library.update_character_info('月猫', category='队友', tposeAssetId=tpose['id'])
        self.library.set_avatar('月猫', self.source / 'textures/texture.png')
        return [first, second, tpose, empty], clip

    def test_rename_moves_all_versions_and_preserves_payloads_and_references(self):
        originals, clip = self.populate()
        before = self.snapshot(self.role())
        info = self.library.character_info('月猫')
        identity = self.library.character_id('月猫')

        self.assertEqual(self.library.rename_character('月猫',' 月夜猫 '), '月夜猫')

        self.assertFalse(self.role().exists())
        self.assertEqual(self.library.characters(), ['月夜猫'])
        self.assertEqual(self.library.character_id('月夜猫'), identity)
        revised = self.library.character_info('月夜猫')
        for field in ('avatar', 'category', 'tposeAssetId'):
            self.assertEqual(info[field], revised[field])
        self.assertEqual(revised['tpose']['id'], originals[2]['id'])
        assets, errors = self.library.list_assets('月夜猫')
        self.assertFalse(errors)
        self.assertEqual({item['id'] for item in assets}, {item['id'] for item in originals})
        for item in assets:
            self.assertEqual(item['character'], '月夜猫')
            group, folder = self.library.asset_location(item)
            self.assertTrue(group.is_relative_to(self.role('月夜猫')))
            self.assertTrue(folder.is_dir())
            original = next(a for a in originals if a['id'] == item['id'])
            for key in ('name', 'revision', 'created', 'createdBy', 'notes', 'files', 'metadata'):
                self.assertEqual(item[key], original[key])
            if not item.get('placeholder'):
                self.assertEqual(self.library.verify(item).read_bytes(), b'isolated Max fixture')
        after = self.snapshot(self.role('月夜猫'))
        self.assertEqual(before.keys(), after.keys())
        for file, payload in before.items():
            if not file.endswith(('character.json','asset.json')):
                self.assertEqual(after[file], payload, file)
        self.assertIn(clip, after.values())

    def test_legacy_copies_and_case_only_rename_keep_identity(self):
        old_info = dict(schema=1, name='Hero')
        for root in (self.root, self.base/'second-copy'):
            write_json(root/'characters/Hero/character.json', old_info)
        second = Library(self.base/'second-copy')
        identity = self.library.character_id('Hero')
        self.assertEqual(second.character_id('Hero'), identity)
        self.assertEqual(self.library.rename_character('Hero','hero'), 'hero')
        self.assertEqual(self.library.characters(), ['hero','月猫'])
        role = read_json(self.role('hero')/'character.json')
        self.assertEqual(role['id'], identity)
        self.assertEqual(role['previousNames'], ['Hero'])
        self.assertEqual(self.library.rename_character('hero','月光'), '月光')
        self.assertEqual(self.library.character_id('月光'), identity)
        self.assertEqual(read_json(self.role('月光')/'character.json')['previousNames'], ['Hero','hero'])

    def test_bad_target_and_corrupt_index_leave_character_untouched(self):
        self.populate()
        self.library.create_character('Hero')
        before = self.snapshot(self.role())
        for name in ('hero', 'CON', 'bad/name'):
            with self.assertRaises(ValueError):
                self.library.rename_character('月猫',name)
            self.assertEqual(self.snapshot(self.role()), before)
        (self.role()/'animation/bad/asset.json').parent.mkdir()
        (self.role()/'animation/bad/asset.json').write_text('{}',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'资产目录'):
            self.library.rename_character('月猫','月光')
        self.assertFalse(self.role('月光').exists())

    def test_failure_while_applying_metadata_restores_all_original_bytes(self):
        self.populate()
        before = self.snapshot(self.role())
        real_replace = os.replace
        applied = []
        def fail_second(source, destination):
            if Path(source).suffix == '.after':
                applied.append(Path(destination))
                if len(applied)==2:
                    raise PermissionError('simulated access denial')
            return real_replace(source,destination)
        with patch('ui.library.os.replace',side_effect=fail_second):
            with self.assertRaisesRegex(PermissionError,'simulated'):
                self.library.rename_character('月猫','月光')
        self.assertEqual(len(applied), 2)
        self.assertEqual(self.snapshot(self.role()), before)
        self.assertFalse(self.role('月光').exists())
        self.assertFalse(list((self.root/'.staging').iterdir()))


if __name__ == '__main__':
    unittest.main()
