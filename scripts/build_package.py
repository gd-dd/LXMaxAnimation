"""Refresh manifest from the explicit runtime file list. Does not publish."""
from pathlib import Path
import hashlib
import json

ROOT=Path(__file__).resolve().parents[1]
FILES=['.lxtool/icon.png','.lxtool/README.md','.lxtool/panel.json','ui/__init__.py',
       'ui/library.py','ui/integrations.py','ui/panel.py','max/bootstrap.ms','max/bridge.py',
       'unity/LXMaxAnimationReceiver.cs']
manifest={'schemaVersion':2,'kind':'lx-tool','name':'LXMaxAnimation',
          'description':'按角色管理 Max 模型、动画和 Pose，一键导入 Unity，同步私有 GitHub 资产库。',
          'version':'0.0.0','category':'动画管线','icon':'.lxtool/icon.png',
          'readme':'.lxtool/README.md','panel':'.lxtool/panel.json','applications':{},'actions':{},
          'files':{file:hashlib.sha256((ROOT/file).read_bytes()).hexdigest() for file in FILES}}
(ROOT/'.lxtool/manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('Manifest refreshed:',len(FILES),'files')
