#!/usr/bin/env python3
"""anim_edit — anim.bin / build.bin 改写（功能 1/2/3）。用法:
  python anim_edit.py FILE [--list]
  python anim_edit.py anim.bin --rename-anim OLD NEW [--framerate N]
  python anim_edit.py anim.bin --set-facing OLD MASK   (MASK 接受 0x.. / 十进制)
  python anim_edit.py build.bin --rename-symbol OLD NEW  (自动重算 SDBM 哈希)
  python anim_edit.py build.bin --rename-build NEW      (BILD 内 build 名；bank 名=zip 文件名)
FILE 为 .bin 或 .zip（zip 内同名成员被改写，其余成员字节保持不变）。
动画名携带 facing 后缀（如 walk_up）时按后缀系统处理；改写后与 Klei 导出器
字节布局一致（11,799 档案往返验证的编码器）。
"""
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'code'))
import anim_bin
import build_bin
from klei_hash import klei_hash


def load(path):
    path = Path(path)
    if path.suffix.lower() == '.zip':
        zf = zipfile.ZipFile(path)
        return zf, {n: zf.read(n) for n in zf.namelist()}
    # 单文件模式：自动携带同目录兄弟 bin（改名需联动两个文件）
    members = {path.name: path.read_bytes()}
    sib = 'build.bin' if path.name == 'anim.bin' else 'anim.bin'
    sp = path.with_name(sib)
    if sp.exists():
        members[sib] = sp.read_bytes()
    return None, members


def save(path, zf, members):
    path = Path(path)
    if zf:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            for n, d in members.items():
                z.writestr(n, d)
        path.write_bytes(buf.getvalue())
    else:
        for n, d in members.items():
            Path(path).with_name(n).write_bytes(d)


def main():
    args = sys.argv[1:]
    if len(args) < 2 or args[1] == '--list' and len(args) < 2:
        print(__doc__)
        return
    path = args[0]
    zf, members = load(path)
    an, bn = 'anim.bin', 'build.bin'
    ab = anim_bin.AnimBin.parse(members[an]) if an in members else None
    bd = build_bin.Build.parse(members[bn]) if bn in members else None
    if '--list' in args:
        if ab:
            for a in ab.anims:
                print(f'anim {a.name!r} facing=0x{a.facing:02X} rate={a.frame_rate} frames={len(a.frames)}')
        if bd:
            for s in bd.symbols:
                nm = s.name or bd.hash_table.get(s.namehash) or s.resolved_name()
                print(f'symbol {nm!r} hash=0x{s.namehash:08X} frames={len(s.frames)}')
        return
    i = 1
    while i < len(args):
        op = args[i]
        if op == '--rename-anim' and ab:
            old, new = args[i + 1], args[i + 2]
            hit = [a for a in ab.anims if anim_bin.split_facing(a.name)[0] == old]
            for a in hit:
                base, mask = anim_bin.split_facing(a.name)
                a.name = anim_bin.facing_suffix(new, mask) if mask != 0xFF else new
            print(f'renamed {len(hit)} anim(s) {old!r} -> {new!r}')
            members[an] = ab.to_bytes()
            i += 3
        elif op == '--framerate' and ab:
            rate = float(args[i + 1])
            for a in ab.anims:
                a.frame_rate = rate
            print(f'framerate -> {rate}')
            members[an] = ab.to_bytes()
            i += 2
        elif op == '--set-facing' and ab:
            name, mask = args[i + 1], int(args[i + 2], 0)
            for a in ab.anims:
                if anim_bin.split_facing(a.name)[0] == name or a.name == name:
                    a.facing = mask & 0xFF
                    print(f'{a.name!r} facing=0x{mask & 0xFF:02X}')
            members[an] = ab.to_bytes()
            i += 3
        elif op == '--rename-build' and bd:
            old, new = bd.name, args[i + 1]
            bd.name = new
            print(f'build name {old!r} -> {new!r} (BILD 名字无哈希，无联动)')
            members[bn] = bd.to_bytes()
            i += 2
        elif op == '--rename-symbol' and bd:
            old, new = args[i + 1], args[i + 2]
            old_hash = klei_hash(old)
            hit = [s for s in bd.symbols if s.name == old
                   or bd.hash_table.get(s.namehash) == old
                   or s.resolved_name() == old]
            for s in hit:
                s.name = new
                s.namehash = klei_hash(new)
            if hit and bd.hash_table:
                nt = {}
                for h, nm in bd.hash_table.items():
                    nt[klei_hash(new) if nm == old else h] = new if nm == old else nm
                bd.hash_table = nt  # 原地保序：no-op 改写字节恒等
            # 联动：anim.bin 元素的 symbol_hash 全部跟随新哈希，否则引用悬空
            n_el = 0
            if hit and ab:
                new_hash = klei_hash(new)
                for a in ab.anims:
                    for fr in a.frames:
                        for el in fr.elements:
                            if el.symbol_hash == old_hash:
                                el.symbol_hash = new_hash
                                n_el += 1
                # anim.bin 自身尾哈希表同步换键，否则 krane/应用无法解析元素名
                if old_hash in ab.hash_table:
                    nt = {}
                    for h, nm in ab.hash_table.items():
                        nt[new_hash if h == old_hash else h] = new if h == old_hash else nm
                    ab.hash_table = nt
            print(f'renamed {len(hit)} symbol(s) {old!r} -> {new!r} '
                  f'(hash 已重算; anim.bin 元素引用更新 {n_el} 处)')
            members[bn] = bd.to_bytes()
            if n_el:
                members[an] = ab.to_bytes()
            i += 3
        else:
            print(f'未知/不适用参数: {op}（该文件是否缺少对应 bin？）')
            i += 1
    save(path, zf, members)


if __name__ == '__main__':
    main()
