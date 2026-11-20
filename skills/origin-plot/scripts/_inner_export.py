# 在 Origin 内置 Python 中运行（由 opju_export.py 填入占位符）：导出当前项目所有工作表为 CSV、所有图为 PNG，
# 并写 info.json（工作簿/列标签、图的坐标轴标题）。DATASETS=1 时先把图里引用的隐藏数据集复制进新工作簿
# （PPT/Word 内嵌 Origin 图的数据通常只以隐藏数据集形式存在）。
import originpro as op, os, json, csv, traceback

OUT = '@@OUT@@'
DATASETS = @@DATASETS@@
log = []


def names(cmd):
    op.lt_exec('string __s$=""; ' + cmd)
    return [n for n in op.get_lt_str('__s$').split('|') if n]


def layers(pg):
    try:
        return list(pg)
    except Exception:
        return []


try:
    os.makedirs(OUT + '/csv', exist_ok=True)
    os.makedirs(OUT + '/png', exist_ok=True)
    graphs = names('doc -e P {__s$=__s$+"%H|";}')
    if DATASETS:
        pairs = []
        for g in graphs:
            if not op.lt_exec('win -a %s; page.active=1; layer -c; __cnt=count;' % g):
                continue
            for i in range(1, int(op.lt_float('__cnt')) + 1):
                op.lt_exec('string __y$="%%(%d,@D)"; string __x$="%%(%d,@X)"; string __lg$="%%(%d,@LG)";' % (i, i, i))
                y, x, lg = op.get_lt_str('__y$'), op.get_lt_str('__x$'), op.get_lt_str('__lg$')
                # 2021 版 @X 常取不到（返回 ###）：按“Book_B 的 X 是 Book_A”的命名惯例推断，需人工核对
                if (not x or x.startswith('#')) and '_' in y:
                    x = y[:-1] + chr(ord(y[-1]) - 1)
                if y and y not in [p[1] for p in pairs]:
                    pairs.append((g, y, x, lg))
        if pairs:
            op.lt_exec('newbook result:=__bk$;')
            k = 0
            for g, y, x, lg in pairs:
                for n in (x, y):
                    k += 1
                    op.lt_exec('win -a %%(__bk$); wks.ncols=%d; col(%d)=%s; col(%d)[L]$="%s"; col(%d)[C]$="%s %s";'
                               % (k, k, n, k, n, k, g, lg))
            log.append('datasets copied: %d' % k)

    info = {'books': [], 'graphs': []}
    for bn in names('doc -e W {__s$=__s$+"%H|";}'):
        wb = op.find_book('w', bn)
        if wb is None:
            continue
        b = {'name': wb.name, 'long': wb.lname, 'sheets': []}
        for wks in layers(wb):
            cols, data = [], []
            for i in range(wks.cols):
                cols.append({k: wks.get_label(i, k) for k in ('L', 'U', 'C')})
                try:
                    data.append(wks.to_list(i))
                except Exception:
                    data.append([])
            b['sheets'].append({'name': wks.name, 'cols': cols, 'rows': max([len(v) for v in data] or [0])})
            with open('%s/csv/%s__%s.csv' % (OUT, wb.name, wks.name), 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                for key in ('L', 'U', 'C'):     # 前三行：长名称、单位、注释
                    w.writerow([c[key] for c in cols])
                for r in range(max([len(v) for v in data] or [0])):
                    w.writerow([v[r] if r < len(v) else '' for v in data])
        info['books'].append(b)
    for g in graphs:
        gp = op.find_graph(g)
        if gp is None:          # 版面页（Layout）等非图页
            continue
        rec = {'name': gp.name, 'long': gp.lname, 'layers': []}
        for li, gl in enumerate(layers(gp)):
            lay = {}
            try:
                lay.update(x=gl.axis('x').title, y=gl.axis('y').title)
            except Exception:
                pass
            # 记录每个图层画了哪些数据集（Book_列）和图例文字，便于把 CSV 列对回图上的曲线
            try:
                op.lt_exec('win -a %s; page.active=%d; layer -c; __cnt=count; string __lt$=legend.text$;' % (g, li + 1))
                lay['plots'] = []
                for i in range(1, int(op.lt_float('__cnt')) + 1):
                    op.lt_exec('string __y$="%%(%d,@D)";' % i)
                    lay['plots'].append(op.get_lt_str('__y$'))
                lay['legend'] = op.get_lt_str('__lt$')
            except Exception as e:
                lay['plots_err'] = str(e)
            rec['layers'].append(lay)
        try:
            gp.save_fig('%s/png/%s.png' % (OUT, gp.name), width=1400)
        except Exception as e:
            rec['err'] = str(e)
        info['graphs'].append(rec)
    json.dump(info, open(OUT + '/info.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
except Exception:
    log.append(traceback.format_exc())
open(OUT + '/export.log', 'w', encoding='utf-8').write(chr(10).join(log))
