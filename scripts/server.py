#!/usr/bin/env python3
"""服务器运维封装（alt_workflow · skills/server-ops）。

设计原则：
- **只读优先**：doctor / ps / health / logs / pull 随时可跑；
  写操作（exec / push / backup）必须显式加 `--yes`，否则只打印将要执行的命令。
- **凭据不回显**：连接信息只从 `private/secrets.json` 的条目读取（默认 `vps_la`），
  密码/密钥不会出现在任何输出里；认证走 SSH 别名或密钥（本机 Windows 无 sshpass，不支持密码认证）。
- 只用 Python 标准库 + 本机 `ssh` / `scp` / `tar`。

用法示例：
    python scripts/server.py doctor
    python scripts/server.py ps
    python scripts/server.py health --port 8787
    python scripts/server.py logs --container loomy-proxy --tail 100
    python scripts/server.py exec --yes -- 'uname -a'
    python scripts/server.py backup --yes --dir <部署目录> --files data/accounts.json data/keys.json
    python scripts/server.py push --yes --src <本地项目> --dest <服务器源码目录>
    python scripts/server.py pull --remote <服务器文件> --local <本机路径>
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "private" / "secrets.json"

# push 时默认排除的内容（运行期数据与凭据一律不上服务器）
DEFAULT_EXCLUDES = [".git", "node_modules", "data", "secrets", "config/config.json", ".deploy-tmp"]

READ_ONLY_HINT = "只打印将要执行的命令；确认无误后加 --yes 真正执行"


def out(text: str = "") -> None:
    print(text)


def head(title: str) -> None:
    out()
    out(f"── {title} " + "─" * max(0, 60 - len(title)))


def die(msg: str, code: int = 1):
    out(f"ERROR: {msg}")
    sys.exit(code)


# Git Bash(MSYS) 会把形如 /www/... 的参数改写成 <Git 安装目录>/www/...，这里还原回服务器路径
MSYS_SEGMENTS = ("www", "wwwroot", "etc", "var", "opt", "root", "srv", "home", "usr", "tmp")


def fix_msys_path(value: str) -> str:
    """还原被 Git Bash 改写的 POSIX 路径（只用于远程路径参数）。

    Git Bash(MSYS) 会把 `python 脚本.py --dest /www/x` 里的 `/www/x` 当成自己的路径改写掉，
    因此远程路径参数都要过这里：能认出来的自动还原，认不出来的直接报错（避免把本地路径当远程用）。
    """
    if not re.match(r"^[A-Za-z]:[\\/]", value):
        return value
    parts = [p for p in re.split(r"[\\/]+", value) if p]
    low = [p.lower() for p in parts]
    # 1) /tmp/... 会被映射到 Windows 临时目录（C:\Users\…\AppData\Local\Temp\…）
    for i in range(1, len(low) - 2):
        if low[i:i + 3] == ["appdata", "local", "temp"]:
            rest = parts[i + 3:]
            fixed = "/tmp" + ("/" + "/".join(rest) if rest else "")
            out(f"  注意：Git Bash 改写了路径，已把 {value} 还原为 {fixed}")
            return fixed
    # 2) 常见服务器目录段（/www/... → <Git 安装目录>/www/...）
    for i, part in enumerate(parts[1:], start=1):
        if part.lower() in MSYS_SEGMENTS:
            fixed = "/" + "/".join(parts[i:])
            out(f"  注意：Git Bash 改写了路径，已把 {value} 还原为 {fixed}")
            return fixed
    die(f"远程路径参数被 Git Bash 改写成了 {value}；请改用 "
        f"`MSYS_NO_PATHCONV=1 python scripts/server.py …` 重跑")


# ---------------------------------------------------------------- 连接信息

def load_server(name: str) -> dict:
    if not SECRETS.exists():
        die(f"缺少 {SECRETS}（从 private.example/ 复制后填写）")
    try:
        data = json.loads(SECRETS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"{SECRETS} 不是合法 JSON：{exc}")
    entry = data.get(name)
    if not isinstance(entry, dict):
        die(f"private/secrets.json 里没有服务器条目 `{name}`")
    if not entry.get("ssh_alias") and not entry.get("host"):
        die(f"条目 `{name}` 既没有 host 也没有 ssh_alias")
    return entry


def ssh_cmd(entry: dict) -> list[str]:
    """构造 ssh 基础命令（不包含远程命令本身）。"""
    base = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=30"]
    alias = str(entry.get("ssh_alias") or "").strip()
    if alias:
        return base + [alias]
    host = str(entry.get("host") or "").strip()
    user = str(entry.get("user") or "root").strip()
    port = str(entry.get("port") or 22)
    key = str(entry.get("key_path") or "").strip()
    cmd = base + ["-p", port]
    if key:
        cmd += ["-i", str(Path(key).expanduser())]
    return cmd + [f"{user}@{host}"]


def scp_cmd(entry: dict) -> list[str]:
    """scp 的选项部分（主机/别名由 scp_target 用 `目标:路径` 形式给出）。"""
    base = ["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    alias = str(entry.get("ssh_alias") or "").strip()
    key = str(entry.get("key_path") or "").strip()
    if alias:
        # 走 ssh_config 别名时，端口/私钥都由别名提供
        return base + (["-i", str(Path(key).expanduser())] if key else [])
    port = str(entry.get("port") or 22)
    cmd = base + ["-P", port]
    if key:
        cmd += ["-i", str(Path(key).expanduser())]
    return cmd


def scp_target(entry: dict, remote_path: str) -> str:
    """给 scp 用的 `[user@]host:path` 目标（别名优先，scp 同样认 ~/.ssh/config 别名）。"""
    alias = str(entry.get("ssh_alias") or "").strip()
    if alias:
        return f"{alias}:{remote_path}"
    host = str(entry.get("host") or "").strip()
    if not host:
        die("条目里既没有 ssh_alias 也没有 host，scp 无法构造目标")
    user = str(entry.get("user") or "root").strip()
    return f"{user}@{host}:{remote_path}"


def run(cmd: list[str], quiet: bool = False) -> subprocess.CompletedProcess:
    if not quiet:
        out("$ " + " ".join(_mask(cmd)))
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _mask(cmd: list[str]) -> list[str]:
    """防止把 -i 后面的私钥路径之外的敏感项打印出来（保留命令可读性）。"""
    masked, skip = [], False
    for part in cmd:
        if skip:
            masked.append("<hidden>")
            skip = False
            continue
        masked.append(part)
        if part in ("-i", "--password-stdin"):
            skip = True
    return masked


def remote(entry: dict, command: str, quiet: bool = False) -> subprocess.CompletedProcess:
    return run(ssh_cmd(entry) + [command], quiet=quiet)


def show(res: subprocess.CompletedProcess, what: str = "") -> bool:
    ok = res.returncode == 0
    body = (res.stdout or "").rstrip()
    err = (res.stderr or "").rstrip()
    if body:
        out(body)
    if err:
        out(("[stderr] " if ok else "ERROR: ") + err)
    if not ok and not err:
        out(f"ERROR: {what or '命令'} 退出码 {res.returncode}")
    return ok


# ---------------------------------------------------------------- 子命令

def cmd_doctor(args) -> int:
    entry = load_server(args.server)
    problems = []

    head("本机依赖")
    for tool in ("ssh", "scp", "tar"):
        path = shutil.which(tool)
        out(f"  {tool:<5} {path or 'MISSING'}")
        if not path:
            problems.append(f"本机缺少 {tool}")
    out(f"  私钥   {entry.get('key_path') or '(用 ssh 别名/默认密钥)'}")
    out(f"  入口   {'ssh ' + str(entry.get('ssh_alias')) if entry.get('ssh_alias') else entry.get('user', 'root') + '@' + str(entry.get('host'))}")
    if not entry.get("ssh_alias") and not entry.get("key_path"):
        out("  提示   没有别名也没有 key_path：若只能密码登录，本机无法脚本化（无 sshpass）")

    head("连通性")
    res = remote(entry, "hostname; uptime | tr -s ' '; cat /etc/os-release | sed -n 2p; uname -r")
    if not show(res, "ssh 连接"):
        problems.append("ssh 连不上（检查别名/密钥/网络）")
        out()
        out("结论：连接失败，后续检查跳过")
        return 1

    head("运行时")
    show(remote(entry, "docker --version; docker-compose version 2>/dev/null | head -1; "
                       "docker compose version 2>/dev/null | head -1; "
                       "command -v node >/dev/null && node -v || echo 'node: MISSING(宿主机)'"))

    head("资源")
    show(remote(entry, "free -m | head -2; df -h / | tail -1"))

    head("容器")
    show(remote(entry, 'docker ps --format "{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}"'))

    head("网络")
    show(remote(entry, 'docker network ls --format "{{.Name}}"'))

    if problems:
        head("结论")
        for p in problems:
            out(f"  ✗ {p}")
        return 1
    head("结论")
    out("  ✓ 本机依赖与服务器连通性正常")
    return 0


def cmd_ps(args) -> int:
    entry = load_server(args.server)
    return 0 if show(remote(entry, 'docker ps --format "{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}"')) else 1


def cmd_health(args) -> int:
    entry = load_server(args.server)
    res = remote(entry, f"curl -s -m {args.timeout} http://127.0.0.1:{args.port}{args.path}")
    return 0 if show(res, "健康检查") else 1


def cmd_logs(args) -> int:
    entry = load_server(args.server)
    cmd = f"docker logs --tail {args.tail}"
    if args.since:
        cmd = f"docker logs --since {args.since}"
    cmd += f" {args.container} 2>&1 | tail -{args.tail}"
    return 0 if show(remote(entry, cmd)) else 1


def cmd_exec(args) -> int:
    entry = load_server(args.server)
    command = args.command
    if isinstance(command, list):
        command = " ".join(command)
    if not command.strip():
        die("没给要执行的命令，例如：exec --yes -- 'uname -a'")
    if not args.yes:
        head(READ_ONLY_HINT)
        out("$ ssh " + str(entry.get("ssh_alias") or entry.get("host")) + " " + repr(command))
        return 0
    return 0 if show(remote(entry, command)) else 1


def cmd_pull(args) -> int:
    entry = load_server(args.server)
    local = Path(args.local).expanduser()
    local.parent.mkdir(parents=True, exist_ok=True)
    remote_path = fix_msys_path(args.remote)
    res = run(scp_cmd(entry) + [scp_target(entry, remote_path), str(local)])
    ok = show(res, "scp 下载")
    if ok:
        out(f"  → 已下载到 {local}（如含凭据，用完请删除）")
    return 0 if ok else 1


def cmd_backup(args) -> int:
    entry = load_server(args.server)
    files = " ".join(f"'{f}'" for f in args.files)
    script = (
        "set -e; D=" + fix_msys_path(args.dir) + "; TS=$(date +%Y%m%d-%H%M%S); "
        "mkdir -p \"$D/backups\"; "
        f"for f in {files}; do "
        "  if [ -f \"$D/$f\" ]; then cp -p \"$D/$f\" \"$D/backups/$(basename \"$f\").$TS.bak\"; "
        "    echo \"backup: $D/backups/$(basename \"$f\").$TS.bak\"; fi; done; "
        "chmod 600 \"$D\"/backups/*.\"$TS\".bak 2>/dev/null || true; "
        "md5sum \"$D\"/backups/*.\"$TS\".bak"
    )
    if not args.yes:
        head(READ_ONLY_HINT)
        out(f"$ ssh {entry.get('ssh_alias') or entry.get('host')} {script!r}")
        return 0
    head("备份")
    ok = show(remote(entry, script), "备份")
    if ok:
        out("  → 请把上面的备份路径与 md5 记进交付说明（回滚时要靠它）")
    return 0 if ok else 1


def cmd_push(args) -> int:
    entry = load_server(args.server)
    dest = fix_msys_path(args.dest)
    src = Path(args.src).expanduser().resolve()
    if not src.is_dir():
        die(f"--src 不是目录：{src}")
    excludes = list(DEFAULT_EXCLUDES) + list(args.exclude or [])
    name = args.name or src.name.lower().replace(" ", "-")
    tarball = Path(tempfile.gettempdir()) / f"{name}-{args.stamp}.tgz"
    staging = f"/tmp/{name}-push"
    tar_cmd = ["tar", "czf", str(tarball), "-C", str(src)]
    for pattern in excludes:
        cleaned = pattern[2:] if pattern.startswith("./") else pattern.lstrip("/")
        tar_cmd.append(f"--exclude=./{cleaned}")
    tar_cmd.append(".")

    head("计划")
    out(f"  本机 {src}")
    out(f"  目标 {entry.get('ssh_alias') or entry.get('host')}:{dest}")
    out(f"  排除 {', '.join(excludes)}")
    if not args.yes:
        head(READ_ONLY_HINT)
        out("  1) " + " ".join(tar_cmd))
        out(f"  2) scp  {tarball} → /tmp/{tarball.name}")
        out(f"  3) ssh  rm -rf {staging} && mkdir -p {staging} && "
            f"tar xzf /tmp/{tarball.name} -C {staging} && rsync -a --delete {staging}/ {dest}/")
        return 0

    head("1/3 打包")
    if not show(run(tar_cmd), "tar"):
        return 1
    out(f"  → {tarball} ({tarball.stat().st_size} bytes)")

    head("2/3 上传")
    if not show(run(scp_cmd(entry) + [str(tarball), scp_target(entry, f"/tmp/{tarball.name}")]), "scp 上传"):
        return 1

    head("3/3 同步到目标目录")
    sync = (f"set -e; rm -rf {staging}; mkdir -p {staging}; "
            f"tar xzf /tmp/{tarball.name} -C {staging}; "
            f"mkdir -p {dest}; rsync -a --delete {staging}/ {dest}/; "
            f"rm -rf {staging}; echo 'synced -> {dest}'")
    if not show(remote(entry, sync), "rsync"):
        return 1
    out()
    out("后续：跑安装脚本 → 重启容器 → 等 healthy → 验证（见 skills/server-ops/02-部署与更新.md）")
    out(f"记得清理：本机 {tarball}、服务器 /tmp/{tarball.name}")
    return 0


# ---------------------------------------------------------------- 入口

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="服务器运维封装（只读优先，写操作需 --yes）")
    parser.add_argument("--server", default="vps_la", help="private/secrets.json 里的条目名（默认 vps_la）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="只读：本机依赖 + 连通性 + 服务器基线").set_defaults(func=cmd_doctor)
    sub.add_parser("ps", help="只读：容器列表").set_defaults(func=cmd_ps)

    p = sub.add_parser("health", help="只读：curl 本机端口的 /health")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--path", default="/health")
    p.add_argument("--timeout", type=int, default=5)
    p.set_defaults(func=cmd_health)

    p = sub.add_parser("logs", help="只读：容器日志尾部")
    p.add_argument("--container", required=True)
    p.add_argument("--tail", type=int, default=100)
    p.add_argument("--since", default="")
    p.set_defaults(func=cmd_logs)

    p = sub.add_parser("exec", help="在服务器执行命令（需 --yes）")
    p.add_argument("--yes", action="store_true")
    p.add_argument("remote_command", nargs=argparse.REMAINDER, metavar="-- 命令")
    p.set_defaults(func=cmd_exec)

    p = sub.add_parser("pull", help="只读：把服务器文件拉回本机")
    p.add_argument("--remote", required=True)
    p.add_argument("--local", required=True)
    p.set_defaults(func=cmd_pull)

    p = sub.add_parser("backup", help="备份部署目录下的文件（需 --yes）")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--dir", required=True, help="部署目录（备份写到 <dir>/backups/）")
    p.add_argument("--files", nargs="+", required=True, help="相对 --dir 的文件列表")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("push", help="打包本机目录并同步到服务器（需 --yes）")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--src", required=True, help="本机项目目录")
    p.add_argument("--dest", required=True, help="服务器目标目录（会被 --delete 同步）")
    p.add_argument("--exclude", action="append", default=[], help="额外排除模式（可重复）")
    p.add_argument("--name", default="", help="包名（默认取目录名）")
    p.add_argument("--stamp", default="src", help="包名后缀，便于区分多次推送")
    p.set_defaults(func=cmd_push)

    args = parser.parse_args()
    if args.command == "exec":
        # argparse.REMAINDER 会把 `--` 也带进来，去掉它
        args.command_list = [c for c in args.remote_command if c != "--"]
        args.command = " ".join(args.command_list)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        out("已中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())
