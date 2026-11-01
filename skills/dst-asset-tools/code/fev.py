"""FEV（FMOD Designer 工程）RIFF 容器解析。

格式事实（59 个 DST data/sound/*.fev 全量实证 + 反编译 dst_core::convert::fmod::fdp）：
- RIFF 容器：`RIFF` + u32 size + form `'FEV '`。
- 根块：`FMT `（4 字节体，DST 全部文件统一为 `00 00 45 00`，u32 LE=0x450000，疑为 FMOD 版本标记 0x45）+ `LIST`（子类型 `'PROJ'`）。
- PROJ 列表固定含 6 块：`OBCT`（工程对象二进制流）、`PROP`（工程属性）、
  `LGCY`（legacy 设置）、`EPRP`（事件属性）、`STRR`（字符串表）、`LANG`（语言表）。
- 块体为 FMOD Designer 专有二进制对象流（事件/波形/包络层级），
  完整 FDP 重建需解码对象流——应用在 dst_core::convert::fmod::fdp 中程序化生成 FDP XML。

验证：59/59 文件解析 0 尾字节（tests/test_all.py::TestFev）。
"""

import struct
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Chunk:
    cid: str          # 4 字符块 ID
    size: int
    data: bytes
    children: List["Chunk"] = field(default_factory=list)
    list_type: Optional[str] = None  # LIST 子类型


def _walk(data: bytes, off: int, end: int) -> List[Chunk]:
    out = []
    while off + 8 <= end:
        cid = data[off:off+4].decode('latin1')
        sz = struct.unpack_from('<I', data, off + 4)[0]
        body = off + 8
        if sz > end - body:
            raise ValueError(f"chunk {cid!r} size {sz} exceeds parent at {off:#x}")
        c = Chunk(cid, sz, data[body:body+sz])
        if cid == 'LIST' and sz >= 4:
            c.list_type = data[body:body+4].decode('latin1')
            c.children = _walk(data, body + 4, body + sz)
        out.append(c)
        off = body + sz + (sz & 1)   # RIFF 字对齐
    if off != end:
        raise ValueError(f"trailing {end-off} bytes at {off:#x}")
    return out


@dataclass
class FevFile:
    version: int
    chunks: List[Chunk]

    @classmethod
    def parse(cls, data: bytes) -> "FevFile":
        if data[:4] != b'RIFF' or data[8:12] != b'FEV ':
            raise ValueError("not an FEV RIFF file")
        sz = struct.unpack_from('<I', data, 4)[0]
        if 8 + sz != len(data):
            raise ValueError(f"RIFF size {sz} != file size {len(data)}")
        chunks = _walk(data, 12, len(data))
        ver = None
        for c in chunks:
            if c.cid == 'FMT ' and c.size >= 4:
                ver = struct.unpack_from('<I', c.data, 0)[0]
        return cls(version=ver, chunks=chunks)

    def proj(self) -> Optional[Chunk]:
        """PROJ LIST（工程对象容器）。"""
        for c in self.chunks:
            if c.cid == 'LIST' and c.list_type == 'PROJ':
                return c
        return None

    def find(self, cid: str) -> Optional[Chunk]:
        """按 ID 找 PROJ 内第一块。"""
        p = self.proj()
        if p:
            for c in p.children:
                if c.cid == cid:
                    return c
        return None


# ============ LGCY 对象流语义提取（经验式，第 6 轮新增） ============
# LGCY 为 FMOD Designer 专有对象序列化流；完整字节级解码未完成（类分发分散在
# 11.6KB 解析器 sub_1419867C0 的子调用中）。以下为实证结构：
#   u32 A, u32 B            —— 段偏移（wandatock=72/96, aqol=984/1312）
#   len(u32)+str 项目名     —— 与 PROP 块一致
#   u32 1, u32 1, u16 标志  —— 项目记录头
#   len=10: 8B GUID + u16   —— 项目 GUID
#   随后为分类/组/事件记录流：len(u32)+name + f32 音量 + 二进制属性，
#   波形引用为 len(u32)+路径（如 "../tock1.mp3"）。

import re as _re
import struct as _struct

_WAVE_RE = _re.compile(r'\.(mp3|wav|ogg)$', _re.IGNORECASE)


def harvest_names(lgcy: bytes):
    """收割 LGCY 中全部长度前缀串：u32 len + len 字节（NUL 结尾、纯 ASCII 可打印）。

    返回 [(offset, name)]；覆盖分类/事件组/事件/波形路径等全部命名对象。
    """
    out, off = [], 0
    n = len(lgcy)
    while off + 4 <= n:
        ln = _struct.unpack_from('<I', lgcy, off)[0]
        if 2 <= ln <= 200 and off + 4 + ln <= n:
            raw = lgcy[off + 4:off + 4 + ln]
            if raw[-1] == 0 and raw[:-1].isascii() and all(32 <= x < 127 for x in raw[:-1]):
                out.append((off, raw[:-1].decode('ascii')))
                off += 4 + ln
                continue
        off += 1
    return out


def extract(path):
    """解析 .fev 并提取语义摘要（第 6 轮经验式提取器）。

    返回 dict：project=项目名，objects=OBCT 对象数，names=全部收割名，
    waveforms=波形文件引用，categories=推断分类（master/music/ambience 系）。
    59/59 DST data/sound .fev 验证通过（项目名与波形引用 100% 提取）。
    """
    data = open(path, 'rb').read()
    f = FevFile.parse(data)
    lgcy = f.find('LGCY')
    if lgcy is None:
        raise ValueError('no LGCY chunk')
    b = lgcy.data
    names = [s for _, s in harvest_names(b)]
    waves = [s for s in names if _WAVE_RE.search(s)]
    proj = f.find('PROP')
    project = None
    if proj is not None and len(proj.data) >= 4:
        ln = _struct.unpack_from('<I', proj.data, 0)[0]
        if 4 + ln <= len(proj.data):
            project = proj.data[4:4 + ln].rstrip(b'\0').decode('ascii', 'replace')
    cat_names = ('master', 'music', 'ambience', 'sfx', 'soundtrack', 'voice',
                 'movement', 'creature', 'player', 'ui', 'weather')
    cats = [s for s in names if s in cat_names or s.startswith(('set_', 'everything_else'))]
    seen, cats2 = set(), []
    for c in cats:
        if c not in seen:
            seen.add(c); cats2.append(c)
    obct = f.find('OBCT')
    objects = _struct.unpack_from('<I', obct.data, 0)[0] if obct else 0
    return {'project': project, 'objects': objects, 'names': names,
            'waveforms': waves, 'categories': cats2}


def to_fdp_skeleton(path_or_summary):
    """从 .fev 生成 FDP XML 骨架（FMOD Designer 项目格式，元素名取自应用
    0x1435b42xx 词汇簇：project/category/eventgroup/event/layer/sounddef 等）。

    注意：骨架仅含层级与命名（含全部事件组/事件名与波形引用），不含属性值——
    属性级还原需完整解码 LGCY 记录流（未完成，见模块头注释）。
    """
    import xml.etree.ElementTree as ET
    if isinstance(path_or_summary, dict):
        s = path_or_summary
    else:
        s = extract(path_or_summary)
    root = ET.Element('project', {'name': s['project'] or '', 'version': '4'})
    cats = ET.SubElement(root, 'categories')
    for c in s['categories']:
        ET.SubElement(cats, 'category', {'name': c})
    groups = ET.SubElement(root, 'eventgroups')
    # 事件组/事件名：set_* 为组前缀约定（DST 项目全部使用 set_sfx/set_music/set_ambience）
    grp_names = [n for n in s['names'] if n.startswith('set_')]
    grp_seen, grp_list = set(), []
    for g in grp_names:
        if g not in grp_seen:
            grp_seen.add(g); grp_list.append(g)
    for g in grp_list:
        eg = ET.SubElement(groups, 'eventgroup', {'name': g})
        ev = ET.SubElement(eg, 'event', {'name': g[4:] if g.startswith('set_') else g})
        layer = ET.SubElement(ev, 'layer', {'name': 'layer00'})
        sd = ET.SubElement(layer, 'sounddef', {'name': 'default'})
        ET.SubElement(sd, 'waveforms')
    waves_el = ET.SubElement(root, 'wavebank')
    for w in s['waveforms']:
        ET.SubElement(waves_el, 'waveform', {'file': w})
    return ET.tostring(root, encoding='unicode')


# ============ 属性级记录布局（第 7 轮，反编译 sub_14198AE00 确认） ============
# 事件记录（Simple 分支，走读器 sub_14198AE00 反编译逐字段核对）：
#   u32 type        —— 8=Simple Event, 16=Complex（其它值 'Invalid event type'）
#   u32 name_idx    —— 事件名引用 STRR 字符串仓库索引（tick1/2/3 实证）
#   160B 属性块     —— memcpy 后由 sub_14198A710 构造属性结构
#   u32 sd_count    —— sounddef 数（Simple 事件 >1 报
#                      'Simple Event must have only 0/1 sounddef'）
#   u16 sd_index    —— sounddef 引用索引
#   56B 属性块 2    —— 尾部属性（音量/音高等）
# 分类记录（wandatock/aqol 手工对齐实证）：
#   len(u32)+name+NUL + f32 volume(实测全 1.0) + 可变尾字段（子类/父类 id）
# 项目记录：u32 A/u32 B 段偏移 + len+项目名 + 1,1,flags + 10B(8B GUID+u16) + u32

def category_volumes(path):
    """提取分类名及其音量 f32（name 后紧跟的 4 字节）。

    返回 [(name, volume)]；覆盖 wandatock 全部 16 个分类（master/music/
    set_music/soundtrack/set_sfx/movement/creature/player/HUD/...）。
    """
    data = open(path, 'rb').read()
    f = FevFile.parse(data)
    lgcy = f.find('LGCY')
    if lgcy is None:
        raise ValueError('no LGCY chunk')
    b = lgcy.data
    out = []
    for off, name in harvest_names(b):
        if off + 4 + len(name) + 1 + 4 <= len(b):
            v = _struct.unpack_from('<f', b, off + 4 + len(name) + 1)[0]
            if -96.0 <= v <= 20.0:  # FMOD 音量 dB 合理范围
                out.append((name, round(v, 3)))
    return out


# ---------------- 事件属性块字段图（第 8 轮，反编译 sub_14198A710 确认） ----------------
# 160 字节事件属性块（LGCY 事件记录内，sub_14198AE00 memcpy 后交 sub_14198A710 解读）：
#   +44  u16  ==16 -> "x_3d"（3D 声像）否则 "x_2d"（2D 声像）
#   +46  byte [5:4] ==1 -> "Logarithmic"（11B 串 0x1435515C5）否则 "Linear"（6B 串 0x1435515D0）
#   +46  byte [3:2] ==1 -> "Head_relative"（13B）否则 "World_relative"（14B）
#   +47  byte / +48 u64 / +66 byte==8 -> "yes"(25945+'s') 否则 "No"(28494)：布尔标志
#   +112 u32  2->Steal_newest 3->Steal_quietest 4->Just_fail 其他->Steal_oldest
#               （maxplaybacks 行为，长度表 12/14/9 @ 0x143551A80/A98）
#   +120/+132/+140 u64：数值属性原样透传（音量/音高范围等）
# ---------------- 事件 56B 尾属性块字段图（第 9 轮，sub_14198AE00 确认） ----------------
# 事件记录 = u32 类型 + u32 STRR 名索引 + 160B 主属性块(见上) + u32 sounddef 计数 +
#            u16 sounddef 索引 + 56B 尾属性块（可用性检查 `剩余>=0x38`，实读 56B）。
# 56B 尾块被拆装进 80B 运行时对象（0x14198AE00 中 sub_14195AF00(8,80) 分配）：
#   尾块 +0..11   -> 对象 +28（3 个 u32 原值）
#   尾块 +12..15  -> 位域：HIDWORD>>9 提取到对象 +48（其余位未解读）
#   尾块 +16..19  -> 对象 +44（u32）
#   尾块 +20..23  -> 布尔：DWORD1(v155[1])!=0 -> 对象 +76（0/1）
#   尾块 +24..39  -> 对象 +52（16B 原样）
#   尾块 +40..47  -> 未拷贝（对象无对应槽）
#   尾块 +48..55  -> 对象 +68（8B 原样）
# u16 sounddef 索引 -> 对象 +24；对象 +8 恒 1、+16 恒 0（层/波形层实例标记）。
# 说明：该对象随后入 Vec 并流向 FDP 写出器；各 u32 的量纲（音量/音高/优先级）
# 需 FDP 写出器侧反编译才能命名，此为结构层字段图。

EVENT_PAN = lambda v: 'x_3d' if v == 16 else 'x_2d'
EVENT_CURVE = lambda b: 'Logarithmic' if (b >> 4) & 3 == 1 else 'Linear'
EVENT_RELATIVE = lambda b: 'Head_relative' if (b >> 2) & 3 == 1 else 'World_relative'
EVENT_STEAL = {2: 'Steal_newest', 3: 'Steal_quietest', 4: 'Just_fail'}


def eprp_points(fev_file):
    """EPRP 块（事件属性包络点表）解码（第 10 轮实证）。

    布局：u32 count + count × 12B 记录 {f32 x, f32 y, u32 flag}；
    x∈[0,1]（时间轴）、y∈[0,1]（值轴）、flag∈{1,2,4}（曲线形状/持续标记，
    语义待 FDP 写出器侧确认）。chunk 尺寸恒等于 4+12*count（59/59 验证）。
    点所属的事件/参数由 LGCY 事件记录引用（全局点池，同 STRR 模式）。
    返回 [(x, y, flag), ...]；无 EPRP 块返回 []。
    """
    ch = fev_file.find('EPRP')
    if ch is None or len(ch.data) < 4:
        return []
    import struct as _s
    (cnt,) = _s.unpack_from('<I', ch.data, 0)
    if 4 + 12 * cnt != len(ch.data):
        raise ValueError(f'EPRP size mismatch: count={cnt}, chunk={len(ch.data)}')
    return [_s.unpack_from('<ffI', ch.data, 4 + 12 * i) for i in range(cnt)]


def event_property_summary(blob):
    """160B 事件属性块 -> 已知语义字段摘要（第 8 轮字段图）。"""
    if len(blob) < 144:
        raise ValueError('property blob too short')
    import struct as _s
    pan = _s.unpack_from('<H', blob, 44)[0]
    b46 = blob[46]
    steal = _s.unpack_from('<I', blob, 112)[0]
    return {
        'pan': EVENT_PAN(pan),
        'curve': EVENT_CURVE(b46),
        'relative': EVENT_RELATIVE(b46),
        'flag66': 'yes' if blob[66] == 8 else 'No',
        'maxplaybacks_behavior': EVENT_STEAL.get(steal, 'Steal_oldest'),
        'raw120': _s.unpack_from('<Q', blob, 120)[0],
        'raw132': _s.unpack_from('<Q', blob, 132)[0],
        'raw140': _s.unpack_from('<Q', blob, 140)[0],
    }
