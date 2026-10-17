"""通用命令行后端：把任意脚本或 CLI 接成子代理。

agent.json 示例：
    {"type": "command",
     "cmd": ["python", "{root}/agents/my_agent/run.py", "--out", "{out_dir}"],
     "image_arg": "--image={image}",
     "stdin": "{prompt}"}

占位符：{root} 工作流根目录、{prompt} 提示词、{out_dir} 输出目录、{image} 单张图片（只用于 image_arg）。
"cmd" 里不写 {prompt} 时，可用 "stdin" 把提示词从标准输入传入。
标准输出作为 text 返回；运行期间输出目录里新出现的文件作为 files 返回。
"""
import shutil
import subprocess
import time

from .common import ROOT, BackendError, images_newer_than


def _fill(s, ctx, **extra):
    return s.format(root=ROOT.as_posix(), prompt=ctx.prompt, out_dir=ctx.out_dir.as_posix(), **extra)


def check(cfg, ctx):
    if not cfg.get("cmd"):
        return "agent.json 缺少 cmd"
    if not shutil.which(cfg["cmd"][0]):
        return f"找不到命令 {cfg['cmd'][0]}"
    return None


def run(cfg, ctx):
    cmd = [_fill(a, ctx) for a in cfg["cmd"]]
    if cfg.get("image_arg"):
        cmd += [_fill(cfg["image_arg"], ctx, image=p) for p in ctx.images]
    cmd[0] = shutil.which(cmd[0])
    stdin = _fill(cfg["stdin"], ctx) if cfg.get("stdin") else None
    if ctx.dry_run:
        return {"dry_run": cmd, "stdin": stdin}

    ctx.out_dir.mkdir(parents=True, exist_ok=True)
    start = time.time() - 1
    try:
        proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=ctx.timeout)
    except subprocess.TimeoutExpired:
        raise BackendError(f"命令超时（{ctx.timeout} 秒）")
    if proc.returncode != 0:
        raise BackendError(f"退出码 {proc.returncode}: {(proc.stderr or proc.stdout).strip()[-800:]}")
    files = [str(p) for p in images_newer_than(ctx.out_dir, start)] if cfg.get("collect_images") else []
    return {"text": proc.stdout.strip(), "files": files}


BACKENDS = {"command": (check, run)}
