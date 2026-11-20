# 在 Origin 内置 Python 中运行（由 origin_plot.py 填入 @@SPEC@@ 后调用 run -pyf）。
# 兼容 Origin 2021 的 originpro：没有 op.pages()、GLayer 没有 lt_exec，样式一律用 LabTalk 设置。
import originpro as op, json, math, re, traceback

SPEC_PATH = '@@SPEC@@'
BS = chr(92)  # 反斜杠；避免 shell/heredoc 吞掉 \f 之类的转义
log = []

CONNECT = {'spline': 9, 'straight': 1, 'bspline': 8, 'none': 0}
PTYPE = {'line_symbol': 202, 'line': 200, 'scatter': 201, 'column': 203}
CJK = re.compile(r'([　-〿一-鿿＀-￯]+)')


def LT(cmd):
    if not op.lt_exec(cmd):
        log.append('FAIL: ' + cmd[:200])


def rich(text, st):
    """中文片段用中文字体（\\f:字体(...)），其余沿用英文字体；转义 LabTalk 的引号。"""
    text = text.replace('"', "'")
    return CJK.sub(lambda m: BS + 'f:' + st['font']['cn'] + '(' + m.group(1) + ')', text)


def color(c):
    return 'color(%s)' % c


def nice_axis(vals, target=5, pad=0.03):
    """按全部数据算整齐的 (from, to, inc)：步长取 1/2/5×10^n，间隔数尽量接近 target，上下限为步长整数倍。
    不用 Origin 自动步长：它只按第一条曲线的范围定步长，多曲线时刻度会很密。"""
    lo0, hi0 = min(vals), max(vals)
    span = hi0 - lo0
    if span == 0:                                 # 全部相同：上下各留半个跨度
        span = abs(lo0) * 0.2 or 1.0
        lo0, hi0 = lo0 - span / 2, hi0 + span / 2
    lo, hi = lo0 - span * pad, hi0 + span * pad
    if lo0 >= 0 > lo:                             # 非负数据不因留白跨到负半轴
        lo = 0.0
    if hi0 <= 0 < hi:
        hi = 0.0
    best = None
    k0 = math.floor(math.log10(span / target))
    for k in range(k0 - 1, k0 + 2):
        for m in (1, 2, 5):
            inc = m * 10 ** k
            f = math.floor(lo / inc + 1e-9) * inc
            t = math.ceil(hi / inc - 1e-9) * inc
            n = round((t - f) / inc)
            key = (abs(n - target), t - f)        # 先比间隔数接近 target，再比留白少
            if best is None or key < best[0]:
                best = (key, f, t, inc)
    _, f, t, inc = best
    # 数据只是略微越过 0（如 -0.001，测量噪声）时不多让出一整格：边界只留 pad 空白、不取整。
    # Origin 的刻度标签按步长整数倍定位，所以标签仍是 0、inc、2inc…
    if lo0 < 0 <= f + inc and -lo0 <= 0.05 * span and f < lo:
        f = min(lo, 0.0)
    if hi0 > 0 >= t - inc and hi0 <= 0.05 * span and t > hi:
        t = max(hi, 0.0)
    r = lambda v: float('%.12g' % v)              # 去掉 0.30000000000000004 之类的浮点尾巴
    return r(f), r(t), r(inc)


def set_axis(a, r):
    LT('layer.%s.from=%g; layer.%s.to=%g;' % (a, r[0], a, r[1]))
    if len(r) > 2 and r[2]:
        LT('layer.%s.inc=%g;' % (a, r[2]))


LEG_X, LEG_Y = 0.04, 0.05                         # 图例离坐标框左右 / 上下边的距离（占框宽、框高的比例）


def legend_box(pos, w, h):
    """图例在坐标框内的位置，返回 (左, 右, 下, 上)，均为 0~1 的比例坐标。"""
    x0 = LEG_X if pos[1] == 'l' else 1 - LEG_X - w
    y0 = 1 - LEG_Y - h if pos[0] == 't' else LEG_Y
    return x0, x0 + w, y0, y0 + h


LINE_M = 0.004                                    # 连线半线宽（占坐标框比例）：连线只有真正穿进图例框才算压线
SYM_M = 0.0015                                    # 每 1 号符号大小对应的半径（9 号符号约 0.014 个框宽）


def curve_points(p, st, n=16):
    """把每条曲线加密成折线点 (x, y, 余量)，用于判断图例是否压线。样条用 Catmull-Rom 近似 Origin 的样条。
    数据点的余量是符号半径（有符号时），连线上插出的点只算半线宽，避免曲线只是从图例旁边擦过也被判成压线。"""
    pts = []
    ptype = p.get('plot_type', st['plot_type'])
    for s in p['series']:
        P = list(zip(s['x'], s['y']))
        spline = s.get('connect', p.get('connect', st['line']['connect'])) == 'spline'
        rs = SYM_M * s.get('symbol_size', st['symbol_size']) if ptype in ('line_symbol', 'scatter') else LINE_M
        for i in range(len(P) - 1):
            p0, p1, p2 = P[max(i - 1, 0)], P[i], P[i + 1]
            p3 = P[min(i + 2, len(P) - 1)]
            pts.append(p1 + (rs,))
            if ptype == 'scatter':
                continue
            for j in range(1, n):
                t = j / n
                if spline:
                    q = tuple(0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t * t
                                     + (-a + 3 * b - 3 * c + d) * t ** 3) for a, b, c, d in zip(p0, p1, p2, p3))
                else:
                    q = (p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t)
                pts.append(q + (LINE_M,))
        pts.extend(q + (rs,) for q in P[-1:])
    return pts


def frac(v, r):
    return (v - r[0]) / (r[1] - r[0])


def hits(pts, box, rng):
    """落在图例框（四周外扩各点自己的余量）里的曲线点。"""
    return [(x, y, m) for x, y, m in pts
            if box[0] - m < frac(x, rng['x']) < box[1] + m and box[2] - m < frac(y, rng['y']) < box[3] + m]


LEG_GAP = 0.02                                    # 扩坐标后曲线与图例之间再留的空（占坐标框比例）


def fit_legend(p, pts, box, pos, auto, rng, ax):
    """图例压到曲线时扩展坐标范围：优先扩纵轴（图例在上就抬高上限，在下就压低下限）；纵轴范围是用户指定的
    才改扩横轴。只扩到曲线刚好不碰图例、再留 LEG_GAP 的空，步长不变，新边界按 步长/10 向外取整；
    不再跳到下一个整齐刻度（那样常常一下扩出一大截空白）。"""
    for _ in range(8):
        if not hits(pts, box, rng):
            return
        if 'y' in auto:
            a, (lo, hi) = 'y', rng['y']
            band = [(y, m) for x, y, m in pts if box[0] - m < frac(x, rng['x']) < box[1] + m]
            if pos[0] == 't':                      # 曲线需低于图例下沿：(y-lo)/(hi-lo) <= box[2]-m-GAP
                hi = max([hi] + [lo + (y - lo) / (box[2] - m - LEG_GAP) for y, m in band if y > lo])
            else:                                  # 曲线需高于图例上沿
                g = [(y, box[3] + m + LEG_GAP) for y, m in band]
                lo = min([lo] + [(y - k * hi) / (1 - k) for y, k in g if y < hi])
        elif 'x' in auto:
            a, (lo, hi) = 'x', rng['x']
            band = [(x, m) for x, y, m in pts if box[2] - m < frac(y, rng['y']) < box[3] + m]
            if pos[1] == 'l':                      # 曲线需在图例右边
                g = [(x, box[1] + m + LEG_GAP) for x, m in band]
                lo = min([lo] + [(x - k * hi) / (1 - k) for x, k in g if x < hi])
            else:
                hi = max([hi] + [lo + (x - lo) / (box[0] - m - LEG_GAP) for x, m in band if x > lo])
        else:
            log.append('提示 %s: 图例压线，但 x_range、y_range 都已指定，未自动调整' % p.get('name', ''))
            return
        inc = op.lt_float('layer.%s.inc' % a)
        q = inc / 10                               # 新边界向外取到 步长/10 的整数倍，数值好看一点
        r = (float('%.12g' % (math.floor(lo / q + 1e-9) * q)), float('%.12g' % (math.ceil(hi / q - 1e-9) * q)), inc)
        set_axis(a, r)
        rng[a] = (r[0], r[1])
        log.append('%s 轴为避让图例调整 %s: from=%g to=%g inc=%g' % (a, p.get('name', ''), r[0], r[1], r[2]))
    if hits(pts, box, rng):
        log.append('提示 %s: 调整 8 次后图例仍压线，请手动设 legend 位置或坐标范围' % p.get('name', ''))


try:
    spec = json.load(open(SPEC_PATH, encoding='utf-8'))
    st = spec['style']
    out = spec['out_dir']
    wks = op.new_sheet('w', lname=spec['name'] + '_data')
    # 1. 数据写入工作表：每个系列占 X、Y 两列
    col = 0
    for p in spec['panels']:
        for s in p['series']:
            wks.from_list(col, s['x'], lname=p.get('x_title', ''), comments=p.get('name', ''))
            wks.from_list(col + 1, s['y'], lname=p.get('y_title', ''), comments=s.get('label', ''))
            s['_c'] = col
            col += 2
    wks.cols_axis('xy' * (col // 2))

    en, cn = st['font']['en'], st['font']['cn']
    for p in spec['panels']:
        pst = dict(st)
        ptype = PTYPE[p.get('plot_type', st['plot_type'])]
        gp = op.new_graph(lname='%s_%s' % (spec['name'], p.get('name', '')))
        gl = gp[0]
        for s in p['series']:
            gl.add_plot(wks, coly=s['_c'] + 1, colx=s['_c'], type=ptype)
        gl.rescale()
        LT('win -a %s;' % gp.name)
        # 2. 系列样式
        for i, s in enumerate(p['series']):
            c = s.get('color', st['palette'][i % len(st['palette'])])
            k = s.get('symbol', st['symbols'][i % len(st['symbols'])])
            d = s.get('dash', st['line']['dash'][i % len(st['line']['dash'])])
            conn = CONNECT[s.get('connect', p.get('connect', st['line']['connect']))]
            cmd = 'layer.plot=%d; set %%C -c %s;' % (i + 1, color(c))
            if ptype in (202, 200):
                cmd += ' set %%C -cl %s; set %%C -w %d; set %%C -d %d; set %%C -l %d;' % (color(c), st['line']['width'], d, conn)
            if ptype in (202, 201):
                cmd += ' set %%C -cf %s; set %%C -k %d; set %%C -z %g;' % (color(c), k, s.get('symbol_size', st['symbol_size']))
            if ptype == 203:
                cmd += ' set %%C -cf %s;' % color(c)
            LT(cmd)
        # 3. 坐标轴
        LT('xb.text$="%s"; yl.text$="%s";' % (rich(p.get('x_title', ''), st), rich(p.get('y_title', ''), st)))
        LT('xb.font=font(%s); yl.font=font(%s); xb.fsize=%g; yl.fsize=%g;' % (en, en, st['size']['axis_title'], st['size']['axis_title']))
        LT('layer.x.label.font=font(%s); layer.y.label.font=font(%s); layer.x.label.pt=%g; layer.y.label.pt=%g;'
           % (en, en, st['size']['tick_label'], st['size']['tick_label']))
        ax = st['axes']
        if ax['frame']:
            LT('layer.x.showAxes=3; layer.y.showAxes=3;')
            if not ax.get('show_top_right_labels'):
                LT('layer.x2.label.show=0; layer.y2.label.show=0;')
        tk = {'in': 5, 'out': 10, 'none': 0}[ax['ticks']]          # 1 主刻度朝内 + 4 次刻度朝内；2+8 朝外
        tk2 = tk if ax.get('top_right_ticks') else 0                # 上/右轴：只留边框线，不画刻度
        LT('layer.x.ticks=%d; layer.y.ticks=%d; layer.x2.ticks=%d; layer.y2.ticks=%d;' % (tk, tk, tk2, tk2))
        LT('layer.x.thickness=%g; layer.y.thickness=%g;' % (ax['thickness'], ax['thickness']))
        auto, rng = {}, {}                         # auto: 自动刻度轴参与计算的数据；rng: 各轴当前 (from, to)
        for a in ('x', 'y'):
            r = p.get(a + '_range')
            if not r:                              # 未指定范围：按本图全部系列自算步长
                auto[a] = [v for s in p['series'] for v in s[a]]
                r = nice_axis(auto[a], ax.get('major_intervals', 5), ax.get('pad', 0.03))
                log.append('%s 轴自动刻度 %s: from=%g to=%g inc=%g' % (a, p.get('name', ''), r[0], r[1], r[2]))
            set_axis(a, r)
            rng[a] = (r[0], r[1])
        # 4. 图例：手写图例文本，中文同样走中文字体
        lg = dict(st['legend'])
        if isinstance(p.get('legend'), dict):
            lg.update(p['legend'])
        elif isinstance(p.get('legend'), str):
            lg['position'] = p['legend']
        elif p.get('legend') is False:
            lg['show'] = False
        if lg['show']:
            lines = [BS + 'l(%d) %s' % (i + 1, rich(s.get('label', ''), st)) for i, s in enumerate(p['series'])]
            LT('legend -r;')
            LT('legend.text$="%s";' % '%(CRLF)'.join(lines))   # LabTalk 字符串里 \n 不换行，要用 %(CRLF)
            LT('legend.background=%d; legend.font=font(%s); legend.fsize=%g;' % (1 if lg['border'] else 0, en, st['size']['legend']))
            pos = lg['position']
            # 图例宽高占坐标框的比例（物理尺寸固定，与坐标范围无关）
            w = op.lt_float('legend.dx') / (rng['x'][1] - rng['x'][0])
            h = op.lt_float('legend.dy') / (rng['y'][1] - rng['y'][0])
            box = legend_box(pos, w, h)
            pts = curve_points(p, st)
            if lg.get('avoid', True):
                # 先试默认位置，压线就换备选位置（默认 tl → tr）；都压线才回到默认位置并扩坐标范围
                for alt in [pos] + [q for q in lg.get('fallback', []) if q != pos]:
                    if not hits(pts, legend_box(alt, w, h), rng):
                        if alt != pos:
                            log.append('图例 %s: %s 压线，改放 %s' % (p.get('name', ''), pos, alt))
                        pos, box = alt, legend_box(alt, w, h)
                        break
                else:
                    fit_legend(p, pts, box, pos, auto, rng, ax)
            X, Y = rng['x'], rng['y']
            LT('legend.x=%g; legend.y=%g;' % (X[0] + (box[0] + w / 2) * (X[1] - X[0]), Y[0] + (box[2] + h / 2) * (Y[1] - Y[0])))
        else:
            LT('label -r legend;')
        # 5. 导出
        fn = spec['name'] + ('_' + p['name'] if len(spec['panels']) > 1 else '') + '.png'
        gp.save_fig(out + '/' + fn, width=st['export']['png_width'])
        log.append('PNG: ' + fn)
except Exception:
    log.append(traceback.format_exc())
open(SPEC_PATH + '.log', 'w', encoding='utf-8').write(chr(10).join(log))
