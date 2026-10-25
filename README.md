# LXMaxAnimation

按角色分类的 3ds Max 动画资产库，连接私有 GitHub 仓库与 Unity / 团结引擎。

## 打开

本工具只作为 LXTool 内容区中的原生面板运行。安装后从“我的工具”打开 LXMaxAnimation，角色列表、Max 操作、Unity 导入和 GitHub 同步均显示在工具架内部。

LX 工具架开发包：`dist/LXTool-package.zip`（v2 / native API 1 / 0.0.0）。开发版从 gd-dd/LXMaxAnimation 默认分支安装 0.0.0 快照；正式 Release 尚未发布。工具源码与私有资产库分离。

## 资产库

- 私有远端：https://github.com/gd-dd/LXMaxAnimationLibrary
- 本机：在面板中选择资产库克隆目录。
- 已提供“示例角色_测试方块”的模型、动画和 Pose，用于检查管线。
- 每次保存保留独立版本；FBX、MAX、贴图、BIP、CLP、PSE 使用 Git LFS。

## 第一次使用

1. 在 Max 中运行 `max/bootstrap.ms`，面板点击刷新连接并选择该实例。
2. 新建角色；选择普通骨骼、Biped 或 CAT；选中根节点及需要保存的蒙皮模型。
3. 输入名称，选择模型 / T-pose、动画或 Pose，点击保存当前选择。保存模型前手动摆好 T-pose。
4. 双击资产导入 Max。Biped / CAT 动画需选中目标角色；普通骨骼通过名称匹配。Pose 应用到当前帧。
5. 选择 Unity 项目，点击一键导入 Unity。首次复制 Editor 接收器，编辑器完成导入后才显示成功。
6. 点击保存并推送上传资产；其他电脑 Git 克隆并执行 `git lfs pull` 后，选择同一库即可使用。

详细行为、依赖和兼容性见 `.lxtool/README.md`。

## 实测与限制

已在 Max 2026.3 和团结 2022.3.62t13 跑过真实批处理测试；普通骨骼、Biped、CAT 的原生通路通过，Unity 返回真实导入结果。GitHub 已验证上传、全新克隆、LFS 下载和文件摘要。其他版本、真实角色的复杂 IK / 约束尚未验收。

无映射的外部 FBX 可以登记与送入 Unity；向 Max 回灌需要先手动导入再由本工具保存。这里没有自动跨骨架重定向。贴图收集针对 Bitmaptexture；第三方程序材质需先烘焙。Humanoid 需要 Unity 可识别的有效 Avatar。

已移除独立启动脚本和 EXE 构建流程。原生加载器验证使用 LXTool 传入的父控件和 QApplication，支持离开清理与重新打开。开发版支持 GitHub 分支快照安装；正式客户端仍需公开稳定 Release。全部清单、命令和证据见 `TODO.md`。

## 开发

Python 3.12 隔离环境安装 `requirements-dev.txt`。
执行 `python -m unittest discover -s tests -v`；通过 `build.ps1` 仅构建 `dist/LXTool-package.zip` 内嵌面板包。
`tests/max_*.py` 仅供独立 3dsmaxbatch 实例运行，会重置它自己的测试场景，不要在工作场景中运行。
