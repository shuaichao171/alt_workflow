# 逆向分析（REA）

> 何时使用：任务结论依赖**无源码的已发布产物**——反编译/分析原生二进制（PE/ELF/Mach-O）、安装包（APK/IPA/DMG/MSIX）、Electron/ASAR/打包 JS、.NET 程序集、固件、HAR 抓包文件，或对比两个已发布版本的行为差异。**有完整可读源码的普通代码/架构分析不用本技能**。

## 前置条件

用之前先检测 REA 工具在本会话是否可用，来源二选一：

1. **MCP 工具（首选）**：当前会话存在 rea 的 MCP 工具就直接用——pi 中为 `mcp__rea` 命名空间（或 mcp 网关里名为 `rea` 的服务器），Claude Code 等客户端中为 `mcp__rea__*` 工具。能用就**不要**先跑诊断/doctor，直接分析。
2. **CLI 回退（会话里没有 MCP 工具时）**：`npx -y rea-agents@latest <命令> --json`。JS/Electron 静态分析零引擎依赖，例如：
   ```bash
   npx -y rea-agents@latest analyze-javascript-application <绝对路径> --json
   ```

- REA 本地源码在 `REA_HOME`（查 [private/paths.md](../private/paths.md)）；深入用法读 `REA_HOME\skill-src\reverse-engineer-anything\SKILL.md` 及其 `references\`，按需选读不全读。
- 需要 Node.js ≥22.19。

## 步骤

1. 按前置条件检测可用性，选定 MCP 或 CLI 路径。
2. 按目标类型选第一个工具：

   | 目标 | 第一个工具 |
   | --- | --- |
   | ASAR / 解包的 JS/Electron 目录 | `analyze_javascript_application` |
   | ZIP/APK/IPA/MSIX/DMG 成员清单 | `open_binary`（传本地路径） |
   | Android APK 代码/类/方法 | `inspect_android_package` |
   | .NET（托管 PE）程序集 | `inspect_managed_artifact` |
   | 用户已打开的浏览器页面 | `list_browser_targets` |
   | 用户已运行的 Electron 应用 | `list_electron_targets` |
   | 原生二进制 / 分析数据库 | `open_binary`，需要概览再 `binary_overview` |

3. 目标不明确时问用户要哪个文件/应用，不要自己挑示例。工具不可用时查会话内 `binary_session` 的 `tool_availability` 了解原因，不要调用未列出的工具。
4. 结论写法：区分**观察 / 推断 / 未知**；引用返回的 Evidence ID；静态分析结论不得说成“运行时观察到”。
5. 原生会话用完 `close_binary` 收尾。

## 注意事项

- 本机 Windows 边界（依据 REA 官方文档，未实测）：Hopper 仅 macOS；Ghidra 在 Windows 为实验性只读；JS/Electron 静态分析、.NET、APK、HAR 抓包分析**不依赖**这些引擎，本机可直接用。
- `npx rea-agents setup` 会往各 AI 客户端安装 REA 自带技能指引，与本技能并存时以本路由表为唯一入口，避免双重触发。
- REA 本地运行，不需要密钥。
