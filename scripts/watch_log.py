#!/usr/bin/env python3
"""会自己结束的日志监视器：给 Claude Code 的 Monitor / 后台命令用，避免“结果早已处理、
监视器却挂到超时，回合结束后又来一条通知”。

    python -I scripts/watch_log.py --log <日志> --match <正则> [--end <正则>]
        [--process dontstarve_steam.exe] [--stop-file <路径>] [--max-seconds 900]

- 每条匹配 --match / --end 的新行原样打印一行（即一条 Monitor 事件）；不打印原始日志。
- 满足任一条件就退出，并在最后打印一行 `WATCH END reason=... events=N elapsed=Ns`：
  end          出现 --end 匹配行（如 `ALL DONE`、`RUNNER_EXIT`）
  process      --process 指定的进程出现过、之后连续 --process-grace 秒不在（容忍 Steam 换 PID 重启）
  no-process   --process 在 --start-timeout 秒内一直没出现
  stop-file    --stop-file 指定的文件出现（驱动脚本收尾时写一个标记文件）
  timeout      到达 --max-seconds（应略小于 Monitor 的 timeout_ms，让结束是一条明确事件而不是 expired）
  too-many     事件数达到 --max-events，防止刷屏被自动停止
- 默认只看启动后新写入的内容；日志被截断/重写（游戏重启会重写 log.txt）时自动从头读，
  因此不会把上一轮残留的标记当成本轮结果。--from-start 则从文件开头读。
- 只用 --end、不用 --match 时，就是“等一个结果”的单次等待器，适合后台命令（只产生一条完成通知）。
- 以共享方式读文件，游戏独占写入时也能读；按 --encoding 解码（默认 utf-8，坏字节替换）。
"""
import argparse
import os
import re
import subprocess
import sys
import time


def process_running(name):
    """进程名是否在运行。Windows 用 tasklist，其它系统用 pgrep。"""
    if os.name == "nt":
        exe = name if name.lower().endswith(".exe") else name + ".exe"
        try:
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe}", "/NH", "/FO", "CSV"],
                                 capture_output=True, text=True, errors="replace", timeout=15).stdout
        except (OSError, subprocess.SubprocessError):
            return None  # 查询失败：不据此判断进程已退出
        return f'"{exe.lower()}"' in out.lower()
    try:
        return subprocess.run(["pgrep", "-x", name], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


class Tail:
    """增量读取日志；文件变短视为被重写，从头开始。"""

    def __init__(self, path, from_start, encoding):
        self.path = path
        self.encoding = encoding
        self.offset = 0 if from_start else self._size()
        self.buf = b""
        self.rewrites = 0

    def _size(self):
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0

    def read_lines(self):
        size = self._size()
        if size < self.offset:
            self.offset, self.buf = 0, b""
            self.rewrites += 1
        if size == self.offset:
            return []
        try:
            with open(self.path, "rb") as f:  # Windows CRT 默认共享读写，不受游戏占用影响
                f.seek(self.offset)
                data = f.read(size - self.offset)
        except OSError:
            return []
        self.offset += len(data)
        self.buf += data
        *lines, self.buf = self.buf.split(b"\n")
        return [ln.rstrip(b"\r").decode(self.encoding, errors="replace") for ln in lines]


def main(argv=None):
    p = argparse.ArgumentParser(description="会自己结束的日志监视器（每行输出即一条事件）")
    p.add_argument("--log", required=True, help="要监视的日志文件（可以暂不存在）")
    p.add_argument("--match", action="append", default=[], help="要报告的行（正则，可多次）")
    p.add_argument("--end", action="append", default=[], help="结束标记（正则，可多次）；匹配后打印该行并退出")
    p.add_argument("--exclude", action="append", default=[], help="排除的行（正则，可多次）")
    p.add_argument("--process", help="被测进程名，如 dontstarve_steam.exe；它退出后监视器也结束")
    p.add_argument("--process-grace", type=float, default=20, help="进程消失多少秒才算退出（默认 20）")
    p.add_argument("--start-timeout", type=float, default=180, help="等进程出现的最长秒数（默认 180）")
    p.add_argument("--stop-file", help="此文件出现即结束（驱动脚本收尾时写入）")
    p.add_argument("--max-seconds", type=float, default=900, help="最长运行秒数（默认 900）")
    p.add_argument("--max-events", type=int, default=150, help="最多报告多少行（默认 150）")
    p.add_argument("--max-line", type=int, default=400, help="每行最多保留的字符数（默认 400）")
    p.add_argument("--interval", type=float, default=1.0, help="轮询间隔秒数（默认 1）")
    p.add_argument("--from-start", action="store_true", help="从文件开头读（默认只读启动后新增的内容）")
    p.add_argument("--encoding", default="utf-8")
    a = p.parse_args(argv)
    if not a.match and not a.end:
        p.error("至少需要 --match 或 --end")

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except AttributeError:
        pass

    match = [re.compile(x) for x in a.match]
    end = [re.compile(x) for x in a.end]
    exclude = [re.compile(x) for x in a.exclude]
    tail = Tail(a.log, a.from_start, a.encoding)
    start = time.monotonic()
    events = 0
    seen_process = False
    process_gone_since = None
    next_process_check = start
    reason = None

    def emit(line):
        nonlocal events
        events += 1
        print(line[: a.max_line], flush=True)

    def drain():
        """收尾时把最后写入的行也过一遍（只报告，不再判断结束）。"""
        for line in tail.read_lines():
            if any(r.search(line) for r in exclude):
                continue
            if any(r.search(line) for r in end) or any(r.search(line) for r in match):
                if events < a.max_events:
                    emit(line)

    try:
        while reason is None:
            for line in tail.read_lines():
                if any(r.search(line) for r in exclude):
                    continue
                if any(r.search(line) for r in end):
                    emit(line)
                    reason = "end"
                    break
                if any(r.search(line) for r in match):
                    emit(line)
                    if events >= a.max_events:
                        reason = "too-many"
                        break
            if reason:
                break
            now = time.monotonic()
            if a.stop_file and os.path.exists(a.stop_file):
                time.sleep(a.interval)
                drain()
                reason = "stop-file"
                break
            if a.process and now >= next_process_check:
                next_process_check = now + min(5.0, max(a.process_grace / 2, a.interval))
                running = process_running(a.process)
                if running:
                    seen_process, process_gone_since = True, None
                elif running is False:
                    if seen_process:
                        process_gone_since = process_gone_since or now
                        if now - process_gone_since >= a.process_grace:
                            drain()
                            reason = "process"
                            break
                    elif now - start >= a.start_timeout:
                        reason = "no-process"
                        break
            if now - start >= a.max_seconds:
                drain()
                reason = "timeout"
                break
            time.sleep(a.interval)
    except KeyboardInterrupt:
        reason = "interrupted"

    extra = f" rewrites={tail.rewrites}" if tail.rewrites else ""
    print(f"WATCH END reason={reason} events={events} elapsed={int(time.monotonic() - start)}s{extra}",
          flush=True)
    return 0 if reason in ("end", "process", "stop-file") else 1


if __name__ == "__main__":
    sys.exit(main())
