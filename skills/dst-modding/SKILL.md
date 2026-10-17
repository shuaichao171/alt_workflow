# 《饥荒》开发

> 何时使用：制作《饥荒》/《饥荒联机版》相关内容（模组、动作、贴图、调试日志等）。

下文的大写占位名（如 `DST_DATA_DIR`）对应的实际路径记录在 [../../private/paths.md](../../private/paths.md)。

## 游戏目录

- **《饥荒联机版》数据目录**：`DST_DATA_DIR`
- **《饥荒》单机版目录**：`DS_GAME_DIR`

## 日志位置

- **《饥荒联机版》客户端日志**：`DST_CLIENT_LOG`
- **主机日志和洞穴日志**：与客户端日志位于同级目录。

## 模组开发

- 编写《饥荒》模组前，必须根据具体内容选择并使用对应的技能。
- 《饥荒》模组技能目录：[mod-skills/](mod-skills/)，分类速查见 [mod-skills/SKILL-CATALOG.md](mod-skills/SKILL-CATALOG.md)。
- 根据当前任务从该目录中选择最少数量的相关 Skill；采取任务行动前，完整读取每个选中 Skill 的 `SKILL.md`。
- 不要读取与当前任务无关的其他 Skill。后续任务的内容发生变化时，重新判断需要使用的 Skill。
- 部分 Skill 里写的源码目录 `D:\steam\...\data\scripts` 是作者本机的默认值，以 `DST_DATA_DIR` 的实际值为准。

## 饥荒动作制作

- 动作制作流程：[animation/README.md](animation/README.md)，先读其中的 [00-注意事项](animation/00-注意事项.md)。
- 相关工具（ktools、FMOD Designer、动画贴图打包工具、OpenSpine 等）路径见 `private/paths.md`。

> `mod-skills/` 与 `animation/` 各自是独立的 Git 仓库（保留了原有提交历史和远程地址），在各自目录里提交、推送。

## 贴图

- 需要生成贴图时，同时使用 [../image-gen/SKILL.md](../image-gen/SKILL.md)。

## 全局对象访问

- 直接访问 `GLOBAL.XXXX` 可能触发《饥荒》的 `__STRICT` 检查并导致报错。
- 访问全局对象前，应先确认目标字段存在，并根据具体场景采用安全的访问方式。
