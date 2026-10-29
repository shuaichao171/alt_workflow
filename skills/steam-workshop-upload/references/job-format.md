# 上传任务 JSON

JSON 文件与日志、计划和快照放在目标项目的 `_ai_work/workshop/`；所有任务中的相对路径均相对于 JSON 所在目录解析。UTF-8 编码，未知字段会报错；工坊 ID 使用字符串，避免 64 位整数精度丢失。

| 字段 | 默认 | 含义 |
| --- | --- | --- |
| `operation` | `update` | `update` 更新；`create` 新建 |
| `app_id` | `322330` | 联机 `322330`，单机 `219740` |
| `workshop_id` | `"0"` | 更新必须填写非零 ID；新建必须为 `"0"` |
| `upload_authorization` | 未设置 | 所有 upload（含用户直接给 ID、新建和仅改元数据）均需本次任务的明确上传指令记录，见下文；只读和离线命令不需要 |
| `target_source` | `user` | `user` 仅用于用户直接指定的 ID/链接；按名称从列表推断的目标必须填 `list` |
| `target_confirmation` | 未设置 | list 目标执行 upload 前必须提供本次任务的用户确认，格式见下文；plan/check/inspect 可先进行 |
| `source_directory` | 必填 | 含 modinfo.lua 的模组根目录 |
| `include` | `["**"]` | 包含规则，可逐项列出文件 |
| `exclude` | `[]` | 排除规则，优先于 include |
| `upload_redundant_files` | `false` | 是否保留官方的九类冗余格式 |
| `update_content` | `true` | 更新模组文件 |
| `update_preview` | `false` | 更新封面，需 preview_file |
| `preview_file` | `""` | 封面路径，最大 1 MiB；不受模组内容过滤影响 |
| `update_metadata` | `false` | 更新标题简介；需要显式 title，可用空 description 清空简介 |
| `title` / `description` | `""` | UTF-8 标题、简介；新建必须显式提供标题 |
| `description_file` | `""` | 从 UTF-8 文件读简介，与 description 二选一 |
| `update_tags` | `false` | 主动替换 Tags，需显式 tags 数组 |
| `tags` | 未设置 | 未设置时更新会保留普通工坊 Tags；提供数组时以该数组为基础替换，并按需要补充版本/单机兼容 Tags |
| `update_version_metadata` | `true` | 联机文件更新同步版本 metadata；更新标题简介时原生核心也会同步可读版本 |
| `version` / `version_compatible` | 从 modinfo 读取 | 动态值不能静态读取时显式提供；version 不得与字面量冲突 |
| `change_note` | `""` | 联机更新说明；单机旧接口忽略 |
| `visibility` | 更新时保留；新建 `2` | `0` 公开、`1` 好友、`2` 私有、`3` 不列出 |
| `force` | `false` | 跳过普通文件更新的“版本相同/旧版本未知”检查；不跳过上传授权、目标确认、清单校验或封面大小检查 |

## 上传授权记录

**仅在本次任务已收到用户明确要求上传、发布或更新创意工坊物品的真实指令后填写。** 准备、打包、开发、查 ID 或确认“ID 没错”均不授权上传。没有指令时省略此字段或保持 decision=pending，不得为了通过检查自动填写。

```json
{
  "upload_authorization": {
    "decision": "authorized",
    "operation": "update",
    "app_id": 322330,
    "workshop_id": "本次指令对应的工坊ID",
    "user_request": "此处逐字记录用户实际上传指令，不得复制占位文字或由 AI 编造"
  }
}
```

合并到正常任务中；新建时绑定 operation=create、workshop_id="0"。授权必须对应当前模组、游戏、目标及操作，条件已满足，且未被用户撤销；不得沿用旧任务记录。操作、游戏或 ID 改变时旧记录不能通过检查，需核实新范围是否已有用户明确指令。其他范围或条件变化同样由 AI 核实，不得扩大授权。

上传入口在计划检查和访问 Steam 前检查 decision=authorized、相同 operation/app_id/workshop_id 及非空 user_request。缺失、pending 或不匹配返回 **`5`**，force 不能跳过。程序无法验证对话真实性或自然语言意图，AI 仍必须核实指令，不能把填入 JSON 当作授权。

列表取得的目标还需独立的 target_confirmation；“确认 ID”只确认目标。用户已明确要求上传且已确认目标时无需重复询问相同授权。任何授权/确认字段变更都需重新 plan。

## 查询本人已发布列表

`list` 使用独立的查询 JSON，不需要 ID 或模组目录：

```json
{
  "app_id": 322330,
  "search_name": "模组名字或关键词"
}
```

```powershell
& "$workflowRoot/scripts/workshop.ps1" list $queryPath
```

`search_name` 可省略或留空。按中英文名称做忽略大小写、兼容字符和空白规范化后的包含匹配，不会自动挑选或上传。`query.list.json` 包含完整 `items`、候选 `matches`、`needs_user_confirmation=true`。读取双语、所有分页、按 ID 去重，限定当前账号、游戏和 Klei 工具 creator AppID `245850`；查询失败不会把部分结果当作成功列表，也不应读取上次残留的输出。

## 列表目标的确认记录

从列表取得 ID 后，先标记 `target_source="list"`，展示具体目标并询问用户。**必须等到本次任务中用户确切选定该目标，才能写入以下确认字段**；不得以“名字相同/只找到一个/以前确认过”代替。

```json
{
  "target_source": "list",
  "target_confirmation": {
    "decision": "confirmed",
    "app_id": 322330,
    "workshop_id": "用户已明确确认的ID",
    "user_reply": "此处记录用户实际答复原文，不得由 AI 编造"
  }
}
```

这段应合并到正常上传任务中，不是独立可运行任务。等待答复时省略 target_confirmation 或保持 decision=pending。上传前检查 decision、游戏、ID 和非空答复；缺失/不一致返回 `4`，在调用 Steam 前停止，force 不生效。程序不能验证对话真实性，AI 必须遵守 SKILL.md 的明确答复规则。确认后修改 JSON 需重新 plan。

规则使用 `/`，匹配忽略大小写：`*` 不跨目录，`?` 匹配一个非分隔字符，`**` 跨目录，`**/` 允许零层目录。规则不接受绝对路径或 `..`。官方冗余扩展名过滤仍按区分大小写的原规则执行。

以下示例未包含 upload_authorization，可直接用于离线准备；实际提交时按真实指令补全授权，再重新 plan。精确选择运行文件的示例：

```json
{
  "operation": "update",
  "app_id": 322330,
  "workshop_id": "替换为已确认的工坊ID",
  "source_directory": "../..",
  "include": ["modinfo.lua", "modmain.lua", "scripts/**", "anim/**", "images/**", "native/runtime.dll"],
  "exclude": ["**/*.bak"],
  "change_note": "修复本次已完成的问题"
}
```

新建示例，先以私有可见性发布；只有用户要求公开时才改为 `0`：

```json
{
  "operation": "create",
  "app_id": 219740,
  "workshop_id": "0",
  "source_directory": "../..",
  "include": ["**"],
  "exclude": ["source/**", "tests/**", "**/*.bak"],
  "update_content": true,
  "update_preview": true,
  "preview_file": "../../preview.jpg",
  "update_metadata": true,
  "title": "模组名称",
  "description_file": "description.txt",
  "tags": ["item"],
  "visibility": 2
}
```

`plan` 会生成 `job.plan.json` 和 `job.workshop/payload_<随机值>/`。快照保留源文件相对布局，联机版附加 manifest。`check` 检查配置、实际选中文件及快照哈希；计划以后有改动就重新生成。运行产物不进入工作流源码目录。

`list` 生成 `query.list.json`；`inspect` 生成 `job.inspect.json`；`upload` 写 `job.upload.log` 和 `job.result.json`。成功退出码 `0`，用法错误 `2`，需要 Steam 协议 `3`，等待明确目标确认 `4`，缺少明确上传授权 `5`，其他错误 `1`。提交后无法确认的状态会保留工坊 ID，先查询再决定是否重试。任务 JSON 文件名应保持稳定，避免绕过创建任务的回执保护。
