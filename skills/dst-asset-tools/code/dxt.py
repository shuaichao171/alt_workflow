"""BC1(DXT1)/BC2(DXT3)/BC3(DXT5) 编解码 —— 像素级对齐 ktech（DST 官方工具链）行为。

验证依据：对 DST 官方贴图逐字节比对（cookbook 256×256 差 9/262,144，为 565 混合舍入余项）。
关键公式：
- 565→888 位复制扩展: 5bit->(v<<3)|(v>>2), 6bit->(v<<2)|(v>>4)
- BC3 alpha 8 值模式: v_k=( (8-k)a0 + k*a1 )/7  (k=0..7)
- BC3 alpha 6 值模式(a0<=a1): /5 插值 + {0,255}
- 预乘路径: RGB 存储为预乘 alpha（DST 常见），输出直通 alpha 时反预乘
"""
import struct


def _ex5(v): return (v << 3) | (v >> 2)
def _ex6(v): return (v << 2) | (v >> 4)


def _c565(c):
    return (_ex5((c >> 11) & 0x1F), _ex6((c >> 5) & 0x3F), _ex5(c & 0x1F))


def _color_pal(c0, c1):
    r0, r1 = _c565(c0), _c565(c1)
    if c0 > c1:
        return [r0, r1,
                ((2 * r0[0] + r1[0]) // 3, (2 * r0[1] + r1[1]) // 3, (2 * r0[2] + r1[2]) // 3),
                ((r0[0] + 2 * r1[0]) // 3, (r0[1] + 2 * r1[1]) // 3, (r0[2] + 2 * r1[2]) // 3)], True
    return [r0, r1,
            ((r0[0] + r1[0]) // 2, (r0[1] + r1[1]) // 2, (r0[2] + r1[2]) // 2),
            (0, 0, 0)], False


def _alpha_pal8(a0, a1):
    return [a0, a1, (6 * a0 + a1) // 7, (5 * a0 + 2 * a1) // 7, (4 * a0 + 3 * a1) // 7,
            (3 * a0 + 4 * a1) // 7, (2 * a0 + 5 * a1) // 7, (a0 + 6 * a1) // 7]


def _alpha_pal6(a0, a1):
    return [a0, a1, (4 * a0 + a1) // 5, (3 * a0 + 2 * a1) // 5,
            (2 * a0 + 3 * a1) // 5, (a0 + 4 * a1) // 5, 0, 255]


# ---- bcdec 约定（应用内置 bcdec_rs 0.2.0 的精确公式，第 7 轮从源码比对确认）----
# 与 squish/ktech 约定的差异：颜色混合在 5/6 位空间带舍入，alpha 用 +1 四舍五入。
def _raw565(c):
    return ((c >> 11) & 0x1F, (c >> 5) & 0x3F, c & 0x1F)


def _color_pal_bcdec(c0, c1):
    r0, g0, b0 = _raw565(c0)
    r1, g1, b1 = _raw565(c1)
    e = ((r0 * 527 + 23) >> 6, (g0 * 259 + 33) >> 6, (b0 * 527 + 23) >> 6), \
         ((r1 * 527 + 23) >> 6, (g1 * 259 + 33) >> 6, (b1 * 527 + 23) >> 6)
    if c0 > c1:
        m = (((2 * r0 + r1) * 351 + 61) >> 7, ((2 * g0 + g1) * 2763 + 1039) >> 11, ((2 * b0 + b1) * 351 + 61) >> 7)
        n = ((r0 + 2 * r1) * 351 + 61) >> 7, ((g0 + 2 * g1) * 2763 + 1039) >> 11, ((b0 + 2 * b1) * 351 + 61) >> 7
        return [e[0], e[1], m, n], True
    m = ((r0 + r1) * 1053 + 125) >> 8, ((g0 + g1) * 4145 + 1019) >> 11, ((b0 + b1) * 1053 + 125) >> 8
    return [e[0], e[1], m, (0, 0, 0)], False


def _alpha_pal8_bcdec(a0, a1):
    return [a0, a1, (6 * a0 + a1 + 1) // 7, (5 * a0 + 2 * a1 + 1) // 7, (4 * a0 + 3 * a1 + 1) // 7,
            (3 * a0 + 4 * a1 + 1) // 7, (2 * a0 + 5 * a1 + 1) // 7, (a0 + 6 * a1 + 1) // 7]


def _alpha_pal6_bcdec(a0, a1):
    return [a0, a1, (4 * a0 + a1 + 1) // 5, (3 * a0 + 2 * a1 + 1) // 5,
            (2 * a0 + 3 * a1 + 1) // 5, (a0 + 4 * a1 + 1) // 5, 0, 255]


def decode_bc1(data, w, h, out=None, convention='ktech'):
    pal_fn = _color_pal_bcdec if convention == 'bcdec' else _color_pal
    out = out if out is not None else bytearray(w * h * 4)
    bw, bh = (w + 3) // 4, (h + 3) // 4
    o = 0
    for by in range(bh):
        for bx in range(bw):
            c0, c1 = struct.unpack_from('<HH', data, o); o += 4
            pal, punch = pal_fn(c0, c1)
            idx = struct.unpack_from('<I', data, o)[0]; o += 4
            for py in range(4):
                for px in range(4):
                    x, y = bx * 4 + px, by * 4 + py
                    if x >= w or y >= h:
                        continue
                    k = py * 4 + px
                    r, g, b = pal[(idx >> (2 * k)) & 3]
                    a = 0 if (punch and ((idx >> (2 * k)) & 3) == 3) else 255
                    i = (y * w + x) * 4
                    out[i] = r; out[i + 1] = g; out[i + 2] = b; out[i + 3] = a
    return bytes(out)


def decode_bc23(data, w, h, mode, out=None, convention='ktech'):
    """mode: 'bc2'(DXT3 显式4bit alpha) 或 'bc3'(DXT5 插值 alpha)。
    convention: 'ktech'(squish floor 约定) 或 'bcdec'(应用 bcdec_rs 舍入约定)。"""
    out = out if out is not None else bytearray(w * h * 4)
    bw, bh = (w + 3) // 4, (h + 3) // 4
    o = 0
    for by in range(bh):
        for bx in range(bw):
            if mode == 'bc2':
                ab = data[o:o + 8]; o += 8
                alpha = [((ab[k // 2] & 0xF) if k % 2 == 0 else (ab[k // 2] >> 4)) * 17 for k in range(16)]
            else:
                a0, a1 = data[o], data[o + 1]; o += 2
                bits = int.from_bytes(data[o:o + 6], 'little'); o += 6
                a8, a6 = (_alpha_pal8_bcdec, _alpha_pal6_bcdec) if convention == 'bcdec' else (_alpha_pal8, _alpha_pal6)
                ap = a8(a0, a1) if a0 > a1 else a6(a0, a1)
                alpha = [ap[(bits >> (3 * k)) & 7] for k in range(16)]
            c0, c1 = struct.unpack_from('<HH', data, o); o += 4
            idx = struct.unpack_from('<I', data, o)[0]; o += 4
            pal, _ = (_color_pal_bcdec if convention == 'bcdec' else _color_pal)(c0, c1)
            for py in range(4):
                for px in range(4):
                    x, y = bx * 4 + px, by * 4 + py
                    if x >= w or y >= h:
                        continue
                    k = py * 4 + px
                    r, g, b = pal[(idx >> (2 * k)) & 3]
                    i = (y * w + x) * 4
                    out[i] = r; out[i + 1] = g; out[i + 2] = b; out[i + 3] = alpha[k]
    return bytes(out)


def unpremultiply(rgba):
    """预乘 alpha -> 直通 alpha（ktech 4.4 逐位复刻）。

    ktech 源码链路（image_operations.hpp demultiplyPixelAlpha，Q16）：
    q16 = min(65535, trunc(c8*65535 / a8))；out8 = (q16+128)//257。
    即 8 位整数等价：先截断后四舍五入，与单次 round 不同（如 c=2,a=4 -> 127 而非 128）。
    """
    out = bytearray(rgba)
    for i in range(0, len(rgba), 4):
        a = rgba[i + 3]
        if a == 0:
            pass  # ktech: a<=0 时直接返回，保留 BC 块原始 RGB（实测 anr 残差即此）
        elif a < 255:
            for c in range(3):
                q16 = min(65535, (rgba[i + c] * 65535) // a)
                out[i + c] = (q16 + 128) // 257
    return bytes(out)


def premultiply(rgba):
    out = bytearray(rgba)
    for i in range(0, len(rgba), 4):
        a = rgba[i + 3]
        for c in range(3):
            out[i + c] = (rgba[i + c] * a + 127) // 255
    return bytes(out)


# ---------------- encoders（规范实现；非逐位复刻任何工具的量化策略） ----------------

def _pack565(r, g, b):
    return (((r >> 3) & 0x1F) << 11) | (((g >> 2) & 0x3F) << 5) | ((b >> 3) & 0x1F)


def _best_endpoints4(block):  # 16 px RGB -> (c0>=c1, pal4 indices)
    rs = [p[0] for p in block]; gs = [p[1] for p in block]; bs = [p[2] for p in block]
    lo = (min(rs), min(gs), min(bs)); hi = (max(rs), max(gs), max(bs))
    c0 = _pack565(*hi); c1 = _pack565(*lo)
    if c0 == c1:
        return c0, c1, [0] * 16
    pal = _color_pal(c0, c1)[0]
    idx = []
    for p in block:
        d = [abs(p[0] - q[0]) + abs(p[1] - q[1]) + abs(p[2] - q[2]) for q in pal]
        idx.append(d.index(min(d)))
    # reorder so c0>c1 required for bc1 full mode; _color_pal with c0>c1 keeps order
    return c0, c1, idx


def encode_bc1(rgba, w, h):
    bw, bh = (w + 3) // 4, (h + 3) // 4
    out = bytearray()
    for by in range(bh):
        for bx in range(bw):
            block = []
            alpha_any = False
            for py in range(4):
                for px in range(4):
                    x, y = min(bx * 4 + px, w - 1), min(by * 4 + py, h - 1)
                    i = (y * w + x) * 4
                    block.append((rgba[i], rgba[i + 1], rgba[i + 2]))
                    if rgba[i + 3] < 128:
                        alpha_any = True
            c0, c1, idx = _best_endpoints4(block)
            if alpha_any and c0 > c1:
                # punchthrough mode: swap so c0<=c1 => index3 transparent
                c0, c1 = c1, c0
                pal = _color_pal(c0, c1)[0]
                idx = []
                for p in block:
                    d = [abs(p[0] - q[0]) + abs(p[1] - q[1]) + abs(p[2] - q[2]) for q in pal]
                    idx.append(d.index(min(d)))
            word = 0
            for k in range(16):
                word |= idx[k] << (2 * k)
            out += struct.pack('<HHI', c0, c1, word)
    return bytes(out)


def encode_bc2_alpha(block_alpha):
    out = bytearray(8)
    for k in range(16):
        v = block_alpha[k] >> 4
        if k % 2 == 0:
            out[k // 2] |= v
        else:
            out[k // 2] |= v << 4
    return bytes(out)


def encode_bc3_alpha(block_alpha):
    a0, a1 = min(block_alpha), max(block_alpha)
    if a0 == a1:
        return bytes([a0, a1]) + b'\x00' * 6
    pal = _alpha_pal8(a0, a1)
    bits = 0
    for k in range(16):
        d = [abs(block_alpha[k] - q) for q in pal]
        bits |= d.index(min(d)) << (3 * k)
    return bytes([a0, a1]) + bits.to_bytes(6, 'little')


def encode_bc23(rgba, w, h, mode):
    bw, bh = (w + 3) // 4, (h + 3) // 4
    out = bytearray()
    for by in range(bh):
        for bx in range(bw):
            block = []; alpha = []
            for py in range(4):
                for px in range(4):
                    x, y = min(bx * 4 + px, w - 1), min(by * 4 + py, h - 1)
                    i = (y * w + x) * 4
                    block.append((rgba[i], rgba[i + 1], rgba[i + 2]))
                    alpha.append(rgba[i + 3])
            out += encode_bc2_alpha(alpha) if mode == 'bc2' else encode_bc3_alpha(alpha)
            c0, c1, idx = _best_endpoints4(block)
            word = 0
            for k in range(16):
                word |= idx[k] << (2 * k)
            out += struct.pack('<HHI', c0, c1, word)
    return bytes(out)
