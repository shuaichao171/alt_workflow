"""子代理后端共用的工具函数：路径、密钥、HTTP、图片检查。仅依赖标准库（Pillow 可选）。"""
import base64
import datetime
import json
import mimetypes
import os
import re
import shutil
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# 工作流根目录：scripts/backends/common.py 往上两级
ROOT = Path(__file__).resolve().parents[2]
PRIVATE_DIR = ROOT / "private"
OUTPUT_DIR = ROOT / "output"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


class BackendError(Exception):
    """后端调用失败；runner 捕获后尝试下一个后端。"""


@dataclass
class Context:
    agent: str
    prompt: str
    images: list = field(default_factory=list)
    out_dir: Path = OUTPUT_DIR
    transparent: bool = False
    timeout: int = 600
    dry_run: bool = False
    secrets: dict = field(default_factory=dict)

    def run_dir(self, backend):
        """每次调用一个独立的临时工作目录，放 last_message.txt 等中间文件。"""
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        d = OUTPUT_DIR / "_runs" / f"{stamp}_{self.agent}_{backend}"
        d.mkdir(parents=True, exist_ok=True)
        return d


# ---------- 密钥 ----------

def load_secrets():
    path = PRIVATE_DIR / "secrets.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return not isinstance(v, str) or not v.strip() or v.strip().startswith("<")


def get_secret(ctx, name):
    """读取 private/secrets.json 中的一组配置；环境变量 ALTWF_<NAME>_<KEY> 优先。占位值视为未配置。"""
    if not name:
        return {}
    entry = dict(ctx.secrets.get(name) or {})
    prefix = "ALTWF_" + re.sub(r"\W", "_", name).upper()
    for key in ("base_url", "api_key", "model"):
        v = os.environ.get(f"{prefix}_{key.upper()}")
        if v:
            entry[key] = v
    return {k: v for k, v in entry.items() if not _is_placeholder(v)}


def require_secret(ctx, name, keys=("base_url", "api_key")):
    entry = get_secret(ctx, name)
    missing = [k for k in keys if k not in entry]
    if missing:
        return None, f"private/secrets.json 中 `{name}` 缺少 {', '.join(missing)}"
    return entry, None


# ---------- HTTP ----------

def api_base(url):
    url = url.rstrip("/")
    return url if url.endswith("/v1") else url + "/v1"


def http_json(url, api_key, body=None, content_type="application/json", timeout=600):
    req = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET")
    req.add_header("Authorization", f"Bearer {api_key}")
    if content_type and body is not None:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise BackendError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:800]}")
    except urllib.error.URLError as e:
        raise BackendError(f"网络请求失败: {e.reason}")


def build_multipart(fields, files):
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, path in files:
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        head = (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                f'filename="{os.path.basename(path)}"\r\nContent-Type: {mime}\r\n\r\n').encode()
        parts.append(head + Path(path).read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def data_uri(path):
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


# ---------- 文件 ----------

def slugify(text, limit=40):
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", text).strip("_")
    return s[:limit] or "image"


def output_name(ctx, index, total, ext):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{index + 1}" if total > 1 else ""
    ctx.out_dir.mkdir(parents=True, exist_ok=True)
    return ctx.out_dir / f"{stamp}_{slugify(ctx.prompt)}{suffix}{ext}"


def copy_outputs(ctx, sources):
    paths = []
    for i, src in enumerate(sources):
        dst = output_name(ctx, i, len(sources), Path(src).suffix.lower())
        shutil.copy2(src, dst)
        paths.append(str(dst))
    return paths


def images_newer_than(folder, since):
    folder = Path(folder)
    if not folder.exists():
        return []
    found = [p for p in folder.rglob("*") if p.suffix.lower() in IMAGE_EXTS and p.stat().st_mtime >= since]
    return sorted(found, key=lambda p: p.stat().st_mtime)


# ---------- 图片后处理 ----------

def check_image(path):
    """返回图片基本信息；透明图额外检查四角 alpha。没有 Pillow 时只返回路径。"""
    try:
        from PIL import Image
    except ImportError:
        return {"file": path, "note": "未安装 Pillow，跳过检查"}
    with Image.open(path) as im:
        info = {"file": path, "mode": im.mode, "size": list(im.size)}
        if im.mode == "RGBA":
            w, h = im.size
            alpha = im.getchannel("A")
            info["corner_alpha"] = [alpha.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
            info["max_alpha"] = alpha.getextrema()[1]
    return info


def fix_alpha(path, threshold=250):
    """把 alpha ≥ threshold 的像素改为 255（Codex 出图物体 alpha 最高只有 254）。"""
    from PIL import Image
    with Image.open(path) as im:
        if im.mode != "RGBA":
            return False
        r, g, b, a = im.split()
        a = a.point(lambda v: 255 if v >= threshold else v)
        Image.merge("RGBA", (r, g, b, a)).save(path)
    return True
