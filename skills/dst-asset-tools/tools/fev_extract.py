#!/usr/bin/env python3
"""fev_extract — .fev 声音工程解析（功能 11/12）。用法:
  python fev_extract.py input.fev [--json OUT.json] [--fdp OUT.fdp]
默认打印项目名/类别/事件组/波形引用摘要；--fdp 生成 FMOD Designer 工程骨架 XML。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'code'))
import fev


def main():
    args = sys.argv[1:]
    src = Path([a for a in args if not a.startswith('--')][0])
    summary = fev.extract(str(src))
    print(f'project: {summary.get("project")!r}')
    print(f'objects: {summary.get("objects")}  names: {len(summary.get("names", []))}')
    cats = summary.get('categories') or []
    print(f'categories: {", ".join(c[:24] for c in cats[:12])}{"..." if len(cats) > 12 else ""}')
    wfs = [n for n in summary.get('names', []) if n.endswith(('.wav', '.mp3', '.ogg'))]
    print(f'waveform refs: {len(wfs)}')
    for w in wfs[:8]:
        print(f'  {w}')
    if len(wfs) > 8:
        print(f'  ... (+{len(wfs) - 8})')
    if '--json' in args:
        out = args[args.index('--json') + 1]
        Path(out).write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'-> {out}')
    if '--fdp' in args:
        out = args[args.index('--fdp') + 1]
        xml = fev.to_fdp_skeleton(str(src))
        Path(out).write_text(xml, encoding='utf-8')
        print(f'-> {out}')


if __name__ == '__main__':
    main()
