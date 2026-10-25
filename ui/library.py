"""Portable, versioned asset library. No host or Qt dependencies."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid
from datetime import datetime, timezone

KINDS = {'model': '模型 / T-pose', 'animation': '动画', 'pose': '单帧 Pose'}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def safe_name(value):
    value = str(value).strip()
    if not value or len(value) > 80 or re.search(r'[<>:"/\\|?*\x00-\x1f]', value) or value.endswith(('.', ' ')):
        raise ValueError('名称不能为空，不能包含路径或 Windows 非法字符，最多 80 字符。')
    if value in ('.', '..') or value.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))}:
        raise ValueError('名称是系统保留名称。')
    return value


def contained(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError('文件路径超出资产目录。')
    return path


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


class Library:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def initialize(self):
        self.root.mkdir(parents=True, exist_ok=True)
        marker = self.root / 'library.json'
        if marker.exists():
            if read_json(marker).get('schema') != 1:
                raise ValueError('不支持的资产库版本。')
        else:
            write_json(marker, {'schema': 1, 'name': 'LXMaxAnimationLibrary'})
        attrs = self.root / '.gitattributes'
        if not attrs.exists():
            attrs.write_text('\n'.join(f'*.{ext} filter=lfs diff=lfs merge=lfs -text' for ext in ['fbx','max','png','jpg','jpeg','tga','tif','tiff','dds','exr','bmp','bip','clp','pse']) + '\n', encoding='utf-8')
        ignore = self.root / '.gitignore'
        if not ignore.exists():
            ignore.write_text('.staging/\n*.tmp\n', encoding='utf-8')

    def characters(self):
        folder = self.root / 'characters'
        return sorted([p.name for p in folder.iterdir() if p.is_dir() and not p.is_symlink()], key=str.casefold) if folder.exists() else []

    def create_character(self, name):
        name = safe_name(name)
        if any(x.casefold() == name.casefold() for x in self.characters()):
            raise ValueError('角色已存在。')
        folder = contained(self.root, 'characters/' + name)
        folder.mkdir(parents=True, exist_ok=False)
        write_json(folder / 'character.json', {'schema': 1, 'name': name})

    def list_assets(self, character=None, query='', kind=None):
        result, errors = [], []
        for name in ([safe_name(character)] if character else self.characters()):
            folder = contained(self.root, 'characters/' + name)
            for meta in folder.glob('*/*/asset.json'):
                try:
                    contained(self.root, meta.relative_to(self.root))
                    data = read_json(meta)
                    if data.get('schema') != 1 or data.get('kind') not in KINDS or data.get('character') != name:
                        raise ValueError('索引格式错误')
                    if (not kind or data['kind'] == kind) and query.casefold() in (data['name'] + ' ' + data.get('notes', '')).casefold():
                        data['_directory'] = str(meta.parent)
                        result.append(data)
                except Exception as exc:
                    errors.append(f'{meta}: {exc}')
        return sorted(result, key=lambda a: a.get('created', ''), reverse=True), errors

    def stage(self):
        path = self.root / '.staging' / uuid.uuid4().hex
        path.mkdir(parents=True)
        return path

    def publish(self, character, name, kind, source, main, notes='', metadata=None):
        character, name = safe_name(character), safe_name(name)
        if character not in self.characters() or kind not in KINDS:
            raise ValueError('请先创建角色并选择资产类型。')
        source = Path(source).resolve()
        main_path = contained(source, main)
        if not main_path.is_file() or main_path.stat().st_size == 0:
            raise ValueError('主文件不存在或为空。')
        if kind in ('model', 'animation') and main_path.suffix.lower() != '.fbx':
            raise ValueError('模型和动画主文件必须是 FBX。')
        if kind == 'pose' and read_json(main_path).get('schema') != 1:
            raise ValueError('Pose 文件格式不正确。')
        revision = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
        destination = contained(self.root, f'characters/{character}/{kind}/{name}--{revision}')
        staging = self.stage()
        try:
            files = {}
            for file in source.rglob('*'):
                if file.is_symlink():
                    raise ValueError('资产包不能包含符号链接。')
                if file.is_file() and file.name != 'asset.json':
                    rel = file.relative_to(source).as_posix()
                    target = contained(staging, rel)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, target)
                    files[rel] = digest(target)
            data = {'schema': 1, 'id': uuid.uuid4().hex, 'character': character, 'name': name,
                    'kind': kind, 'revision': revision, 'created': datetime.now(timezone.utc).isoformat(),
                    'main': Path(main).as_posix(), 'notes': notes, 'files': files, 'metadata': metadata or {}}
            write_json(staging / 'asset.json', data)
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging.rename(destination)
            data['_directory'] = str(destination)
            return data
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def verify(self, asset):
        folder = contained(self.root, Path(asset['_directory']).relative_to(self.root))
        if asset['main'] not in asset['files']:
            raise ValueError('主文件未列入清单。')
        for rel, expected in asset['files'].items():
            file = contained(folder, rel)
            if not file.is_file() or digest(file) != expected:
                raise ValueError(f'文件缺失或摘要不符（可能尚未 git lfs pull）：{rel}')
        return contained(folder, asset['main'])

    def import_fbx(self, character, name, kind, file):
        if kind not in ('model', 'animation'):
            raise ValueError('外部 FBX 只能登记为模型或动画。')
        stage = self.stage()
        try:
            shutil.copy2(file, stage / 'asset.fbx')
            return self.publish(character, name, kind, stage, 'asset.fbx', metadata={'source': Path(file).name})
        finally:
            shutil.rmtree(stage)

    def character_info(self, name):
        folder = contained(self.root, 'characters/' + safe_name(name))
        info = read_json(folder / 'character.json')
        info.setdefault('category', '')
        info.setdefault('avatar', '')
        assets, _ = self.list_assets(name, kind='model')
        current = next((a for a in assets if a['id'] == info.get('tposeAssetId')), assets[0] if assets else None)
        info['tpose'] = current
        return info

    def categories(self):
        return read_json(self.root / 'library.json').get('categories', [])

    def add_category(self, name):
        name = safe_name(name)
        data = read_json(self.root / 'library.json')
        values = data.setdefault('categories', [])
        if name.casefold() not in [v.casefold() for v in values]:
            values.append(name)
            write_json(self.root / 'library.json', data)

    def update_character_info(self, name, **changes):
        folder = contained(self.root, 'characters/' + safe_name(name))
        info = read_json(folder / 'character.json')
        allowed = {'category', 'avatar', 'tposeAssetId', 'rig'}
        if set(changes) - allowed:
            raise ValueError('未知角色字段。')
        if changes.get('category') and changes['category'] not in self.categories():
            raise ValueError('请先创建分类。')
        if changes.get('avatar'):
            contained(folder, changes['avatar'])
        info.update(changes)
        write_json(folder / 'character.json', info)

    def set_avatar(self, name, file):
        # UI normalizes images to PNG before storing; revision name prevents cache collisions.
        folder = contained(self.root, 'characters/' + safe_name(name))
        relative = 'avatars/' + uuid.uuid4().hex + '.png'
        target = contained(folder, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
        self.update_character_info(name, avatar=relative)

    def import_character(self, name, source, main, metadata, category='', update=False):
        name = safe_name(name)
        if category and category not in self.categories():
            raise ValueError('分类不存在。')
        exists = name in self.characters()
        if exists != update:
            raise ValueError('角色已存在，请使用更新 T-pose。' if exists else '待更新的角色不存在。')
        if not (Path(source) / 'tpose.json').is_file():
            raise ValueError('角色必须包含 T-pose。')
        if not exists:
            self.create_character(name)
        original_info=read_json(contained(self.root,'characters/'+name)/'character.json')
        asset=None
        try:
            asset = self.publish(name, 'T-pose', 'model', source, main, metadata=metadata)
            self.update_character_info(name, tposeAssetId=asset['id'], rig=metadata.get('rig', 'Generic'), category=category)
            avatar = Path(source) / 'avatar.png'
            if avatar.is_file():
                self.set_avatar(name, avatar)
            return asset
        except Exception:
            # New role creation is transactional: no empty role on export/validation failure.
            if not exists:
                folder = contained(self.root, 'characters/' + name)
                shutil.rmtree(folder)
            else:
                write_json(contained(self.root,'characters/'+name)/'character.json',original_info)
                if asset:
                    folder=contained(self.root,Path(asset['_directory']).relative_to(self.root))
                    shutil.rmtree(folder)
            raise

    def mark_superseded(self, previous, current):
        from . import clips
        old_folder=contained(self.root,Path(previous['_directory']).relative_to(self.root))
        new_folder=contained(self.root,Path(current['_directory']).relative_to(self.root))
        old=read_json(old_folder/'asset.json');new=read_json(new_folder/'asset.json')
        old['supersededBy']=current['id'];new['replaces']=previous['id']
        if previous['kind']=='animation' and (old_folder/'clips.json').is_file():
            data=clips.load(self,previous)
            replacement=clips.document(current)
            replacement['clips']=data['clips'];replacement['extensions']=data.get('extensions',{})
            for key in ('fbxSettings','targetEditor','fieldSet'):
                if key in data:replacement[key]=data[key]
            try:clips.save(self,current,replacement)
            except ValueError:
                new['clipMigrationWarning']='旧 Clip 范围不适用于新场景，请重新拆分。原配置保留在旧版本。'
        write_json(new_folder/'asset.json',new);write_json(old_folder/'asset.json',old)
        return new.get('clipMigrationWarning','')
