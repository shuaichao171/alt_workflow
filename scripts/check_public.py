#!/usr/bin/env python3
"""公开前检查：确认敏感内容不会被提交或公开。

    python scripts/check_public.py

检查项（全部通过退出码为 0，否则为 1）：
1. `git status` 中不出现 `private/`、`output/` 下的文件（未跟踪/已暂存/已修改都算）。
2. git 索引未跟踪 `private/`、`output/` 下的文件。
3. `.gitignore` 包含 `private/` 与 `output/`。
4. `private.example/secrets.json` 的值仍是占位（以 `<` 开头或为空）。
5. 已跟踪文件内容中不包含 `private/secrets.json` 里的真实密钥值（只比对文件，不输出密钥）。
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_DIRS = ("private/", "output/")
# 比对样本取的字段名：这些字段的值绝不允许出现在已跟踪文件里
SECRET_KEYS = ("api_key", "password", "token", "access_token", "secret", "session", "key")


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def real_secrets():
    """读取 private/secrets.json 里已填写的敏感值（只在本脚本内使用，不输出）。"""
    path = ROOT / "private" / "secrets.json"
    if not path.exists():
        return []
    values = []
    for entry in json.loads(path.read_text(encoding="utf-8")).values():
        if not isinstance(entry, dict):
            continue
        for key, raw in entry.items():
            if key not in SECRET_KEYS:
                continue
            v = str(raw).strip()
            # 过短的值（如 user=root、port=22）不作比对样本，避免误报
            if v and not v.startswith("<") and len(v) >= 6:
                values.append(v)
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
            for k in ("api_key", "base_url", "password", "ssh_alias"):
                v = str(entry.get(k, "")).strip()
                if v and not v.startswith("<"):
                    problems.append(f"private.example/secrets.json 的 {name}.{k} 不是占位值：{v[:4]}***")

    secrets = real_secrets()
    if secrets:
        for f in git("ls-files").splitlines():
            p = ROOT / f
            if not p.is_file():
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if any(s in content for s in secrets):
                problems.append(f"{f} 中包含 private/secrets.json 的真实密钥值")

    if problems:
        print("[check_public] 发现问题：")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("[check_public] 通过：敏感目录未入库、模板为占位值、已跟踪文件无真实密钥。")


if __name__ == "__main__":
    main()
