# 上传器经验整理

来源：KleiWorkshopUploader v2.8 的上传、查询与文件暂存代码，2026-10-29 提取；此技能保留该部分源码及 MulanPSL-2.0 许可，移除了 WinForms 界面、图片浏览和删除功能，保留命令行只读列表用于按名称寻找目标。

## 接口与依赖

| 项目 | 联机版 | 单机版 |
| --- | --- | --- |
| 目标 AppID | `322330` | `219740` |
| 提交接口 | Steam UGC：CreateItem / StartItemUpdate / SubmitItemUpdate | RemoteStorage：PublishWorkshopFile / CommitPublishedFileUpdate |
| 上传内容 | 文件目录，重新生成根目录 `mod.manifest` | 根部直接包含模组文件的 ZIP，保留已有 `mod.manifest` |
| 版本 | `modinfo.lua` 的 version → metadata 与 version Tags | version Tags；兼容性 Tags 从 modinfo 同步 |
| 更新说明 | 支持 change_note | 旧接口忽略更新说明 |

- Steamworks 初始化使用**工具 AppID `245850`**，目标游戏 ID 另行传递。不能简单把 `steam_appid.txt` 换成目标游戏 ID。
- 只读列表同样使用 creator AppID `245850`，consumer AppID 为游戏；实测旧接口把游戏 ID 当 creator 会使 CreateQueryUserUGCRequest 失败。分页遍历所有结果，中英文查询后按 ID 去重；返回结果还校验当前账号和目标游戏。
- 原生 DLL 为 x86，所以命令行也编译为 x86。单文件程序仍需要 .NET 10 x86 运行时；配套 `steam_api.dll` 已随技能放在 `assets/win-x86/`，脚本自动复制。精简核心不依赖 Windows Forms/Windows Desktop Runtime。
- 内置 DLL 与 v2.8 上传器使用的文件一致，SHA-256：`D99D425793F588FBC15F91C7765977CDD642B477BE01DAC41C0388AB6A5D492D`。
- Steam 必须在线登录且具有相应游戏、工具与物品发布权限。中文标题简介通过 UTF-8 原生封送传递。
- 单机版 RemoteStorage 写入并分享文件时，旧接口可能返回 FileNotFound；保留原上传器的唯一远程文件名重试逻辑。提交回调异常可能已提交，必须查询结果后判断。

## 文件规则

- 官方规则只把 `.illegaldummyformat` 当作非法扩展名；**不会禁止 DLL、EXE、BAT、CMD、PS1、ZIP 等格式**。
- 冗余格式仅为小写 `.png`、`.jpg`、`.jpeg`、`.gif`、`.bmp`、`.fla`、`.scml`、`.mp3`、`.wav`，比较区分大小写。`upload_redundant_files=true` 可包含它们；包含/排除规则仍生效。
- 跳过点开头的文件/目录、符号链接和目录联接。工作流另外排除 `_ai_work/` 及本次任务目录，避免把构建和快照递归装进上传内容。
- AI 的文件选择与官方格式过滤分别生效：先决定本次需要什么，再生成快照。可用 `include` 给出完整文件列表，不需要复制整个软件或修改源模组。
- 联机版 `mod.manifest` 是二进制：ASCII `MNFS`、小端 uint32 版本 `1`、条目数、逐项 SDBM 哈希。哈希输入为实际暂存文件相对路径的**小写 UTF-8**，用 `/` 分隔；不包含 manifest 自身。先当前目录文件，再递归子目录，每层按忽略大小写的文件名排序。
- 单机 ZIP 不增加外层模组目录。生成物只存在任务工作目录；不修改源模组清单。

## 不能省略的检查

- 上传前确认游戏、物品 ID、版本、实际文件与更新开关；更新时尽量保留已有标题简介、封面、可见性和普通 Tags。
- `modinfo.lua` 仅静态读取字符串和布尔字面量，不执行 Lua。计算或引用变量的版本需由 AI 核实后在任务里显式提供；显式版本不得与可读字面版本冲突。
- Steam 预览图控制在 1 MiB 内，且只在要求更新封面时提交；封面可以独立于模组内容过滤规则。
- 需要找 ID 时，`list` 读取当前账号已发布列表（分页、双语、去重），按名称给出候选；列表取得的目标必须得到本次任务的用户明确确认。提交后回查直接按物品 ID 查询，检查更新时间推进、版本、可见性与预期 Tags，最多查三次，不重复读取完整列表。
- 若 Steam 要求接受法律协议，或提交后查不到新版本，应报告待确认状态；查询重试和重复上传是不同操作。新建得到 ID 后先落回执，避免因为后续失败重复创建。
- 失败后保留任务 JSON、计划、快照、日志和回执；无需重新填写标题简介或更新说明。

## 本次验证范围

离线测试覆盖文件规则、路径/链接处理、中文路径、DST manifest、DS manifest 保留、源文件与快照变更检测，以及列表目标缺少确认、待确认、游戏/ID 不匹配时的上传阻止（force 不跳过）。原生接口通过已有物品详情、本人单机/联机已发布列表、名称匹配查询验证；没有为了接入工作流向 Steam 发布或更新物品。实际提交逻辑沿用原上传器核心，下一次用户授权发布时再验收真实提交与回查。

需要回归这些行为时，从任意目录运行下面的测试；`$testWorkspace` 应指向目标项目的 `_ai_work/` 子目录，测试不会提交 Steam 更新：

```powershell
& "$workflowRoot/skills/steam-workshop-upload/tests/offline.ps1" -Workspace $testWorkspace
```
