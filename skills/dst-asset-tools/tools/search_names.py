#!/usr/bin/env python3
"""search_names — 从游戏 scripts.zip / .po 提取资源名（功能 16）。用法:
  python search_names.py scripts.zip [OUT.json]
提取 prefab/build/bank/skin 名（与应用内嵌正则一致，2130 prefab / 2046 build /
1399 bank 量级），供移植时资源定位与改名核对。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'code'))
import search_index


def main():
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix('.names.json')
    if src.suffix == '.zip':
        res = search_index.scan_scripts_zip(str(src))
    else:
        res = search_index.scan_po(str(src))
    for k, v in sorted(res.items()):
        print(f'{k}: {len(v)}')
    res = {k: sorted(v) if isinstance(v, (set, frozenset)) else v for k, v in res.items()}
    Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'-> {out}')


if __name__ == '__main__':
    main()
