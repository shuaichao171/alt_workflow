"""squish BC1/BC2/BC3 编码器忠实移植（Simon Brown libsquish，ktools-4.4 内置版）。

这是 ktech.exe 的实际编码后端（ktech 以纯 kDxtN flags 调 squish::CompressImage →
默认 ClusterFit + Rec.701 感知度量 (0.2126,0.7152,0.0722,0)，非迭代）；
DST Mod Tool 侧对应物为 texpresso 2.0.2（同一算法的 Rust 移植）。

移植范围（逐函数对照 ktools_src/lib/squish/*.cpp）：
- ColourSet（去重/权重 sqrt/remap，DXT1 透明剔除）
- ComputeWeightedCovariance + ComputePrincipleComponent（三次特征多项式 + 幂选择）
- ClusterFit Compress3/Compress4（最小二乘端点 + 三/四簇划分搜索）
- SingleColourFit（LUT 精确单色拟合，count==1 时分发）
- RangeFit（count==0 兜底）
- WriteColourBlock3/4 + FloatTo565、CompressAlphaDxt3/Dxt5、WriteAlphaBlock5/7
- CompressMasked 分发 + CompressImage 边缘块 mask 语义

浮点语义：C++ 为 f32/SIMD；本移植用 f64 精确算术（Reciprocal=精确除法，
对应标量后端；SSE 后端的 _mm_rcp_ps+1 轮 NR 与精确除法差 ≤1ulp）。
量化截断处（FloatToInt/Truncate/格点量化）语义严格一致，边界平局可能罕见不同。
"""

import math

try:
    from ._squish_lut import LOOKUP_5_3, LOOKUP_6_3, LOOKUP_5_4, LOOKUP_6_4
except ImportError:
    from _squish_lut import LOOKUP_5_3, LOOKUP_6_3, LOOKUP_5_4, LOOKUP_6_4

_METRIC = (0.2126, 0.7152, 0.0722)  # Rec.709 luma（squish 感知度量默认）


def _ftoi(a, limit):
    """FloatToInt: ANSI 向零取整 + 0.5 实现四舍五入，再夹取。"""
    i = int(a + 0.5)
    return 0 if i < 0 else (limit if i > limit else i)


# ---------------------------------------------------------------- ColourSet

def _colourset(rgba, mask, is_dxt1):
    """rgba: 16 像素 × RGBA 字节序列；mask: 16 位有效位。
    返回 (points, weights, remap, transparent)。"""
    points, weights, remap = [], [], [-1] * 16
    transparent = False
    for i in range(16):
        if not (mask >> i) & 1:
            continue
        if is_dxt1 and rgba[4 * i + 3] < 128:
            remap[i] = -1
            transparent = True
            continue
        for j in range(i + 1):
            if j == i:
                points.append((rgba[4 * i] / 255.0, rgba[4 * i + 1] / 255.0,
                               rgba[4 * i + 2] / 255.0))
                weights.append(1.0)
                remap[i] = len(points) - 1
                break
            if ((mask >> j) & 1 and rgba[4 * i] == rgba[4 * j]
                    and rgba[4 * i + 1] == rgba[4 * j + 1]
                    and rgba[4 * i + 2] == rgba[4 * j + 2]
                    and (rgba[4 * j + 3] >= 128 or not is_dxt1)):
                idx = remap[j]
                weights[idx] += 1.0
                remap[i] = idx
                break
    weights = [math.sqrt(w) for w in weights]
    return points, weights, remap, transparent


def _remap_indices(source, remap):
    return [3 if r == -1 else source[r] for r in remap]


# ------------------------------------------------- 协方差 / 主成分（maths.cpp）

def _covariance(points, weights):
    total = 0.0
    cx = cy = cz = 0.0
    for (x, y, z), w in zip(points, weights):
        total += w
        cx += w * x
        cy += w * y
        cz += w * z
    cx /= total
    cy /= total
    cz /= total
    m = [0.0] * 6  # xx, xy, xz, yy, yz, zz
    for (x, y, z), w in zip(points, weights):
        ax, ay, az = x - cx, y - cy, z - cz
        bx, by, bz = w * ax, w * ay, w * az
        m[0] += ax * bx
        m[1] += ax * by
        m[2] += ax * bz
        m[3] += ay * by
        m[4] += ay * bz
        m[5] += az * bz
    return m


def _ev_mult1(m, e):
    """GetMultiplicity1Evector: M-eI 的伴随（余子式）取最大分量列。"""
    mm = (m[0] - e, m[1], m[2], m[3] - e, m[4], m[5] - e)
    u = (mm[3] * mm[5] - mm[4] * mm[4],
         mm[2] * mm[4] - mm[1] * mm[5],
         mm[1] * mm[4] - mm[2] * mm[3],
         mm[0] * mm[5] - mm[2] * mm[2],
         mm[1] * mm[2] - mm[4] * mm[0],
         mm[0] * mm[3] - mm[1] * mm[1])
    mi = 0
    mc = abs(u[0])
    for i in range(1, 6):
        c = abs(u[i])
        if c > mc:
            mc, mi = c, i
    if mi == 0:
        return (u[0], u[1], u[2])
    if mi in (1, 3):
        return (u[1], u[3], u[4])
    return (u[2], u[4], u[5])


def _ev_mult2(m, e):
    """GetMultiplicity2Evector: (M-eI) 取最大分量所在行的余子式挑选。"""
    mm = (m[0] - e, m[1], m[2], m[3] - e, m[4], m[5] - e)
    mi = 0
    mc = abs(mm[0])
    for i in range(1, 6):
        c = abs(mm[i])
        if c > mc:
            mc, mi = c, i
    if mi in (0, 1):
        return (-mm[1], mm[0], 0.0)
    if mi == 2:
        return (mm[2], 0.0, -mm[0])
    if mi in (3, 4):
        return (0.0, -mm[4], mm[3])
    return (0.0, -mm[5], mm[4])


def _principle_component(m):
    """ComputePrincipleComponent：三次特征多项式 + 三根三角法。"""
    c0 = (m[0] * m[3] * m[5] + 2.0 * m[1] * m[2] * m[4]
          - m[0] * m[4] * m[4] - m[3] * m[2] * m[2] - m[5] * m[1] * m[1])
    c1 = (m[0] * m[3] + m[0] * m[5] + m[3] * m[5]
          - m[1] * m[1] - m[2] * m[2] - m[4] * m[4])
    c2 = m[0] + m[3] + m[5]
    a = c1 - (1.0 / 3.0) * c2 * c2
    b = (-2.0 / 27.0) * c2 * c2 * c2 + (1.0 / 3.0) * c1 * c2 - c0
    q = 0.25 * b * b + (1.0 / 27.0) * a * a * a
    eps = 1.192092896e-07  # FLT_EPSILON
    if eps < q:
        return (1.0, 1.0, 1.0)  # 多重根 → 单位向量
    if q < -eps:
        theta = math.atan2(math.sqrt(-q), -0.5 * b)
        rho = math.sqrt(0.25 * b * b - q)
        rt = rho ** (1.0 / 3.0)
        ct = math.cos(theta / 3.0)
        st = math.sin(theta / 3.0)
        l1 = (1.0 / 3.0) * c2 + 2.0 * rt * ct
        l2 = (1.0 / 3.0) * c2 - rt * (ct + math.sqrt(3.0) * st)
        l3 = (1.0 / 3.0) * c2 - rt * (ct - math.sqrt(3.0) * st)
        if abs(l2) > abs(l1):
            l1 = l2
        if abs(l3) > abs(l1):
            l1 = l3
        return _ev_mult1(m, l1)
    # Q≈0：二重根。rt = cbrt(±b/2)，l1 重根、l2 单根
    if b < 0.0:
        rt = -((-0.5 * b) ** (1.0 / 3.0))
    else:
        rt = (0.5 * b) ** (1.0 / 3.0)
    l1 = (1.0 / 3.0) * c2 + rt
    l2 = (1.0 / 3.0) * c2 - 2.0 * rt
    if abs(l1) > abs(l2):
        return _ev_mult2(m, l1)
    return _ev_mult1(m, l2)


# ---------------------------------------------------------------- 块写出

def _float_to_565(c):
    return ((_ftoi(31.0 * c[0], 31) << 11)
            | (_ftoi(63.0 * c[1], 63) << 5)
            | _ftoi(31.0 * c[2], 31))


def _write_colour_block(a, b, indices):
    out = bytearray(8)
    out[0], out[1] = a & 0xFF, (a >> 8) & 0xFF
    out[2], out[3] = b & 0xFF, (b >> 8) & 0xFF
    for i in range(4):
        k = indices[4 * i:4 * i + 4]
        out[4 + i] = k[0] | (k[1] << 2) | (k[2] << 4) | (k[3] << 6)
    return bytes(out)


def _write_colour_block3(start, end, indices):
    a, b = _float_to_565(start), _float_to_565(end)
    if a <= b:
        remapped = indices
    else:
        a, b = b, a
        remapped = [1 if k == 0 else (0 if k == 1 else k) for k in indices]
    return _write_colour_block(a, b, remapped)


def _write_colour_block4(start, end, indices):
    a, b = _float_to_565(start), _float_to_565(end)
    if a < b:
        a, b = b, a
        remapped = [(k ^ 0x1) & 0x3 for k in indices]
    elif a == b:
        remapped = [0] * 16
    else:
        remapped = indices
    return _write_colour_block(a, b, remapped)


# ---------------------------------------------------------------- ClusterFit

_GRID = (31.0, 63.0, 31.0)
_GRIDRCP = (1.0 / 31.0, 1.0 / 63.0, 1.0 / 31.0)


class _ClusterFit(object):
    ITERATIONS = 1  # ktech 非迭代默认

    def __init__(self, points, weights, remap=None):
        self.points, self.weights = points, weights
        self.remap = remap if remap is not None else list(range(len(points)))
        self.besterror = float('inf')
        self.principle = _principle_component(_covariance(points, weights))
        self.order = []

    def _construct_ordering(self, axis, iteration):
        count = len(self.points)
        dps = [p[0] * axis[0] + p[1] * axis[1] + p[2] * axis[2]
               for p in self.points]
        order = list(range(count))
        # 稳定插入排序（严格 <，与 C++ 一致）
        for i in range(count):
            for j in range(i, 0, -1):
                if dps[j] < dps[j - 1]:
                    dps[j], dps[j - 1] = dps[j - 1], dps[j]
                    order[j], order[j - 1] = order[j - 1], order[j]
                else:
                    break
        for it in range(iteration):
            if self.order[it][:count] == order[:count]:
                return False
        self.order.append(order)
        # 加权点（w 通道承载权和）
        self.pw = [(self.points[j][0] * self.weights[j], self.points[j][1] * self.weights[j], self.points[j][2] * self.weights[j],
                    self.weights[j]) for j in order]
        self.xw = [sum(col) for col in zip(*self.pw)] if count else [0.0] * 4
        return True

    def _ls(self, alphax, alpha2, betax, beta2, alphabeta):
        """最小二乘端点 + 格点量化；返回 (a[3], b[3], error)。"""
        a, b, err = [0.0] * 3, [0.0] * 3, 0.0
        factor_set = True
        for ch in range(3):
            factor = (alpha2 * beta2 - alphabeta * alphabeta)
            if factor == 0.0:
                factor_set = False
                break
            factor = 1.0 / factor
            av = (alphax[ch] * beta2 - betax[ch] * alphabeta) * factor
            bv = (betax[ch] * alpha2 - alphax[ch] * alphabeta) * factor
            av = min(1.0, max(0.0, av))
            bv = min(1.0, max(0.0, bv))
            av = int(_GRID[ch] * av + 0.5) * _GRIDRCP[ch]
            bv = int(_GRID[ch] * bv + 0.5) * _GRIDRCP[ch]
            a[ch], b[ch] = av, bv
        if not factor_set:
            return None
        for ch in range(3):
            e = (a[ch] * a[ch] * alpha2 + b[ch] * b[ch] * beta2
                 - 2.0 * a[ch] * alphax[ch] - 2.0 * b[ch] * betax[ch]
                 + 2.0 * a[ch] * b[ch] * alphabeta)
            err += _METRIC[ch] * e
        return a, b, err

    def _run(self, nmode):
        """nmode=3/4：严格对照 C++——每次迭代只搜当前 ordering，
        以进入本函数时的 self.besterror 为基线，严格更优才接受。"""
        count = len(self.points)
        self.order = []
        self._construct_ordering(self.principle, 0)
        best = None  # (err, a, b, i, j, k)
        iteration = 0
        while True:
            res = (self._search3(count) if nmode == 3 else self._search4(count))
            improved = res is not None
            if improved:
                best = res
                self.besterror = res[0]
            if not improved:
                break
            iteration += 1
            if iteration >= self.ITERATIONS:
                break
            axis = tuple(best[2][ch] - best[1][ch] for ch in range(3))
            if not self._construct_ordering(axis, iteration):
                break
        if best is None:
            return None
        return best + (self.order[len(self.order) - 1],)

    def _emit(self, nmode):
        r = self._run(nmode)
        if r is None:
            return None
        err, a, b, i, j, k, order = r
        unordered = [0] * 16
        rng = [(0, i, 0), (i, j, 2), (j, k if nmode == 4 else len(self.points),
                                       3 if nmode == 4 else 1)]
        for m0, m1, val in rng:
            for m in range(m0, m1):
                unordered[order[m]] = val
        if nmode == 4:
            for m in range(k, len(self.points)):
                unordered[order[m]] = 1
        indices = _remap_indices(unordered, self.remap)
        blk = (_write_colour_block3 if nmode == 3 else _write_colour_block4)(a, b, indices)
        return blk, err

    def _curr(self, iteration):
        """取第 iteration 个 ordering 的加权点与总和。"""
        order = self.order[iteration]
        pws = [(self.points[j][0] * self.weights[j], self.points[j][1] * self.weights[j], self.points[j][2] * self.weights[j],
                    self.weights[j]) for j in order]
        xw = [sum(c) for c in zip(*pws)] if pws else [0.0] * 4
        return order, pws, xw

    def _search3(self, count):
        """三簇 [0,i)/[i,j)/[j,count)：仅当严格优于 self.besterror 时返回。"""
        iteration = len(self.order) - 1
        order, pws, xw = self._curr(iteration)
        besterror = self.besterror
        best = None
        part0 = [0.0] * 4
        for i in range(count):
            part1 = list(pws[0]) if i == 0 else [0.0] * 4
            j = 1 if i == 0 else i
            while True:
                part2 = [xw[c] - part1[c] - part0[c] for c in range(4)]
                alphax = [part1[c] * 0.5 + part0[c] for c in range(4)]
                alpha2 = alphax[3]
                betax = [part1[c] * 0.5 + part2[c] for c in range(4)]
                beta2 = betax[3]
                alphabeta = part1[3] * 0.25
                r = self._ls(alphax, alpha2, betax, beta2, alphabeta)
                if r is not None:
                    a, b, err = r
                    if err < besterror:
                        besterror = err
                        best = (err, a, b, i, j, count)
                if j == count:
                    break
                for c in range(4):
                    part1[c] += pws[j][c]
                j += 1
            for c in range(4):
                part0[c] += pws[i][c]
        return best

    def _search4(self, count):
        """四簇 [0,i)/[i,j)/[j,k)/[k,count)。"""
        iteration = len(self.order) - 1
        order, pws, xw = self._curr(iteration)
        besterror = self.besterror
        best = None
        ot23 = (1.0 / 3.0,) * 3 + (1.0 / 9.0,)
        tt23 = (2.0 / 3.0,) * 3 + (4.0 / 9.0,)
        tn = 2.0 / 9.0
        part0 = [0.0] * 4
        for i in range(count):
            part1 = [0.0] * 4
            j = i
            while True:
                part2 = list(pws[0]) if j == 0 else [0.0] * 4
                k = 1 if j == 0 else j
                while True:
                    part3 = [xw[c] - part2[c] - part1[c] - part0[c]
                             for c in range(4)]
                    alphax = [part2[c] * ot23[c] + part1[c] * tt23[c]
                              + part0[c] for c in range(4)]
                    alpha2 = alphax[3]
                    betax = [part1[c] * ot23[c] + part2[c] * tt23[c]
                             + part3[c] for c in range(4)]
                    beta2 = betax[3]
                    alphabeta = tn * (part1[3] + part2[3])
                    r = self._ls(alphax, alpha2, betax, beta2, alphabeta)
                    if r is not None:
                        a, b, err = r
                        if err < besterror:
                            besterror = err
                            best = (err, a, b, i, j, k)
                    if k == count:
                        break
                    for c in range(4):
                        part2[c] += pws[k][c]
                    k += 1
                if j == count:
                    break
                for c in range(4):
                    part1[c] += pws[j][c]
                j += 1
            for c in range(4):
                part0[c] += pws[i][c]
        return best


def _cluster_compress_block(points, weights, remap, nmode):
    """ClusterFit 单块（nmode=3/4）。返回 (block_bytes, error) 或 None。"""
    fit = _ClusterFit(points, weights)
    r = fit._run(nmode)  # 兼容入口
    if r is None:
        return None
    err, a, b, i, j, k, order = r
    if nmode == 3:
        unordered = [0] * 16
        for m in range(i):
            unordered[order[m]] = 0
        for m in range(i, j):
            unordered[order[m]] = 2
        for m in range(j, len(points)):
            unordered[order[m]] = 1
        indices = _remap_indices(unordered, remap)
        blk = _write_colour_block3(a, b, indices)
    else:
        unordered = [0] * 16
        for m in range(i):
            unordered[order[m]] = 0
        for m in range(i, j):
            unordered[order[m]] = 2
        for m in range(j, k):
            unordered[order[m]] = 3
        for m in range(k, len(points)):
            unordered[order[m]] = 1
        indices = _remap_indices(unordered, remap)
        blk = _write_colour_block4(a, b, indices)
    return blk, err


# ------------------------------------------------------------- SingleColourFit

def _single_colour_fit(points, remap, nmode):
    colour = (_ftoi(255.0 * points[0][0], 255),
              _ftoi(255.0 * points[0][1], 255),
              _ftoi(255.0 * points[0][2], 255))
    tables = (LOOKUP_5_3, LOOKUP_6_3, LOOKUP_5_3) if nmode == 3 else \
             (LOOKUP_5_4, LOOKUP_6_4, LOOKUP_5_4)
    besterr = 0x7FFFFFFF
    best = None
    for index in range(2):
        sources = []
        err = 0
        for ch in range(3):
            s0, s1 = tables[ch][colour[ch]][0:3], tables[ch][colour[ch]][3:6]
            src = s0 if index == 0 else s1
            sources.append(src)
            err += src[2] * src[2]
        if err < besterr:
            besterr = err
            start = (sources[0][0] / 31.0, sources[1][0] / 63.0,
                     sources[2][0] / 31.0)
            end = (sources[0][1] / 31.0, sources[1][1] / 63.0,
                   sources[2][1] / 31.0)
            idx = 2 * index
            best = (start, end, idx, err)
    if best is None:
        return None
    start, end, idx, err = best
    indices = _remap_indices([idx] * len(points), remap)
    if nmode == 3:
        return _write_colour_block3(start, end, indices), err
    return _write_colour_block4(start, end, indices), err


# ------------------------------------------------------------------ RangeFit

def _range_fit(points, remap, nmode):
    count = len(points)
    if count:
        principle = _principle_component(_covariance(points, [1.0] * count))
        start = end = points[0]
        dmin = dmax = sum(p * q for p, q in zip(points[0], principle))
        for p in points[1:]:
            d = sum(x * q for x, q in zip(p, principle))
            if d < dmin:
                start, dmin = p, d
            elif d > dmax:
                end, dmax = p, d
    else:
        start = end = (0.0, 0.0, 0.0)
    def grid(c):
        return tuple(int(_GRID[ch] * min(1.0, max(0.0, c[ch])) + 0.5)
                     * _GRIDRCP[ch] for ch in range(3))
    start, end = grid(start), grid(end)
    if nmode == 3:
        codes = [start, end,
                 tuple(0.5 * (start[c] + end[c]) for c in range(3))]
    else:
        codes = [start,
                 tuple((2.0 * start[c] + end[c]) / 3.0 for c in range(3)),
                 tuple((start[c] + 2.0 * end[c]) / 3.0 for c in range(3)),
                 end]
    unordered = []
    for p in points:
        best, idx = float('inf'), 0
        for ci, code in enumerate(codes):
            d = sum(_METRIC[c] * (p[c] - code[c]) ** 2 for c in range(3))
            if d < best:
                best, idx = d, ci
        unordered.append(idx)
    indices = _remap_indices(unordered, remap)
    if nmode == 3:
        return _write_colour_block3(start, end, indices)
    return _write_colour_block4(start, end, indices)


# ------------------------------------------------------------------ alpha

def _compress_alpha_dxt3(rgba, mask):
    out = bytearray(8)
    for i in range(8):
        q1 = _ftoi(rgba[8 * i + 3] * (15.0 / 255.0), 15)
        q2 = _ftoi(rgba[8 * i + 7] * (15.0 / 255.0), 15)
        if not (mask >> (2 * i)) & 1:
            q1 = 0
        if not (mask >> (2 * i + 1)) & 1:
            q2 = 0
        out[i] = q1 | (q2 << 4)
    return bytes(out)


def _fix_range(mn, mx, steps):
    if mx - mn < steps:
        mx = min(mn + steps, 255)
    if mx - mn < steps:
        mn = max(0, mx - steps)
    return mn, mx


def _fit_codes(rgba, mask, codes):
    indices = [0] * 16
    err = 0
    for i in range(16):
        if not (mask >> i) & 1:
            continue
        value = rgba[4 * i + 3]
        least, index = 0x7FFFFFFF, 0
        for j in range(8):
            dist = (value - codes[j]) ** 2
            if dist < least:
                least, index = dist, j
        indices[i] = index
        err += least
    return indices, err


def _write_alpha_block(a0, a1, indices):
    out = bytearray(8)
    out[0], out[1] = a0, a1
    v = 0
    for j in range(16):
        v |= indices[j] << (3 * j)
    out[2:8] = v.to_bytes(6, 'little')
    return bytes(out)


def _write_alpha_block5(a0, a1, indices):
    if a0 > a1:
        a0, a1 = a1, a0
        indices = [1 if k == 0 else (0 if k == 1 else (7 - k if k <= 5 else k))
                   for k in indices]
    return _write_alpha_block(a0, a1, indices)


def _write_alpha_block7(a0, a1, indices):
    if a0 < a1:
        a0, a1 = a1, a0
        indices = [1 if k == 0 else (0 if k == 1 else 9 - k) for k in indices]
    return _write_alpha_block(a0, a1, indices)


def _compress_alpha_dxt5(rgba, mask):
    min5, max5, min7, max7 = 255, 0, 255, 0
    for i in range(16):
        if not (mask >> i) & 1:
            continue
        v = rgba[4 * i + 3]
        if v < min7:
            min7 = v
        if v > max7:
            max7 = v
        if v != 0 and v < min5:
            min5 = v
        if v != 255 and v > max5:
            max5 = v
    if min5 > max5:
        min5 = max5
    if min7 > max7:
        min7 = max7
    min5, max5 = _fix_range(min5, max5, 5)
    min7, max7 = _fix_range(min7, max7, 7)
    codes5 = [min5, max5] + [((5 - i) * min5 + i * max5) // 5 for i in range(1, 5)] + [0, 255]
    codes7 = [min7, max7] + [((7 - i) * min7 + i * max7) // 7 for i in range(1, 7)]
    ind5, err5 = _fit_codes(rgba, mask, codes5)
    ind7, err7 = _fit_codes(rgba, mask, codes7)
    if err5 <= err7:
        return _write_alpha_block5(min5, max5, ind5)
    return _write_alpha_block7(min7, max7, ind7)


# ------------------------------------------------------------------ 分发

def compress_masked(rgba, mask, mode):
    """压缩单个 4x4 块。rgba: 64 字节；mask: 16 位；mode: 'dxt1'|'dxt3'|'dxt5'。
    返回 8 字节(dxt1) 或 16 字节。"""
    is_dxt1 = mode == 'dxt1'
    points, weights, remap, transparent = _colourset(rgba, mask, is_dxt1)
    count = len(points)

    def colour_part():
        if count == 1:
            r3 = _single_colour_fit(points, remap, 3)
            r4 = _single_colour_fit(points, remap, 4)
        elif count == 0:
            r3 = (_range_fit(points, remap, 3), float('inf'))
            r4 = (_range_fit(points, remap, 4), float('inf'))
        else:
            # C++ 语义：Compress3 先行，Compress4 以其误差为基线，严格更优才覆盖
            fit = _ClusterFit(points, weights, remap)
            r3 = fit._emit(3)
            r4 = fit._emit(4)
        return r3, r4

    if is_dxt1:
        r3, r4 = colour_part()
        if transparent:
            return r3[0] if r3 else _write_colour_block3((0, 0, 0), (0, 0, 0), [3] * 16)
        best = None
        besterr = float('inf')
        for r in (r3, r4):
            if r and r[1] < besterr:
                best, besterr = r, r[1]
        return best[0] if best else _write_colour_block4((0, 0, 0), (0, 0, 0), [0] * 16)

    # dxt3/dxt5：alpha 块在前 + 颜色块（仅 4 色）
    alpha = _compress_alpha_dxt3(rgba, mask) if mode == 'dxt3' else \
        _compress_alpha_dxt5(rgba, mask)
    # 注意：DXT3/5 时 ColourSet 不剔除透明（is_dxt1=False）
    if count == 1:
        r4 = _single_colour_fit(points, remap, 4)
        colour = r4[0]
    elif count == 0:
        colour = _range_fit(points, remap, 4)
    else:
        colour = _cluster_compress_block(points, weights, remap, 4)[0]
    return alpha + colour


def compress_image(rgba, w, h, mode):
    """全图压缩（CompressImage 边缘 mask 语义：越界像素不参与）。"""
    bw, bh = (w + 3) // 4, (h + 3) // 4
    bsize = 8 if mode == 'dxt1' else 16
    out = bytearray(bsize * bw * bh)
    o = 0
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            src = bytearray(64)
            mask = 0
            for py in range(4):
                for px in range(4):
                    sx, sy = x + px, y + py
                    if sx < w and sy < h:
                        i = 4 * (w * sy + sx)
                        src[4 * (4 * py + px):4 * (4 * py + px) + 4] = rgba[i:i + 4]
                        mask |= 1 << (4 * py + px)
            out[o:o + bsize] = compress_masked(bytes(src), mask, mode)
            o += bsize
    return bytes(out)
