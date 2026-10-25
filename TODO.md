# LXMaxAnimation 交付清单

## 2026-10-26 已确认范围
- LXTool 原生内嵌面板；角色弹窗和左右两栏。只绑定一个 Max 实例。
- 创建角色必须选中全部角色对象，包括模型、骨骼、控制器及辅助节点。T-pose 是角色实体；贴图可选，默认视口头像，可替换。
- 动画和 Pose 保存不需要选择，使用整个场景；相对角色清单多出、缺少、重名或结构变化均失败并提示。
- 每个选中动画 / Pose 有直接从 Max 保存按钮；只有明确保存才改库。
- 双击动画替换 Max 当前场景；不自动备份。独立工作副本隔离库文件。Pose 覆盖当前帧并打键。
- 动画使用场景范围与 FPS。角色更新保留既有资产，保存产生可追溯版本。
- 全量 FBX 配置按目标版本记录；文件级 Model / Rig / Animation / Materials 和独立 Clip 设置。命名预设和五种默认预设，不改分段。
- Unity 实际连接和 Clip 后处理暂停，本轮只存 JSON。独立私有资产仓库已存在。
- 用户要求不再提问，尽量推进、自查、完成后关机。

## 实现与验证
- [x] 角色模型、分类、头像、版本更新、原库兼容
- [x] 全场景完整性校验、单 Max 会话、实时状态、工作副本
- [x] 普通标量控制器及自定义属性 Pose；Biped、CAT 路径
- [x] 两栏资产排序搜索、角色弹窗、直接保存
- [x] Clip 独立配置和验证、文件级 FBX 配置、预设分段保护
- [x] 实际编辑器反射字段：70 文件字段、31 Clip 字段；只读和过时字段单独审计
- [x] 18 项单元测试；真实 Qt 排序、筛选、角色类别、Clip、预设保护和持久化
- [x] LXTool 真实 NativePanelHandle 加载、关闭和重开
- [x] 独立 Max 2026.3：普通控制器 / 自定义属性 / 完整性错误 / 工作副本隔离 / 模型重载 / 可选贴图
- [x] 独立 Max 2026.3：Biped 36 对象与 CAT 2 对象 Pose / 动画，无选择保存与场景清单不变
- [x] 文档、JSON 契约及版本边界
- [x] 最终摘要 / 包生成校验（14 个运行文件，开发包已生成）
- [x] GitHub 默认分支推送并通过开发商店真实安装（local-data/development-verification.json）
- 关机在会话最终验证结束后执行，不提前终止构建和检查。
- [ ] 真实生产角色人工验收（用户休息，保留待验收，不代签）

## 验证命令与证据
- `python -m unittest discover -s tests -p "test_*.py"`：18 passed。
- `python tests/ui_smoke.py`：passed；local-data/panel-workflow.png、characters.png。
- `python tests/native_loader_smoke.py E:/project/LXTools/LXTools/src`：passed。
- `3dsmaxbatch tests/max_workflow.py`：local-data/workflow-result.json。
- `3dsmaxbatch tests/max_rigs.py`：local-data/max-rigs-result.json，两类型均 ok。
- 编辑器反射：local-data/unity-schema.log 中 SCHEMA_EXPORTED 70 / 31；ui/unity-schema.json。
- `scripts/build_package.py` 与 lx-tool-creator/validate_tool.py：14 个运行文件通过。

开发版本维持 0.0.0，不创建正式 Release。其他 Max / Unity 版本、复杂第三方控制器和生产角色未实测。Unity 新配置尚未执行导入；历史接收器测试不代表本轮配置已接入。

最终自查：CAT 测试原先使用无效的位置属性，已改为变换矩阵并增加非零位移断言。最终批处理日志为 Task Completed Successfully；Biped / CAT 均通过，避免空动作假阳性。
