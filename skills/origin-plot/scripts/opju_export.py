# -*- coding: utf-8 -*-
"""把 Origin 项目（.opju/.opj）里的数据和图导出：工作表 → CSV（前三行为长名称/单位/注释），图 → PNG，结构 → info.json。

用法（不要加 -I）:
    python skills/origin-plot/scripts/opju_export.py <项目文件> <输出目录> [--datasets]

--datasets：额外把图中引用的隐藏数据集复制成工作表再导出（用于 ole_extract.py 抽出的内嵌图 .opj）。
源文件不会被修改：脚本先复制一份可写副本给 Origin 打开，结束后删除副本并关闭 Origin。
"""
import argparse, os, shutil, sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('out')
    ap.add_argument('--datasets', action='store_true')
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    ext = os.path.splitext(a.src)[1].lower()
    work = os.path.join(out, '_src_copy' + ext)
    shutil.copyfile(a.src, work)
    os.chmod(work, 0o666)                      # 只读源文件的副本也要可写，否则 Origin 打开受限
    code = open(os.path.join(HERE, '_inner_export.py'), encoding='utf-8').read()
    code = code.replace('@@OUT@@', out.replace('\\', '/')).replace('@@DATASETS@@', '1' if a.datasets else '0')
    inner = os.path.join(out, '_inner_export_run.py')
    open(inner, 'w', encoding='utf-8').write(code)

    import win32com.client as wc
    app = wc.Dispatch('Origin.Application')
    app.Visible = 0
    try:
        print('打开:', app.Load(work))
        print('导出:', app.Execute('run -pyf "%s";' % inner.replace('\\', '/')))
    finally:
        app.Exit()
    for f in (work, inner):
        try:
            os.remove(f)
        except OSError:
            pass
    log = os.path.join(out, 'export.log')
    if os.path.exists(log) and open(log, encoding='utf-8').read().strip():
        print(open(log, encoding='utf-8').read())
    n_csv = len(os.listdir(os.path.join(out, 'csv'))) if os.path.isdir(os.path.join(out, 'csv')) else 0
    n_png = len(os.listdir(os.path.join(out, 'png'))) if os.path.isdir(os.path.join(out, 'png')) else 0
    print('CSV %d 个，PNG %d 个 → %s' % (n_csv, n_png, out))


if __name__ == '__main__':
    main()
