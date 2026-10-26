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

LABELS.update(dict(zip(
    'importVisibility importBlendShapeDeformPercent addCollider normalSmoothingAngle swapUVChannels weldVertices bakeAxisConversion optimizeBones keepQuads indexFormat preserveHierarchy generateSecondaryUV secondaryUVAngleDistortion secondaryUVAreaDistortion secondaryUVHardAngle secondaryUVMarginMethod secondaryUVPackMargin secondaryUVMinLightmapResolution secondaryUVMinObjectScale generateAnimations meshOptimizationFlags optimizeMeshPolygons optimizeMeshVertices skinWeights maxBonesPerVertex minBoneWeight importNormals normalSmoothingSource importBlendShapeNormals normalCalculationMode importTangents bakeIK removeConstantScaleCurves strictVertexDataChecks optimizeGameObjects extraExposedTransformPaths extraUserProperties aCLCompressionLevel aCLCurvePrecision animationWrapMode humanoidOversampling motionNodeName useSRGBMaterialColor sortHierarchyByName autoGenerateAvatarMappingIfUnspecified isVirtualGeometry'.split(),
    '导入可见性|导入形态键变形百分比|添加碰撞体|法线平滑角度|交换 UV 通道|焊接顶点|烘焙坐标轴转换|优化骨骼|保留四边形|索引格式|保留层级|生成光照贴图 UV|UV 角度畸变|UV 面积畸变|UV 硬边角度|UV 边距方式|UV 打包边距|最小光照贴图分辨率|最小物体缩放|动画生成方式|网格优化选项|优化多边形|优化顶点|蒙皮权重模式|每顶点最大骨骼数|最小骨骼权重|导入法线|法线平滑来源|形态键法线|法线计算方式|导入切线|烘焙 IK|移除恒定缩放曲线|严格顶点数据检查|优化游戏对象|额外暴露的节点路径|额外用户属性|ACL 压缩级别|ACL 曲线精度|动画播放边界模式|人形动画过采样|根运动节点名称|材质颜色使用 sRGB|按名称排序层级|缺省时自动生成 Avatar 映射|虚拟几何体'.split('|'))))

OPTION_LABELS=dict(zip(
    'ACL AngleWeighted AreaAndAngleWeighted AreaWeighted Auto Automatic BasedOnMaterialName BasedOnModelNameAndMaterialName BasedOnTextureName BasedOnTextureName_Or_ModelNameAndMaterialName Calculate CalculateLegacy CalculateLegacyWithSplitTangents CalculateMikk Clamp ClampForever CopyFromOther CreateFromThisModel Custom Default Everything Everywhere External Extreme8Bit FromAngle FromSmoothingGroups GenerateAnimations Generic High Highest Human Import ImportStandard ImportViaMaterialDescription InNodes InOriginalRoots InPrefab InRoot KeyframeReduction KeyframeReductionAndCompression Legacy LegacyImport Local Loop Low Manual Medium NoAvatar None Off Once Optimal PingPong PolygonOrder PreferSmoothingGroups RecursiveUp Standard UInt16 UInt32 Unweighted Unweighted_Legacy VertexOrder X1 X2 X4 X8'.split(),
    'ACL 压缩|角度加权|面积和角度加权|面积加权|自动|自动|按材质名|按模型名和材质名|按贴图名|按贴图名或模型名与材质名|计算|传统计算|传统计算并拆分切线|MikkTSpace 计算|钳制|持续钳制|从其他模型复制|从本模型创建|自定义|默认|全部|所有位置|外部|极限 8 位|按角度|按平滑组|生成动画|通用|高|最高|人形|导入|标准导入|通过材质描述导入|在节点中|在原始根节点中|在预制体中|在根节点中|减少关键帧|减少关键帧并压缩|传统|传统导入|本地|循环|低|手动|中|不使用 Avatar|无|关闭|单次|最优|往返|多边形顺序|优先平滑组|向上递归|标准|16 位无符号|32 位无符号|不加权|传统不加权|顶点顺序|1 倍|2 倍|4 倍|8 倍'.split('|')))

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
            if options:
                control=QComboBox()
                for option in options:control.addItem(OPTION_LABELS.get(option,option)+' · '+option,option)
            elif kind=='System.Boolean':control=QCheckBox()
            elif kind=='System.Int32':control=QSpinBox();control.setRange(-1000000000,1000000000)
            elif kind=='System.Single':control=QDoubleSpinBox();control.setRange(-1e9,1e9);control.setDecimals(6)
            elif kind=='System.String' or kind in ('UnityEngine.Avatar','UnityEngine.AvatarMask','UnityEngine.AnimationClip'):control=QLineEdit()
            else:control=ExpandingJson()
            label=QLabel(LABELS.get(key,key)+'\n'+re.sub(r'(?=[A-Z])','\u200b',key));label.setWordWrap(True)
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
                if control.findData(str(value))<0:control.addItem(str(value),str(value))
                control.setCurrentIndex(control.findData(str(value)))
            elif isinstance(control,(QSpinBox,QDoubleSpinBox)):control.setValue(value)
            elif isinstance(control,QPlainTextEdit):control.setPlainText(json.dumps(value,ensure_ascii=False,indent=2))
            else:control.setText(value or '')

    def values(self):
        values=copy.deepcopy(self.original)
        for key,control in self.controls.items():
            if isinstance(control,QCheckBox):value=control.isChecked()
            elif isinstance(control,QComboBox):value=control.currentData()
            elif isinstance(control,(QSpinBox,QDoubleSpinBox)):value=control.value()
            elif isinstance(control,QPlainTextEdit):
                try:value=json.loads(control.toPlainText())
                except ValueError as exc:raise ValueError(key+' JSON 格式错误：'+str(exc)) from exc
            else:value=control.text()
            values[key]=value
        return validate(values,self.scope)
