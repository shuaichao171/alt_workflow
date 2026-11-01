# ktech / krane 用法卡（ktools 4.4）

> 路径：`KTOOLS_DIR`（见 private/paths.md）。二者是贴图/动画转换的黄金参照 oracle，与 `code/` 内自研编解码器互为验证。

## ktech（PNG ↔ .tex）

```
ktech.exe [选项] 输入 [输出]        # 扩展名决定方向
  -c dxt1|dxt3|dxt5|rgb|rgba        # 压缩格式（默认 dxt5）
  -t 1d|2d|3d|cube                  # 纹理类型
  --no-mipmaps                      # 不生成 mip 链
  --no-premultiply                  # 不预乘 alpha
  -i                                # 只打印 .tex 信息
  -Q 0..1                           # 质量（影响 DXT 编码迭代）
```

**语义（十五轮实测）**：
- **编码恒预乘 alpha**（所有格式含 rgb/rgba），并 bottom-up 存储；**`--no-premultiply` 对编码是空操作**（2026-11 对照实验：两种参数输出字节相同），仅影响 PNG 解码输出
- **PNG 输出会反预乘**（a=0 时保留 RGB 原值不动），并已翻正行序——与自研解码对比时勿再翻转
- 不做 pow2 缩放：2050x1026 原样编码
- 编码算法 = squish 标量 ClusterFit（非迭代、Rec.709 感知权重）；`code/squish_port.py` 与之 alpha 块 100% 一致、色彩块 ~83% 位一致（其余为 f32/f64 平局翻转）
- spec word 位域：格式 5 位 [8:4]（0=DXT1,1=DXT3,2=DXT5,4=RGBA,5=RGB），mip 数 5 位 [17:13]，类型 4 位 [12:9]；[31:20]=0xFFF、[19:17]=0b110 为 Klei PC 文件恒定值
- `-v` 不带参数（带尾巴会被当输入文件）

## krane（bin → SCML/PNG）

```
krane.exe [--build 名] [--bank 名] [--mark-atlases] [--] 输入路径... 输出目录
```

- 输入为目录（含 anim.bin+build.bin）或两个 bin 文件本身；同目录的 `atlas-*.tex` 需存在（否则报错）
- 输出 Spriter SCML + 各符号帧 PNG；实体名 = build 名，动画名沿用 anim.bin（含 facing 后缀原样保留）
- 只做反编译方向（不能 SCML→bin）；SCML→bin 用 DST Mod Tool 或 `code/build_bin.py`+`anim_bin.py` 自行构造
- ktools 源码为 nsimplex/ktools（GPL v2），`ktech` 解码走 squish::DecompressImage

## oracle 对比纪律

1. 像素对比必须先对齐两件事：行序（ktech PNG 已翻正）与预乘（ktech 输出已反乘）
2. DXT 是有损格式：同一 PNG 两次编码结果稳定，但不同实现（ktech vs 自研）位级差异 ~15% 像素、幅度 ±1 属预期；判断"算法正确"用 alpha 块 100% + 色彩块统计，不追求逐位
3. 无损路径（RGB888、容器层、bin 结构）必须逐位一致才算通过

## 游戏端验证边界（2026-11-01 实测）

- 专用服务器（nullrenderer，dedicated）**不加载 ANIM 资产包**：原生 pigman 对照同样报 "Could not find anim build/bank"，
  因此 headless 专用服无法验证 anim/tex 的游戏级解析
- 渲染客户端验证需手动：mod 在客户端 mods 界面启用（modindex 为二进制格式，不能离线改写）后开服/进服观察；
  自动化受 Steam/Klei 握手与 modindex 启用机制阻断
- 结论：游戏级解析以工具对比为准（ktech 解码字节级全等 + krane 往返 + DST Mod Tool 导入差分），
  这是可自动化的最强验证通道
