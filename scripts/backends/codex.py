"""Codex CLI 后端：走用户已登录的 ChatGPT / Codex 账号额度，不需要 API 密钥。

- codex_image：让 Codex 用内置生图工具出图，再从 generated_images 目录取回。
- codex_text ：把图片和问题交给 Codex，返回它的最终回复（识图、问答）。

提示词通过 stdin 传入，避免 Windows 命令行转义问题。不读取 ~/.codex 下的登录凭据。
"""
import os
import shutil
import subprocess
import time
from pathlib import Path

from .common import BackendError, copy_outputs, images_newer_than

DEFAULT_GEN_DIR = "~/.codex/generated_images"


def _exe(cfg):
    exe = shutil.which(cfg.get("exe", "codex"))
    if not exe:
        raise BackendError("找不到 codex 命令（npm i -g @openai/codex 并登录）")
    return exe


def check(cfg, ctx):
    try:
        _exe(cfg)
    except BackendError as e:
        return str(e)
    return None


def _run(cfg, ctx, prompt, sandbox, backend):
    run_dir = ctx.run_dir(backend)
    last_msg = run_dir / "last_message.txt"
    cmd = [_exe(cfg), "exec", "--skip-git-repo-check", "-s", sandbox, "-C", str(run_dir)]
    if cfg.get("model"):
        cmd += ["-m", cfg["model"]]
    cmd += [f"--image={Path(p).resolve()}" for p in ctx.images]
    cmd += ["-o", str(last_msg), "-"]  # "-"：从 stdin 读提示词

    if ctx.dry_run:
        return run_dir, None, {"dry_run": cmd, "stdin": prompt}

    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=ctx.timeout, cwd=run_dir)
    except subprocess.TimeoutExpired:
        raise BackendError(f"codex 超时（{ctx.timeout} 秒）")
    (run_dir / "codex_stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
    (run_dir / "codex_stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    reply = last_msg.read_text(encoding="utf-8", errors="replace").strip() if last_msg.exists() else ""
    if proc.returncode != 0 and not reply:
        tail = (proc.stderr or proc.stdout or "").strip()[-800:]
        raise BackendError(f"codex 退出码 {proc.returncode}: {tail}")
    return run_dir, reply, None


def run_image(cfg, ctx):
    prompt = cfg.get("prompt_template", "{prompt}").format(prompt=ctx.prompt)
    if ctx.images:
        prompt += "\n\n" + cfg.get("reference_note", "Use the attached image(s) as reference.")
    if ctx.transparent:
        prompt += "\n\n" + cfg.get("transparent_suffix", "Use a TRANSPARENT background.")

    start = time.time() - 1
    run_dir, reply, dry = _run(cfg, ctx, prompt, cfg.get("sandbox", "workspace-write"), "codex_image")
    if dry:
        return dry

    # Codex 沙盒在本机常报 apply deny-read ACLs、复制不出文件，所以直接去 generated_images 取新图
    gen_dir = Path(os.path.expanduser(cfg.get("generated_images_dir", DEFAULT_GEN_DIR)))
    found = images_newer_than(gen_dir, start) or images_newer_than(run_dir, start)
    if not found:
        raise BackendError(f"codex 未生成图片。回复：{reply[:500]}")
    return {"files": copy_outputs(ctx, found), "text": reply, "run_dir": str(run_dir)}


def run_text(cfg, ctx):
    prompt = cfg.get("prompt_template", "{prompt}").format(prompt=ctx.prompt)
    run_dir, reply, dry = _run(cfg, ctx, prompt, cfg.get("sandbox", "read-only"), "codex_text")
    if dry:
        return dry
    if not reply:
        raise BackendError("codex 没有返回内容")
    return {"text": reply, "run_dir": str(run_dir)}


BACKENDS = {
    "codex_image": (check, run_image),
    "codex_text": (check, run_text),
}
