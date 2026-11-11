# 安卓模拟器（Android Studio AVD）

> 何时使用：需要在安卓环境里安装/运行 APK、adb 调试、抓日志或截图、root 读写应用数据、frida 等动态分析，并且用户没有指定用真机或雷电模拟器时。

## 前置条件

本机路径见 `private/paths.md`：

| 占位名 | 用途 |
| --- | --- |
| `ANDROID_SDK_DIR` | Android SDK 根目录（emulator、platform-tools、build-tools、system-images 都在这里） |
| `ANDROID_EMULATOR_EXE` | `emulator.exe`，一律用绝对路径调用 |
| `ANDROID_ADB` | PATH 里的 `adb`（与 SDK 自带版本一致） |
| `ANDROID_AVD_NAME` | 默认 AVD 名 |
| `ANDROID_AVD_DIR` | 该 AVD 的数据目录（`config.ini`、快照、userdata） |
| `ANDROID_REAL_DEVICE_SERIAL` | 常连着的真机序列号，用来和模拟器区分 |
| `LDPLAYER_DIR` | 雷电模拟器目录（只用于排查冲突，本技能不操作它） |

AVD 规格（2026-11-11 实测）：Android 14（API 34）`google_apis` x86_64 镜像，pixel_4 外形 1080×2280 @440dpi，4 核 / 1.5 GB 内存，无 Play 商店；`ro.debuggable=1`，`adb root` 可用；ABI 列表 `x86_64,arm64-v8a`，ARM 应用经 `libndk_translation` 转译运行。

## 步骤

### 1. 先查有没有在运行，并找到它的序列号

```powershell
adb devices -l
```

- 输出里可能同时有真机（`ANDROID_REAL_DEVICE_SERIAL`）和模拟器，**所有 adb 命令都带 `-s <序列号>`**，不要依赖默认设备。
- 确认某个 `emulator-55xx` 是不是本 AVD：`adb -s <序列号> emu avd name` 应输出 `ANDROID_AVD_NAME`（真机和雷电对这条命令不返回 AVD 名）；也可用 `adb -s <序列号> shell getprop ro.boot.qemu.avd_name`。
- 已在运行 = 任务开始前就开着，本次任务**不得关闭它**（见 rules/00）。记下这一点。

### 2. 没运行时再启动（本次任务启动的要在结束时关闭）

**默认无头启动**（`-no-window`，不弹出模拟器窗口，不打扰用户用电脑）：

```powershell
Start-Process -FilePath "<ANDROID_EMULATOR_EXE>" -ArgumentList '-avd','<ANDROID_AVD_NAME>','-no-window','-no-snapshot-save','-no-boot-anim','-no-audio'
```

- **只有用户明确要求看模拟器画面时**，才去掉 `-no-window` 带窗口启动。AI 自己要检查界面时，用下文的 `screencap` 截图和 `uiautomator dump`，不要为此开窗口。
- 用 `Start-Process` 脱离当前终端，否则命令会一直阻塞。
- 需要冷启动时加 `-no-snapshot-load`。
- 等待开机完成（`sys.boot_completed` 为 `1` 才算可用，`wait-for-device` 只代表 adbd 起来了）：

```powershell
adb -s emulator-5554 wait-for-device
while ("$(adb -s emulator-5554 shell getprop sys.boot_completed)".Trim() -ne '1') { Start-Sleep 2 }
```

序列号以 `adb devices` 实际显示为准：5554 被占用时 AVD 会顺延到 `emulator-5556`。

### 3. 常用操作

| 目的 | 命令 |
| --- | --- |
| 安装 / 覆盖安装 | `adb -s $S install -r <apk>`；降级加 `-d` |
| 清数据 / 卸载 | `adb -s $S shell pm clear <包名>` / `adb -s $S uninstall <包名>` |
| 启动应用 | `adb -s $S shell monkey -p <包名> -c android.intent.category.LAUNCHER 1` |
| 取 root shell | `adb -s $S root` 后 `adb -s $S shell`（之后 `whoami` 为 `root`） |
| 截图 | `adb -s $S shell screencap -p /sdcard/s.png` 再 `adb -s $S pull /sdcard/s.png <目标项目>/_ai_work/` |
| UI 结构 | `adb -s $S shell uiautomator dump /sdcard/ui.xml` 再 pull |
| 点击 / 输入 / 返回 | `adb -s $S shell input tap X Y` / `input text <文本>` / `input keyevent 4` |
| 日志 | `adb -s $S logcat -d -v time > <目标项目>/_ai_work/logcat.txt`；先 `logcat -c` 清空 |
| 推送工具 | 放 `/data/local/tmp/` 并 `chmod 755`；本机架构是 x86_64，原生工具（如 frida-server）要选 x86_64 版本 |
| 主机代理 | 模拟器里访问主机用 `10.0.2.2`：`adb -s $S shell settings put global http_proxy 10.0.2.2:<端口>`，用完 `settings put global http_proxy :0` |
| 关闭（仅限本次启动的） | `adb -s $S emu kill` |

### 4. 收尾

- 本次任务启动的模拟器：用 `adb -s $S emu kill` 关闭，再用 `adb devices` 确认它已消失。
- 任务前就在运行的：保持运行；改过的全局状态（代理、`adb root`、推送的临时文件）按需还原。
- 截图、日志、拉出来的文件放在目标项目的 `_ai_work/`，不放工作流目录。

## 注意事项

- **PowerShell 不能重定向二进制**：`adb exec-out screencap -p > s.png` 在 PowerShell 里会把 PNG 写坏；用上表的「设备端保存 + pull」，或在 Bash 里执行。
- 系统级 `ANDROID_HOME` 已于 2026-11-11 改为 `ANDROID_SDK_DIR`（之前指向一个不存在的目录）。修改前就打开的终端和程序仍是旧值，所以 emulator 和 SDK 工具依然用绝对路径调用。
- **与雷电模拟器冲突**：雷电运行时也会显示为 `emulator-5554`，所以要用 `emu avd name` 确认身份。雷电自带的 adb 是 34.0.4，与本机 37.0.1 不一致，启动雷电可能导致 adb server 被重启、设备暂时掉线；两者同时开时先 `adb devices` 确认。
- **不要靠快照来还原环境**：启动参数 `-no-snapshot-save` 只保证不覆盖 `default_boot` 快照。2026-11-11 实测本次启动实际为冷启动（`uptime` 与进程运行时长一致），之前留在 `/data/local/tmp` 的文件仍在，说明 `/data` 的改动会保留。需要干净环境时用 `pm clear` 或卸载重装，并在报告里写明。保存或覆盖快照（`adb emu avd snapshot save`）要先征得用户同意。
- 应用的风控/反模拟器检测可能识别出 AVD（`ro.boot.qemu`、`goldfish`/`ranchu` 等特征），结论要注明是在模拟器上得出的；需要真机结论时改用 `ANDROID_REAL_DEVICE_SERIAL`，并先征得用户同意。
