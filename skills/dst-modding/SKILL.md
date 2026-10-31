# 《饥荒》开发

> 何时使用：制作《饥荒》/《饥荒联机版》相关内容（模组、动作、贴图、调试日志等）。

下文的大写占位名（如 `DST_DATA_DIR`）对应的实际路径记录在 [../../private/paths.md](../../private/paths.md)。

## 游戏目录

- **《饥荒联机版》数据目录**：`DST_DATA_DIR`
- **《饥荒》单机版目录**：`DS_GAME_DIR`

## 日志位置

- **《饥荒联机版》客户端日志**：`DST_CLIENT_LOG`
- **主机日志和洞穴日志**：与客户端日志位于同级目录。
- **《饥荒》单机版日志**：`DS_LOG`。

## 联机版 → 单机版移植

- 把《饥荒联机版》的角色、技能树、物品、界面、音效移植到《饥荒》单机版（Base / RoG / SW / Hamlet），或修复、审查、测试已有的单机移植模组时，使用 [ds-porting/README.md](ds-porting/README.md)，按其中的文件分工只读当前需要的部分。
- 写或审查移植代码前必读其中的 [02-API差异速查](ds-porting/02-API差异速查.md)；启动单机游戏、操作存档前必读 [06-测试与存档安全](ds-porting/06-测试与存档安全.md)。
- mod-skills 以联机版源码为基线，移植时只用来理解联机版一侧的原始设计，单机一侧的写法以 ds-porting 和单机源码为准。
- 每完成一个移植或修完一个新坑，按 [08-案例索引](ds-porting/08-案例索引.md) 末尾的说明把经验补回 ds-porting。

## 模组开发

- 编写《饥荒》模组前，必须根据具体内容选择并使用对应的技能。
- 《饥荒》模组技能目录：[mod-skills/](mod-skills/)，分类速查见 [mod-skills/SKILL-CATALOG.md](mod-skills/SKILL-CATALOG.md)。
- 根据当前任务从该目录中选择最少数量的相关 Skill；采取任务行动前，完整读取每个选中 Skill 的 `SKILL.md`。
- 不要读取与当前任务无关的其他 Skill。后续任务的内容发生变化时，重新判断需要使用的 Skill。
- Skill 里的源码与工具路径用 `DST_DATA_DIR`、`DST_GAME_HOME` 占位；其中的 PowerShell 脚本先读同名环境变量，也可用 `-Root` 显式传入。

## 工坊上传

- 只有用户明确要求上传/发布，或需要只读查询工坊时，才使用 [../steam-workshop-upload/SKILL.md](../steam-workshop-upload/SKILL.md)；授权条件以 [rules/40-workshop-upload.md](../../rules/40-workshop-upload.md) 为准。仅开发模组时不加载上传技能，也不追加发布步骤。

## 无头测试

- 用户要求《饥荒联机版》无头测试、专服验证或自动运行游戏回归时，使用 [mod-skills/dst-dedicated-server-testing/SKILL.md](mod-skills/dst-dedicated-server-testing/SKILL.md)。
- 修改影响引擎运行的逻辑（如组件、动作、AI、状态机、碰撞、存档、世界生成）时，按该技能选择相关无头用例；执行前完整阅读其通用流程。纯文档、静态资源修改按实际需要验证。
- 单分片离线回归直接用该技能的 `scripts/dst_headless_run.py`（快照 → 独立集群 → 行为脚本 → 判定 → 清理），只需写行为脚本；改动后先跑 `mod-skills/dst-debugging-testing/scripts/dst_lua_check.py` 做语法和组件方法静态检查。
- 通用流程见 [mod-skills/dst-dedicated-server-testing/references/headless-workflow.md](mod-skills/dst-dedicated-server-testing/references/headless-workflow.md)，覆盖隔离环境、场景驱动、结果判定、修复复测与进程清理。具体用例由当前模组定义。
- 无头测试不能验收贴图显示、界面、真实客户端预测或网络同步；涉及这些行为时追加相应的客户端验证，并明确未执行项。《饥荒》单机版没有专服，不套用联机版专服命令，改用游戏内自动测试模组，见 [ds-porting/06-测试与存档安全](ds-porting/06-测试与存档安全.md)。

## 饥荒动作制作

- 动作制作流程：[animation/README.md](animation/README.md)，先读其中的 [00-注意事项](animation/00-注意事项.md)。
- 相关工具（ktools、FMOD Designer、动画贴图打包工具、OpenSpine 等）路径见 `private/paths.md`。
- animation/ 流程按可独立发布设计，内部用 `*_HOME` 环境变量名引用工具路径；在本工作流内使用时按下表映射到 `private/paths.md` 的占位名取实际路径：

  | animation/ 里的名字 | `private/paths.md` 占位名 |
  | --- | --- |
  | `OPENSPINE_HOME` | `OPENSPINE_DIR` |
  | `DST_MOD_TOOLS_HOME` | `DST_MOD_TOOLS_DIR` |
  | `DST_GAME_HOME` | `DST_GAME_HOME`（同名条目） |
  | `DST_SCML_ANALYZER` | `DST_SCML_ANALYZER`（同名条目） |

> `mod-skills/` 是独立的 Git 仓库（子模块），在其目录里提交、推送；`animation/` 和 `ds-porting/` 是本工作流的普通文件。

## 贴图

- 需要生成贴图时，同时使用 [../image-gen/SKILL.md](../image-gen/SKILL.md)。

## 全局对象访问

- 直接访问 `GLOBAL.XXXX` 可能触发《饥荒》的 `__STRICT` 检查并导致报错。
- 访问全局对象前，应先确认目标字段存在，并根据具体场景采用安全的访问方式。
