"""build.bin（BILD v6）解析与写出。

布局（参照 Klei mod_tools 血统的 DstAnimTool build_compiler.py + 本地样本逐字段验证；
ktools skeletoncb 样本 alphaverts 234+486+438=1158 全对上）：
  'BILD', u32 version(=6)
  u32 total_symbols, u32 total_frames
  string build_name
  u32 num_materials; per: string texture_name
  per symbol:
    u32 symbol_hash          (klei_hash = 小写 SDBM)
    u32 num_frames
    per frame:
      u32 frame_num, u32 duration
      f32 bbox_x, bbox_y, bbox_w, bbox_h
      u32 alphavert_start, u32 alphavert_count
  u32 num_alphaverts
  per alphavert: 6×f32 (x,y,z,u,v,w)
  [若字典非空] u32 num_hashed_strings; per: u32 hash + string name   ← 尾部符号表
"""
import struct
try:
    from .klei_hash import klei_hash, resolve
except ImportError:
    from klei_hash import klei_hash, resolve


class Frame:
    __slots__ = ('num', 'duration', 'x', 'y', 'w', 'h', 'av_start', 'av_count')

    def __init__(self, num, duration, x, y, w, h, av_start=0, av_count=0):
        self.num, self.duration = num, duration
        self.x, self.y, self.w, self.h = x, y, w, h
        self.av_start, self.av_count = av_start, av_count


class Symbol:
    def __init__(self, name=None, namehash=None):
        self.name = name            # 可为 None（仅哈希）
        self.namehash = namehash if namehash is not None else (klei_hash(name) if name else 0)
        self.frames = []

    def resolved_name(self, extra=None):
        if self.name:
            return self.name
        return resolve(self.namehash)


class Build:
    def __init__(self):
        self.version = 6
        self.name = ''
        self.materials = []         # [texture_name]
        self.symbols = []           # [Symbol]
        self.alphaverts = []        # [(x,y,z,u,v,w)]
        self.hash_table = {}        # 尾部 hash->name 表（写出时保留/重建）
        self.hashtab_present = False  # 原文件是否显式写了（可能为 0 的）计数字段

    @classmethod
    def parse(cls, data: bytes) -> "Build":
        r = _R(data)
        if r.raw(4) != b'BILD':
            raise ValueError('not a build.bin (BILD)')
        b = cls()
        b.version = r.u32()
        total_symbols = r.u32()
        r.u32()  # total frames（冗余计数，校验用）
        b.name = r.string()
        for _ in range(r.u32()):
            b.materials.append(r.string())
        for _ in range(total_symbols):
            sym = Symbol(namehash=r.u32())
            for _ in range(r.u32()):
                num = r.u32(); dur = r.u32()
                x, y, w, h = r.f32(), r.f32(), r.f32(), r.f32()
                av_start, av_count = r.u32(), r.u32()
                sym.frames.append(Frame(num, dur, x, y, w, h, av_start, av_count))
            b.symbols.append(sym)
        for _ in range(r.u32()):
            b.alphaverts.append(struct.pack('<6f', *[r.f32() for _ in range(6)]))
        if r.left() >= 4:
            b.hashtab_present = True    # 计数字段存在（即使为 0）——Klei 导出器两种写法都有
            for _ in range(r.u32()):
                h = r.u32(); b.hash_table[h] = r.string()
        if r.left():
            raise ValueError(f'{r.left()} trailing bytes in build.bin')
        return b

    def to_bytes(self) -> bytes:
        out = bytearray()
        out += b'BILD' + struct.pack('<I', self.version)
        out += struct.pack('<I', len(self.symbols))
        out += struct.pack('<I', sum(len(s.frames) for s in self.symbols))
        _wstr(out, self.name)
        out += struct.pack('<I', len(self.materials))
        for m in self.materials:
            _wstr(out, m)
        for sym in self.symbols:
            out += struct.pack('<I', sym.namehash)
            out += struct.pack('<I', len(sym.frames))
            for f in sym.frames:
                out += struct.pack('<IIffffII', f.num, f.duration,
                                   f.x, f.y, f.w, f.h, f.av_start, f.av_count)
        out += struct.pack('<I', len(self.alphaverts))
        for v in self.alphaverts:
            out += v
        if self.hash_table or self.hashtab_present:
            out += struct.pack('<I', len(self.hash_table))
            for h, n in self.hash_table.items():
                out += struct.pack('<I', h)
                _wstr(out, n)
        return bytes(out)


class _R:
    def __init__(s, d): s.d = d; s.o = 0
    def u32(s):
        v = struct.unpack_from('<I', s.d, s.o)[0]; s.o += 4; return v
    def f32(s):
        v = struct.unpack_from('<f', s.d, s.o)[0]; s.o += 4; return v
    def raw(s, n):
        v = s.d[s.o:s.o + n]; s.o += n; return v
    def string(s):
        n = s.u32()
        return s.raw(n).decode('utf-8', 'replace')
    def left(s): return len(s.d) - s.o


def _wstr(out, s):
    b = s.encode('utf-8')
    out += struct.pack('<I', len(b)) + b
