# 生成或编辑位图

> 何时使用：需要生成、修改图片，制作贴图、图标、插画、透明素材。

## 调用方式

统一通过画图子代理 `painter`（定义见 [../../agents/painter/](../../agents/painter/)）：

```
python scripts/call_agent.py painter "<英文提示词>" -i 参考图1.png -i 参考图2.png --transparent -o <输出目录>
```

- 脚本按 [agent.json](../../agents/painter/agent.json) 里的顺序尝试后端：**首选 Codex CLI**（走用户已登录的 ChatGPT / Codex 账号额度）；Codex 不可用（未登录、额度用完、调用失败）时自动退回 OpenAI 兼容接口（需在 `private/secrets.json` 配置 `painter_api`）。
- 也可用 `--backend codex_image` / `--backend openai_images` 强制指定后端。
- 结果以 JSON 打印到标准输出，`files` 字段是生成图片的路径。
- Codex 一次约 3～5 分钟（实测约 5 万 token）。在 Claude Code 中用较长超时（10 分钟）或后台运行。`failed to refresh available models: request timed out` 报错不影响出图。

## 工作流程

1. 写英文提示词，用 `-i` 附参考图（风格、尺寸、视角）。
2. 生成后用 Read 查看结果，不满意就调整提示词迭代。
3. 取回的图在本地处理（抠背景、裁剪、缩放、对齐 pivot），合成预览给用户看，**确认后**才放进项目或打包。

## 透明图

- 加 `--transparent`：Codex 后端会在提示词里追加透明背景要求，接口后端会传 `background=transparent`。
- 实测 2026-10-09：Codex 输出 RGBA PNG，背景 alpha 为 0、边缘干净。Codex 的回复可能误报「背景是黑的」——透明像素的 RGB 是 0，以文件本身为准：用 Python 检查 mode 是否 RGBA、四角 alpha 是否为 0（脚本返回的 `checks` 字段已做此检查）。
- 实测物体本身 alpha 最高只有 254，用作游戏贴图前把接近不透明的像素（≥250）改成 255（`--fix-alpha` 自动处理，需要 Pillow）。
- 透明效果不理想时退回纯色背景（如 `#FF00FF` 品红）自己抠。

## 约束

- 提示词里写明用 `gpt-image-2.5-sunburst` 生图（用户要求，脚本已自动追加）。内置工具没有模型参数，这句话只是偏好、不能保证实际模型；不要因此改走需要 `OPENAI_API_KEY` 的 imagegen CLI 回退方式。
- 只用官方 CLI 的 `codex exec`，不要用脚本或浏览器操控 ChatGPT 网页；不批量循环刷图，不把账号额度用于用户以外的人。
- 不要读取、输出或改动 `~/.codex` 下的登录凭据，也不要读取或输出 `private/secrets.json` 里的密钥。
