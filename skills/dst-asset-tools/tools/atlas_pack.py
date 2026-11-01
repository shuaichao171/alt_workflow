#!/usr/bin/env python3
"""atlas_pack — 目录 PNG 打包成图集（功能 8，shelf 等价实现）。用法:
  python atlas_pack.py PNG目录 输出前缀 [--size 2048] [--gap 0]
生成 前缀.png（RGBA，bottom-up 存储）+ 前缀.regions.json（x,y,w,h,name）。
注意：应用的摆放启发式未从二进制恢复（终局结论），本实现为其等价 shelf 装箱。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'code'))
from atlas import ShelfPacker
from pngio import read_png, write_png


def main():
    args = sys.argv[1:]
    size = int(args[args.index('--size') + 1]) if '--size' in args else 2048
    gap = int(args[args.index('--gap') + 1]) if '--gap' in args else 0
    files = [a for a in args if not a.startswith('--') and
             (args.index(a) == 0 or args[args.index(a) - 1] not in ('--size', '--gap'))]
    src, prefix = Path(files[0]), Path(files[1])
    imgs = []
    for p in sorted(src.glob('*.png')):
        w, h, rgba = read_png(str(p))
        imgs.append((p.stem, w, h, rgba))
    packer = ShelfPacker(max_width=size, max_height=size, padding=gap)
    placed, (W, H) = packer.pack([(n, w, h) for n, w, h, _ in imgs])
    canvas = bytearray(W * H * 4)
    regions = []
    lookup = {n: (w, h, rgba) for n, w, h, rgba in imgs}
    for n, (x, y) in placed.items():
        w, h, rgba = lookup[n]
        for row in range(h):
            ty = H - 1 - y - row  # bottom-up：图集首行=画布最底行
            o = (ty * W + x) * 4
            canvas[o:o + w * 4] = rgba[row * w * 4:(row + 1) * w * 4]
        regions.append({'name': n, 'x': x, 'y': y, 'w': w, 'h': h})
    write_png(str(prefix) + '.png', W, H, bytes(canvas))
    Path(str(prefix) + '.regions.json').write_text(
        json.dumps({'width': W, 'height': H, 'regions': regions}, indent=1), encoding='utf-8')
    print(f'{len(placed)} sprites -> {prefix}.png {W}x{H}')


if __name__ == '__main__':
    main()
