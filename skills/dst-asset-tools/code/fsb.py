"""FSB5 (.fsb) 银行解析 + Vorbis 流提取 —— DST 音频格式。

依据 DST Mod Tool 实际使用的开源 crate fsbex（github.com/astral4/fsbex，MIT/Apache-2.0，
应用以 git 依赖 commit af968bf 静态链接）逆向整理；格式层与 fsbex::header 逐字段一致，
已对 DST 官方全部 156 个 .fsb 文件做结构走查验证。

银行头（version=1 时 60 字节；version=0 为 64 字节且无 flags）：
  0x00 'FSB5' | 0x04 u32 version(0/1) | 0x08 u32 流数 | 0x0c u32 流头总大小
  0x10 u32 名字表大小 | 0x14 u32 流数据总大小 | 0x18 u32 音频格式(1..17)
  0x1c 跳过 4 | 0x20 u32 flags | 0x24..0x3c 未知元数据(GUID 区)
流头 u64 LE 位域（bilge 低位在前）：
  bit0   has_chunks | [4:1] 采样率枚举(0=4000,1=8000,2=11000,3=11025,4=16000,
  5=22050,6=24000,7=32000,8=44100,9=48000,10=96000) | [6:5] 声道(0=1,1=2,2=6,3=8)
  | [33:7] 数据偏移(×32 字节) | [63:34] 采样数
块（has_chunks 时，可重复）：u32 = bit0 more | [31:8] size | [7:1] kind
  kind: 1=Channels(覆盖声道 u8) 2=SampleRate(u32) 3=Loop(start,end)
  4=Comment 6=XmaSeek 7=DSP系数 9=AT9 10=xWMA 11=VorbisSeek(首 4B 为 setup 头 CRC32)
  13=PeakVolume 14=VorbisIntraLayers(u32 层数×原声道) 15=OpusDataSize
名字表：n×u32 偏移 + 偏移差分切的 NUL 结尾名字串。
流数据：base(60/64)+流头大小+名字表 之后；Vorbis 分帧 = u16 长度前缀 + 包体，
  0x0000/0xFFFF 为结束哨兵（fsbex::encode::vorbis）。
Vorbis setup 头不在银行内：按 VorbisSeek 块的 CRC32 查 161 项查找表
  （fsbex 内嵌 FMOD 质量档 setup 头，data/fsb_vorbis_setup.json.gz）。
"""
import struct, zlib, io, gzip, json, os

MAGIC = b'FSB5'
FORMAT_NAMES = {1: 'PCM8', 2: 'PCM16', 3: 'PCM24', 4: 'PCM32', 5: 'PCMFloat',
                6: 'GCADPCM', 7: 'IMAADPCM', 8: 'VAG', 9: 'HEVAG', 10: 'XMA',
                11: 'MPEG', 12: 'CELT', 13: 'ATRAC9', 14: 'XWMA', 15: 'Vorbis',
                16: 'FADPCM', 17: 'Opus'}
RATE_ENUM = {0: 4000, 1: 8000, 2: 11000, 3: 11025, 4: 16000, 5: 22050,
             6: 24000, 7: 32000, 8: 44100, 9: 48000, 10: 96000}
CHUNK_KINDS = {1: 'channels', 2: 'sample_rate', 3: 'loop', 4: 'comment',
               6: 'xma_seek', 7: 'dsp_coeffs', 9: 'at9_cfg', 10: 'xwma_cfg',
               11: 'vorbis_seek', 13: 'peak_volume', 14: 'vorbis_layers', 15: 'opus_size'}

_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
_setup_table = None


def vorbis_setup_table():
    """{crc32: setup_header_bytes} —— 161 项，来自 fsbex vorbis_lookup.rs。"""
    global _setup_table
    if _setup_table is None:
        with gzip.open(os.path.join(_DATA_DIR, 'fsb_vorbis_setup.json.gz'), 'rt') as f:
            raw = json.load(f)
        _setup_table = {int(k, 16): bytes.fromhex(v) for k, v in raw.items()}
    return _setup_table


class Stream:
    __slots__ = ('index', 'sample_rate', 'channels', 'data_offset', 'num_samples',
                 'size', 'loop', 'vorbis_crc32', 'name', 'data_base')

    def __init__(self):
        self.index = 0; self.sample_rate = 0; self.channels = 1
        self.data_offset = 0; self.num_samples = 0; self.size = 0
        self.loop = None; self.vorbis_crc32 = None; self.name = None
        self.data_base = 0

    def read_data(self, bank_bytes):
        base = self.data_base + self.data_offset
        return bank_bytes[base:base + self.size]

    def vorbis_packets(self, bank_bytes):
        """按 u16 前缀分帧，返回包列表（不含结束哨兵）。"""
        d = self.read_data(bank_bytes)
        out, o = [], 0
        while o + 2 <= len(d):
            n = struct.unpack_from('<H', d, o)[0]
            if n == 0 or n == 0xFFFF:
                break
            o += 2
            out.append(d[o:o + n]); o += n
        return out


class FsbBank:
    def __init__(self):
        self.version = 1; self.format = 0; self.flags = 0
        self.num_streams = 0; self.stream_headers_size = 0
        self.name_table_size = 0; self.total_stream_size = 0
        self.streams = []; self.data_base = 0; self.trailing = 0

    # ---------- 解析（fsbex::header::Header::parse 对齐） ----------
    @classmethod
    def parse(cls, data: bytes) -> "FsbBank":
        if data[:4] != MAGIC:
            raise ValueError('not an FSB5 file')
        b = cls()
        b.version, b.num_streams, b.stream_headers_size, b.name_table_size, \
            b.total_stream_size, b.format = struct.unpack_from('<IIIIII', data, 4)
        if b.version == 1:
            b.flags = struct.unpack_from('<I', data, 0x20)[0]
            base = 60
        elif b.version == 0:
            base = 64
        else:
            raise ValueError(f'unknown FSB5 version {b.version}')
        o = base
        streams = []
        for i in range(b.num_streams):
            s = Stream(); s.index = i
            s.data_base = base + b.stream_headers_size + b.name_table_size
            h = struct.unpack_from('<Q', data, o)[0]; o += 8
            has_chunks = h & 1
            s.sample_rate = RATE_ENUM.get((h >> 1) & 0xF, 0) or 4000
            ch = (h >> 5) & 3
            s.channels = (1, 2, 6, 8)[ch]
            s.data_offset = ((h >> 7) & 0x7FFFFFF) * 32
            s.num_samples = h >> 34
            if has_chunks:
                while True:
                    c = struct.unpack_from('<I', data, o)[0]
                    more = c & 1
                    size = (c >> 1) & 0xFFFFFF
                    kind = c >> 25
                    o += 4
                    p = o
                    if kind == 1:
                        s.channels = data[o]; o += 1
                    elif kind == 2:
                        s.sample_rate = struct.unpack_from('<I', data, o)[0]; o += 4
                    elif kind == 3:
                        st, en = struct.unpack_from('<II', data, o); o += 8
                        s.loop = (st, en - st)
                    elif kind == 11:
                        s.vorbis_crc32 = struct.unpack_from('<I', data, o)[0]; o += 4
                    elif kind == 14:
                        layers = struct.unpack_from('<I', data, o)[0]; o += 4
                        s.channels = layers * s.channels
                    o = p + size
                    if not more:
                        break
            streams.append(s)
        # 尺寸 = 相邻偏移差；最后一条以 total_stream_size 为哨兵
        offs = [s.data_offset for s in streams] + [b.total_stream_size]
        for s, a, z in zip(streams, offs, offs[1:]):
            s.size = z - a
        # 名字表
        if b.name_table_size:
            no = base + b.stream_headers_size
            npos = [struct.unpack_from('<I', data, no + 4 * i)[0]
                    for i in range(b.num_streams)] + [b.name_table_size]
            for s, a, z in zip(streams, npos, npos[1:]):
                s.name = data[no + a: no + z].split(b'\0')[0].decode('utf-8', 'replace')
        b.streams = streams
        b.data_base = base + b.stream_headers_size + b.name_table_size
        b.trailing = len(data) - (b.data_base + b.total_stream_size)
        return b

    # ---------- PCM → WAV 重建（fsbex encode/pcm.rs 对齐） ----------
    def to_wav(self, stream: Stream, data: bytes) -> bytes:
        """PCM8/16/24/32/Float 流 -> WAV（44B 头 + 流字节原样拷贝，含尾余量）。

        与 fsbex encode::pcm 一致：头用 info.size 作 data 长度；小端样本直拷；
        Float 用 fmt=3，整型 PCM 用 fmt=1。
        """
        if self.format not in (1, 2, 3, 4, 5):
            raise ValueError(f'not a PCM bank (format={self.format})')
        depth = {1: 1, 2: 2, 3: 3, 4: 4, 5: 4}[self.format]
        audio_fmt = 3 if self.format == 5 else 1
        d = stream.read_data(data)
        ch, rate = stream.channels, stream.sample_rate
        hdr = (b'RIFF' + struct.pack('<I', 36 + len(d)) + b'WAVEfmt ' +
               struct.pack('<IHHIIHH', 16, audio_fmt, ch, rate,
                           rate * ch * depth, ch * depth, depth * 8) +
               b'data' + struct.pack('<I', len(d)))
        return hdr + d

    # ---------- MPEG → MP3 重建（dst_re 扩展；fsbex v0.3.0 上游拒收 MPEG） ----------
    # FSB5 MPEG 布局（实测 31 流）：MP3 帧之间用 0x00 填充到固定步进（如 64kbps/44100
    # 帧 209B→步进 212；160kbps/44100 帧 523B→步进 524），末帧零填充补齐至流声明长度；
    # 部分 FMOD 音效在实音帧后重复空 LAME 信息帧+零填充作静音尾（见 wandatocksfx）。
    _MP3_BITR = {1: 32, 2: 40, 3: 48, 4: 56, 5: 64, 6: 80, 7: 96, 8: 112,
                 9: 128, 10: 160, 11: 192, 12: 224, 13: 256, 14: 320}
    _MP3_RATES = {(3, 0): 44100, (3, 1): 48000, (3, 2): 32000,
                  (2, 0): 22050, (2, 1): 24000, (2, 2): 16000}

    def to_mp3(self, stream: Stream, data: bytes) -> bytes:
        """MPEG 流 -> 标准 MP3 帧链（剥除帧间/尾部 0x00 填充，仅保留完整帧）。

        零填充会破坏标准 demuxer 的帧链探测，故输出剥填充后的干净帧序列。
        """
        if self.format != 11:
            raise ValueError(f'not an MPEG bank (format={self.format})')
        d = stream.read_data(data)
        out = bytearray()
        o = 0
        while o + 4 <= len(d):
            if d[o] == 0xFF and (d[o + 1] & 0xE0) == 0xE0:
                b1, b2 = d[o + 1], d[o + 2]
                ver, layer = (b1 >> 3) & 3, (b1 >> 1) & 3
                br = self._MP3_BITR.get((b2 >> 4) & 0xF)
                sr = self._MP3_RATES.get((ver, (b2 >> 2) & 3))
                pad = (b2 >> 1) & 1
                if (br is None or sr is None or ver not in (2, 3)
                        or layer != 1):
                    o += 1
                    continue
                flen = 144 * br * 1000 // sr + pad
                if o + flen > len(d):
                    break  # 末尾截断帧（零填充补齐），不输出
                out += d[o:o + flen]
                o += flen
            elif d[o] == 0:
                o += 1
            else:
                o += 1
        return bytes(out)

    # ---------- Vorbis → Ogg 重建 ----------
    def to_ogg(self, stream: Stream, data: bytes) -> bytes:
        """把流的 Vorbis 包重封为 Ogg（setup 头按 CRC32 查表）。

        注意：fsbex 原实现是 lewton 解码 + vorbis_rs 重编码（有损重编码）；
        本实现是包级无损重封。granule 位置为近似（中间页 0，末页=总采样数），
        结构 CRC 全部校验正确。
        """
        if self.format != 15:
            raise ValueError('not a Vorbis bank')
        tbl = vorbis_setup_table()
        if stream.vorbis_crc32 is None:
            raise ValueError('stream has no vorbis seek chunk (crc32)')
        setup = tbl.get(stream.vorbis_crc32)
        if setup is None:
            raise ValueError(f'crc32 {stream.vorbis_crc32:08X} not in setup table')
        idh = (b'\x01vorbis' + b'\0' * 4 + bytes([stream.channels]) +
               struct.pack('<I', stream.sample_rate) + b'\0' * 12 +
               bytes([(11 << 4) | 8]) + b'\x01')
        vendor = b'dst_re'
        cmh = (b'\x03vorbis' + struct.pack('<I', len(vendor)) + vendor +
               b'\0' * 4 + b'\x01')
        packets = stream.vorbis_packets(data)
        ogg = bytearray()
        seq = [0]
        serial = stream.vorbis_crc32 or 1

        def page(htype, granule, payload_packets, header_len=None):
            body = bytearray()
            segs = []
            for p in payload_packets:
                body += p
                n = len(p)
                full, rem = divmod(n, 255)
                segs += [255] * full + [rem if rem else 0]
                if rem == 0 and header_len is None:
                    segs[-1] = 0  # 255 倍数包需 0 结尾段
            # 修正：255 倍数包应输出 full 个 255 + 1 个 0；上面 rem==0 时已补
            # Ogg 页头: OggS(4) ver(1) htype(1) granule(8) serial(4) seq(4) crc(4,先置 0) segcnt(1) segs
            hdr = bytearray(b'OggS\0')
            hdr.append(htype)
            hdr += struct.pack('<Q', granule) + struct.pack('<II', serial, seq[0]) + b'\0\0\0\0'
            hdr.append(len(segs)); hdr += bytes(segs)
            full_page = bytes(hdr) + bytes(body)
            t = _ogg_crc_table()
            c = 0
            for byte in full_page:
                c = ((c << 8) ^ t[((c >> 24) & 0xFF) ^ byte]) & 0xFFFFFFFF
            hdr[22:26] = struct.pack('<I', c)
            seq[0] += 1
            return bytes(hdr) + bytes(body)

        ogg += page(0x02, 0, [idh])
        ogg += page(0x00, 0, [cmh])
        ogg += page(0x00, 0, [setup])
        for i, p in enumerate(packets):
            last = i == len(packets) - 1
            ogg += page(0x04 if last else 0x00, stream.num_samples if last else 0, [p])
        return bytes(ogg)


_OGG_CRC = None


def _ogg_crc_table():
    global _OGG_CRC
    if _OGG_CRC is None:
        t = []
        for i in range(256):
            c = i << 24
            for _ in range(8):
                c = ((c << 1) ^ 0x04C11DB7) if (c & 0x80000000) else (c << 1)
                c &= 0xFFFFFFFF
            t.append(c)
        _OGG_CRC = t
    return _OGG_CRC
