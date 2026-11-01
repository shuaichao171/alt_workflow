#!/usr/bin/env python3
"""tex2png — .tex -> PNG（功能 6）。用法:
  python tex2png.py input.tex [output.png] [--mip N] [--raw]
默认解码 mip0 并按 Klei 约定反预乘（ktech PNG 输出等价）；--raw 保留存储像素。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'code'))
import ktex
from pngio import write_png


def main():
    args = sys.argv[1:]
    mip = 0
    raw = False
    pos = []
    for a in args:
        if a == '--mip':
            mip = int(args[args.index('--mip') + 1])
        elif a == '--raw':
            raw = True
        elif not a.startswith('-') or args.index(a) != args.index('--mip') + 1:
            pos.append(a)
    src = Path(pos[0])
    dst = Path(pos[1]) if len(pos) > 1 else src.with_suffix('.png')
    t = ktex.KTex.parse(src.read_bytes())
    w, h = t.mips[mip][0], t.mips[mip][1]
    rgba = t.decode_mip(mip, unpremultiply_alpha=None if raw else 'auto')
    write_png(str(dst), w, h, rgba)
    print(f'{src.name} -> {dst.name}  {w}x{h} fmt={t.fmt} mips={len(t.mips)}')


if __name__ == '__main__':
    main()
