# FBX / Clip 配置契约 v1

`clips.json` 是动画版本旁的可编辑 sidecar，不属于不可变二进制 SHA 清单。schema 为 `lx-animation-clips`，schemaVersion 为 1；assetId、revision、source 绑定源动画，不接受错配版本。

- source: main、fps、firstFrame、lastFrame。
- targetEditor: 2022.3 或 2022.3.62t13；fieldSet 记录生成字段集的编辑器版本。
- fbxSettings: 文件级 ModelImporter 属性，按 Unity API 名称存储。materialRemaps 数组额外记录 sourceName、type、targetGuid / targetPath；extensions 对象保留后续版本字段。
- clips: 每段 id、name、firstFrame、lastFrame、takeName、notes、settings。前三个来源字段及分段绝不由预设替换。
- settings: ModelImporterClipAnimation 的可写字段；name、firstFrame、lastFrame、takeName 在外层；transformMask 数组可记录 path、active；extensions 保留扩展。
- events: 当前契约以源帧 frame 和函数 function 记录事件，可附 stringParameter、floatParameter、intParameter、objectReference。Unity 适配层负责按 FPS 和片段范围转换时间，不直接把源帧当秒数。
- curves: 数组，每项 name 与 curve（keys 数组，包含 time、value、inTangent、outTangent 等）。结构在当前工具中原样保留，实际 Unity 语义验证由后续适配层完成。
- humanDescription: human、skeleton 数组和扭转 / 拉伸 / feetSpacing / hasTranslationDoF 参数；骨骼条目和 HumanLimit 由 Unity 的字段约定解释。
- sourceAvatar / maskSource / additiveSelectedAnimation: Unity 项目资源路径或 GUID 字符串。不能把外部操作系统路径当 Unity 对象引用。

`unity-presets.json` 位于资产库根目录：schemaVersion=1，presets={名称:{fbxSettings:{...},clipSettings:{...}}}。默认预设只读，用户可另存命名。禁止在 clipSettings 放入分段或 Take 字段；套用失败时不修改原配置。应用只影响选中 Clip 和该 FBX 的文件级设置。

新保存动画版本会保留文件级配置和原 Clip；当原分段不适用于新源帧范围时，不裁剪分段，提示重新处理，旧版本的完整配置仍保留。

字段来源：本机编辑器反射导出的 ui/unity-schema.json；只读和 obsolete 字段也在此记录以审计覆盖范围。基础参考：https://docs.unity3d.com/2022.3/Documentation/ScriptReference/ModelImporter.html 与 ModelImporterClipAnimation.html。不同 Unity 版本应新增字段集并显式映射；当前不执行 Unity 导入。
