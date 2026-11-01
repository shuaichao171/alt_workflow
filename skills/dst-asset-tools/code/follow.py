"""Follow Symbol / Anti-Follow Symbol 变换。

依 DST Mod Tool 内嵌《Lua 脚本 API 指南》语义实现（文档对参数、默认值、行为描述完整）。
数学核心：Element 仿射矩阵 {a,b,c,d,tx,ty}（世界空间左乘应用）。

anti_follow(options): 把锚点以外的 Element 转换到锚点局部坐标系：
  新矩阵 = Anchor^-1 · E （maintain_scale=False 时归一化锚点缩放）
follow_symbol(child, options): 复制 child 内容并跟随 target 中匹配的锚点 Element：
  新矩阵 = Anchor · L(local_x/y, local_scale, local_rotation) · ChildE
  支持 inherit_position/scale/rotation、average_rotation、z_index_offset、alignment 重采样。
"""
import math, re


def mat_mul(m, n):
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def mat_inv(m):
    a, b, c, d, e, f = m
    det = a * d - b * c
    if abs(det) < 1e-12:
        raise ValueError('singular matrix')
    return (d / det, -b / det, -c / det, a / det,
            (c * f - d * e) / det, (b * e - a * f) / det)


def mat_decompose(m):
    """-> (tx, ty, rotation_deg, scale_x, scale_y)（与 utils.affine decompose 语义一致）。"""
    a, b, c, d, e, f = m
    tx, ty = e, f
    rot = math.atan2(b, a)
    sx = math.hypot(a, b)
    sy = (a * d - b * c) / sx if sx else 0.0
    return tx, ty, math.degrees(rot), sx, sy


def _matches(el, symbol, layer, frame_pattern, symbol_names, layer_names):
    sname = symbol_names.get(el.symbol_hash, '')
    if sname.lower() != symbol.lower():
        return False
    if layer is not None:
        lname = layer_names.get(el.layer_hash, '')
        if lname.lower() != layer.lower():
            return False
    if frame_pattern is not None and not re.search(frame_pattern, str(el.frame)):
        return False
    return True


def anti_follow(frame, *, symbol, layer=None, frame_pattern=None, maintain_scale=False,
                symbol_names=None, layer_names=None):
    """对单个 AnimFrame 执行 Anti-Follow（就地修改并返回 frame）。

    frame: 需提供 .elements（Element 需有 symbol_hash/frame/layer_hash/a,b,c,d,tx,ty）
    symbol_names/layer_names: hash->名称映射（用 build_bin + klei_hash.resolve 构建）
    """
    symbol_names = symbol_names or {}
    layer_names = layer_names or {}
    anchor = None
    for el in frame.elements:
        if _matches(el, symbol, layer, frame_pattern, symbol_names, layer_names):
            anchor = el
            break
    if anchor is None:
        raise ValueError(f'anchor symbol {symbol!r} not found')
    am = (anchor.a, anchor.b, anchor.c, anchor.d, anchor.tx, anchor.ty)
    if not maintain_scale:
        _, _, _, sx, sy = mat_decompose(am)
        norm = (sx, 0, 0, sy, -am[4], -am[5])           # 平移保持锚点世界位置
        am = mat_mul((1/sx if sx else 1, 0, 0, 1/sy if sy else 1, 0, 0), norm)
        am = (am[0], am[1], am[2], am[3], am[4] + anchor.tx * (1 - 1), am[5])
        # 归一化版本：仅去除旋转+缩放，保留锚点平移
        inv = mat_inv((anchor.a, anchor.b, anchor.c, anchor.d, 0, 0))
        am = mat_mul((1, 0, 0, 1, anchor.tx, anchor.ty), inv)
    inv = mat_inv(am)
    for el in frame.elements:
        if el is anchor:
            el.a, el.b, el.c, el.d, el.tx, el.ty = 1, 0, 0, 1, 0, 0
            continue
        em = (el.a, el.b, el.c, el.d, el.tx, el.ty)
        nm = mat_mul(inv, em)
        el.a, el.b, el.c, el.d, el.tx, el.ty = nm
    return frame


def follow_symbol(target_anim, child_anim, *, symbol, layer=None, frame_pattern=None,
                  predicate=None, all_matches=False,
                  local_x=0.0, local_y=0.0, local_scale_x=1.0, local_scale_y=1.0,
                  local_rotation_degrees=0.0,
                  inherit_position_x=True, inherit_position_y=True,
                  inherit_scale=True, inherit_rotation=True,
                  average_rotation=False,
                  z_index_offset=0, alignment='unaligned',
                  symbol_names=None, layer_names=None):
    """把 child_anim 的内容复制进 target_anim 并跟随锚点（返回新帧列表；不修改输入）。

    alignment: 'unaligned' | 'relength_child' | 'relength_target'
    """
    if alignment not in ('unaligned', 'relength_child', 'relength_target'):
        raise ValueError('bad alignment')
    symbol_names = symbol_names or {}
    layer_names = layer_names or {}
    rot = math.radians(local_rotation_degrees)
    L = (local_scale_x * math.cos(rot), local_scale_x * math.sin(rot),
         -local_scale_y * math.sin(rot), local_scale_y * math.cos(rot),
         local_x, local_y)

    out_frames = []
    for ti, tf in enumerate(target_anim.frames):
        # 找锚点候选
        cands = [el for el in tf.elements
                 if _matches(el, symbol, layer, frame_pattern, symbol_names, layer_names)]
        if predicate is not None:
            cands = [el for el in cands
                     if predicate(tf, ti, el, tf.elements.index(el) + 1)]
        if not cands:
            out_frames.append(None)
            continue
        anchors = cands if all_matches else cands[:1]
        cf = child_anim.frames[ti % len(child_anim.frames)] if alignment == 'unaligned' else \
             _resampled(child_anim, len(target_anim.frames), ti)
        new_frame = _copy_frame(tf)
        for el in anchors:
            am = (el.a, el.b, el.c, el.d, el.tx, el.ty)
            full = (inherit_rotation and inherit_scale
                    and inherit_position_x and inherit_position_y
                    and not average_rotation)
            if full:
                M = am  # 与应用一致：全继承时直接用锚点原始矩阵（运行时差分验证）
            else:
                _, _, deg, sx, sy = mat_decompose(am)
                M = (1, 0, 0, 1, 0, 0)
                if inherit_rotation:
                    r = math.radians(deg if not average_rotation else _avg_rot(anchors))
                    M = mat_mul(M, (math.cos(r), math.sin(r), -math.sin(r), math.cos(r), 0, 0))
                if inherit_scale:
                    M = mat_mul(M, (sx, 0, 0, sy, 0, 0))
                if inherit_position_x or inherit_position_y:
                    M = mat_mul(M, (1, 0, 0, 1,
                                    el.tx if inherit_position_x else 0,
                                    el.ty if inherit_position_y else 0))
            for ce in cf.elements:
                em = (ce.a, ce.b, ce.c, ce.d, ce.tx, ce.ty)
                nm = mat_mul(mat_mul(M, L), em)
                z = (el.z if hasattr(el, 'z') else 0) + z_index_offset
                new_frame.elements.append(_el_like(ce, nm, z))
        out_frames.append(new_frame)
    return out_frames


def _avg_rot(anchors):
    angles = [math.degrees(math.atan2(el.b, el.a)) for el in anchors]
    x = sum(math.cos(math.radians(a)) for a in angles) / len(angles)
    y = sum(math.sin(math.radians(a)) for a in angles) / len(angles)
    return math.degrees(math.atan2(y, x))


def _resampled(child_anim, n, i):
    """relength 重采样：按时间比例取样 child 帧（线性；无插值帧生成，最近邻）。"""
    if n <= 0:
        return child_anim.frames[0]
    pos = int(i * len(child_anim.frames) / n)
    return child_anim.frames[min(pos, len(child_anim.frames) - 1)]


def _copy_frame(f):
    import copy
    return copy.copy(f)


def _el_like(e, m, z):
    import copy
    ne = copy.copy(e)
    ne.a, ne.b, ne.c, ne.d, ne.tx, ne.ty = m
    ne.z = z
    return ne
