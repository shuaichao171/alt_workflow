---
name: steam-workshop-upload
description: 用户明确要求上传、发布或更新《饥荒》和《饥荒联机版》创意工坊物品时使用；也可按任务需要只读查询本人列表、按名称寻找 ID，匹配目标须经用户明确确认。
---

# 饥荒工坊上传

使用精简命令行核心；无需打开上传器界面。上传经验及两种游戏的区别见 [references/upload-notes.md](references/upload-notes.md)，任务 JSON 字段见 [references/job-format.md](references/job-format.md)。

## 上传前置条件

- 遵守 [工坊上传授权规则](../../rules/40-workshop-upload.md)：**只有用户在本次任务中明确要求上传、发布或更新创意工坊物品，才执行 upload 或任何其他工坊写入。** “修好后上传”须先完成修复；用户仅要求开发、测试、打包、准备方案或查 ID 时，完成相应工作即可，不追加上传。
- 提供 ID/链接、确认“ID 没错”、测试通过、版本已改、存在历史配置或回执，都不能代替明确上传指令。“更新模组”未明确涉及工坊时不能按上传处理。不得编造指令或沿用旧任务授权；用户取消或要求暂不上传时停止提交。
- 只有实际收到明确指令后，才按 [任务格式](references/job-format.md#上传授权记录) 写入本次 `upload_authorization`，记录用户指令原文，并绑定 operation / app_id / workshop_id。未授权时省略此字段或保持 `decision="pending"`。不要复制文档占位文字当作真实授权。
- 上传授权与列表 ID 确认分别检查；同一句真实回复可同时满足两者。用户已明确要求上传且目标条件已满足时，无需重复索要相同授权。程序只能检查记录完整性及绑定关系，指令的真实性、范围和条件仍由 AI 核实。

## 环境与入口

- Windows、.NET 10 SDK、x86 .NET 10 运行时；Steam 已启动并在线登录有发布权限的账号。
- 技能已包含 Klei Mod Tools 配套的 **32 位** [steam_api.dll](assets/win-x86/steam_api.dll)，脚本默认自动复制使用，无需完整上传器或外部 DLL 路径配置。特殊情况可用 `-SteamApiDll` 覆盖。不要读取 Steam/CLI 登录凭据。
- 入口：[../../scripts/workshop.ps1](../../scripts/workshop.ps1)。源码位于本技能 `scripts/`，首次使用自动编译到任务 JSON 所在目录的 `_workshop_tool/`；构建与运行产物均放在目标项目内。
- `plan`、`check` 完全离线；`list`、`inspect` 只读工坊，按当前任务需要使用；`upload` 会发布。未收到明确上传指令时不得提交。用户明确指定了 ID/链接并授权上传时，准备完成后直接执行；**通过列表和名称找到的 ID 必须先按下节取得明确确认，即使用户此前已说“帮我上传”也不能省略。**

## 不记得 ID：先查询，再确认

1. 在目标项目的 `_ai_work/workshop/query.json` 写 `{"app_id":322330,"search_name":"模组名字或关键词"}`（单机改为 `219740`），运行 `& "$workflowRoot/scripts/workshop.ps1" list $queryPath`。不需要 workshop_id、模组目录或上传配置；空 search_name 返回全部本人已发布物品。未知游戏时可分别只读查询两种游戏。
2. 仅在 list 退出码为 `0` 时读取本次 `query.list.json`；失败时不复用旧结果。列表仅包含当前登录账号在指定游戏下、由 Klei 工具创建的已发布物品；按 ID 去重，提供中英文名称、版本、更新时间、可见性和链接。`matches` 是名称包含匹配的候选，`items` 保留完整列表供 AI 比对别名和项目内容。不得把名称相似度、唯一匹配或同名当作确认；未找到时继续核查或向用户说明，不自动创建新物品。
3. 展示候选的**游戏、名称、ID、工坊链接**，有必要时补充版本/更新时间与推荐理由。使用匹配 ID 前向用户明确询问目标，即使仅一个候选或名称完全相同也必须询问。已获上传指令时可问：“找到联机版《名称》，ID 123，链接……。确认把当前模组上传到这个物品吗？”仅查 ID 时只报告或确认目标，不把查询扩展为上传。
4. **没得到确切答复，不执行 upload。** 无回复、超时、“可能是”“应该吧”“再看看”等含糊答复均不能视为同意；多个候选时，笼统“好的”但无法确定对象也不算。可以继续文件选择、离线 plan/check 和只读 inspect，保持确认待处理。用户明确选定候选（如“就第二个”）或在单一明确目标下回答“确认/是的”后，才能继续已授权的上传任务。
5. 所有列表推断的目标都写 `target_source="list"`。取得本次任务的真实回复后才填写 `target_confirmation`：`decision="confirmed"`、相同的 app_id / workshop_id、`user_reply` 保存用户答复原文。不得自行编造回复、把推断目标改成 user、自动填 confirmed，或复用旧任务的确认。确认后仍保留 list 来源。游戏或 ID 改变时原确认失效，必须重新询问。

确认格式及可运行的查询配置见 [references/job-format.md](references/job-format.md)。退出码 `5` 表示缺少明确上传授权，`4` 表示等待目标确认；`force` 均不能跳过。程序在访问 Steam 前检查这些条件；答复是否明确以及是否真实来自用户仍由 AI 按上述规则判断。

## 已绑定模组：marker 直连（免查免确认）

- 每次上传成功（verified）后，工具自动在模组根目录写入 `.workshop-target.json`（点开头文件，不进入上传内容），记录绑定的 app_id、工坊 ID、标题与版本。
- 模组根目录存在该文件时，后续更新任务直接写 `target_source="marker"`：`workshop_id` 可填字符串 `"0"`，由工具按绑定解析（也可显式填与绑定一致的 ID，不一致会被拒绝）；无需再 `list` 查询与逐次确认。
- 绑定不改变授权要求：`upload_authorization` 仍须记录本次真实上传指令（其 `workshop_id` 同样可填 `"0"` 随绑定解析）。首次上传尚未生成绑定时，仍按上节查询并确认。
- 更换绑定物品（改 ID、换单机/联机、删除标记）是用户决策：AI 需先向用户说明并取得明确指令，再由用户改文件或经一次确认后的成功上传覆盖；不得为绕过确认而改写标记。

## 选择目标和文件

1. 识别模组根目录（含 `modinfo.lua`），确认游戏：联机 `322330`，单机 `219740`。用户直接给出 ID/链接时使用指定目标；模组根目录已有 `.workshop-target.json` 绑定时按上节 marker 直连；否则先按上节读列表并取得明确确认，项目旧配置只能帮助比对候选。不要仅凭目录名推测 ID，也不要把“更新”变成“新建”。
2. 查看项目文件和资源引用，按实际运行需要决定上传内容。用 `include` / `exclude` 表达选择，也可以在 `include` 中逐项列出相对文件路径。保留所需 Lua、动画 ZIP、TEX/XML、音效、字体、原生库等；`modmain.lua`、`modworldgenmain.lua` 是否需要取决于模组类型。
3. 源工程、备份、日志、测试、说明、构建输出是否发布，由项目和用户要求决定；不要用扩展名黑名单误删 DLL、EXE、ZIP 或运行时资源。原始图片/音频确有运行需求时，设置 `upload_redundant_files=true` 并用文件规则控制范围。点开头的名称、链接及任务产物目录会跳过。
4. 更新前读取本地 `version`，用 `inspect` 或列表结果比对工坊版本。普通文件更新需有不同的版本；**工坊版本与本地相同时，默认直接自增本地版本号后上传，无需向用户二次确认**：把版本末段数字 +1（如 `3.42`→`3.43`、`0.4.93`→`0.4.94`），同步写入 `modinfo.lua` 字面量并按新版本重新 `plan`。仅当版本末段无法解析为数字、或工坊旧版本未知时才询问用户；仅用户明确要求同版本覆盖时使用 `force=true`。

## 执行

在 `<目标项目>/_ai_work/workshop/job.json` 写任务。最小更新示例（此处 `source_directory` 相对于 JSON 所在目录）：

```json
{
  "operation": "update",
  "app_id": 322330,
  "workshop_id": "替换为已确认的工坊ID",
  "source_directory": "../..",
  "include": ["**"],
  "exclude": ["docs/**", "tests/**", "**/*.bak"],
  "change_note": "本次实际变更说明"
}
```

此示例只能用于准备，未包含上传授权；实际提交前必须根据真实指令填写 `upload_authorization`，列表目标还须填写 `target_confirmation`，然后重新 plan。示例 `exclude` 需按项目调整。更新默认保留工坊标题、简介、封面和可见性；同步版本时合并保留已有普通 Tags。需要更改这些字段或创建新物品时，先读 [job-format.md](references/job-format.md)。

下列 `$workflowRoot` 为工作流根目录，`$jobPath` 为目标项目的任务 JSON 绝对路径；命令可从任意目录执行：

```powershell
& "$workflowRoot/scripts/workshop.ps1" plan $jobPath
& "$workflowRoot/scripts/workshop.ps1" check $jobPath
& "$workflowRoot/scripts/workshop.ps1" inspect $jobPath  # 需要查询已有物品时
& "$workflowRoot/scripts/workshop.ps1" upload $jobPath   # 仅在用户明确要求上传、授权记录齐全且目标条件满足后执行
```

- 检查 `job.plan.json` 中的实际文件、跳过原因、版本，以及联机版生成的 `mod.manifest`。发现选择错误就调整配置重新 `plan`。选中文件、配置、简介文件或封面变化后必须重新 `plan`。
- `upload` 首先检查明确上传授权及列表目标确认，再校验清单和快照，读取当前工坊状态后再次校验，然后仅上传计划中的内容。命令无交互提示；缺少授权时返回 `5`，不得自动补造记录再重试。
- 新建任务的 `operation=create`、`workshop_id="0"`，必须同时提供文件、封面、标题简介。创建得到的 ID 会立即写入回执；后续使用该 ID 更新，不再次创建。

## 结果与重试

- 只有退出码 `0` 且 `job.result.json` 的 `status=verified`，才能报告“上传并确认成功”。回执还包含 ID、链接和版本；详细日志在 `job.upload.log`。
- `submitted_unverified`、`failed_or_uncertain`、`created_pending` 或协议提示不等于未提交。保留回执，先 `inspect` 或检查工坊页面。脚本只重试查询，不自动重新发布；创建任务有回执时会阻止重复创建。
