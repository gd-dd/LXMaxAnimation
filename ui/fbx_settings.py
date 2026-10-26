"""Typed FBX options from the installed 2022.3 editor API, with version tagging."""
import copy
import json
import math
import re
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QFormLayout,QCheckBox,QComboBox,QDoubleSpinBox,QSpinBox,
    QLineEdit,QPlainTextEdit,QTabWidget,QScrollArea,QLabel)
from .widgets import ExpandingJson

SCHEMA=json.loads(Path(__file__).with_name('unity-schema.json').read_text('utf-8-sig'))
PROTECTED={'name','firstFrame','lastFrame','takeName'}
EXTRAS=[{'name':'materialRemaps','type':'Remap[]','defaultJson':'[]','options':[]},
        {'name':'extensions','type':'Object','defaultJson':'{}','options':[]}]

def fields(scope):
    source=[f for f in SCHEMA[scope] if f['name'] not in PROTECTED]
    if scope=='clip':
        priority=['loopTime','loopPose','mirror','cycleOffset','lockRootRotation','lockRootHeightY','lockRootPositionXZ']
        source.sort(key=lambda f:priority.index(f['name']) if f['name'] in priority else len(priority))
    return source+(EXTRAS if scope=='importer' else [
        {'name':'transformMask','type':'Mask[]','defaultJson':'[]','options':[]},
        {'name':'extensions','type':'Object','defaultJson':'{}','options':[]}])

def defaults(scope):
    result={f['name']:json.loads(f['defaultJson']) for f in fields(scope)}
    if scope=='importer':
        result['humanDescription']={'human':[],'skeleton':[],'upperArmTwist':0.5,'lowerArmTwist':0.5,
            'upperLegTwist':0.5,'lowerLegTwist':0.5,'armStretch':0.05,'legStretch':0.05,'feetSpacing':0.0,'hasTranslationDoF':False}
    return result

def validate(settings,scope):
    if not isinstance(settings,dict):raise ValueError('FBX 配置必须为对象。')
    for field in fields(scope):
        key=field['name']
        if key not in settings:continue
        value=settings[key];kind=field['type'];options=field['options']
        if options and value not in options:raise ValueError(key+'：无效选项。')
        if kind=='System.Boolean' and not isinstance(value,bool):raise ValueError(key+' 必须为布尔值。')
        if kind in ('System.Single','System.Int32'):
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError(key+' 必须为有限数值。')
            if kind=='System.Int32' and int(value)!=value:raise ValueError(key+' 必须为整数。')
        if kind.endswith('[]') and not isinstance(value,list):raise ValueError(key+' 必须为数组。')
        if kind in ('Object','UnityEngine.HumanDescription') and not isinstance(value,dict):raise ValueError(key+' 必须为对象。')
    json.dumps(settings,allow_nan=False)
    return settings

def group(name):
    if name.startswith('material') or name=='useSRGBMaterialColor':return 'Materials · 材质'
    if name in {'animationType','avatarSetup','sourceAvatar','humanDescription','autoGenerateAvatarMappingIfUnspecified',
                'optimizeGameObjects','extraExposedTransformPaths','skinWeights','maxBonesPerVertex','minBoneWeight'}:return 'Rig · 骨骼'
    if name.startswith(('animation','aCL')) or name in {'importAnimation','generateAnimations','bakeIK','resampleCurves',
            'removeConstantScaleCurves','importAnimatedCustomProperties','importConstraints','humanoidOversampling','motionNodeName'}:return 'Animation · 动画'
    return 'Model · 模型'

LABELS={'globalScale':'缩放','useFileUnits':'文件单位','useFileScale':'文件缩放','importBlendShapes':'导入 BlendShapes',
 'importCameras':'导入相机','importLights':'导入灯光','isReadable':'读写网格','meshCompression':'网格压缩',
 'animationType':'动画类型','avatarSetup':'Avatar 定义','sourceAvatar':'源 Avatar 路径 / GUID',
 'humanDescription':'Humanoid 骨骼映射及肌肉限制','materialRemaps':'材质重映射','transformMask':'骨骼遮罩',
 'animationCompression':'动画压缩','importAnimation':'导入动画','loopTime':'循环时间','loopPose':'循环姿态',
 'lockRootRotation':'根旋转烘焙到姿态','lockRootHeightY':'根高度烘焙到姿态','lockRootPositionXZ':'根位移烘焙到姿态',
 'maskSource':'AvatarMask 路径 / GUID','events':'动画事件','curves':'附加曲线','extensions':'版本扩展字段'}
LABELS.update({'wrapMode':'播放边界模式','loop':'旧版循环标记','rotationOffset':'根旋转偏移','heightOffset':'根高度偏移',
 'cycleOffset':'循环起点偏移','mirror':'镜像动作','keepOriginalOrientation':'保持原始朝向','keepOriginalPositionY':'保持原始高度',
 'keepOriginalPositionXZ':'保持原始水平位置','heightFromFeet':'基于脚部计算高度','maskType':'遮罩模式',
 'hasAdditiveReferencePose':'启用叠加参考姿态','additiveReferencePoseFrame':'叠加参考帧','additiveType':'叠加模式',
 'basePoseType':'基准姿态类型','additiveSelectedAnimation':'参考动画资源','additiveSelectedAnimationFrameIndex':'参考动画帧',
 'lockToRoot':'锁定根节点','intervals':'动画区间','materialImportMode':'材质导入模式','materialLocation':'材质存储位置',
 'materialName':'材质命名','materialSearch':'材质查找范围','animationRotationError':'旋转压缩容差',
 'animationPositionError':'位置压缩容差','animationScaleError':'缩放压缩容差','resampleCurves':'重采样曲线',
 'importConstraints':'导入约束','importAnimatedCustomProperties':'导入动画自定义属性'})

TUANJIE={'aCLCompressionLevel','aCLCurvePrecision','isVirtualGeometry','additiveType','basePoseType',
         'additiveSelectedAnimation','additiveSelectedAnimationFrameIndex','intervals','lockToRoot'}

class SettingsForm(QTabWidget):
    def __init__(self,scope,parent=None):
        super().__init__(parent);self.scope=scope;self.controls={};self.original={};self.forms={}
        if scope=='clip':self.tabBar().hide()
        for title in (['Model · 模型','Rig · 骨骼','Animation · 动画','Materials · 材质'] if scope=='importer' else ['Clip · 独立配置']):
            body=QWidget();body.setObjectName('SettingsBody');body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
            form=QFormLayout(body);form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(body);self.addTab(scroll,title);self.forms[title]=form
        for field in fields(scope):
            key=field['name'];kind=field['type'];options=field['options']
            if options:control=QComboBox();control.addItems(options)
            elif kind=='System.Boolean':control=QCheckBox()
            elif kind=='System.Int32':control=QSpinBox();control.setRange(-1000000000,1000000000)
            elif kind=='System.Single':control=QDoubleSpinBox();control.setRange(-1e9,1e9);control.setDecimals(6)
            elif kind=='System.String' or kind in ('UnityEngine.Avatar','UnityEngine.AvatarMask','UnityEngine.AnimationClip'):control=QLineEdit()
            else:control=ExpandingJson()
            label=QLabel(LABELS.get(key,re.sub(r'(?=[A-Z])','\u200b',key)));label.setWordWrap(True)
            label.setFixedWidth(155);label.setToolTip(key)
            if not isinstance(control,QCheckBox):control.setMinimumWidth(260);control.setMinimumHeight(34)
            if key in TUANJIE:label.setText(label.text()+'（团结扩展）')
            control.setToolTip(key+' · '+kind+('（结构化 JSON）' if isinstance(control,QPlainTextEdit) else ''))
            self.forms[group(key) if scope=='importer' else 'Clip · 独立配置'].addRow(label,control);self.controls[key]=control
        self.set_values(defaults(scope))

    def set_values(self,values):
        self.original=copy.deepcopy(values)
        for key,control in self.controls.items():
            value=values.get(key,defaults(self.scope)[key])
            if isinstance(control,QCheckBox):control.setChecked(bool(value))
            elif isinstance(control,QComboBox):
                if control.findText(str(value))<0:control.addItem(str(value))
                control.setCurrentText(str(value))
            elif isinstance(control,(QSpinBox,QDoubleSpinBox)):control.setValue(value)
            elif isinstance(control,QPlainTextEdit):control.setPlainText(json.dumps(value,ensure_ascii=False,indent=2))
            else:control.setText(value or '')

    def values(self):
        values=copy.deepcopy(self.original)
        for key,control in self.controls.items():
            if isinstance(control,QCheckBox):value=control.isChecked()
            elif isinstance(control,QComboBox):value=control.currentText()
            elif isinstance(control,(QSpinBox,QDoubleSpinBox)):value=control.value()
            elif isinstance(control,QPlainTextEdit):
                try:value=json.loads(control.toPlainText())
                except ValueError as exc:raise ValueError(key+' JSON 格式错误：'+str(exc)) from exc
            else:value=control.text()
            values[key]=value
        return validate(values,self.scope)
