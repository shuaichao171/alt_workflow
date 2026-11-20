# -*- coding: utf-8 -*-
"""从 .pptx/.docx 中抽出内嵌的 Origin 图对象（progId 为 Origin*.Graph），保存为可被 Origin 打开的 .opj。

用法（不要加 -I）:
    python skills/origin-plot/scripts/ole_extract.py <文件.pptx|.docx> <输出目录>

随后对每个 .opj 运行：opju_export.py <xxx.opj> <目录> --datasets
内嵌对象是 OLE 复合文档，其中的 Contents 流就是 Origin 项目（文件头 CPYA/CPYUA）。
"""
import os, posixpath, re, sys, zipfile

sys.stdout.reconfigure(encoding='utf-8')


def read_contents(bin_path):
    import pythoncom
    st = pythoncom.StgOpenStorage(bin_path, None, 0x10, None, 0)   # STGM_SHARE_EXCLUSIVE | READ
    try:
        s = st.OpenStream('Contents', None, 0x10, 0)
    except Exception:
        return None
    data = b''
    while True:
        chunk = s.Read(1 << 20)
        if not chunk:
            break
        data += chunk
    del s, st
    return data


def main():
    src, out = sys.argv[1], os.path.abspath(sys.argv[2])
    os.makedirs(out, exist_ok=True)
    z = zipfile.ZipFile(src)
    parts = [n for n in z.namelist() if n.endswith('.xml') and ('/slides/slide' in n or n == 'word/document.xml')]
    seen = set()
    for part in sorted(parts, key=lambda n: [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', n)]):
        x = z.read(part).decode('utf-8', 'ignore')
        if 'Origin' not in x:
            continue
        d, b = posixpath.split(part)
        rx = z.read(posixpath.join(d, '_rels', b + '.rels')).decode('utf-8')
        rels = {}
        for r in re.findall(r'<Relationship [^>]*/>', rx):
            rels[re.search(r'Id="([^"]+)"', r).group(1)] = re.search(r'Target="([^"]+)"', r).group(1)
        text = ' / '.join(t for t in re.findall(r'<a:t>([^<]*)</a:t>', x) if t.strip())[:100]
        for m in re.finditer(r'<(?:p:oleObj|o:OLEObject)\b[^>]*>', x):
            tag = m.group(0)
            pid = re.search(r'(?:progId|ProgID)="([^"]+)"', tag)
            rid = re.search(r'r:id="([^"]+)"', tag)
            if not pid or not pid.group(1).startswith('Origin') or not rid:
                continue
            tgt = posixpath.normpath(posixpath.join(d, rels[rid.group(1)]))
            if tgt in seen:
                continue
            seen.add(tgt)
            stem = '%s_%s' % (os.path.splitext(b)[0], os.path.splitext(posixpath.basename(tgt))[0])
            bin_path = os.path.join(out, stem + '.bin')
            open(bin_path, 'wb').write(z.read(tgt))
            data = read_contents(bin_path)
            os.remove(bin_path)
            if not data:
                print('跳过（无 Contents 流）:', stem)
                continue
            open(os.path.join(out, stem + '.opj'), 'wb').write(data)
            print('%s.opj  %s  %d 字节 | %s' % (stem, pid.group(1), len(data), text))


if __name__ == '__main__':
    main()
