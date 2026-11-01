"""ETC2 (Ericsson Texture Compression v2) 解码器 — dst_re 标准实现。

应用（DST Mod Tool）的 KTEX 扩展格式枚举 0x12=ETC2（反编译 sub_141B30F60 确认）；
其导出编码用 etcpak，解码为标准 GPU 语义，故此处实现与 Khronos 规范一致的标准解码。

算法参考：Khronos OpenGL ES 3.0 规范 ETC2 部分（模式判定/位域与之一致）；
交叉验证 oracle：texture2ddecoder 1.0.6（K0lb3，decode_etc2/decode_etc2a8）。

模式判定（每 8 字节 RGB 块，diff 位 = data[3] bit1）：
  diff=0  -> ETC1 individual（两个 4:4:4 基色）
  diff=1  -> R/G/B 各为 base5(高位)+diff3；若 R 通道和越界[0,255] -> T 模式；
             否则 G 越界 -> H 模式；否则 B 越界 -> Planar 模式；
             全部在界 -> ETC1 differential。
T/H 模式重解析位域为两个基色 + ETC2DistanceTable[8]={3,6,11,16,23,32,41,64} 距离；
Planar 模式三顶点 R/O/H 按双线性 r = clamp((x*(RO-O)+y*(RH-O)+4*O+2)>>2)。
像素索引：48 位 LSB-first 流，每像素 3 位（2 位在 MSB 字节对）；
ETC1 模式只用 2 位（j 决定修饰表正负项选择，k 决定符号），ETC2 T/H 用满 3 位。

RGBA8 = 每 16 字节块：前 8 字节 EAC alpha（base8+4bit 乘数+4bit 修饰表+48bit 索引，
alpha=clamp(base+mult*mod)），后 8 字节 ETC2 RGB 块。
"""
import struct

_WO = (0, 4, 8, 12, 1, 5, 9, 13, 2, 6, 10, 14, 3, 7, 11, 15)
_WOR = (15, 11, 7, 3, 14, 10, 6, 2, 13, 9, 5, 1, 12, 8, 4, 0)
_ETC1_MOD = ((2, 8), (5, 17), (9, 29), (13, 42), (18, 60), (24, 80), (33, 106), (47, 183))
_SUBBLOCK = ((0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1),
             (0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1))
_DIST = (3, 6, 11, 16, 23, 32, 41, 64)
_ALPHA_MOD = (
    (-3, -6, -9, -15, 2, 5, 8, 14), (-3, -7, -10, -13, 2, 6, 9, 12),
    (-2, -5, -8, -13, 1, 4, 7, 12), (-2, -4, -6, -13, 1, 3, 5, 12),
    (-3, -6, -8, -12, 2, 5, 7, 11), (-3, -7, -9, -11, 2, 6, 8, 10),
    (-4, -7, -8, -11, 3, 6, 7, 10), (-3, -5, -8, -11, 2, 4, 7, 10),
    (-2, -6, -8, -10, 1, 5, 7, 9), (-2, -5, -8, -10, 1, 4, 7, 9),
    (-2, -4, -8, -10, 1, 3, 7, 9), (-2, -5, -7, -10, 1, 4, 6, 9),
    (-3, -4, -7, -10, 2, 3, 6, 9), (-1, -2, -3, -10, 0, 1, 2, 9),
    (-4, -6, -8, -9, 3, 5, 7, 8), (-3, -5, -7, -9, 2, 4, 6, 8))


def _clamp(n):
    return 0 if n < 0 else 255 if n > 255 else n


def _block_rgb(data):
    """解码一个 8 字节 ETC2 RGB 块 -> 16 个 RGBA 像素（行主序）。"""
    j = data[6] << 8 | data[7]
    k = data[4] << 8 | data[5]
    out = bytearray(64)

    if data[3] & 2:
        r = data[0] & 0xF8
        dr = (data[0] << 3 & 0x18) - (data[0] << 3 & 0x20)
        g = data[1] & 0xF8
        dg = (data[1] << 3 & 0x18) - (data[1] << 3 & 0x20)
        b = data[2] & 0xF8
        db = (data[2] << 3 & 0x18) - (data[2] << 3 & 0x20)
        if r + dr < 0 or r + dr > 255:
            # ---- T 模式 ----
            r0 = (data[0] << 3 & 0xC0) | (data[0] << 4 & 0x30) | (data[0] >> 1 & 0xC) | (data[0] & 3)
            g0 = (data[1] & 0xF0) | data[1] >> 4
            b0 = (data[1] & 0x0F) | (data[1] << 4 & 0xFF)
            r1 = (data[2] & 0xF0) | data[2] >> 4
            g1 = (data[2] & 0x0F) | (data[2] << 4 & 0xFF)
            b1 = (data[3] & 0xF0) | data[3] >> 4
            d = _DIST[(data[3] >> 1 & 6) | (data[3] & 1)]
            cs = ((r0, g0, b0), (r1 + d, g1 + d, b1 + d), (r1, g1, b1), (r1 - d, g1 - d, b1 - d))
            cs = tuple(tuple(_clamp(v) for v in c) for c in cs)
            k <<= 1
            for i in range(16):
                p = cs[(k & 2) | (j & 1)]
                o = _WO[i] * 4
                out[o:o + 3] = bytes(p)
                out[o + 3] = 255
                j >>= 1; k >>= 1
        elif g + dg < 0 or g + dg > 255:
            # ---- H 模式 ----
            r0 = (data[0] << 1 & 0xF0) | (data[0] >> 3 & 0xF)
            g0 = (data[0] << 5 & 0xE0) | (data[1] & 0x10)
            g0 |= g0 >> 4
            b0 = (data[1] & 8) | (data[1] << 1 & 6) | data[2] >> 7
            b0 |= b0 << 4
            r1 = (data[2] << 1 & 0xF0) | (data[2] >> 3 & 0xF)
            g1 = (data[2] << 5 & 0xE0) | (data[3] >> 3 & 0x10)
            g1 |= g1 >> 4
            b1 = (data[3] << 1 & 0xF0) | (data[3] >> 3 & 0xF)
            d = (data[3] & 4) | (data[3] << 1 & 2)
            if r0 > r1 or (r0 == r1 and (g0 > g1 or (g0 == g1 and b0 >= b1))):
                d += 1
            d = _DIST[d]
            cs = ((r0 + d, g0 + d, b0 + d), (r0 - d, g0 - d, b0 - d),
                  (r1 + d, g1 + d, b1 + d), (r1 - d, g1 - d, b1 - d))
            cs = tuple(tuple(_clamp(v) for v in c) for c in cs)
            k <<= 1
            for i in range(16):
                p = cs[(k & 2) | (j & 1)]
                o = _WO[i] * 4
                out[o:o + 3] = bytes(p)
                out[o + 3] = 255
                j >>= 1; k >>= 1
        elif b + db < 0 or b + db > 255:
            # ---- Planar 模式 ----
            O0 = (data[0] << 1 & 0xFC) | (data[0] >> 5 & 3)
            O1 = (data[0] << 7 & 0x80) | (data[1] & 0x7E) | (data[0] & 1)
            O2 = (data[1] << 7 & 0x80) | (data[2] << 2 & 0x60) | (data[2] << 3 & 0x18) | (data[3] >> 5 & 4)
            O2 |= O2 >> 6
            R0 = (data[3] << 1 & 0xF8) | (data[3] << 2 & 4) | (data[3] >> 5 & 3)
            R1 = (data[4] & 0xFE) | data[4] >> 7
            R2 = (data[4] << 7 & 0x80) | (data[5] >> 1 & 0x7C)
            R2 |= R2 >> 6
            H0 = (data[5] << 5 & 0xE0) | (data[6] >> 3 & 0x1C) | (data[5] >> 1 & 3)
            H1 = (data[6] << 3 & 0xF8) | (data[7] >> 5 & 0x6) | (data[6] >> 4 & 1)
            H2 = (data[7] << 2 & 0xFF) | (data[7] >> 4 & 3)
            O = (O0, O1, O2); R = (R0, R1, R2); H = (H0, H1, H2)
            i = 0
            for y in range(4):
                for x in range(4):
                    o = i * 4
                    out[o] = _clamp((x * (R[0] - O[0]) + y * (H[0] - O[0]) + 4 * O[0] + 2) >> 2)
                    out[o + 1] = _clamp((x * (R[1] - O[1]) + y * (H[1] - O[1]) + 4 * O[1] + 2) >> 2)
                    out[o + 2] = _clamp((x * (R[2] - O[2]) + y * (H[2] - O[2]) + 4 * O[2] + 2) >> 2)
                    out[o + 3] = 255
                    i += 1
        else:
            # ---- differential（同 ETC1）----
            code = (data[3] >> 5, data[3] >> 2 & 7)
            tbl = _SUBBLOCK[data[3] & 1]
            c0 = (r | r >> 5, g | g >> 5, b | b >> 5)
            c1 = (r + dr, g + dg, b + db)
            c1 = (c1[0] | c1[0] >> 5, c1[1] | c1[1] >> 5, c1[2] | c1[2] >> 5)
            cc = (c0, c1)
            for i in range(16):
                s = tbl[i]
                m = _ETC1_MOD[code[s]][j & 1]
                p = cc[s]
                sign = -m if k & 1 else m
                o = _WO[i] * 4
                out[o] = _clamp(p[0] + sign)
                out[o + 1] = _clamp(p[1] + sign)
                out[o + 2] = _clamp(p[2] + sign)
                out[o + 3] = 255
                j >>= 1; k >>= 1
    else:
        # ---- individual（同 ETC1）----
        code = (data[3] >> 5, data[3] >> 2 & 7)
        tbl = _SUBBLOCK[data[3] & 1]
        c0 = ((data[0] & 0xF0) | data[0] >> 4, (data[1] & 0xF0) | data[1] >> 4, (data[2] & 0xF0) | data[2] >> 4)
        c1 = ((data[0] & 0x0F) | (data[0] << 4 & 0xFF), (data[1] & 0x0F) | (data[1] << 4 & 0xFF), (data[2] & 0x0F) | (data[2] << 4 & 0xFF))
        cc = (c0, c1)
        for i in range(16):
            s = tbl[i]
            m = _ETC1_MOD[code[s]][j & 1]
            p = cc[s]
            sign = -m if k & 1 else m
            o = _WO[i] * 4
            out[o] = _clamp(p[0] + sign)
            out[o + 1] = _clamp(p[1] + sign)
            out[o + 2] = _clamp(p[2] + sign)
            out[o + 3] = 255
            j >>= 1; k >>= 1
    return bytes(out)


def _block_alpha(data):
    """解码一个 8 字节 EAC alpha 块 -> 16 个 u8（行主序）。"""
    mult = data[1] >> 4
    out = bytearray(16)
    if mult == 0:
        for i in range(16):
            out[i] = data[0]
        return bytes(out)
    tbl = _ALPHA_MOD[data[1] & 0xF]
    l = int.from_bytes(data, 'big')  # bton64=大端解释；从低位(data[7])向上逐 3 位消费 48 位
    for i in range(16):
        out[_WOR[i]] = _clamp(data[0] + mult * tbl[l & 7])
        l >>= 3
    return bytes(out)


def decode_etc2_rgb8(data, w, h):
    """整图解码 ETC2 RGB8（块行主序，自顶向下）-> RGBA bytes。"""
    bx = (w + 3) // 4
    by = (h + 3) // 4
    img = bytearray(w * h * 4)
    for y in range(by):
        for x in range(bx):
            off = (y * bx + x) * 8
            blk = _block_rgb(data[off:off + 8])
            px = x * 4; py = y * 4
            for r in range(4):
                if py + r >= h: break
                for c in range(4):
                    if px + c >= w: continue
                    so = (r * 4 + c) * 4
                    do = ((py + r) * w + px + c) * 4
                    img[do:do + 4] = blk[so:so + 4]
    return bytes(img)


def decode_etc2_rgba8(data, w, h):
    """整图解码 ETC2 RGBA8（每块 16B：EAC alpha 前 8B + RGB 后 8B）-> RGBA bytes。"""
    bx = (w + 3) // 4
    by = (h + 3) // 4
    img = bytearray(w * h * 4)
    for y in range(by):
        for x in range(bx):
            off = (y * bx + x) * 16
            alpha = _block_alpha(data[off:off + 8])
            blk = _block_rgb(data[off + 8:off + 16])
            px = x * 4; py = y * 4
            for r in range(4):
                if py + r >= h: break
                for c in range(4):
                    if px + c >= w: continue
                    so = (r * 4 + c) * 4
                    do = ((py + r) * w + px + c) * 4
                    img[do:do + 4] = blk[so:so + 4]
                    img[do + 3] = alpha[r * 4 + c]
    return bytes(img)
