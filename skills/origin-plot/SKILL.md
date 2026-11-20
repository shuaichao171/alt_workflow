# Origin 画图

> 何时使用：需要用 Origin 画科研/论文曲线图（统一样式批量出图、重绘风格不一的旧图），或从 .opju/.opj 导出数据和图，或从 PPT/Word 里抽取内嵌的 Origin 图及其数据

## 前置条件

- 本机装有 Origin（安装目录见 `private/paths.md` 的 `ORIGIN_DIR`，已验证 Origin 2021）；COM ProgID `Origin.Application`。
- Python 包：`pywin32`、`openpyxl`（读 xlsx）、`Pillow`（拼版预览）。
- 运行脚本时**不要**加 `python -I`：pywin32 装在用户 site-packages，`-I` 会导致 `import pythoncom` 失败。
- 脚本自己启动独立的 Origin 实例并在结束时 `Exit()`，不会接管或关闭用户已经打开的 Origin。

## 目录

| 文件 | 作用 |
| --- | --- |
| `style.json` | 默认画图样式（字体、字号、配色、符号、线型、坐标轴、图例、导出尺寸），每项都有 `_说明` |
| `scripts/origin_plot.py` | 主入口：读作图描述 JSON → 合并样式 → Origin 画图 → 导出 PNG + 保存 .opju |
| `scripts/_inner_plot.py` | 在 Origin 内置 Python 中执行的画图代码（由主入口调用，勿直接运行） |
| `scripts/opju_export.py` | 导出已有 .opju/.opj 的全部工作表（CSV）与图（PNG） |
| `scripts/_inner_export.py` | 上面脚本在 Origin 内执行的部分 |
| `scripts/ole_extract.py` | 从 .pptx/.docx 抽出内嵌 Origin 图为 .opj |
| `examples/example_spec.json` | 作图描述示例（虚构数据，含双系列、虚线、`%` 单位） |

## 默认样式（style.json）

| 项 | 默认值 | 说明 |
| --- | --- | --- |
| 字体 | 中文 宋体 `SimSun`，西文/数字 `Times New Roman` | 轴标题中的中文片段自动套中文字体 |
| 字号 | 轴标题 26，刻度 22，图例 22 | Origin 字号单位；导出 1400 px 宽后插入论文约等于小五~五号 |
| 配色 | `#C0392B` 红、`#1F4E9A` 蓝、`#2E8B57` 绿、`#E67E22` 橙、`#7B3F99` 紫、`#333333` 深灰 | 按系列顺序循环 |
| 符号 | 圆、方、上三角、菱形、下三角、星（Origin 代码 2,1,3,5,4,8），大小 9，实心同色 | |
| 连线 | 样条（`spline`，穿过数据点），线宽 1000（≈1.5 pt），实线 | 可选 `straight`、`bspline`（不过点）、`none` |
| 图类型 | 点线图 `line_symbol` | 可选 `line`、`scatter`、`column` |
| 坐标轴 | 四边封闭边框；只在下、左轴画刻度（朝内），上、右轴只有边框线，不画刻度也不显示数值；轴线粗 1.5 | 需要上、右刻度时设 `axes.top_right_ticks: true` |
| 刻度步长 | 未写 `x_range`/`y_range` 时，脚本按本图**全部系列**自算：步长取 1/2/5×10^n，主刻度间隔约 5 个（`major_intervals`），两端留 3% 空白（`pad`），非负数据不跨到负轴；数据只是略微越过 0（不超过跨度的 5%，如测量噪声 -0.001）时下限只留空白、不多让一整格 | 运行日志会打印每个轴算出的 from/to/inc |
| 图例 | 显示，带黑色边框，默认左上角 `tl`；左上角压线就改放右上角 `tr`（`legend.fallback`） | 两个角都压线才回到左上角并扩坐标范围：优先扩纵轴上限，纵轴范围是手工指定的才改扩横轴；只扩到曲线刚好不碰图例、再留约 2% 框高的空，步长不变（如 70～130 扩成 70～134，而不是跳到 60～140）。数据点按符号半径算，点之间的连线只有真正穿进图例框才算压线。两个范围都已指定时只在日志里提示。`legend.avoid: false` 关闭避让 |
| 单位写法 | 斜杠式「物理量/单位」，如 `推力/N`、`俯仰力矩/(N·m)` | 符合 GB/T 3102 论文惯例 |
| 导出 | PNG 宽 1400 px，同时保存 .opju | |
| 拼版预览 | 2 列，子图标签宋体 40 号放在子图下方 | 只用于预览，论文排版仍以单图为准 |

改全局默认：编辑 `style.json`。只改某张图：在作图描述里写 `"style": {...}`，与默认值深度合并。

## 作图描述（spec.json）

```json
{
  "name": "图3-8",
  "out_dir": "../重绘/图3-8",
  "style": {"axes": {"major_intervals": 6}},
  "panels": [
    {
      "name": "a", "label": "（a）最大推力",
      "x_title": "主条厚度/mm", "y_title": "最大推力/N",
      "x_range": [0.5, 2.0, 0.5], "y_range": [0, 2],
      "legend": "tl",
      "series": [
        {"label": "f = 0.4 Hz", "x": [0.6, 0.8], "y": [0.27, 0.40]},
        {"label": "f = 0.8 Hz", "file": "数据.xlsx", "sheet": "Sheet1",
         "header_row": 14, "rows": [15, 21], "x": "主条厚度", "y": "平均最大推力",
         "y_scale": 1000, "color": "#2E8B57", "symbol": 3, "dash": 1, "connect": "straight"}
      ]
    }
  ]
}
```

- `out_dir`、`file` 的相对路径都按 spec 文件所在目录解析；命令行 `--out` 优先。
- 系列数据二选一：内联 `x`/`y` 数组；或 `file`（xlsx/csv）+ 列标识。列标识可以是表头文字、Excel 列字母（`B`）或 0 起的整数。`header_row` 为表头行号（1 起，0 表示无表头），`rows` 为数据行闭区间，缺省到表尾；非数值行自动跳过。
- 每个系列可单独覆盖 `color`、`symbol`、`symbol_size`、`dash`（0 实线、1 虚线、2 点线…）、`connect`。
- 图例默认左上角、被挡就换右上角，一般不用写。确实需要换位置时，panel 里写 `legend`: `"tr"`/`"bl"`/`"br"`/`false`/`{...}`。panel 还可以写 `plot_type`、`connect`。
- 想让图例避让时改横轴而不是纵轴，就给该 panel 写死 `y_range`、不写 `x_range`。
- 单 panel 时输出 `<name>.png`；多 panel 时输出 `<name>_<panel>.png`。

## 步骤

1. 把作图描述写在**目标项目**里（如 `<项目>/绘图数据/origin_spec/图x-y.json`，或 `<项目>/_ai_work/`），尽量用 `file` 引用原始数据表，不要手抄数字。
2. 运行：

   ```
   python <工作流>/skills/origin-plot/scripts/origin_plot.py <spec.json> [--out <目录>] [--grid] [--no-opju]
   ```

   终端打印每张 PNG；有 `FAIL:` 或 `Traceback` 时退出码为 1，中间文件保留在 `<输出目录>/_origin_tmp/` 供排查。
3. 用读图工具逐张查看 PNG（曲线是否过点、图例是否遮挡曲线、刻度范围是否合理），不满意就改 spec 重跑，例如换 `legend` 位置或设 `y_range`。
4. 需要手工细调时打开同目录的 `.opju`，在 Origin 里改完自己导出。
5. 交付时说明 PNG / .opju 的位置，以及数据取自哪个文件的哪几行。

### 导出已有 Origin 项目的数据

```
python <工作流>/skills/origin-plot/scripts/opju_export.py <项目.opju> <输出目录>
```

得到 `csv/`（前三行为长名称/单位/注释）、`png/`、`info.json`。源文件只读；脚本先复制一份可写副本给 Origin 打开。

### 抽取 PPT/Word 里内嵌的 Origin 图

```
python <工作流>/skills/origin-plot/scripts/ole_extract.py <文件.pptx|.docx> <输出目录>
python <工作流>/skills/origin-plot/scripts/opju_export.py <输出目录>/<xxx>.opj <导出目录> --datasets
```

内嵌图的数据存放在隐藏数据集里，必须加 `--datasets` 才能导出成工作表。

## 注意事项

- （2026-11-15 实测，Origin 2021）COM 直接读写中文文本会乱码；所有画图都放到 Origin 内置 Python（`run -pyf`）里做，再由宿主脚本调 COM 的 `NewProject` / `Execute` / `Save` / `Exit`。
- （同上）originpro 2021 没有 `op.pages()`，`GLayer` 没有 `lt_exec`，`Plot` 没有 `lt_range`。样式一律用 LabTalk：先 `win -a <图名>`，再 `layer.plot=n; set %C ...`。枚举窗口用 `doc -e W` / `doc -e P`。
- （同上）`op.save` 和 LabTalk `save` 在脚本里会失败，保存要用宿主端 COM 的 `app.Save(路径)`。
- （同上）样条连线是 `set %C -l 9`，与 Origin 界面「Spline」一致、曲线穿过数据点。`-l 8` 是 B 样条，不过点；`-l 5` 会把图例搞乱。
- （同上）**不要依赖 Origin 的自动刻度**：`rescale` 只按第一条曲线的数据范围定步长，再把上下限拉长去包住其他曲线。例如小范围曲线在前时，纵轴从 5 个刻度变成 17 个；再执行 `rescale` 或 `layer -a` 也不会重算步长。所以脚本统一自算 from/to/inc（见 `nice_axis`）。刻度字号和图层高度不影响 Origin 选步长。
- （同上）图例边框：`legend.background=1`。图例多行文本必须用 `%(CRLF)` 连接，写 `\n` 会显示成字母 n。
- （同上）中文要用富文本 `\f:SimSun(中文)` 包起来，其余文字跟随对象的西文字体。在 bash heredoc 里写反斜杠会被吞掉，代码里用 `chr(92)`。
- （同上）`merge_graph` 在脚本里合并多图会失败。论文子图建议单独导出、在 Word 里排版；`--grid` 只生成预览拼图。
- （同上）内嵌图的隐藏数据集取 Y 用 `%(i,@D)`，`@X` 返回 `###`，X 列名只能按命名规律推断（如 `Book2_B` → `Book2_A`），导出后要人工核对 X/Y 配对。
- （同上）读 OLE 复合文档用 `pythoncom.StgOpenStorage`，读完要 `del` 存储对象，否则临时文件被锁、删不掉。
- 每次运行都会新开一个 Origin 实例并在结束时关闭。若脚本异常中断，用任务管理器结束本次多出来的 `Origin64.exe`，不要关闭用户原本开着的 Origin。
