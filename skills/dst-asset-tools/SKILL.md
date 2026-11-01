# 《饥荒》二进制资产工具

> 何时使用：需要解析、修改或转换《饥荒》二进制资产——`anim.bin`、`build.bin`、`.tex`、`.fsb`、`.fev`，或做 Klei 哈希反查、碰撞盒重算、图集打包、资源名提取。纯 Python 实现，无第三方依赖（2026-11 从 DST Mod Tool v1.1.13 逆向提取，十五轮全语料验证）。

## 前置条件

- Python 3.10+，无第三方依赖（`code/` 自带数据文件）
- ktech/krane（可选，作黄金参照）：路径见 `private/paths.md` 的 `KTOOLS_DIR`

## 功能 → 工具

`cd` 到本技能目录后运行；以下 `python tools/xxx.py` 均可直接使用。

| 功能 | 工具 | 示例 |
| --- | --- | --- |
| .tex → PNG | `tools/tex2png.py` | `python tools/tex2png.py atlas-0.tex out.png [--mip 3] [--raw]` |
| PNG → .tex | `tools/png2tex.py` | `python tools/png2tex.py in.png out.tex [--fmt dxt5\|rgb\|rgba] [--no-mips] [--no-premultiply]` |
| 动画改名/朝向/帧率（anim.bin/build.bin/zip） | `tools/anim_edit.py` | `--list` / `--rename-anim OLD NEW` / `--rename-symbol OLD NEW` / `--set-facing NAME 0x30` / `--framerate 30` |
| 碰撞盒重算（纯几何 C' 公式） | `tools/collision_calc.py` | `python tools/collision_calc.py anim.bin build.bin [--apply]`（f0 与应用逐位一致） |
| 图集打包（shelf 装箱） | `tools/atlas_pack.py` | `python tools/atlas_pack.py PNG目录 输出前缀 [--size 2048] [--gap 0]` |
| .fsb 音库提取 | `tools/fsb_extract.py` | 自动按格式出 .ogg/.wav/.mp3；`--list` 仅列清单 |
| .fev 声音工程解析 | `tools/fev_extract.py` | `--fdp out.fdp` 生成 FMOD Designer 骨架 XML |
| 资源名提取 | `tools/search_names.py` | `python tools/search_names.py scripts.zip out.json`（约 2130 prefab / 2046 build / 1399 bank） |
| follow / anti_follow 矩阵算法 | `code/follow.py` | 见模块 docstring（与应用运行时逐位一致） |

## 直用模块 API

```python
import sys; sys.path.insert(0, '<本技能>/code')
import build_bin, anim_bin, ktex, klei_hash, fsb, fev
bd = build_bin.Build.parse(open('build.bin','rb').read())   # 类方法 parse，不是模块级函数
ab = anim_bin.AnimBin.parse(open('anim.bin','rb').read())
ab.anims[0].name, ab.anims[0].facing, ab.anims[0].frame_rate
klei_hash.klei_hash('cb1'), klei_hash.resolve(0x31221732)  # 小写 SDBM；12,522 条内嵌字典
ktex.KTex.parse(data).decode_mip(0)                        # 返回 rgba bytes（已翻正行序）
```

**API 名坑**（历史教训：错名被 except 吞掉得出"0 结果"假象）：
- `Build.parse` / `AnimBin.parse` / `KTex.parse` / `FsbBank.parse` 是类方法；模块没有同名顶层函数
- `klei_hash` 模块无 `strhash`；哈希函数也叫 `klei_hash`（`from klei_hash import klei_hash`）
- `AnimBin` 无 `bank_name`（anim.bin 无 bank 层，bank 名来自 build/实体名）
- 符号名优先查 `bd.hash_table.get(s.namehash)`（build 自带尾表），`s.resolved_name()` 只查全局字典
- `fsb.FsbBank` 的导出是方法 `b.to_ogg/to_wav/to_mp3(stream, data)`；格式在 `b.format`（15=Vorbis、11=MPEG、1-5=PCM）
- `Build.alphaverts` 是打包的 24 字节 blob，需 `struct.unpack('<6f', v)`

## 注意事项（实测结论，2026-11-01）

- **byte 级还原范围**：build/anim 编码器与 Klei 官方导出器在全部 11,799 个 DST+DLC 档案上往返一致；.tex 容器层全语料（1012 张）一致，像素层 ktech 等价
- **贴图语义**：Klei 纹理 bottom-up 存储（工具已处理）；DXT5 默认预乘 alpha，`tex2png` 默认反预乘（`--raw` 保留）；DXT 有损再编码差 ~2.6% 属正常
- **朝向（facing）**：动画名后缀系统（`_up`/`_90s`/8 位二进制如 `_11010000`）；二进制位序是本实现的文档化约定（MSB-first），官方游戏动画名从无后缀、无数据影响
- **碰撞盒**：应用的重算含非确定性渲染态成分（同输入异出）；本工具的纯几何公式是其确定性内核，帧 0 逐位一致
- **图集**：应用原摆放启发式未从二进制恢复，本 shelf 装箱为等价实现
- `.fev` 深层语义（LGCY 全字段）与 FDP 完整重建为部分恢复（骨架级）
- **编码器**：PNG→.tex 用 squish ClusterFit（与 ktech 同源算法，2026-11 差分验证：alpha 块 100%、色彩块 ~99% 一致、往返 PSNR 持平；残差为 f32/f64 网格边界，属构建产物）
- **改名+krane 坑**：`--rename-symbol` 自动联动 anim 元素哈希与两个尾表；但新哈希若**跨越**其它符号哈希，krane 4.4 反编译会错裁 PNG（DST Mod Tool 导入不受影响，已验证逐位一致）——需要 krane 反编译时选不越序的名字
- ktech/krane 参照用法与坑见 [ktech-krane.md](ktech-krane.md)
