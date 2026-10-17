# UAC / 管理员权限

- 命令出现「拒绝访问 / 需要提升权限」类错误时才需要提权，先用普通权限确认确实需要，不要习惯性提权。
- 提权方法：把命令写入临时 `.cmd`/`.ps1` 脚本，脚本内把输出重定向到日志文件，然后用 `Start-Process -FilePath <脚本> -Verb RunAs -Wait` 启动，结束后读取日志验证结果；多条命令尽量合并为一次提权执行。
- 本机 UAC 当前为「从不通知」（ConsentPromptBehaviorAdmin=0），管理员提权会被静默自动放行，用户看不到任何提示；因此提权前必须先向用户说明将要以管理员身份运行的具体命令。可用 `reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v ConsentPromptBehaviorAdmin` 确认当前模式（0=静默通过，5=默认弹窗）。
- 若确认到 UAC 为弹窗模式（值为 5）：`-Wait` 会一直阻塞等待用户在 UAC 窗口点「是」，需提前提醒用户注意屏幕变暗的弹窗，不要误以为命令卡死。
