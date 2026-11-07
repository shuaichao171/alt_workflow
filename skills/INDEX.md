# 技能路由表

根据当前任务内容，从下表挑选**最少数量**的相关技能；动手前完整读取选中技能的 `SKILL.md`。不要读取与当前任务无关的技能。任务内容变化时重新判断。

| 技能 | 何时使用 | 文件 |
| --- | --- | --- |
| 生成/编辑位图 | 需要生成、修改图片，制作贴图、图标、插画、透明素材 | [image-gen/SKILL.md](image-gen/SKILL.md) |
| 饥荒工坊上传 | 用户明确要求上传、发布或更新《饥荒》/《饥荒联机版》工坊物品，或需要只读查询本人已发布列表/ID（授权规则见 rules/40） | [steam-workshop-upload/SKILL.md](steam-workshop-upload/SKILL.md) |
| 《饥荒》开发 | 制作《饥荒》/《饥荒联机版》相关内容：模组、动作、贴图、调试日志、无头测试；把联机版内容移植到单机版，或修复、测试单机移植模组（内含 48 个模组专项技能、动作制作流程与联机→单机移植流程） | [dst-modding/SKILL.md](dst-modding/SKILL.md) |
| 《饥荒》二进制资产 | 需要解析、修改或转换《饥荒》动画/贴图/音频/声音工程二进制文件（anim.bin、build.bin、.tex、.fsb、.fev），或 Klei 哈希反查、碰撞重算、图集打包、资源名提取 | [dst-asset-tools/SKILL.md](dst-asset-tools/SKILL.md) |
| 服务器运维 | 在远程服务器上部署/更新服务、迁移容器与账号数据、备份回滚、改 Nginx/宝塔配置、只读巡检与排障 | [server-ops/SKILL.md](server-ops/SKILL.md) |
| 逆向分析 | 任务结论依赖无源码的已发布产物：反编译/分析二进制、安装包（APK/IPA/DMG/MSIX）、Electron/ASAR/打包 JS、.NET 程序集、固件、HAR 抓包，或已发布版本行为对比；用前检测本会话有无 rea 工具（MCP 优先，CLI 回退）。**有完整源码的普通分析不用** | [rea/SKILL.md](rea/SKILL.md) |

> 新增技能：复制 [_template/](_template/) 为新目录，填写 `SKILL.md`，然后在上表加一行。
> 「何时使用」写清触发条件，AI 只靠这一列判断要不要读该技能。
