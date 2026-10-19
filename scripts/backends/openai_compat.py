"""OpenAI 兼容接口后端，密钥来自 private/secrets.json（agent.json 里用 "secret" 指定条目名）。

- openai_images：/images/generations 或 /images/edits（附参考图时）。
- openai_chat  ：/chat/completions，图片以 data URI 传入（识图、问答）。
"""
import base64
import json
import urllib.error
import urllib.request
from pathlib import Path

from .common import (BackendError, api_base, build_multipart, data_uri, http_json, output_name,
                     require_secret)


def check(cfg, ctx):
    _, err = require_secret(ctx, cfg.get("secret"))
    return err


def _conf(cfg, ctx):
    entry, err = require_secret(ctx, cfg.get("secret"))
    if err:
        raise BackendError(err)
    model = entry.get("model") or cfg.get("model")
    if not model:
        raise BackendError("未指定模型（agent.json 的 model 或 secrets 的 model）")
    return api_base(entry["base_url"]), entry["api_key"], model


def run_images(cfg, ctx):
    base, key, model = _conf(cfg, ctx)
    params = {"model": model, "prompt": ctx.prompt, "n": cfg.get("n", 1)}
    for k in ("size", "quality", "output_format"):
        if cfg.get(k) and cfg[k] != "auto":
            params[k] = cfg[k]
    if ctx.transparent:
        params["background"] = "transparent"

    if ctx.images:
        field = "image[]" if len(ctx.images) > 1 else "image"
        url = f"{base}/images/edits"
        body, ctype = build_multipart({k: str(v) for k, v in params.items()}, [(field, p) for p in ctx.images])
    else:
        url = f"{base}/images/generations"
        body, ctype = json.dumps(params).encode(), "application/json"
    if ctx.dry_run:
        return {"dry_run": {"url": url, "params": params, "images": ctx.images}}

    data = http_json(url, key, body, ctype, ctx.timeout)
    items = data.get("data") or []
    ext = "." + params.get("output_format", "png").replace("jpeg", "jpg")
    files, revised = [], None
    for i, item in enumerate(items):
        if item.get("b64_json"):
            raw = base64.b64decode(item["b64_json"])
        elif item.get("url"):
            try:
                with urllib.request.urlopen(item["url"], timeout=ctx.timeout) as r:
                    raw = r.read()
            except (urllib.error.URLError, OSError, ValueError) as e:
                raise BackendError(f"下载生成图片失败: {e}")
        else:
            continue
        path = output_name(ctx, i, len(items), ext)
        Path(path).write_bytes(raw)
        files.append(str(path))
        revised = revised or item.get("revised_prompt")
    if not files:
        raise BackendError(f"返回中没有图片: {json.dumps(data, ensure_ascii=False)[:500]}")
    return {"files": files, "text": revised}


def run_chat(cfg, ctx):
    base, key, model = _conf(cfg, ctx)
    content = [{"type": "text", "text": cfg.get("prompt_template", "{prompt}").format(prompt=ctx.prompt)}]
    content += [{"type": "image_url", "image_url": {"url": data_uri(p)}} for p in ctx.images]
    payload = {"model": model, "messages": [{"role": "user", "content": content}]}
    if cfg.get("system"):
        payload["messages"].insert(0, {"role": "system", "content": cfg["system"]})
    if ctx.dry_run:
        return {"dry_run": {"url": f"{base}/chat/completions", "model": model, "images": ctx.images}}

    data = http_json(f"{base}/chat/completions", key, json.dumps(payload).encode(), timeout=ctx.timeout)
    try:
        return {"text": data["choices"][0]["message"]["content"]}
    except (KeyError, IndexError):
        raise BackendError(f"返回格式异常: {json.dumps(data, ensure_ascii=False)[:500]}")


BACKENDS = {
    "openai_images": (check, run_images),
    "openai_chat": (check, run_chat),
}
