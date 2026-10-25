# LXMaxAnimation

按角色管理模型、贴图、骨骼 T-pose、动画和单帧 Pose，连接 3ds Max、Unity / 团结引擎与私有 GitHub 资产仓库。

界面内嵌在 LXTool 内容区，从“我的工具”打开；使用工具架的窗口和运行时。面板随工具架导航打开、关闭和重新加载。

## 使用
1. 选择一个本地资产库目录并创建角色。已克隆资产库可直接选择其根目录。
2. 在 Max 中通过 Scripting → Run Script 运行本工具 `max/bootstrap.ms`。面板刷新连接后选择目标实例。
3. 选择普通骨骼、Biped 或 CAT。选中角色根节点及关联蒙皮模型，填写名称和动画帧范围，点击保存当前选择。
4. 在角色列表中搜索、筛选资产。双击导入所选 Max 场景。Biped / CAT 原生动画需先选中目标角色；Pose 应用到 Max 当前帧。
5. 选择 Unity 项目根目录和 Generic / Humanoid，点击一键导入 Unity。首次自动安装 Editor 接收器，等待项目编译与导入回执。
6. 填写私有 GitHub 仓库地址，初始化 Git LFS；保存并推送或拉取。使用本机 Git 的登录信息，不在工具包中保存密码。

## 保存内容
- 模型 / T-pose：当前帧的 FBX、原生选择集 source.max、Bitmap 贴图副本、贴图映射、姿态记录。保存前请自行将角色置于 T-pose。
- 动画：指定帧范围的 FBX 和原生选择集；Biped 同时保存 BIP，CAT 同时保存 CLP。
- 单帧 Pose：节点名称、父子结构与局部变换；CAT 另存原生 PSE。
- 每次保存生成独立版本和 SHA-256 清单；不覆盖旧版本。

## 依赖与兼容性
- LXTools native API 1，Python 3.12 / PySide6 6.8.3。
- 3ds Max Python / pymxs、FBX 插件；2026 本机联调，其他版本待验证。支持 PySide6 和 PySide2 的桥接导入。
- Unity / 团结引擎 Editor；项目必须包含 Assets 和 ProjectSettings。Generic 与 Humanoid 可选，Humanoid 需有效 Avatar。
- Git 与 Git LFS；私有仓库需本机 Git 已登录并有写权限。

## 使用边界
- 同名同层级骨骼回灌；不自动完成不同骨架的动作重定向。普通骨骼动画回灌要求节点映射；无映射的外部 FBX 可登记和送入 Unity，需先在 Max 导入并由本工具保存后回灌。
- Biped 使用原生 BIP，CAT 使用原生 CLP/PSE。Biped 加载为原生片段，CAT 加载至当前帧的新层；复杂约束、IK 和自定义控制器需用实际角色验证。
- Pose 修改当前帧关键帧；不修改整个动画时间范围。Biped 动画模式下不设置骨骼缩放。
- Max 原生模型合并保留绑定；FBX 提供 Unity 交换。高版本 source.max 无法由低版本 Max 打开。
- 贴图收集目前针对标准 Bitmaptexture，FBX 内嵌材质不等同于 Unity Shader 转换。第三方程序材质需先烘焙为贴图。
- 关闭面板不关闭宿主。超时提示不代表宿主已取消，检查结果后再重试。
- 开发版本 0.0.0，未发布正式 Release。
