---
name: windows-app-launch
description: Launch a Windows desktop application and immediately move its new windows to another virtual desktop when the user explicitly requests that behavior.
---

# Windows 应用跨桌面启动

仅在用户明确要求「在另一个桌面启动」「启动后立刻移走」或指定虚拟桌面时使用。普通启动不自动移动；后台服务和隐藏辅助进程仍按原有方式启动。

## 适用范围

- 本机已验证：**Windows 10 22H2、build 19045、64 位 PowerShell 5.1 / 7**。使用 Windows 桌面管理接口，不依赖截图。其他系统版本会在启动应用前拒绝执行；接口与系统版本有关，不直接解除版本检查。
- 接受明确的 `.exe` 完整路径、参数数组和工作目录。本机程序路径从 `private/paths.md` 取得；不要把真实路径写入公开技能或示例配置。
- 默认只移动本轮新进程的、新出现的可见顶层应用窗口。不会移动旧窗口，也不会主动切换当前桌面。
- 应用若需要存档或配置备份，先完成对应技能的准备。例如《饥荒》仍须执行 [存档安全流程](../dst-modding/ds-porting/06-测试与存档安全.md)，本工具不替代备份、静音或游戏内验证。

## 调用

先准备目标项目内本轮 `_ai_work/` 目录。`$workflowRoot` 为工作流根目录，`$appExe` 为已确认的应用路径，`$runDir` 为本轮工作目录：

```powershell
& (Join-Path $workflowRoot 'skills/windows-app-launch/scripts/start_on_desktop.ps1') `
    -FilePath $appExe `
    -StatePath (Join-Path $runDir 'launch-state.json')
```

也可点入 [desktop_launch.ps1](scripts/desktop_launch.ps1)，调用 `Start-AppOnDesktop`，取得结构化结果。

常用参数：

| 参数 | 行为 |
| --- | --- |
| `-DesktopNumber 2` | 指定已有桌面，编号从 1 开始；不存在则在启动前报错。省略时选择另一个已有桌面，只有一个桌面时新建一个 |
| `-ArgumentList @('argument one', 'argument two')` | 按参数数组传递，保留空字符串、空格、引号和末尾反斜杠；不拼接 shell 命令 |
| `-WorkingDirectory $appWorkingDir` | 指定工作目录；省略时使用启动文件所在目录 |
| `-MatchExecutablePath @($finalExe)` | 启动器与实际应用路径不同时，明确允许移动的最终程序路径；不按同名程序或任意子进程猜测 |
| `-ObserveSeconds 10` | 首次移动后继续观察新窗口，覆盖启动器换 PID、启动画面换主窗口等情况；启动较慢时按实际情况增加 |
| `-TimeoutSeconds 45` | 等待首个合格窗口的上限。无窗口、只复用了旧窗口或路径不匹配时超时报错 |
| `-AllowNewWindowsInExistingProcess` | 仅在已确认该应用会创建独立新窗口时显式启用；允许旧进程中新建的 HWND，仍排除全部旧 HWND，包括启动前隐藏的窗口 |

单实例应用如果只激活旧窗口，不属于本轮新窗口，脚本不会将其移走。需要独立窗口时，先确认应用自己的新窗口或独立实例参数，再决定是否启用旧进程的新窗口选项。不要同时让另一任务操作同一应用。

## 验证与交接

- 编译、桌面接口初始化和目标桌面准备在启动前完成。默认每 20 毫秒检查一次窗口；窗口出现后即尝试移动，不等待主菜单或其他应用内容加载。
- 用**完整可执行文件路径、PID、进程启动时间及 HWND**区分实例。移动前写入状态文件并再次核对窗口身份，移动后读取桌面 ID 验证。仅对窗口刚出现但尚未注册到系统桌面管理器的情况最多重试 2 秒；权限等其他错误直接停止。
- 脚本返回前默认有 10 秒观察期，不能把脚本总返回时间当成移动耗时。状态文件中 `Windows[].FirstDetectedMs`、`MoveCompletedMs` 是相对发出启动调用的时间；`DetectionToMoveMs` 是检测到窗口至移动完成的间隔，`MoveApiMs` 是移动调用耗时。
- 应用可能短暂显示或抢占前台；不能承诺完全不闪窗。虚拟桌面不隔离键鼠，也不改变声音。固定在所有桌面的应用不会被自动取消固定；验证不符合预期时报告失败。
- 状态文件只能用新文件名。失败时保留文件，按 `Status`、`Failure`、`Windows` 和 `NewProcesses` 排查；出现部分成功时，不能报告全部成功。已移动窗口后来改变桌面时报告变化，不反复把它拖回。
- 工具只负责启动和移动，应用保留给后续任务。整个任务完成时按通用守则关闭本轮窗口；用户要求留着查看或手测时保留，待交接结束后清理。关闭前再次核对日志中的路径、进程启动时间和窗口身份；不要按进程名批量结束。复用旧进程时只关闭本轮新窗口，不能结束承载旧窗口的进程。
- 后续若需 computer-use 操作，目标必须回到当前可操作桌面，并重新绑定、激活窗口；不要求截图工具在非当前桌面上继续工作。

## 维护与实测

运行 [策略测试](tests/test_launch_policy.ps1) 和 [原生测试](tests/test_native_launch.ps1)，通过 `-WorkDir` 指定本轮任务工作目录，不把生成的 exe 和日志放进技能目录。原生测试只操作自己编译的测试应用，可加 `-IncludeNotepad` 测试系统记事本；测试结束关闭自建窗口，不操作其他用户应用。

2026-11-17 已实测：饥荒窗口一出现后立即移走；通用脚本覆盖记事本、多实例中的旧窗口保护、参数传递、窗口重建、不同路径启动器换进程、无窗口超时，以及旧进程新窗口的默认排除和显式启用。日志计时反映单次运行，不能作为所有应用的延迟承诺。

接口布局参考维护者的 [Windows 10 实现](https://github.com/MScholtes/VirtualDesktop/blob/master/VirtualDesktop.cs)，验证使用微软的 [窗口桌面 ID 接口](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ivirtualdesktopmanager-getwindowdesktopid)。
