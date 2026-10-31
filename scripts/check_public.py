#!/usr/bin/env python3
"""公开前检查：确认敏感内容不会被提交或公开。

    python scripts/check_public.py

检查项（全部通过退出码为 0，否则为 1）：
1. `git status` 中不出现 `private/`、`output/` 下的文件（未跟踪/已暂存/已修改都算）。
2. git 索引未跟踪 `private/`、`output/` 下的文件。
3. `.gitignore` 包含 `private/` 与 `output/`。
4. `private.example/secrets.json` 的值仍是占位（以 `<` 开头或为空）。
5. 已跟踪文件（含子模块）中不包含 `private/secrets.json` 的真实密钥、服务器地址、
   私有接口域名，也不包含 `private/paths.md` 里的本机绝对路径（只报字段名，不输出值）。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_DIRS = ("private/", "output/")
# 比对样本取的字段名：这些字段的值绝不允许出现在已跟踪文件里
SECRET_KEYS = ("api_key", "password", "token", "access_token", "secret", "session", "key",
               "host", "key_path")
# 公共示例域名，不算私有地址
PUBLIC_HOSTS = ("example.com", "api.openai.com", "localhost", "127.0.0.1")


def git(*args):
    return subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def real_secrets():
    """读取 private/ 里已填写的敏感值，返回 [(标签, 值)]（只在本脚本内使用，不输出值）。"""
    values = []
    path = ROOT / "private" / "secrets.json"
    if path.exists():
        for name, entry in json.loads(path.read_text(encoding="utf-8")).items():
            if not isinstance(entry, dict):
                continue
            for key, raw in entry.items():
                v = str(raw).strip()
                if key == "base_url":  # 只比对域名部分，路径 /v1 之类太常见
                    v = re.sub(r"^\w+://", "", v).split("/")[0]
                    if any(v.endswith(h) for h in PUBLIC_HOSTS):
                        continue
                elif key not in SECRET_KEYS:
                    continue
                # 过短的值（如 user=root、port=22）不作比对样本，避免误报
                if v and not v.startswith("<") and len(v) >= 6:
                    values.append((f"secrets.json 的 {name}.{key}", v))
    paths = ROOT / "private" / "paths.md"
    if paths.exists():
        # 只比对 Windows 绝对路径（本机路径）；服务器上的通用目录（如宝塔默认目录）不算隐私
        for m in re.finditer(r"^\| `([A-Z0-9_]+)` \|[^|]*\| `([A-Za-z]:[\\/][^`]+)`",
                             paths.read_text(encoding="utf-8"), re.M):
            for variant in {m.group(2), m.group(2).replace("\\", "/")}:
                if len(variant) >= 8:
                    values.append((f"paths.md 的 {m.group(1)}", variant))
    return values


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    problems = []

    dirty = [l[3:].strip('"') for l in git("status", "--porcelain").splitlines()
             if any(l[3:].strip('"').startswith(d) for d in SENSITIVE_DIRS)]
    if dirty:
        problems.append("git status 中出现敏感目录文件：\n    " + "\n    ".join(dirty))

    tracked = [l for l in git("ls-files").splitlines() if any(l.startswith(d) for d in SENSITIVE_DIRS)]
    if tracked:
        problems.append("git 已跟踪敏感目录文件：\n    " + "\n    ".join(tracked))

    gitignore = ROOT / ".gitignore"
    text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    for d in SENSITIVE_DIRS:
        if d not in text:
            problems.append(f".gitignore 缺少 {d}")

    tpl = ROOT / "private.example" / "secrets.json"
    if tpl.exists():
        for name, entry in json.loads(tpl.read_text(encoding="utf-8")).items():
            if name.startswith("_") or not isinstance(entry, dict):
                continue
            for k in ("api_key", "base_url", "password", "host", "key_path"):
                v = str(entry.get(k, "")).strip()
                if v and not v.startswith("<"):
                    problems.append(f"private.example/secrets.json 的 {name}.{k} 不是占位值：{v[:4]}***")

    secrets = real_secrets()
    if secrets:
        # 子模块同样公开，一并扫描
        for f in git("ls-files", "--recurse-submodules").splitlines():
            p = ROOT / f
            if not p.is_file():
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            labels = sorted({label for label, v in secrets if v in content})
            if labels:
                problems.append(f"{f} 中包含 {'、'.join(labels)} 的真实值")

    if problems:
        print("[check_public] 发现问题：")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("[check_public] 通过：敏感目录未入库、模板为占位值、已跟踪文件无真实密钥。")


if __name__ == "__main__":
    main()
