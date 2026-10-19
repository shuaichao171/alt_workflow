# 子代理清单

子代理用来补足主 AI 自己做不到或做不好的能力。任务需要时自行选择调用，不必等用户指示；但会消耗账号额度的调用（标注「额度」的后端）不要批量循环刷。

## 调用方式

```
python scripts/call_agent.py <代理名> "<提示词>" [-i 图片 ...] [-o 输出目录] [--backend 后端类型] [--dry-run]
python scripts/call_agent.py --list        # 查看每个代理的后端是否已配置可用
python scripts/call_agent.py --doctor      # 环境自检：Python、Pillow、private 配置、子模块、后端
```

- `scripts/call_agent.py` 相对于工作流根目录；在其他项目里工作时，用工作流根目录拼出脚本路径即可，脚本可在任意当前目录下运行。
- `-i`、`-o` 的相对路径相对于调用时的当前目录。
- 结果是 JSON：`ok` 是否成功，`backend` 实际使用的后端，`files` 生成的文件，`text` 文字回复，`attempts` 每个后端的尝试记录。
- 后端按 `agent.json` 中的顺序尝试：未配置密钥的自动跳过，失败的换下一个。
- 耗时较长（Codex 3～5 分钟）。在 Claude Code 中用 10 分钟超时或后台运行。
- 其他参数：`--prompt-file 文件` 或省略提示词/传 `-` 从 stdin 读取；`--transparent` 透明背景；`--fix-alpha` 把 alpha ≥250 补满为 255（需 Pillow）；`--timeout 秒`（默认取 agent.json 的 timeout 或 600）。

## 代理列表

| 代理 | 用途 | 输出 | 后端（按优先级） | 配置 |
| --- | --- | --- | --- | --- |
| `painter` | 生成/编辑位图，支持参考图、`--transparent`、`--fix-alpha` | `files` | `codex_image`（额度）→ `openai_images` | [painter/agent.json](painter/agent.json)，密钥 `painter_api` |
| `vision` | 识图：描述图片、读图中文字、检查 UI 截图和生成结果（必须 `-i`） | `text` | `openai_chat` → `codex_text`（额度） | [vision/agent.json](vision/agent.json)，密钥 `vision_api` |
| `glm-代码审查` | 代码审查：代码或 diff 放进提示词（或 `--prompt-file`），返回按严重程度分级的问题清单 | `text` | `openai_chat` | [glm-代码审查/agent.json](glm-代码审查/agent.json)，密钥 `glm_api` |

使用画图代理前先读 [../skills/image-gen/SKILL.md](../skills/image-gen/SKILL.md)。

## 后端类型

| 类型 | 说明 | 需要 |
| --- | --- | --- |
| `codex_image` | `codex exec` 调用 Codex 内置生图工具，从 `generated_images` 取回图片 | 已登录 Codex CLI |
| `codex_text` | `codex exec` 只读模式，返回 Codex 的最终回复 | 已登录 Codex CLI |
| `openai_images` | OpenAI 兼容 `/images/generations`、`/images/edits` | `private/secrets.json` 条目 |
| `openai_chat` | OpenAI 兼容 `/chat/completions`，图片以 base64 传入 | `private/secrets.json` 条目 |
| `command` | 任意脚本/CLI，见 [../scripts/backends/command.py](../scripts/backends/command.py) | 命令在 PATH 中 |

## 新增子代理

1. 复制 [_template/](_template/) 为 `agents/<新名称>/`，修改 `agent.json` 的 `description`、`output`、`backends`。
2. 需要密钥时，在 `private/secrets.json` 和 `private.example/secrets.json` 中各加一个同名条目（后者只放占位值）。
3. 现有后端不够用时，在 `scripts/backends/` 写新模块，并在 `scripts/backends/__init__.py` 注册。
4. 在上方「代理列表」加一行，运行 `python scripts/call_agent.py --list` 确认可用。
