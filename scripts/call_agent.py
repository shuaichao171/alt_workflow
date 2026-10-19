#!/usr/bin/env python3
"""子代理统一调用入口。

    python scripts/call_agent.py --list                         # 列出子代理及后端可用情况
    python scripts/call_agent.py --doctor                      # 环境自检：Pillow、private 配置、子模块、后端
    python scripts/call_agent.py painter "a red apple icon" --transparent -o out/
    python scripts/call_agent.py vision "图里有什么文字？" -i shot.png
    python scripts/call_agent.py painter "..." --backend openai_images --dry-run

按 agents/<名称>/agent.json 中 backends 的顺序依次尝试：未配置的跳过，失败的换下一个。
结果以 JSON 打印到标准输出：ok / backend / files / text / checks / attempts。
-i 和 -o 的相对路径相对于调用时的当前目录；脚本自身的路径相对于工作流根目录解析，可在任意目录下调用。
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backends import BACKENDS  # noqa: E402
from backends.common import OUTPUT_DIR, PRIVATE_DIR, ROOT, BackendError, Context, check_image, fix_alpha, load_secrets  # noqa: E402

AGENTS_DIR = ROOT / "agents"


def load_agent(name):
    path = AGENTS_DIR / name / "agent.json"
    if not path.exists():
        names = ", ".join(list_agent_names()) or "无"
        sys.exit(f"[错误] 未找到子代理 `{name}`（可用：{names}）")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_agent_names():
    return sorted(p.parent.name for p in AGENTS_DIR.glob("*/agent.json") if not p.parent.name.startswith("_"))


def cmd_list(secrets):
    ctx = Context(agent="", prompt="", secrets=secrets)
    rows = []
    for name in list_agent_names():
        agent = load_agent(name)
        backends = []
        for b in agent.get("backends", []):
            check, _ = BACKENDS.get(b["type"], (None, None))
            reason = "未知后端类型" if check is None else check(b, ctx)
            backends.append({"type": b["type"], "available": reason is None, "reason": reason})
        rows.append({"agent": name, "description": agent.get("description", ""),
                     "output": agent.get("output", ""), "backends": backends})
    return rows


def cmd_doctor(secrets):
    """环境自检：Python、Pillow、private 配置、secrets 条目、子模块和各代理后端可用性。"""
    rows = []

    def add(item, ok, note=""):
        rows.append({"item": item, "ok": bool(ok), "note": note})

    add(f"Python {sys.version.split()[0]}", True)
    try:
        import PIL  # noqa: F401
        add("Pillow（图片检查 / --fix-alpha）", True)
    except ImportError:
        add("Pillow（图片检查 / --fix-alpha）", False, "未安装：pip install Pillow")

    add("private/ 目录", PRIVATE_DIR.is_dir(), "缺失时复制 private.example 为 private")
    for name in ("secrets.json", "paths.md"):
        add(f"private/{name}", (PRIVATE_DIR / name).exists())

    for name, entry in sorted((secrets or {}).items()):
        if name.startswith("_") or not isinstance(entry, dict):
            continue  # 跳过 _comment 等说明键
        vals = entry if isinstance(entry, dict) else {}
        ok = all(str(vals.get(k, "<")).strip() and not str(vals.get(k, "<")).strip().startswith("<")
                 for k in ("base_url", "api_key"))
        add(f"secrets 条目 {name}", ok, "已配置" if ok else "仍是占位值，对应后端会自动跳过")

    paths_md = PRIVATE_DIR / "paths.md"
    if paths_md.exists():
        unfilled = [m.group(1) for m in re.finditer(r"^\| `([A-Z0-9_]+)` \|.*\|.*<.*\|\s*$",
                                                    paths_md.read_text(encoding="utf-8"), re.M)]
        add("private/paths.md 未填值条目", True, "、".join(unfilled) or "无")

    sub = ROOT / "skills/dst-modding/mod-skills/SKILL-CATALOG.md"
    add("mod-skills 子模块", sub.exists(), "缺失时运行 git submodule update --init")

    for row in cmd_list(secrets):
        ok = any(b["available"] for b in row["backends"])
        note = "；".join(f"{b['type']}：{b['reason'] or '可用'}" for b in row["backends"])
        add(f"代理 {row['agent']}", ok, note)
    return rows

def run_agent(agent, ctx, only_backend=None):
    attempts = []
    if only_backend and not any(b.get("type") == only_backend for b in agent.get("backends", [])):
        if only_backend in BACKENDS:
            reason = f"代理 {ctx.agent} 未配置后端 {only_backend}（可用：{', '.join(b['type'] for b in agent.get('backends', []))}）"
        else:
            reason = f"未知后端类型 {only_backend}（可用：{', '.join(BACKENDS)}）"
        return {"ok": False, "agent": ctx.agent,
                "attempts": [{"backend": only_backend, "status": "skipped", "reason": reason}]}
    for b in agent.get("backends", []):
        btype = b["type"]
        if only_backend and btype != only_backend:
            continue
        if btype not in BACKENDS:
            attempts.append({"backend": btype, "status": "skipped", "reason": "未知后端类型"})
            continue
        check, run = BACKENDS[btype]
        reason = check(b, ctx)
        if reason:
            attempts.append({"backend": btype, "status": "skipped", "reason": reason})
            continue
        print(f"[{ctx.agent}] 使用后端 {btype} ...", file=sys.stderr)
        try:
            result = run(b, ctx)
        except BackendError as e:
            attempts.append({"backend": btype, "status": "failed", "reason": str(e)})
            print(f"[{ctx.agent}] {btype} 失败：{e}", file=sys.stderr)
            continue
        attempts.append({"backend": btype, "status": "ok"})
        return {"ok": True, "agent": ctx.agent, "backend": btype, **result, "attempts": attempts}
    return {"ok": False, "agent": ctx.agent, "attempts": attempts}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    p = argparse.ArgumentParser(description="调用工作流子代理")
    p.add_argument("agent", nargs="?", help="子代理名称，见 agents/INDEX.md")
    p.add_argument("prompt", nargs="?", help="提示词；省略或为 - 时从 stdin 读取")
    p.add_argument("--prompt-file", help="从文件读取提示词")
    p.add_argument("-i", "--image", action="append", default=[], help="输入/参考图片，可多次指定")
    p.add_argument("-o", "--out", help="输出目录，默认 output/<子代理名>/")
    p.add_argument("--backend", help="只使用指定类型的后端")
    p.add_argument("--transparent", action="store_true", help="生成透明背景图（画图类代理）")
    p.add_argument("--fix-alpha", action="store_true", help="把 alpha ≥250 的像素改为 255（需要 Pillow）")
    p.add_argument("--timeout", type=int, help="单个后端超时秒数，默认取 agent.json 的 timeout 或 600")
    p.add_argument("--dry-run", action="store_true", help="只打印将要执行的命令/请求，不真正调用")
    p.add_argument("--list", action="store_true", help="列出所有子代理及后端可用情况")
    p.add_argument("--doctor", action="store_true", help="环境自检：Python、Pillow、private 配置、子模块和后端")
    args = p.parse_args()

    secrets = load_secrets()
    if args.doctor:
        print(json.dumps(cmd_doctor(secrets), ensure_ascii=False, indent=2))
        return
    if args.list or not args.agent:
        print(json.dumps(cmd_list(secrets), ensure_ascii=False, indent=2))
        return

    agent = load_agent(args.agent)
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    elif args.prompt and args.prompt != "-":
        prompt = args.prompt
    elif not sys.stdin.isatty():
        prompt = sys.stdin.read()
    else:
        prompt = agent.get("default_prompt", "")
    if not prompt.strip():
        p.error("需要提供提示词")

    images = []
    for img in args.image:
        path = Path(img).resolve()
        if not path.exists():
            sys.exit(f"[错误] 图片不存在: {img}")
        images.append(str(path))
    if agent.get("requires_image") and not images:
        p.error(f"子代理 {args.agent} 需要用 -i 指定图片")

    ctx = Context(agent=args.agent, prompt=prompt.strip(), images=images,
                  out_dir=Path(args.out).resolve() if args.out else OUTPUT_DIR / args.agent,
                  transparent=args.transparent, timeout=args.timeout or agent.get("timeout", 600),
                  dry_run=args.dry_run, secrets=secrets)
    result = run_agent(agent, ctx, args.backend)

    if result.get("files"):
        if args.fix_alpha:
            for f in result["files"]:
                fix_alpha(f)
        result["checks"] = [check_image(f) for f in result["files"]]

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
