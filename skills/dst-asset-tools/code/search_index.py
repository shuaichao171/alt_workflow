"""资源搜索索引 —— 正则与扫描路径提取自 DST Mod Tool.exe 内嵌 dst-search 模块。

正则源：二进制 0x33f9c00 区域（dst-search/src/prefab.rs 的 regex 字面量）；
路径源：0x3038c00 区域（游戏目录/工坊/DLC 判定字符串）。
"""
import re, zipfile

PATTERNS = {
    "po_msgctxt_names": re.compile(rb'msgctxt\s+"STRINGS\.NAMES\.(.+)"'),
    "po_msgstr": re.compile(rb'msgstr\s+"(.+)"'),
    "prefab_table": re.compile(rb'[^\s]+\s*=\s*\{(.+)\}'),
    "prefab_assign": re.compile(rb'prefab\s*=\s*"([^"]+)"'),
    "build_assign": re.compile(rb'build\s*=\s*"([^"]+)"'),
    "bank_assign": re.compile(rb'bank\s*=\s*"([^"]+)"'),
    "create_prefab_skin": re.compile(rb'CreatePrefabSkin\("([^"]+)"'),
    "base_prefab": re.compile(rb'base_prefab\s*=\s*"([^"]+)"'),
}

SCAN_PATHS = {
    "dst_game_bundles": ["data/databundles/scripts.zip", "data/databundles/images.zip"],
    "ds_dlc": ["data/DLC0001", "data/DLC0002", "data/DLC0003"],
    "workshop_dst": "workshop/content/322330",
    "dst_content": "content/322330",
    "lang_files": ["scripts/languages/chinese_s.po",
                   "scripts/prefabs/skinprefabs.lua",
                   "scripts/skin_affinity_info.lua",
                   "scripts/screens/redux/scrapbookdata.lua"],
}


def scan_scripts_zip(zip_path):
    """扫描 scripts.zip，返回 {kind: set(names)}：prefab/build/bank/skin 提取。"""
    found = {"prefab": set(), "build": set(), "bank": set(), "skin": set(),
             "base_prefab": set()}
    with zipfile.ZipFile(zip_path) as zf:
        for n in zf.namelist():
            if not n.endswith('.lua'):
                continue
            try:
                src = zf.read(n)
            except Exception:
                continue
            for m in PATTERNS["prefab_assign"].finditer(src):
                found["prefab"].add(m.group(1).decode('utf-8', 'replace'))
            for m in PATTERNS["build_assign"].finditer(src):
                found["build"].add(m.group(1).decode('utf-8', 'replace'))
            for m in PATTERNS["bank_assign"].finditer(src):
                found["bank"].add(m.group(1).decode('utf-8', 'replace'))
            for m in PATTERNS["create_prefab_skin"].finditer(src):
                found["skin"].add(m.group(1).decode('utf-8', 'replace'))
            for m in PATTERNS["base_prefab"].finditer(src):
                found["base_prefab"].add(m.group(1).decode('utf-8', 'replace'))
    return found


def scan_po(path):
    """从 .po 语言文件提取 中文名 <-> 内部名 映射。"""
    out = []
    data = open(path, 'rb').read()
    ctxs = list(PATTERNS["po_msgctxt_names"].finditer(data))
    for i, m in enumerate(ctxs):
        seg_end = ctxs[i + 1].start() if i + 1 < len(ctxs) else len(data)
        seg = data[m.end():seg_end]
        t = PATTERNS["po_msgstr"].search(seg)
        if t:
            out.append((m.group(1).decode('utf-8', 'replace'),
                        t.group(1).decode('utf-8', 'replace')))
    return out
