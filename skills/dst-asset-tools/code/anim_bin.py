"""anim.bin（ANIM v4）解析与写出。

布局（参照 DstAnimTool anim_compiler.py + 本地样本验证：
bank 头 "animation"+facing 0xff+root hash 0x7f731acc+sdbm("skeletoncb") 全对上）：
  'ANIM', u32 version(=4)
  u32 total_element_refs, u32 total_frames, u32 total_events, u32 num_anims
  per anim:
    string anim_name（方向后缀已剥离）
    u8 facing 位掩码: bit0=RIGHT bit1=UP bit2=LEFT bit3=DOWN
                      bit4=UPRIGHT bit5=UPLEFT bit6=DOWNRIGHT bit7=DOWNLEFT
    u32 root_symbol_hash
    f32 frame_rate
    u32 num_frames
    per frame:
      4×f32 bbox(x,y,w,h)
      u32 num_events; per: u32 event_hash
      u32 num_elements; per element:
        u32 symbol_hash, u32 symbol_frame, u32 layer_hash
        7×f32 m_a,b,c,d,tx,ty,z   (z = (idx/num)*10-5，Klei 导出器约定)
  [若字典非空] u32 num_hashed_strings; per: u32 hash + string name

DST Mod Tool 扩展：非通用 Facing 组合用 8 位二进制后缀（changelog 1.1.x），如 "_11010000"。
"""
import struct, re
try:
    from .klei_hash import klei_hash, resolve
except ImportError:
    from klei_hash import klei_hash, resolve

FACING_RIGHT = 1 << 0
FACING_UP = 1 << 1
FACING_LEFT = 1 << 2
FACING_DOWN = 1 << 3
FACING_UPRIGHT = 1 << 4
FACING_UPLEFT = 1 << 5
FACING_DOWNRIGHT = 1 << 6
FACING_DOWNLEFT = 1 << 7

_SUFFIX_FACINGS = [
    ("_up", FACING_UP), ("_down", FACING_DOWN), ("_side", FACING_LEFT | FACING_RIGHT),
    ("_left", FACING_LEFT), ("_right", FACING_RIGHT),
    ("_upside", FACING_UPLEFT | FACING_UPRIGHT),
    ("_downside", FACING_DOWNLEFT | FACING_DOWNRIGHT),
    ("_upleft", FACING_UPLEFT), ("_upright", FACING_UPRIGHT),
    ("_downleft", FACING_DOWNLEFT), ("_downright", FACING_DOWNRIGHT),
    ("_45s", FACING_UPLEFT | FACING_UPRIGHT | FACING_DOWNLEFT | FACING_DOWNRIGHT),
    ("_90s", FACING_UP | FACING_DOWN | FACING_LEFT | FACING_RIGHT),
]


# Facing 后缀语料事实（第 11 轮，全 DST+DS 语料 24,133 动画名验证）：
# 官方游戏数据的动画名 NEVER 携带 facing 后缀（0/24,133）——facing 恒由文件内字节承载；
# 后缀（命名+8 位二进制）是 DST Mod Tool 自有的 SCML 打包约定，仅在工具链内生效。
# 同一 bank 中同名动画可存多份不同 facing 字节（如 'idle_on' 同时存 0x8/0x5/0x2/0x30/0xc0），
# 即“同名多 facing 变体”机制（运行时按方向选择变体）；dst_re 逐 Anim 保留各自 facing。
# 8 位二进制后缀位序：应用侧序列化表在 sub_14191b640（256 项 mask→后缀 预计算表），
# 嵌入文档保证 binary 后缀 round-trip；本实现 MSB-first 为文档化约定（与 facing_suffix 互逆）。

def split_facing(anim_name: str):
    """名称 -> (基名, facing 掩码)。通用后缀表 + 8 位二进制后缀（DST Mod Tool 扩展）。"""
    for suf, mask in _SUFFIX_FACINGS:
        if anim_name.endswith(suf):
            return anim_name[:-len(suf)], mask
    m = re.search(r'_([01]{8})\Z', anim_name)
    if m:
        # 8 位二进制后缀，MSB 在前（与 facing_suffix 写出一致；首位=bit7）
        return anim_name[:-9], int(m.group(1), 2)
    return anim_name, 0xFF & (FACING_UP | FACING_DOWN | FACING_LEFT | FACING_RIGHT |
                              FACING_UPLEFT | FACING_UPRIGHT | FACING_DOWNLEFT | FACING_DOWNRIGHT)


def facing_suffix(base: str, mask: int) -> str:
    """(基名, 掩码) -> 带后缀名称；通用组合用助记后缀，其它用 8 位二进制。"""
    for suf, m in _SUFFIX_FACINGS:
        if mask == m:
            return base + suf
    return base + '_' + ''.join('1' if mask & (1 << b) else '0' for b in range(7, -1, -1))


class Element:
    __slots__ = ('symbol_hash', 'frame', 'layer_hash', 'a', 'b', 'c', 'd', 'tx', 'ty', 'z')

    def __init__(self, symbol_hash, frame, layer_hash, a=1, b=0, c=0, d=1, tx=0, ty=0, z=0):
        self.symbol_hash, self.frame, self.layer_hash = symbol_hash, frame, layer_hash
        self.a, self.b, self.c, self.d, self.tx, self.ty, self.z = a, b, c, d, tx, ty, z


class AnimFrame:
    def __init__(self, x=0, y=0, w=0, h=0):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.events = []      # [event_hash]
        self.elements = []    # [Element]


class Anim:
    def __init__(self, name, facing=0xFF, root_hash=0, frame_rate=30.0):
        self.name, self.facing, self.root_hash, self.frame_rate = name, facing, root_hash, frame_rate
        self.frames = []


class AnimBin:
    def __init__(self):
        self.version = 4
        self.anims = []
        self.hash_table = {}

    @classmethod
    def parse(cls, data: bytes) -> "AnimBin":
        r = _R(data)
        if r.raw(4) != b'ANIM':
            raise ValueError('not an anim.bin (ANIM)')
        a = cls()
        a.version = r.u32()
        r.u32(); r.u32(); r.u32()   # totals（冗余）
        for _ in range(r.u32()):
            name = r.string()
            facing = r.raw(1)[0]
            root = r.u32()
            rate = r.f32()
            anim = Anim(name, facing, root, rate)
            for _ in range(r.u32()):
                fr = AnimFrame(*[r.f32() for _ in range(4)])
                for _ in range(r.u32()):
                    fr.events.append(r.u32())
                for _ in range(r.u32()):
                    sh = r.u32(); sf = r.u32(); lh = r.u32()
                    m = [r.f32() for _ in range(7)]
                    fr.elements.append(Element(sh, sf, lh, *m))
                anim.frames.append(fr)
            a.anims.append(anim)
        if r.left() >= 4:
            for _ in range(r.u32()):
                h = r.u32(); a.hash_table[h] = r.string()
        if r.left():
            raise ValueError(f'{r.left()} trailing bytes in anim.bin')
        return a

    def to_bytes(self) -> bytes:
        out = bytearray()
        out += b'ANIM' + struct.pack('<I', self.version)
        out += struct.pack('<IIII',
                           sum(len(f.elements) for a in self.anims for f in a.frames),
                           sum(len(a.frames) for a in self.anims),
                           sum(len(f.events) for a in self.anims for f in a.frames),
                           len(self.anims))
        for anim in self.anims:
            _wstr(out, anim.name)
            out += struct.pack('<B', anim.facing & 0xFF)
            out += struct.pack('<I', anim.root_hash)
            out += struct.pack('<fI', anim.frame_rate, len(anim.frames))
            for f in anim.frames:
                out += struct.pack('<ffff', f.x, f.y, f.w, f.h)
                out += struct.pack('<I', len(f.events))
                for e in f.events:
                    out += struct.pack('<I', e)
                out += struct.pack('<I', len(f.elements))
                for el in f.elements:
                    out += struct.pack('<IIIfffffff', el.symbol_hash, el.frame, el.layer_hash,
                                       el.a, el.b, el.c, el.d, el.tx, el.ty, el.z)
        if self.hash_table:
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
        n = s.u32(); return s.raw(n).decode('utf-8', 'replace')
    def left(s): return len(s.d) - s.o


def _wstr(out, s):
    b = s.encode('utf-8')
    out += struct.pack('<I', len(b)) + b
