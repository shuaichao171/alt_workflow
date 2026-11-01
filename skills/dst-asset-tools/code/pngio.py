"""极简 PNG 读写（纯 zlib，支持 8-bit RGB/RGBA/灰度，无隔行）。

- write_png(path, w, h, rgba)  rgba 为 bytes/bytearray，行主序 RGBA
- read_png(path) -> (w, h, rgba)
"""
import struct
import zlib


def write_png(path, w, h, rgba):
    assert len(rgba) == w * h * 4, 'rgba length mismatch'
    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)  # filter: None
        raw += rgba[y * stride:(y + 1) * stride]
    cid = struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)

    def chunk(tag, body):
        c = struct.pack('>I', len(body)) + tag + body
        return c + struct.pack('>I', zlib.crc32(tag + body) & 0xFFFFFFFF)

    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(chunk(b'IHDR', cid))
        f.write(chunk(b'IDAT', zlib.compress(bytes(raw), 9)))
        f.write(chunk(b'IEND', b''))


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read_png(path):
    data = open(path, 'rb').read()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', 'not a PNG'
    pos, w, h, depth, ctype = 8, 0, 0, 0, 0
    idat = bytearray()
    while pos < len(data):
        ln, tag = struct.unpack_from('>I4s', data, pos)
        body = data[pos + 8: pos + 8 + ln]
        pos += 12 + ln
        if tag == b'IHDR':
            w, h, depth, ctype = struct.unpack_from('>IIBB', body, 0)
            assert depth == 8 and ctype in (0, 2, 6) and body[12] == 0, \
                'unsupported PNG (need 8bit gray/RGB/RGBA, no interlace)'
        elif tag == b'IDAT':
            idat += body
        elif tag == b'IEND':
            break
    ch = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(bytes(idat))
    stride = w * ch
    out = bytearray(w * h * 4)
    prev = bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1: (y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - ch] if i >= ch else 0
            b = prev[i]
            c = prev[i - ch] if i >= ch else 0
            if f == 1:
                line[i] = (line[i] + a) & 0xFF
            elif f == 2:
                line[i] = (line[i] + b) & 0xFF
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 0xFF
            elif f == 4:
                line[i] = (line[i] + _paeth(a, b, c)) & 0xFF
        for x in range(w):
            i, o = x * ch, (y * w + x) * 4
            if ch == 1:
                out[o:o + 3] = line[i:i + 1] * 3
                out[o + 3] = 255
            elif ch == 3:
                out[o:o + 3] = line[i:i + 3]
                out[o + 3] = 255
            else:
                out[o:o + 4] = line[i:i + 4]
        prev = line
    return w, h, bytes(out)
