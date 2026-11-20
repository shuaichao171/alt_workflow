# -*- coding: utf-8 -*-
"""按作图描述文件（JSON）驱动 Origin 画图：套用默认样式，导出 PNG，并保存 .opju 供手工微调。

用法（不要加 -I，pywin32 需要用户 site-packages）:
    python skills/origin-plot/scripts/origin_plot.py <spec.json> [--out <输出目录>] [--no-opju] [--grid]

spec.json 结构见 skills/origin-plot/SKILL.md 与 examples/。数据可内联 x/y，也可引用 xlsx/csv 的列。
"""
import argparse, copy, csv, json, os, shutil, sys, time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def col_index(key, header):
    """列标识：整数（0 起）、Excel 列字母（A、B…）或表头文字。"""
    if isinstance(key, int):
        return key
    if key in header:
        return header.index(key)
    if key.isalpha() and key.isupper() and len(key) <= 3:
        n = 0
        for ch in key:
            n = n * 26 + ord(ch) - 64
        return n - 1
    raise KeyError('找不到列 %r（表头：%s）' % (key, header))


def read_table(path, sheet=None):
    if path.lower().endswith('.csv'):
        with open(path, encoding='utf-8-sig') as f:
            return [r for r in csv.reader(f)]
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    return [list(r) for r in ws.iter_rows(values_only=True)]


def num(v):
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def resolve_series(s, base_dir):
    """把 {"file":..., "x":..., "y":...} 形式的系列解析成数值列表。"""
    if 'file' not in s:
        return s
    path = s['file'] if os.path.isabs(s['file']) else os.path.join(base_dir, s['file'])
    rows = read_table(path, s.get('sheet'))
    hr = s.get('header_row', 1)                      # 表头所在行（1 起），0 表示无表头
    header = [str(c).strip() if c is not None else '' for c in rows[hr - 1]] if hr else []
    r0, r1 = s.get('rows', [hr + 1, len(rows)])      # 数据行范围（1 起，闭区间）
    xi, yi = col_index(s['x'], header), col_index(s['y'], header)
    xs, ys = [], []
    for r in rows[r0 - 1:r1]:
        x, y = num(r[xi] if xi < len(r) else None), num(r[yi] if yi < len(r) else None)
        if x is not None and y is not None:
            xs.append(x * s.get('x_scale', 1)); ys.append(y * s.get('y_scale', 1))
    out = {k: v for k, v in s.items() if k not in ('file', 'sheet', 'x', 'y', 'rows', 'header_row', 'x_scale', 'y_scale')}
    out.update(x=xs, y=ys)
    return out


def compose_grid(spec, out_dir, st):
    from PIL import Image, ImageDraw, ImageFont
    files = [os.path.join(out_dir, '%s_%s.png' % (spec['name'], p['name'])) for p in spec['panels']]
    ims = [Image.open(f).convert('RGB') for f in files]
    w, h = ims[0].size
    cols = spec.get('grid', {}).get('cols', st['grid']['cols'])
    rows = (len(ims) + cols - 1) // cols
    lab_h = int(st['grid']['label_font_size'] * 1.8)
    font = ImageFont.truetype(os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts', 'simsun.ttc'),
                              st['grid']['label_font_size'])
    sheet = Image.new('RGB', (w * cols, (h + lab_h) * rows), 'white')
    d = ImageDraw.Draw(sheet)
    for i, (im, p) in enumerate(zip(ims, spec['panels'])):
        x0, y0 = (i % cols) * w, (i // cols) * (h + lab_h)
        sheet.paste(im.resize((w, h)), (x0, y0))
        lab = p.get('label', '（%s）' % p['name'])
        tw = d.textlength(lab, font=font)
        d.text((x0 + (w - tw) / 2, y0 + h + lab_h * 0.15), lab, fill='black', font=font)
    fn = os.path.join(out_dir, spec['name'] + '_拼版预览.png')
    sheet.save(fn)
    return fn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('spec')
    ap.add_argument('--out', help='输出目录（默认取 spec 的 out_dir，否则为 spec 所在目录）')
    ap.add_argument('--no-opju', action='store_true')
    ap.add_argument('--grid', action='store_true', help='多 panel 时额外输出拼版预览图')
    a = ap.parse_args()

    spec_path = os.path.abspath(a.spec)
    base = os.path.dirname(spec_path)
    spec = json.load(open(spec_path, encoding='utf-8'))
    style = json.load(open(os.path.join(SKILL, 'style.json'), encoding='utf-8'))
    style = {k: v for k, v in style.items() if not k.startswith('_')}
    spec['style'] = deep_merge(style, spec.get('style'))
    if a.out:
        out_dir = os.path.abspath(a.out)
    else:                                      # spec 里的相对路径按 spec 文件所在目录解析
        out_dir = os.path.abspath(os.path.join(base, spec.get('out_dir') or '.'))
    os.makedirs(out_dir, exist_ok=True)
    spec['out_dir'] = out_dir.replace('\\', '/')
    for p in spec['panels']:
        p['series'] = [resolve_series(s, base) for s in p['series']]

    tmp = os.path.join(out_dir, '_origin_tmp')
    os.makedirs(tmp, exist_ok=True)
    rs = os.path.join(tmp, 'spec_resolved.json')
    json.dump(spec, open(rs, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    inner = open(os.path.join(HERE, '_inner_plot.py'), encoding='utf-8').read().replace('@@SPEC@@', rs.replace('\\', '/'))
    inner_path = os.path.join(tmp, '_inner_plot_run.py')
    open(inner_path, 'w', encoding='utf-8').write(inner)

    import win32com.client as wc
    app = wc.Dispatch('Origin.Application')   # 新开一个 Origin 实例，不会接管用户已打开的 Origin
    app.Visible = 0
    try:
        app.NewProject()
        ok = app.Execute('run -pyf "%s";' % inner_path.replace('\\', '/'))
        opju = os.path.join(out_dir, spec['name'] + '.opju')
        if not a.no_opju and spec['style']['export'].get('save_opju', True):
            app.Save(opju)
    finally:
        app.Exit()
    log = open(rs + '.log', encoding='utf-8').read() if os.path.exists(rs + '.log') else '（无日志）'
    print('Origin 执行:', ok)
    print(log)
    if a.grid and len(spec['panels']) > 1:
        print('拼版预览:', compose_grid(spec, out_dir, spec['style']))
    if 'Traceback' in log or 'FAIL' in log:
        print('！有失败的步骤，详见上方日志；中间文件保留在', tmp)
        sys.exit(1)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
