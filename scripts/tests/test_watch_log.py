"""watch_log.py 的自测：python -I scripts/tests/test_watch_log.py"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "watch_log.py")


def run(args, timeout=60):
    t0 = time.monotonic()
    r = subprocess.run([sys.executable, "-I", SCRIPT, *args], capture_output=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    return r, time.monotonic() - t0


def write_later(path, chunks, delay=0.6, mode="ab"):
    def go():
        for c in chunks:
            time.sleep(delay)
            if c is None:  # 模拟游戏重启重写日志
                with open(path, "wb"):
                    pass
                continue
            with open(path, mode) as f:
                f.write(c.encode("utf-8"))
    th = threading.Thread(target=go, daemon=True)
    th.start()
    return th


class WatchLogTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="watchlog_")
        self.log = os.path.join(self.dir, "log.txt")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_end_marker_exits_and_ignores_old_content(self):
        with open(self.log, "w", encoding="utf-8") as f:
            f.write("[T] FAIL old run\n[T] ALL DONE\n")  # 上一轮残留，不能触发
        write_later(self.log, ["noise\n[T] FAIL 新的失败\n", "[T] PASS ok\n[T] ALL DONE\n"])
        r, dt = run(["--log", self.log, "--match", r"\] FAIL", "--end", "ALL DONE",
                     "--max-seconds", "20", "--interval", "0.2"])
        lines = r.stdout.strip().splitlines()
        self.assertEqual(lines[0], "[T] FAIL 新的失败")
        self.assertEqual(lines[1], "[T] ALL DONE")
        self.assertTrue(lines[-1].startswith("WATCH END reason=end events=2"), lines)
        self.assertEqual(r.returncode, 0)
        self.assertLess(dt, 10)

    def test_rewritten_log_is_read_from_start(self):
        with open(self.log, "w", encoding="utf-8") as f:
            f.write("x" * 500 + "\n")
        write_later(self.log, [None, "[T] FAIL after restart\n[T] ALL DONE\n"])
        r, _ = run(["--log", self.log, "--match", "FAIL", "--end", "ALL DONE",
                    "--max-seconds", "20", "--interval", "0.2"])
        self.assertIn("[T] FAIL after restart", r.stdout)
        self.assertIn("reason=end", r.stdout)
        self.assertIn("rewrites=1", r.stdout)

    def test_stop_file(self):
        stop = os.path.join(self.dir, "done.flag")
        write_later(self.log, ["[T] FAIL a\n"])
        threading.Timer(1.5, lambda: open(stop, "w").close()).start()
        r, dt = run(["--log", self.log, "--match", "FAIL", "--stop-file", stop,
                     "--max-seconds", "20", "--interval", "0.2"])
        self.assertIn("[T] FAIL a", r.stdout)
        self.assertIn("reason=stop-file", r.stdout)
        self.assertLess(dt, 10)

    def test_timeout_is_an_explicit_event(self):
        r, dt = run(["--log", self.log, "--end", "NEVER", "--max-seconds", "1.5", "--interval", "0.2"])
        self.assertIn("WATCH END reason=timeout events=0", r.stdout)
        self.assertEqual(r.returncode, 1)
        self.assertLess(dt, 8)

    def test_max_events(self):
        write_later(self.log, ["".join(f"FAIL {i}\n" for i in range(10))])
        r, _ = run(["--log", self.log, "--match", "FAIL", "--max-events", "3",
                    "--max-seconds", "20", "--interval", "0.2"])
        self.assertIn("reason=too-many events=3", r.stdout)

    def test_process_never_started(self):
        r, dt = run(["--log", self.log, "--match", "FAIL", "--process", "no_such_proc_watchlog.exe",
                     "--start-timeout", "1", "--max-seconds", "20", "--interval", "0.2"])
        self.assertIn("reason=no-process", r.stdout)
        self.assertLess(dt, 15)

    @unittest.skipUnless(os.name == "nt", "Windows 进程名检测")
    def test_process_exit_ends_watch(self):
        exe = os.path.join(self.dir, "watchlog_fakegame.exe")
        shutil.copy(os.path.join(os.environ["SystemRoot"], "System32", "PING.EXE"), exe)
        proc = subprocess.Popen([exe, "-n", "4", "127.0.0.1"], stdout=subprocess.DEVNULL)
        try:
            write_later(self.log, ["[T] FAIL while running\n"])
            r, dt = run(["--log", self.log, "--match", "FAIL", "--process", "watchlog_fakegame.exe",
                         "--process-grace", "2", "--max-seconds", "40", "--interval", "0.2"])
        finally:
            proc.kill()
        self.assertIn("[T] FAIL while running", r.stdout)
        self.assertIn("reason=process", r.stdout)
        self.assertLess(dt, 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
