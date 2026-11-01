"""Klei 哈希（SDBM 变体，小写归一）+ 内嵌反查字典。

还原自 DST Mod Tool.exe：
- 算法: h = c + (h<<6) + (h<<16) - h, 输入按 ord(c.lower()) —— 与 Klei mod_tools/DstAnimTool
  的 strhash 完全一致；对内嵌 12,522 条字典 100% 命中（见 tests）。
- 字典: 提取自二进制 0x355f659..0x35b23a3 的 "hash":"name" 数据段（serde 内嵌）。
"""
import json, os, gzip

_DICT = None
_DICT_PATH = os.path.join(os.path.dirname(__file__), "data", "klei_hash_dict.json.gz")


def klei_hash(name: str) -> int:
    """DST 资源符号哈希（不区分大小写）。"""
    h = 0
    for ch in name:
        v = ord(ch.lower())
        h = (v + (h << 6) + (h << 16) - h) & 0xFFFFFFFF
    return h


def load_dict() -> dict:
    """加载 DST Mod Tool 内嵌的 hash→name 反查字典（12,522 条）。"""
    global _DICT
    if _DICT is None:
        with gzip.open(_DICT_PATH, "rt", encoding="utf-8") as f:
            _DICT = {int(k): v for k, v in json.load(f).items()}
    return _DICT


def resolve(h: int, default=None) -> str:
    """把 32 位哈希还原为符号名；查不到返回 default。"""
    return load_dict().get(h & 0xFFFFFFFF, default)


def hash_all_matches(name: str):
    """debug: 返回字典中与 name 同哈希的所有条目。"""
    h = klei_hash(name)
    return (h, resolve(h))
