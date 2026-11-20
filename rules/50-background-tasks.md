# 后台任务与通知

适用于 Claude Code 的后台命令（`run_in_background`）和 `Monitor`，其他代理的同类机制同理。目标：**一次运行只通知一次结果，回合结束后不再收到已处理过的通知。**

常见的重复来源：`tail -f | grep` 这类不会自己结束的监视器配上 15～30 分钟超时，测试几分钟就跑完、结果已在回合里处理掉，监视器却一直挂到超时，回合结束后又送来 `Monitor expired` 或迟到的日志事件；或者同一次运行同时开了后台驱动、Monitor 和前台轮询三条等待渠道。

## 开始前：一次运行只留一条等待渠道

- **只要最终结果**：驱动脚本用后台命令运行，等它的完成通知；或者前台等待（`until grep -q <结束标记> <输出>; do sleep 2; done`，单次 ≤10 分钟）。二选一，不要后台跑完还再前台轮询它的输出文件，也不要再加 Monitor 盯同一件事。
- **需要中途事件**（失败一出现就修、截图标记）才用 Monitor，命令必须能自己结束：用 [watch_log.py](../scripts/watch_log.py)，给出结束标记 `--end`、被测进程 `--process` 或驱动收尾时写的 `--stop-file`，再加 `--max-seconds`。`timeout_ms` 只比 `--max-seconds` 多留 1～2 分钟，按预计时长设，不要习惯性设 30 分钟。
- 不要裸用 `tail -f`、`while true` 做一次性等待；`tail -f | grep -m 1` 在日志变安静后同样不会退出。

```bash
python -I scripts/watch_log.py --log "<日志>" \
  --match '\] (FAIL|INFO)|LUA ERROR|stack traceback' --end 'ALL DONE' \
  --process dontstarve_steam.exe --max-seconds 900
```

（脚本路径相对工作流根目录；在目标项目里运行时写完整路径。）监视器结束时一定打印一行 `WATCH END reason=...`（`end`/`process`/`stop-file` 为正常结束，`timeout`/`no-process`/`too-many` 要查原因）。

## 结束回合前：清点本回合开的后台任务

1. 结果已经读到并处理完的 Monitor、纯等待命令：用 `TaskStop` 停掉，不留到超时。
2. 还在做清理的驱动脚本（还原存档、关闭游戏、恢复静音）**不要停**：前台等它退出后再收尾；确实要长时间运行的，在总结里写明“驱动仍在运行，完成后会再通知一次”。
3. 交给用户手动操作（游戏留着给用户玩）时，先停掉所有盯这个进程或日志的监视器，否则用户的操作会继续触发事件。

## 收到通知时

- 先看它对应的任务结果是否已经处理过（同一 task-id 已读过输出、`WATCH END` 已收到、`Monitor expired` 而测试早已结束）。处理过就**一句话说明已处理、无需操作**，不重复分析、不重跑、不重复长总结。
- 只有带来新信息（新失败、新结果、异常退出）的通知才继续工作。
