"""Refresh manifest from the explicit runtime file list. Does not publish."""
from pathlib import Path
import hashlib
import json

ROOT=Path(__file__).resolve().parents[1]
FILES=['.lxtool/icon.png','.lxtool/README.md','.lxtool/panel.json','ui/__init__.py',
       'ui/library.py','ui/integrations.py','ui/panel.py','ui/clips.py','ui/clip_editor.py','ui/dialogs.py','ui/fbx_settings.py','ui/unity-schema.json',
       'max/bootstrap.ms','max/bridge.py']
manifest={'schemaVersion':2,'kind':'lx-tool','name':'LXMaxAnimation',
          'description':'连接 Max，以 T-pose 管理角色、完整动画场景和 Pose，编辑独立 Clip 配置。',
          'version':'0.0.0','category':'动画管线','icon':'.lxtool/icon.png',
          'readme':'.lxtool/README.md','panel':'.lxtool/panel.json','applications':{},'actions':{},
          'files':{file:hashlib.sha256((ROOT/file).read_bytes()).hexdigest() for file in FILES}}
(ROOT/'.lxtool/manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
print('Manifest refreshed:',len(FILES),'files')
