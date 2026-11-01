"""DST 二进制资产工具集（从 DST Mod Tool v1.1.13 逆向提取，十五轮语料验证）。

模块速查：
- klei_hash   Klei 小写 SDBM + 12,522 条内嵌字典（hash<->名字）
- build_bin   build.bin 编解码（BILD v5/v6，byte 级往返）
- anim_bin    anim.bin 编解码（ANIM v3/v4 + facing 后缀系统）
- follow      follow_symbol / anti_follow 矩阵算法
- ktex        .tex 编解码（DXT5/RGB888/ETC2/ASTC）
- dxt         BC1/2/3 解码（ktech/bcdec 双约定）+ squish 编码底座
- etc2/astc   块解码（与 texture2ddecoder 逐位一致）
- squish_port ktech 等价 DXT 编码（ClusterFit）
- atlas       shelf 图集装箱（等价实现）
- fsb         .fsb -> Ogg/WAV/MP3（Vorbis setup 表内嵌）
- fev         .fev 解析 + FDP 骨架 XML
- search_index 游戏脚本资源名提取正则
"""
from . import (klei_hash, build_bin, anim_bin, follow, ktex, dxt, etc2, astc,
               squish_port, atlas, fsb, fev, search_index)

__all__ = ["klei_hash", "build_bin", "anim_bin", "follow", "ktex", "dxt",
           "etc2", "astc", "squish_port", "atlas", "fsb", "fev", "search_index"]
__version__ = "1.0.0"
