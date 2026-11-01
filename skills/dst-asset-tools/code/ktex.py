"""KTEX (.tex) 容器编解码 —— DST 贴图格式。

spec u32 位域（ktech 编码矩阵 + DST 官方资源交叉验证，并由 IDA 反编译
DST Mod Tool 的 spec 解码函数 sub_141B30F60 逐字段确认）：
  [31:20] = 平台/高位标志（12 位，PC 文件为 0xFFC/0xFFD）
  [19:18] = 3（PC 文件常量，应用另读）
  [17:13] = mip 计数（5 位；mips = spec>>13 & 0x1F）
  [12:9]  = 纹理类型（1d=0, 2d=1, cube=2, 3d=3；应用读 4 位并封顶 4=未知）
  [8:4]   = 像素格式（5 位！）：0=DXT1 1=DXT3 2=DXT5 4=RGBA8888 5=RGB888
             0x12=ETC2 0x18=ASTC 8x8（后两个为 DST Mod Tool 扩展，反编译确认；
             超出 0xF 故 bit8 会被置位）
  [3:0]   = 0（PS3/Xbox 大端标记 0xA/0xB/0xC 由应用识别）
mip 表（头部 8 字节后，每项 10 字节）：{ u16 w, u16 h, u16 stride, u32 len }
数据：最大层在前逐层紧随；行序自底向上（解码需垂直翻转）。
"""
import struct
try:
    from . import dxt, etc2, astc
except ImportError:
    import dxt, etc2, astc
try:
    from . import squish_port
except ImportError:
    import squish_port

MAGIC = b'KTEX'
FORMAT_DXT1 = 0
FORMAT_DXT3 = 1
FORMAT_DXT5 = 2
FORMAT_RGBA8888 = 4
FORMAT_RGB888 = 5
FORMAT_ETC2 = 0x12      # DST Mod Tool 扩展（反编译 sub_141B30F60 case 0x12）
FORMAT_ASTC_8X8 = 0x18  # DST Mod Tool 扩展（反编译 case 0x18；内嵌 astcenc 编解码）
FORMAT_NAMES = {0: 'DXT1', 1: 'DXT3', 2: 'DXT5', 4: 'RGBA8888', 5: 'RGB888',
                FORMAT_ETC2: 'ETC2', FORMAT_ASTC_8X8: 'ASTC 8x8'}
TYPE_NAMES = {0: '1d', 1: '2d', 2: 'cube', 3: '3d'}

FORMAT_UNCOMPRESSED = {FORMAT_RGBA8888: 4, FORMAT_RGB888: 3}
# 块尺寸（宽,高,每块字节数）：用于校验 stride=len 推导（app 扩展格式无游戏样本，
# 值按标准 ETC2 RGB8（4x4 块 8B）与 ASTC 8x8（8x8 块 16B）标注，待样本验证）
FORMAT_BLOCK = {FORMAT_DXT1: (4, 4, 8), FORMAT_DXT3: (4, 4, 16), FORMAT_DXT5: (4, 4, 16),
                FORMAT_ETC2: (4, 4, 8), FORMAT_ASTC_8X8: (8, 8, 16)}


def _block_bytes(fmt):
    return {FORMAT_DXT1: 8, FORMAT_DXT3: 16, FORMAT_DXT5: 16}[fmt]


class KTex:
    def __init__(self):
        self.fmt = FORMAT_DXT5
        self.tex_type = 1          # [11:9] 2d
        self.premultiplied = False # 数据层语义标记（不写入 spec，仅供解码路径选择）
        self.mips = []             # [(w,h,stride,bytes), ...] 最大层在前

    # ---------- 解析 ----------
    @classmethod
    def parse(cls, data: bytes) -> "KTex":
        if data[:4] != MAGIC:
            raise ValueError("not a KTEX file")
        spec = struct.unpack_from('<I', data, 4)[0]
        t = cls()
        t.fmt = (spec >> 4) & 0x1F
        t.tex_type = (spec >> 9) & 0xF
        t.premultiplied = t.fmt in (FORMAT_DXT3, FORMAT_DXT5)
        n = (spec >> 13) & 0x1F
        if n == 0:   # mips 字段为 0 且无层数信息：按逐层二分推导（1 层起）
            w, h = struct.unpack_from('<HH', data, 8)
            n = 1
            ww, hh = w, h
            while ww > 1 or hh > 1:
                ww, hh = max(1, ww // 2), max(1, hh // 2)
                n += 1
        o = 8
        for _ in range(n):
            w, h, stride, lo, hi = struct.unpack_from('<HHHHH', data, o)
            t.mips.append([w, h, stride, (hi << 16) | lo, None])
            o += 10
        for m in t.mips:
            m[4] = data[o:o + m[3]]
            o += m[3]
        if o != len(data):
            raise ValueError(f"trailing bytes: file={len(data)} consumed={o}")
        return t

    @classmethod
    def parse_with_len(cls, data: bytes) -> "KTex":
        """支持 ktech 旧式 0xC000 标志：根据尺寸逐层推导 mip 数。"""
        if data[:4] != MAGIC:
            raise ValueError("not a KTEX file")
        spec = struct.unpack_from('<I', data, 4)[0]
        t = cls()
        t.fmt = (spec >> 4) & 0x1F
        t.tex_type = (spec >> 9) & 0xF
        t.premultiplied = t.fmt in (FORMAT_DXT3, FORMAT_DXT5)
        n = (spec >> 13) & 0x1F
        if n == 0:
            w, h = struct.unpack_from('<HH', data, 8)
            n = 1
            ww, hh = w, h
            while ww > 1 or hh > 1:
                ww, hh = max(1, ww // 2), max(1, hh // 2)
                n += 1
        o = 8
        for _ in range(n):
            w, h, stride, lo, hi = struct.unpack_from('<HHHHH', data, o)
            t.mips.append([w, h, stride, (hi << 16) | lo, None])
            o += 10
        for m in t.mips:
            m[4] = data[o:o + m[3]]
            o += m[3]
        if o != len(data):
            raise ValueError(f"trailing bytes: file={len(data)} consumed={o}")
        return t

    # ---------- 写出 ----------
    def to_bytes(self) -> bytes:
        n = len(self.mips)
        spec = 0xFFF << 20
        spec |= 0b110 << 17
        spec |= (n & 0x1F) << 13          # mips 5 位 [17:13]
        spec |= (self.tex_type & 0xF) << 9
        spec |= (self.fmt & 0x1F) << 4
        out = bytearray(MAGIC + struct.pack('<I', spec))
        for w, h, stride, ln, payload in self.mips:
            out += struct.pack('<HHHHH', w, h, stride, ln & 0xFFFF, ln >> 16)
        for m in self.mips:
            out += m[4]
        return bytes(out)

    # ---------- 解码 ----------
    def decode_mip(self, index=0, unpremultiply_alpha=None):
        """解码指定 mip 为 RGBA（已翻转为正常行序）。
        unpremultiply_alpha: None=按 self.premultiplied，True/False 强制。"""
        w, h, stride, ln, payload = self.mips[index]
        if self.fmt == FORMAT_DXT1:
            raw = dxt.decode_bc1(payload, w, h)
        elif self.fmt == FORMAT_DXT3:
            raw = dxt.decode_bc23(payload, w, h, 'bc2')
        elif self.fmt == FORMAT_DXT5:
            raw = dxt.decode_bc23(payload, w, h, 'bc3')
        elif self.fmt == FORMAT_RGBA8888:
            raw = bytes(payload[:w * h * 4])
        elif self.fmt == FORMAT_RGB888:
            raw = bytearray(w * h * 4)
            for i in range(w * h):
                raw[4 * i:4 * i + 4] = bytes(payload[3 * i:3 * i + 3]) + b'\xff'
            raw = bytes(raw)
        elif self.fmt == FORMAT_ETC2:
            raw = etc2.decode_etc2_rgb8(payload, w, h)
        elif self.fmt == FORMAT_ASTC_8X8:
            raw = astc.decode_astc(payload, w, h, 8, 8)
        else:
            raise ValueError(f"pixel decode for format {FORMAT_NAMES.get(self.fmt, hex(self.fmt))} not implemented "
                 "(app-extended ETC2/ASTC lack game samples; container/mip-table layer fully parsed)")
        up = self.premultiplied if unpremultiply_alpha is None else unpremultiply_alpha
        if up and self.fmt in (FORMAT_DXT3, FORMAT_DXT5):
            raw = dxt.unpremultiply(raw)
        # 底部向上行序 -> 翻转
        rows = [raw[y * w * 4:(y + 1) * w * 4] for y in range(h)]
        return b''.join(reversed(rows))

    # ---------- 从 RGBA 构建 ----------
    @classmethod
    def from_rgba(cls, rgba, w, h, fmt=FORMAT_DXT5, mips=True, premultiplied=False):
        t = cls()
        t.fmt = fmt
        t.premultiplied = premultiplied and fmt in (FORMAT_DXT3, FORMAT_DXT5)
        src = dxt.premultiply(rgba) if t.premultiplied else bytes(rgba)
        # 翻转为底部向上
        rows = [src[y * w * 4:(y + 1) * w * 4] for y in range(h)]
        src = b''.join(reversed(rows))
        ww, hh = w, h
        while True:
            if fmt in FORMAT_UNCOMPRESSED:
                bpp = FORMAT_UNCOMPRESSED[fmt]
                payload = src if (ww == w and hh == h) else _downsample_raw(src, w, h, ww, hh, bpp)
                ln = ww * hh * bpp
                stride = ww * bpp
            else:
                payload = src if (ww == w and hh == h) else _downsample_rgba(src, w, h, ww, hh)
                # squish ClusterFit/SingleColourFit（与 ktech/应用编码器同源，round-8 差分验证）
                payload = squish_port.compress_image(
                    payload, ww, hh,
                    'dxt1' if fmt == FORMAT_DXT1 else 'dxt3' if fmt == FORMAT_DXT3 else 'dxt5')
                stride = ((ww + 3) // 4) * _block_bytes(fmt)
                ln = ((ww + 3) // 4) * ((hh + 3) // 4) * _block_bytes(fmt)
            t.mips.append([ww, hh, stride, ln, payload])
            if not mips or (ww == 1 and hh == 1):
                break
            ww, hh = max(1, ww // 2), max(1, hh // 2)
        return t


def _downsample_rgba(src, w, h, tw, th):
    """box 下采样（生成 mip 链用；写路径为规范实现）。"""
    out = bytearray()
    for y in range(th):
        for x in range(tw):
            x0, y0 = x * w // tw, y * h // th
            x1, y1 = max(x0 + 1, (x + 1) * w // tw), max(y0 + 1, (y + 1) * h // th)
            rs = gs = bs = as_ = n = 0
            for yy in range(y0, min(y1, h)):
                for xx in range(x0, min(x1, w)):
                    i = (yy * w + xx) * 4
                    rs += src[i]; gs += src[i + 1]; bs += src[i + 2]; as_ += src[i + 3]; n += 1
            out += bytes((rs // n, gs // n, bs // n, as_ // n))
    return bytes(out)


def _downsample_raw(src, w, h, tw, th, bpp):
    out = bytearray()
    for y in range(th):
        for x in range(tw):
            x0, y0 = x * w // tw, y * h // th
            x1, y1 = max(x0 + 1, (x + 1) * w // tw), max(y0 + 1, (y + 1) * h // th)
            acc = [0] * bpp; n = 0
            for yy in range(y0, min(y1, h)):
                for xx in range(x0, min(x1, w)):
                    i = (yy * w + xx) * bpp
                    for c in range(bpp):
                        acc[c] += src[i + c]
                    n += 1
            out += bytes(a // n for a in acc)
    return bytes(out)
