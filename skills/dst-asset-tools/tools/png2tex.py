#!/usr/bin/env python3
"""png2tex — PNG -> .tex（功能 7）。用法:
  python png2tex.py input.png [output.tex] [--fmt dxt5|rgb|rgba] [--no-mips] [--no-premultiply]
编码与 ktech 同算法（squish ClusterFit，默认预乘 alpha、生成 mip 链、bottom-up 存储）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'code'))
import ktex
from pngio import read_png

FMT = {'dxt5': ktex.FORMAT_DXT5, 'rgb': ktex.FORMAT_RGB888, 'rgba': ktex.FORMAT_RGBA8888}


def main():
    args = sys.argv[1:]
    fmt = ktex.FORMAT_DXT5
    mips, premul = True, True
    pos = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--fmt':
            i += 1
            fmt = FMT[args[i]]
        elif a == '--no-mips':
            mips = False
        elif a == '--no-premultiply':
            premul = False
        else:
            pos.append(a)
        i += 1
    src = Path(pos[0])
    dst = Path(pos[1]) if len(pos) > 1 else src.with_suffix('.tex')
    w, h, rgba = read_png(str(src))
    t = ktex.KTex.from_rgba(rgba, w, h, fmt=fmt, mips=mips, premultiplied=premul)
    dst.write_bytes(t.to_bytes())
    print(f'{src.name} -> {dst.name}  {w}x{h} mips={len(t.mips)} premul={premul}')


if __name__ == '__main__':
    main()
