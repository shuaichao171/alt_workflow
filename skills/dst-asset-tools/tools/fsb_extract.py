#!/usr/bin/env python3
"""fsb_extract — .fsb 音库提取（功能 9/10）。用法:
  python fsb_extract.py input.fsb [输出目录] [--list]
按 bank 格式自动分发：Vorbis->.ogg / PCM*->.wav / MPEG->.mp3。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'code'))
from fsb import FsbBank, FORMAT_NAMES


def main():
    args = [a for a in sys.argv[1:] if a != '--list']
    listing = '--list' in sys.argv
    src = Path(args[0])
    out = Path(args[1]) if len(args) > 1 else src.with_suffix('')
    data = src.read_bytes()
    b = FsbBank.parse(data)
    kind = FORMAT_NAMES.get(b.format, str(b.format))
    print(f'{src.name}: {b.num_streams} streams, format={kind}, trailing={b.trailing}B')
    if listing:
        for s in b.streams:
            print(f'  [{s.index}] {s.name} {s.sample_rate}Hz ch={s.channels} '
                  f'{s.num_samples}sm {s.size}B crc={s.vorbis_crc32}')
        return
    out.mkdir(parents=True, exist_ok=True)
    for s in b.streams:
        ext = {15: 'ogg', 11: 'mp3'}.get(b.format, 'wav')
        fn = out / f'{s.index:03d}_{(s.name or "stream").replace("/", "_")}.{ext}'
        if b.format == 15:
            blob = b.to_ogg(s, data)
        elif b.format == 11:
            blob = b.to_mp3(s, data)
        elif b.format in (1, 2, 3, 4, 5):
            blob = b.to_wav(s, data)
        else:
            print(f'  skip [{s.index}] unsupported format {kind}')
            continue
        fn.write_bytes(blob)
        print(f'  {fn.name} ({len(blob)}B)')


if __name__ == '__main__':
    main()
