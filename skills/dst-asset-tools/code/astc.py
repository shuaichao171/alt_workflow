"""ASTC LDR/HDR 块解码（Python 移植版）。

移植自 texture2ddecoder（github.com/K0lb3，MIT 许可）的 astc.cpp——
与该库逐函数对应（decode_astc / decode_block / decode_block_params /
decode_intseq / decode_endpoints / decode_weights / select_partition /
applicate_color），保持其整数运算语义（含 C 的截断与 u32 回绕）。

KTEX 中的 ASTC 固定为 8x8 块（spec 格式枚举 0x18，见反编译 sub_141B30F60）。
输出：RGBA 字节流（行主序），与 etc2.py 一致。

注意：随机字节可能构成 C 实现中依赖越界读/未初始化字段的非法块，
两者在非法块上不保证一致；正常编码器产物（astcenc）均为合法块。
"""

try:
    from ._astc_tables import BIT_REV, TRITS, QUINTS, MT, MQ
except ImportError:
    from _astc_tables import BIT_REV, TRITS, QUINTS, MT, MQ

_WEIGHT_PREC_A = (0, 0, 0, 3, 0, 5, 3, 0, 0, 0, 5, 3, 0, 5, 3, 0)
_WEIGHT_PREC_B = (0, 0, 1, 0, 2, 0, 1, 3, 0, 0, 1, 2, 4, 2, 3, 5)
_CEM_A = (0, 3, 5, 0, 3, 5, 0, 3, 5, 0, 3, 5, 0, 3, 5, 0, 3, 0, 0)
_CEM_B = (8, 6, 5, 7, 5, 4, 6, 4, 3, 5, 3, 2, 4, 2, 1, 3, 1, 2, 1)
_TR_COEF = (0, 204, 93, 44, 22, 11, 5)   # decode_endpoints 内部 TritsTable
_QN_COEF = (0, 113, 54, 26, 13, 6)       # decode_endpoints 内部 QuintsTable
# applicate_color 的 CEM->HDR 映射（FuncTableC / FuncTableA）
_C_HDR = (0, 0, 1, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1)
_A_HDR = (0, 0, 1, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1)


def _clamp(n):
    return 0 if n < 0 else 255 if n > 255 else n


def _clamp_hdr(n):
    return 0 if n < 0 else 0xFFF if n > 0xFFF else n


def _fp16_to_f32(h):
    """IEEE half -> float（fp16_ieee_to_fp32_value 等价）。"""
    s = -1.0 if h >> 15 else 1.0
    e = (h >> 10) & 0x1F
    m = h & 0x3FF
    if e == 0:
        return s * m * 2.0 ** -24
    if e == 31:
        return float('inf') if m == 0 else float('nan')
    return s * (1.0 + m / 1024.0) * 2.0 ** (e - 15)


def _f32_to_u8(f):
    import math
    c = math.floor(f * 255 + 0.5)  # roundf
    return 0 if c < 0 else 255 if c > 255 else c


def _bit_reverse_u64(d, bits):
    r = int(f'{d:064b}'[::-1], 2) if d else 0
    return r >> (64 - bits)


class _Block:
    __slots__ = ('bw', 'bh', 'width', 'height', 'part_num', 'dual_plane',
                 'plane_selector', 'weight_range', 'weight_num', 'cem',
                 'cem_range', 'endpoint_value_num', 'endpoints', 'weights', 'legal',
                 'partition')


def _decode_intseq(v, offset, a, b, count, reverse):
    """整数序列解码（trits/quints/plain bits）→ [(bits, nonbits), ...]。

    v: 块的 128 位小端整数视图；对应 C 的 getbits/getbits64 语义。
    """
    out = []
    if count <= 0:
        return out
    n = 0
    if a == 3:
        mask = (1 << b) - 1
        block_count = (count + 4) // 5
        last_block_count = (count + 4) % 5 + 1
        block_size = 8 + 5 * b
        last_block_size = (block_size * last_block_count + 4) // 5
        for i in range(block_count):
            if reverse:
                p = offset - i * block_size
                now_size = block_size if i < block_count - 1 else last_block_size
                d = _bit_reverse_u64(_gb64(v, p - now_size, now_size), now_size)
            else:
                p = offset + i * block_size
                now_size = block_size if i < block_count - 1 else last_block_size
                d = (v >> p) & ((1 << now_size) - 1) if now_size else 0
            x = ((d >> b) & 3) | ((d >> b * 2) & 0xC) | ((d >> b * 3) & 0x10) | \
                ((d >> b * 4) & 0x60) | ((d >> b * 5) & 0x80)
            for j in range(5):
                if n >= count:
                    break
                out.append(((d >> (MT[j] + b * j)) & mask, TRITS[j][x]))
                n += 1
    elif a == 5:
        mask = (1 << b) - 1
        block_count = (count + 2) // 3
        last_block_count = (count + 2) % 3 + 1
        block_size = 7 + 3 * b
        last_block_size = (block_size * last_block_count + 2) // 3
        for i in range(block_count):
            if reverse:
                p = offset - i * block_size
                now_size = block_size if i < block_count - 1 else last_block_size
                d = _bit_reverse_u64(_gb64(v, p - now_size, now_size), now_size)
            else:
                p = offset + i * block_size
                now_size = block_size if i < block_count - 1 else last_block_size
                d = (v >> p) & ((1 << now_size) - 1) if now_size else 0
            x = ((d >> b) & 7) | ((d >> b * 2) & 0x18) | ((d >> b * 3) & 0x60)
            for j in range(3):
                if n >= count:
                    break
                out.append(((d >> (MQ[j] + b * j)) & mask, QUINTS[j][x]))
                n += 1
    else:
        for n in range(count):
            if reverse:
                p = offset - b * (n + 1)
                val = _gb64(v, p, b)
                out.append((BIT_REV[val] >> (8 - b), 0))
            else:
                p = offset + b * n
                out.append(((v >> p) & ((1 << b) - 1), 0))
    return out


def _gb64(v, bit, size):
    """C getbits64 语义：bit<0 时从低 64 位左移（对应 C 的 *(u64*)buf << -bit 分支）。"""
    if size <= 0:
        return 0
    mask = (1 << size) - 1
    if bit < 0:
        return ((v & 0xFFFFFFFFFFFFFFFF) << -bit) & mask
    return (v >> bit) & mask


def _gb(v, bit, ln):
    """C getbits：*(int*)(buf+bit/8) >> (bit%8) & mask 的 128 位视图等价。"""
    if ln <= 0:
        return 0
    if bit < 0:
        return (v << -bit) & ((1 << ln) - 1)
    return (v >> bit) & ((1 << ln) - 1)


def _decode_block_params(buf, d):
    v = int.from_bytes(buf, 'little')
    u16_0 = buf[0] | buf[1] << 8
    d.dual_plane = (buf[1] >> 2) & 1
    d.weight_range = (buf[0] >> 4 & 1) | ((buf[1] << 2) & 8)
    if buf[0] & 3:
        d.weight_range |= (buf[0] << 1) & 6
        c = buf[0] & 0xC
        if c == 0:
            d.width = (u16_0 >> 7 & 3) + 4
            d.height = (buf[0] >> 5 & 3) + 2
        elif c == 4:
            d.width = (u16_0 >> 7 & 3) + 8
            d.height = (buf[0] >> 5 & 3) + 2
        elif c == 8:
            d.width = (buf[0] >> 5 & 3) + 2
            d.height = (u16_0 >> 7 & 3) + 8
        else:
            if buf[1] & 1:
                d.width = (buf[0] >> 7 & 1) + 2
                d.height = (buf[0] >> 5 & 3) + 2
            else:
                d.width = (buf[0] >> 5 & 3) + 2
                d.height = (buf[0] >> 7 & 1) + 6
    else:
        d.weight_range |= (buf[0] >> 1) & 6
        c = u16_0 & 0x180
        if c == 0:
            d.width = 12
            d.height = (buf[0] >> 5 & 3) + 2
        elif c == 0x80:
            d.width = (buf[0] >> 5 & 3) + 2
            d.height = 12
        elif c == 0x100:
            d.width = (buf[0] >> 5 & 3) + 6
            d.height = (buf[1] >> 1 & 3) + 6
            d.dual_plane = 0
            d.weight_range &= 7
        else:
            d.width = 10 if buf[0] & 0x20 else 6
            d.height = 6 if buf[0] & 0x20 else 10

    d.part_num = (buf[1] >> 3 & 3) + 1
    d.weight_num = d.width * d.height
    if d.dual_plane:
        d.weight_num *= 2

    wa = _WEIGHT_PREC_A[d.weight_range]
    wb = _WEIGHT_PREC_B[d.weight_range]
    if wa == 3:
        weight_bits = d.weight_num * wb + (d.weight_num * 8 + 4) // 5
    elif wa == 5:
        weight_bits = d.weight_num * wb + (d.weight_num * 7 + 2) // 3
    else:
        weight_bits = d.weight_num * wb

    u16_1 = buf[1] | buf[2] << 8
    u16_2 = buf[2] | buf[3] << 8
    cem = [0, 0, 0, 0]
    if d.part_num == 1:
        cem[0] = u16_1 >> 5 & 0xF
        config_bits = 17
        cem_base = 0
    else:
        cem_base = u16_2 >> 7 & 3
        if cem_base == 0:
            c0 = buf[3] >> 1 & 0xF
            for i in range(d.part_num):
                cem[i] = c0
            config_bits = 29
        else:
            for i in range(d.part_num):
                cem[i] = (((buf[3] >> (i + 1)) & 1) + cem_base - 1) << 2
            if d.part_num == 2:
                cem[0] |= buf[3] >> 3 & 3
                cem[1] |= _gb(v, 126 - weight_bits, 2)
            elif d.part_num == 3:
                cem[0] |= buf[3] >> 4 & 1
                cem[0] |= _gb(v, 122 - weight_bits, 2) & 2
                cem[1] |= _gb(v, 124 - weight_bits, 2)
                cem[2] |= _gb(v, 126 - weight_bits, 2)
            else:
                for i in range(4):
                    cem[i] |= _gb(v, 120 + i * 2 - weight_bits, 2)
            config_bits = 25 + d.part_num * 3
    d.cem = cem

    if d.dual_plane:
        config_bits += 2
        d.plane_selector = _gb(v, (130 - weight_bits - d.part_num * 3) if cem_base else (126 - weight_bits), 2)
    else:
        d.plane_selector = 0

    remain_bits = 128 - config_bits - weight_bits
    d.endpoint_value_num = sum((cem[i] >> 1 & 6) + 2 for i in range(d.part_num))

    d.cem_range = 18
    d.legal = False
    for i in range(len(_CEM_A)):
        ca, cb = _CEM_A[i], _CEM_B[i]
        if ca == 3:
            endpoint_bits = d.endpoint_value_num * cb + (d.endpoint_value_num * 8 + 4) // 5
        elif ca == 5:
            endpoint_bits = d.endpoint_value_num * cb + (d.endpoint_value_num * 7 + 2) // 3
        else:
            endpoint_bits = d.endpoint_value_num * cb
        if endpoint_bits <= remain_bits:
            d.cem_range = i
            d.legal = True
            break


def _bit_transfer_signed(a, b):
    """in-place：对应 C bit_transfer_signed(&v[a], &v[b])——注意 C 传参 (a=v[i], b=v[j])。"""
    b2 = (b >> 1) | (a & 0x80)
    a2 = (a >> 1) & 0x3F
    if a2 & 0x20:
        a2 -= 0x40
    return a2, b2


def _decode_endpoints_hdr7(ep, vi):
    v = ep['ev'][vi:vi + 4]
    modeval = ((v[2] >> 4) & 0x8) | ((v[1] >> 5) & 0x4) | (v[0] >> 6)
    if (modeval & 0xC) != 0xC:
        major, mode = modeval >> 2, modeval & 3
    elif modeval != 0xF:
        major, mode = modeval & 3, 4
    else:
        major, mode = 0, 5
    c = [v[0] & 0x3F, v[1] & 0x1F, v[2] & 0x1F, v[3] & 0x1F]
    if mode == 0:
        c[3] |= v[3] & 0x60
        c[0] |= (v[3] >> 1) & 0x40
        c[0] |= (v[2] << 1) & 0x80
        c[0] |= (v[1] << 3) & 0x300
        c[0] |= (v[2] << 5) & 0x400
        c = [x << 1 for x in c]
    elif mode == 1:
        c[1] |= v[1] & 0x20
        c[2] |= v[2] & 0x20
        c[0] |= (v[3] >> 1) & 0x40
        c[0] |= (v[2] << 1) & 0x80
        c[0] |= (v[1] << 2) & 0x100
        c[0] |= (v[3] << 4) & 0x600
        c = [x << 1 for x in c]
    elif mode == 2:
        c[3] |= v[3] & 0xE0
        c[0] |= (v[2] << 1) & 0xC0
        c[0] |= (v[1] << 3) & 0x300
        c = [x << 2 for x in c]
    elif mode == 3:
        c[1] |= v[1] & 0x20
        c[2] |= v[2] & 0x20
        c[3] |= v[3] & 0x60
        c[0] |= (v[3] >> 1) & 0x40
        c[0] |= (v[2] << 1) & 0x80
        c[0] |= (v[1] << 2) & 0x100
        c = [x << 3 for x in c]
    elif mode == 4:
        c[1] |= v[1] & 0x60
        c[2] |= v[2] & 0x60
        c[3] |= v[3] & 0x20
        c[0] |= (v[3] >> 1) & 0x40
        c[0] |= (v[3] << 1) & 0x80
        c = [x << 4 for x in c]
    else:
        c[1] |= v[1] & 0x60
        c[2] |= v[2] & 0x60
        c[3] |= v[3] & 0x60
        c[0] |= (v[3] >> 1) & 0x40
        c = [x << 5 for x in c]
    if mode != 5:
        c[1] = c[0] - c[1]
        c[2] = c[0] - c[2]
    if major == 1:
        vals = (c[1] - c[3], c[0] - c[3], c[2] - c[3], 0x780, c[1], c[0], c[2], 0x780)
    elif major == 2:
        vals = (c[2] - c[3], c[1] - c[3], c[0] - c[3], 0x780, c[2], c[1], c[0], 0x780)
    else:
        vals = (c[0] - c[3], c[1] - c[3], c[2] - c[3], 0x780, c[0], c[1], c[2], 0x780)
    ep['out'] = [_clamp_hdr(x) for x in vals]


def _decode_endpoints_hdr11(ep, vi, alpha1, alpha2):
    v = ep['ev'][vi:vi + 6]
    major = (v[4] >> 7) | ((v[5] >> 6) & 2)
    if major == 3:
        ep['out'] = [v[0] << 4, v[2] << 4, (v[4] << 5) & 0xFE0, alpha1,
                     v[1] << 4, v[3] << 4, (v[5] << 5) & 0xFE0, alpha2]
        return
    mode = (v[1] >> 7) | ((v[2] >> 6) & 2) | ((v[3] >> 5) & 4)
    va = v[0] | ((v[1] << 2) & 0x100)
    vb0 = v[2] & 0x3F
    vb1 = v[3] & 0x3F
    vc = v[1] & 0x3F
    if mode in (0, 2):
        vd0 = (v[4] & 0x7F) - 128 if v[4] & 0x40 else v[4] & 0x7F
        vd1 = (v[5] & 0x7F) - 128 if v[5] & 0x40 else v[5] & 0x7F
    elif mode in (1, 3, 5, 7):
        vd0 = (v[4] & 0x3F) - 64 if v[4] & 0x20 else v[4] & 0x3F
        vd1 = (v[5] & 0x3F) - 64 if v[5] & 0x20 else v[5] & 0x3F
    else:
        vd0 = (v[4] & 0x1F) - 32 if v[4] & 0x10 else v[4] & 0x1F
        vd1 = (v[5] & 0x1F) - 32 if v[5] & 0x10 else v[5] & 0x1F

    if mode == 0:
        vb0 |= v[2] & 0x40
        vb1 |= v[3] & 0x40
    elif mode == 1:
        vb0 |= v[2] & 0x40
        vb1 |= v[3] & 0x40
        vb0 |= (v[4] << 1) & 0x80
        vb1 |= (v[5] << 1) & 0x80
    elif mode == 2:
        va |= (v[2] << 3) & 0x200
        vc |= v[3] & 0x40
    elif mode == 3:
        va |= (v[4] << 3) & 0x200
        vc |= v[5] & 0x40
        vb0 |= v[2] & 0x40
        vb1 |= v[3] & 0x40
    elif mode == 4:
        va |= (v[4] << 4) & 0x200
        va |= (v[5] << 5) & 0x400
        vb0 |= v[2] & 0x40
        vb1 |= v[3] & 0x40
        vb0 |= (v[4] << 1) & 0x80
        vb1 |= (v[5] << 1) & 0x80
    elif mode == 5:
        va |= (v[2] << 3) & 0x200
        va |= (v[3] << 4) & 0x400
        vc |= v[5] & 0x40
        vc |= (v[4] << 1) & 0x80
    elif mode == 6:
        va |= (v[4] << 4) & 0x200
        va |= (v[5] << 5) & 0x400
        va |= (v[4] << 5) & 0x800
        vc |= v[5] & 0x40
        vb0 |= v[2] & 0x40
        vb1 |= v[3] & 0x40
    else:
        va |= (v[2] << 3) & 0x200
        va |= (v[3] << 4) & 0x400
        va |= (v[4] << 5) & 0x800
        vc |= v[5] & 0x40

    shamt = (mode >> 1) ^ 3
    va <<= shamt
    vb0 <<= shamt
    vb1 <<= shamt
    vc <<= shamt
    mult = 1 << shamt
    vd0 *= mult
    vd1 *= mult

    if major == 1:
        vals = (va - vb0 - vc - vd0, va - vc, va - vb1 - vc - vd1, alpha1, va - vb0, va, va - vb1, alpha2)
    elif major == 2:
        vals = (va - vb1 - vc - vd1, va - vb0 - vc - vd0, va - vc, alpha1, va - vb1, va - vb0, va, alpha2)
    else:
        vals = (va - vc, va - vb0 - vc - vd0, va - vb1 - vc - vd1, alpha1, va, va - vb0, va - vb1, alpha2)
    ep['out'] = [_clamp_hdr(x) for x in vals]


def _decode_endpoints(v128, d):
    ev = [0] * 32
    seq = _decode_intseq(v128, 17 if d.part_num == 1 else 29,
                         _CEM_A[d.cem_range], _CEM_B[d.cem_range], d.endpoint_value_num, 0)
    ca, cb = _CEM_A[d.cem_range], _CEM_B[d.cem_range]
    if ca == 3:
        ccoef = _TR_COEF[cb]
        for i in range(d.endpoint_value_num):
            a = (seq[i][0] & 1) * 0x1FF
            x = seq[i][0] >> 1
            if cb == 1:
                b = 0
            elif cb == 2:
                b = 0b100010110 * x
            elif cb == 3:
                b = x << 7 | x << 2 | x
            elif cb == 4:
                b = x << 6 | x
            elif cb == 5:
                b = x << 5 | x >> 2
            else:
                b = x << 4 | x >> 4
            ev[i] = ((a & 0x80) | (((seq[i][1] * ccoef + b) ^ a) >> 2)) & 0xFF if False else \
                (a & 0x80) | ((seq[i][1] * ccoef + b) ^ a) >> 2
    elif ca == 5:
        ccoef = _QN_COEF[cb]
        for i in range(d.endpoint_value_num):
            a = (seq[i][0] & 1) * 0x1FF
            x = seq[i][0] >> 1
            if cb == 1:
                b = 0
            elif cb == 2:
                b = 0b100001100 * x
            elif cb == 3:
                b = x << 7 | x << 1 | x >> 1
            elif cb == 4:
                b = x << 6 | x >> 1
            else:
                b = x << 5 | x >> 3
            ev[i] = (a & 0x80) | ((seq[i][1] * ccoef + b) ^ a) >> 2
    else:
        for i in range(d.endpoint_value_num):
            bits = seq[i][0]
            if cb == 1:
                ev[i] = bits * 0xFF
            elif cb == 2:
                ev[i] = bits * 0x55
            elif cb == 3:
                ev[i] = bits << 5 | bits << 2 | bits >> 1
            elif cb == 4:
                ev[i] = bits << 4 | bits
            elif cb == 5:
                ev[i] = bits << 3 | bits >> 2
            elif cb == 6:
                ev[i] = bits << 2 | bits >> 4
            elif cb == 7:
                ev[i] = bits << 1 | bits >> 6
            else:
                ev[i] = bits

    d.endpoints = [[0] * 8 for _ in range(4)]
    vi = 0
    for cem_i in range(d.part_num):
        cem = d.cem[cem_i]
        if cem == 0:
            d.endpoints[cem_i] = [ev[vi], ev[vi], ev[vi], 255, ev[vi + 1], ev[vi + 1], ev[vi + 1], 255]
        elif cem == 1:
            l0 = (ev[vi] >> 2) | (ev[vi + 1] & 0xC0)
            l1 = _clamp(l0 + (ev[vi + 1] & 0x3F))
            d.endpoints[cem_i] = [l0, l0, l0, 255, l1, l1, l1, 255]
        elif cem == 2:
            if ev[vi] <= ev[vi + 1]:
                y0, y1 = ev[vi] << 4, ev[vi + 1] << 4
            else:
                y0, y1 = (ev[vi + 1] << 4) + 8, (ev[vi] << 4) - 8
            d.endpoints[cem_i] = [y0, y0, y0, 0x780, y1, y1, y1, 0x780]
        elif cem == 3:
            if ev[vi] & 0x80:
                y0 = ((ev[vi + 1] & 0xE0) << 4) | ((ev[vi] & 0x7F) << 2)
                dd = (ev[vi + 1] & 0x1F) << 2
            else:
                y0 = ((ev[vi + 1] & 0xF0) << 4) | ((ev[vi] & 0x7F) << 1)
                dd = (ev[vi + 1] & 0x0F) << 1
            y1 = _clamp_hdr(y0 + dd)
            d.endpoints[cem_i] = [y0, y0, y0, 0x780, y1, y1, y1, 0x780]
        elif cem == 4:
            d.endpoints[cem_i] = [ev[vi], ev[vi], ev[vi], ev[vi + 2], ev[vi + 1], ev[vi + 1], ev[vi + 1], ev[vi + 3]]
        elif cem == 5:
            ev[vi + 1], ev[vi] = _bit_transfer_signed(ev[vi + 1], ev[vi])
            ev[vi + 3], ev[vi + 2] = _bit_transfer_signed(ev[vi + 3], ev[vi + 2])
            ev[vi + 1] += ev[vi]
            d.endpoints[cem_i] = [_clamp(ev[vi])] * 3 + [_clamp(ev[vi + 2])] + \
                                 [_clamp(ev[vi + 1])] * 3 + [_clamp(ev[vi + 2] + ev[vi + 3])]
        elif cem == 6:
            d.endpoints[cem_i] = [ev[vi] * ev[vi + 3] >> 8, ev[vi + 1] * ev[vi + 3] >> 8,
                                  ev[vi + 2] * ev[vi + 3] >> 8, 255,
                                  ev[vi], ev[vi + 1], ev[vi + 2], 255]
        elif cem == 7:
            ep = {'ev': ev}
            _decode_endpoints_hdr7(ep, vi)
            d.endpoints[cem_i] = ep['out']
        elif cem == 8:
            if ev[vi] + ev[vi + 2] + ev[vi + 4] <= ev[vi + 1] + ev[vi + 3] + ev[vi + 5]:
                d.endpoints[cem_i] = [ev[vi], ev[vi + 2], ev[vi + 4], 255,
                                      ev[vi + 1], ev[vi + 3], ev[vi + 5], 255]
            else:
                r1, g1, b1 = ev[vi + 1], ev[vi + 3], ev[vi + 5]
                r2, g2, b2 = ev[vi], ev[vi + 2], ev[vi + 4]
                d.endpoints[cem_i] = [(r1 + b1) >> 1, (g1 + b1) >> 1, b1, 255,
                                      (r2 + b2) >> 1, (g2 + b2) >> 1, b2, 255]
        elif cem == 9:
            ev[vi + 1], ev[vi] = _bit_transfer_signed(ev[vi + 1], ev[vi])
            ev[vi + 3], ev[vi + 2] = _bit_transfer_signed(ev[vi + 3], ev[vi + 2])
            ev[vi + 5], ev[vi + 4] = _bit_transfer_signed(ev[vi + 5], ev[vi + 4])
            if ev[vi + 1] + ev[vi + 3] + ev[vi + 5] >= 0:
                d.endpoints[cem_i] = [_clamp(ev[vi]), _clamp(ev[vi + 2]), _clamp(ev[vi + 4]), 255,
                                      _clamp(ev[vi] + ev[vi + 1]), _clamp(ev[vi + 2] + ev[vi + 3]),
                                      _clamp(ev[vi + 4] + ev[vi + 5]), 255]
            else:
                r1, g1, b1 = ev[vi] + ev[vi + 1], ev[vi + 2] + ev[vi + 3], ev[vi + 4] + ev[vi + 5]
                r2, g2, b2 = ev[vi], ev[vi + 2], ev[vi + 4]
                d.endpoints[cem_i] = [_clamp((r1 + b1) >> 1), _clamp((g1 + b1) >> 1), _clamp(b1), 255,
                                      _clamp((r2 + b2) >> 1), _clamp((g2 + b2) >> 1), _clamp(b2), 255]
        elif cem == 10:
            d.endpoints[cem_i] = [ev[vi] * ev[vi + 3] >> 8, ev[vi + 1] * ev[vi + 3] >> 8,
                                  ev[vi + 2] * ev[vi + 3] >> 8, ev[vi + 4],
                                  ev[vi], ev[vi + 1], ev[vi + 2], ev[vi + 5]]
        elif cem == 11:
            ep = {'ev': ev}
            _decode_endpoints_hdr11(ep, vi, 0x780, 0x780)
            d.endpoints[cem_i] = ep['out']
        elif cem == 12:
            if ev[vi] + ev[vi + 2] + ev[vi + 4] <= ev[vi + 1] + ev[vi + 3] + ev[vi + 5]:
                d.endpoints[cem_i] = [ev[vi], ev[vi + 2], ev[vi + 4], ev[vi + 6],
                                      ev[vi + 1], ev[vi + 3], ev[vi + 5], ev[vi + 7]]
            else:
                d.endpoints[cem_i] = [(ev[vi + 1] + ev[vi + 5]) >> 1, (ev[vi + 3] + ev[vi + 5]) >> 1,
                                      ev[vi + 5], ev[vi + 7],
                                      (ev[vi] + ev[vi + 4]) >> 1, (ev[vi + 2] + ev[vi + 4]) >> 1,
                                      ev[vi + 4], ev[vi + 6]]
        elif cem == 13:
            ev[vi + 1], ev[vi] = _bit_transfer_signed(ev[vi + 1], ev[vi])
            ev[vi + 3], ev[vi + 2] = _bit_transfer_signed(ev[vi + 3], ev[vi + 2])
            ev[vi + 5], ev[vi + 4] = _bit_transfer_signed(ev[vi + 5], ev[vi + 4])
            ev[vi + 7], ev[vi + 6] = _bit_transfer_signed(ev[vi + 7], ev[vi + 6])
            if ev[vi + 1] + ev[vi + 3] + ev[vi + 5] >= 0:
                d.endpoints[cem_i] = [_clamp(ev[vi]), _clamp(ev[vi + 2]), _clamp(ev[vi + 4]), _clamp(ev[vi + 6]),
                                      _clamp(ev[vi] + ev[vi + 1]), _clamp(ev[vi + 2] + ev[vi + 3]),
                                      _clamp(ev[vi + 4] + ev[vi + 5]), _clamp(ev[vi + 6] + ev[vi + 7])]
            else:
                r1 = ev[vi] + ev[vi + 1]
                g1 = ev[vi + 2] + ev[vi + 3]
                b1 = ev[vi + 4] + ev[vi + 5]
                a1 = ev[vi + 6] + ev[vi + 7]
                d.endpoints[cem_i] = [_clamp((r1 + b1) >> 1), _clamp((g1 + b1) >> 1), _clamp(b1), _clamp(a1),
                                      _clamp((ev[vi] + ev[vi + 4]) >> 1), _clamp((ev[vi + 2] + ev[vi + 4]) >> 1),
                                      _clamp(ev[vi + 4]), _clamp(ev[vi + 6])]
        elif cem == 14:
            ep = {'ev': ev}
            _decode_endpoints_hdr11(ep, vi, ev[vi + 6], ev[vi + 7])
            d.endpoints[cem_i] = ep['out']
        elif cem == 15:
            mode = ((ev[vi + 6] >> 7) & 1) | ((ev[vi + 7] >> 6) & 2)
            ev[vi + 6] &= 0x7F
            ev[vi + 7] &= 0x7F
            ep = {'ev': ev}
            if mode == 3:
                _decode_endpoints_hdr11(ep, vi, ev[vi + 6] << 5, ev[vi + 7] << 5)
            else:
                ev[vi + 6] |= (ev[vi + 7] << (mode + 1)) & 0x780
                ev[vi + 7] = ((ev[vi + 7] & (0x3F >> mode)) ^ (0x20 >> mode)) - (0x20 >> mode)
                ev[vi + 6] <<= 4 - mode
                ev[vi + 7] <<= 4 - mode
                _decode_endpoints_hdr11(ep, vi, ev[vi + 6], _clamp_hdr(ev[vi + 6] + ev[vi + 7]))
            d.endpoints[cem_i] = ep['out']
        vi += (d.cem[cem_i] // 4 + 1) * 2


def _decode_weights(v128, d):
    seq = _decode_intseq(v128, 128, _WEIGHT_PREC_A[d.weight_range], _WEIGHT_PREC_B[d.weight_range],
                         d.weight_num, 1)
    wa = _WEIGHT_PREC_A[d.weight_range]
    wb = _WEIGHT_PREC_B[d.weight_range]
    wv = [0] * (d.weight_num + 32)
    if wa == 0:
        for i in range(d.weight_num):
            bits = seq[i][0]
            if wb == 1:
                wv[i] = 63 if bits else 0
            elif wb == 2:
                wv[i] = bits << 4 | bits << 2 | bits
            elif wb == 3:
                wv[i] = bits << 3 | bits
            elif wb == 4:
                wv[i] = bits << 2 | bits >> 2
            else:
                wv[i] = bits << 1 | bits >> 4
        for i in range(d.weight_num):
            if wv[i] > 32:
                wv[i] += 1
    elif wb == 0:
        s = 32 if wa == 3 else 16
        for i in range(d.weight_num):
            wv[i] = seq[i][1] * s
    else:
        if wa == 3:
            for i in range(d.weight_num):
                if wb == 1:
                    wv[i] = seq[i][1] * 50
                elif wb == 2:
                    wv[i] = seq[i][1] * 23
                    if seq[i][0] & 2:
                        wv[i] += 0b1000101
                else:
                    wv[i] = seq[i][1] * 11 + ((seq[i][0] << 4 | seq[i][0] >> 1) & 0b1100011)
        else:  # wa == 5
            for i in range(d.weight_num):
                if wb == 1:
                    wv[i] = seq[i][1] * 28
                else:
                    wv[i] = seq[i][1] * 13
                    if seq[i][0] & 2:
                        wv[i] += 0b1000010
        for i in range(d.weight_num):
            a = (seq[i][0] & 1) * 0x7F
            wv[i] = ((a & 0x20) | ((wv[i] ^ a) >> 2))
            if wv[i] > 32:
                wv[i] += 1

    ds = (1024 + d.bw // 2) // (d.bw - 1)
    dt = (1024 + d.bh // 2) // (d.bh - 1)
    pn = 2 if d.dual_plane else 1
    d.weights = [[0, 0] for _ in range(144)]
    i = 0
    for t in range(d.bh):
        for s in range(d.bw):
            gs = (ds * s * (d.width - 1) + 32) >> 6
            gt = (dt * t * (d.height - 1) + 32) >> 6
            fs = gs & 0xF
            ft = gt & 0xF
            vv = (gs >> 4) + (gt >> 4) * d.width
            w11 = (fs * ft + 8) >> 4
            w10 = ft - w11
            w01 = fs - w11
            w00 = 16 - fs - ft + w11
            for p in range(pn):
                p00 = wv[vv * pn + p]
                p01 = wv[(vv + 1) * pn + p]
                p10 = wv[(vv + d.width) * pn + p]
                p11 = wv[(vv + d.width + 1) * pn + p]
                d.weights[i][p] = (p00 * w00 + p01 * w01 + p10 * w10 + p11 * w11 + 8) >> 4
            i += 1


def _select_partition(buf, d):
    small_block = d.bw * d.bh < 31
    seed = ((int.from_bytes(buf[:4], 'little') >> 13) & 0x3FF) | ((d.part_num - 1) << 10)

    rnum = seed & 0xFFFFFFFF
    rnum ^= rnum >> 15
    rnum = (rnum - (rnum << 17)) & 0xFFFFFFFF
    rnum = (rnum + (rnum << 7)) & 0xFFFFFFFF
    rnum = (rnum + (rnum << 4)) & 0xFFFFFFFF
    rnum ^= rnum >> 5
    rnum = (rnum + (rnum << 16)) & 0xFFFFFFFF
    rnum ^= rnum >> 7
    rnum ^= rnum >> 3
    rnum = (rnum ^ ((rnum << 6) & 0xFFFFFFFF)) & 0xFFFFFFFF
    rnum ^= rnum >> 17

    seeds = [(rnum >> (i * 4)) & 0xF for i in range(8)]
    seeds = [s * s for s in seeds]

    sh = [4 if seed & 2 else 5, 6 if d.part_num == 3 else 5]
    if seed & 1:
        seeds = [seeds[i] >> sh[i % 2] for i in range(8)]
    else:
        seeds = [seeds[i] >> sh[1 - i % 2] for i in range(8)]

    d.partition = [0] * (d.bw * d.bh)
    i = 0
    if small_block:
        for t in range(d.bh):
            for s in range(d.bw):
                x = s << 1
                y = t << 1
                a = (seeds[0] * x + seeds[1] * y + (rnum >> 14)) & 0x3F
                b = (seeds[2] * x + seeds[3] * y + (rnum >> 10)) & 0x3F
                c = 0 if d.part_num < 3 else (seeds[4] * x + seeds[5] * y + (rnum >> 6)) & 0x3F
                dd = 0 if d.part_num < 4 else (seeds[6] * x + seeds[7] * y + (rnum >> 2)) & 0x3F
                d.partition[i] = 0 if (a >= b and a >= c and a >= dd) else 1 if (b >= c and b >= dd) else 2 if c >= dd else 3
                i += 1
    else:
        for y in range(d.bh):
            for x in range(d.bw):
                a = (seeds[0] * x + seeds[1] * y + (rnum >> 14)) & 0x3F
                b = (seeds[2] * x + seeds[3] * y + (rnum >> 10)) & 0x3F
                c = 0 if d.part_num < 3 else (seeds[4] * x + seeds[5] * y + (rnum >> 6)) & 0x3F
                dd = 0 if d.part_num < 4 else (seeds[6] * x + seeds[7] * y + (rnum >> 2)) & 0x3F
                d.partition[i] = 0 if (a >= b and a >= c and a >= dd) else 1 if (b >= c and b >= dd) else 2 if c >= dd else 3
                i += 1


def _select_color(v0, v1, weight):
    return (((((v0 << 8 | v0) * (64 - weight) + (v1 << 8 | v1) * weight + 32) >> 6) * 255 + 32768) // 65536)


def _select_color_hdr(v0, v1, weight):
    c = (((v0 << 4) * (64 - weight) + (v1 << 4) * weight + 32) >> 6) & 0xFFFF
    m = c & 0x7FF
    if m < 512:
        m *= 3
    elif m < 1536:
        m = 4 * m - 512
    else:
        m = 5 * m - 2048
    f = _fp16_to_f32(((c >> 1) & 0x7C00) | (m >> 3))
    import math
    if math.isfinite(f):
        return _f32_to_u8(f)
    return 255


def _applicate_color(d):
    out = [None] * (d.bw * d.bh)
    if d.dual_plane:
        ps = [0, 0, 0, 0]
        ps[d.plane_selector] = 1
        for i in range(d.bw * d.bh):
            p = d.partition[i] if d.part_num > 1 else 0
            e = d.endpoints[p]
            fc = _select_color_hdr if _C_HDR[d.cem[p]] else _select_color
            fa = _select_color_hdr if _A_HDR[d.cem[p]] else _select_color
            out[i] = (fc(e[0], e[4], d.weights[i][ps[0]]),
                      fc(e[1], e[5], d.weights[i][ps[1]]),
                      fc(e[2], e[6], d.weights[i][ps[2]]),
                      fa(e[3], e[7], d.weights[i][ps[3]]))
    else:
        for i in range(d.bw * d.bh):
            p = d.partition[i] if d.part_num > 1 else 0
            e = d.endpoints[p]
            fc = _select_color_hdr if _C_HDR[d.cem[p]] else _select_color
            fa = _select_color_hdr if _A_HDR[d.cem[p]] else _select_color
            out[i] = (fc(e[0], e[4], d.weights[i][0]),
                      fc(e[1], e[5], d.weights[i][0]),
                      fc(e[2], e[6], d.weights[i][0]),
                      fa(e[3], e[7], d.weights[i][0]))
    return out


def decode_block(buf, bw, bh):
    """解码单个 16 字节 ASTC 块 → [(r,g,b,a)] * bw*bh。"""
    if buf[0] == 0xFC and (buf[1] & 1) == 1:
        if buf[1] & 2:
            c = (_f32_to_u8(_fp16_to_f32(buf[8] | buf[9] << 8)),
                 _f32_to_u8(_fp16_to_f32(buf[10] | buf[11] << 8)),
                 _f32_to_u8(_fp16_to_f32(buf[12] | buf[13] << 8)),
                 _f32_to_u8(_fp16_to_f32(buf[14] | buf[15] << 8)))
        else:
            c = (buf[9], buf[11], buf[13], buf[15])
        return [c] * (bw * bh)
    if (((buf[0] & 0xC3) == 0xC0 and (buf[1] & 1) == 1) or (buf[0] & 0xF) == 0):
        return [(255, 0, 255, 255)] * (bw * bh)

    v128 = int.from_bytes(buf, 'little')
    d = _Block()
    d.bw, d.bh = bw, bh
    _decode_block_params(buf, d)
    _decode_endpoints(v128, d)
    _decode_weights(v128, d)
    if d.part_num > 1:
        _select_partition(buf, d)
    else:
        d.partition = [0] * (bw * bh)
    return _applicate_color(d)


def decode_astc(data, w, h, bw=8, bh=8):
    """整图解码（行主序 RGBA 字节）。data 长度须为 16*ceil(w/bw)*ceil(h/bh)。"""
    nbx = (w + bw - 1) // bw
    nby = (h + bh - 1) // bh
    img = bytearray(w * h * 4)
    for by in range(nby):
        for bx in range(nbx):
            blk = data[(by * nbx + bx) * 16:(by * nbx + bx) * 16 + 16]
            buf = decode_block(blk, bw, bh)
            x0 = bw * bx
            for yy in range(bh):
                y = by * bh + yy
                if y >= h:
                    break
                for xx in range(bw):
                    x = x0 + xx
                    if x >= w:
                        break
                    r, g, b, a = buf[yy * bw + xx]
                    o = (y * w + x) * 4
                    img[o:o + 4] = bytes((r, g, b, a))
    return bytes(img)
