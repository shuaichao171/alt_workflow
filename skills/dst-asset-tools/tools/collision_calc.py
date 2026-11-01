#!/usr/bin/env python3
"""collision_calc — 动画帧碰撞盒重算（功能 5，C' 确定性内核）。用法:
  python collision_calc.py anim.bin build.bin [--apply] [--anim NAME]
公式（与应用纯几何内核逐位一致）：每帧 = 全部元素（列向量约定
X=a*x+c*y+tx, Y=b*x+d*y+ty）变换其符号帧顶点界后的并集，取 center/size。
"""
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'code'))
import anim_bin
import build_bin


def calc(ab, bd):
    by_hash = {s.namehash: s for s in bd.symbols}
    out = {}
    for anim in ab.anims:
        quads = []
        for fr in anim.frames:
            X0 = Y0 = X1 = Y1 = None
            for el in fr.elements:
                sy = by_hash.get(el.symbol_hash)
                if sy is None or not sy.frames:
                    continue
                f = sy.frames[min(el.frame, len(sy.frames) - 1)]
                vs = [struct.unpack('<6f', v) for v in bd.alphaverts[f.av_start: f.av_start + f.av_count]]
                if not vs:
                    continue
                x0 = min(v[0] for v in vs); x1 = max(v[0] for v in vs)
                y0 = min(v[1] for v in vs); y1 = max(v[1] for v in vs)
                pts = [(el.a * x + el.c * y + el.tx, el.b * x + el.d * y + el.ty)
                       for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                X0 = min(xs) if X0 is None else min(X0, min(xs))
                X1 = max(xs) if X1 is None else max(X1, max(xs))
                Y0 = min(ys) if Y0 is None else min(Y0, min(ys))
                Y1 = max(ys) if Y1 is None else max(Y1, max(ys))
            quads.append(((X0 + X1) / 2, (Y0 + Y1) / 2, X1 - X0, Y1 - Y0) if X0 is not None else None)
        out[anim.name] = quads
    return out


def main():
    args = sys.argv[1:]
    apply_ = '--apply' in args
    name = args[args.index('--anim') + 1] if '--anim' in args else None
    files = [a for a in args if not a.startswith('--') and
             (args.index(a) == 0 or args[args.index(a) - 1] not in ('--anim',))]
    ab = anim_bin.AnimBin.parse(Path(files[0]).read_bytes())
    bd = build_bin.Build.parse(Path(files[1]).read_bytes())
    res = calc(ab, bd)
    if apply_:
        n = 0
        for anim in ab.anims:
            if name and anim_bin.split_facing(anim.name)[0] != name:
                continue
            for fr, q in zip(anim.frames, res[anim.name]):
                if q:
                    fr.x, fr.y, fr.w, fr.h = q
                    n += 1
        Path(files[0]).write_bytes(ab.to_bytes())
        print(f'applied {n} quads -> {files[0]}')
    else:
        print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
