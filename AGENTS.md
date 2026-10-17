# alt_workflow · AI 工作流入口

> 这是工作流的**启动文件**。任何 AI（Claude、Codex 等）开始工作前，先完整读完本文件，再按「启动流程」执行。
> 本工作流内所有路径都是**相对于本文件所在目录（工作流根目录）** 的相对路径。

## 启动流程

1. **加载通用守则**：读取 [rules/](rules/) 下全部 `*.md`。这些规则对每个任务都生效，优先级高于技能。
2. **选择技能**：根据当前任务内容，在 [skills/INDEX.md](skills/INDEX.md) 的路由表里挑选**最少数量**的相关技能；动手前完整读取每个选中技能的 `SKILL.md`。与当前任务无关的技能不要读。
3. **按需调用子代理**：任务需要自己做不到或做不好的能力（生图、识图……）时，查 [agents/INDEX.md](agents/INDEX.md)，通过 `python scripts/call_agent.py <代理名> ...` 调用。
4. **本机环境信息**：需要本机软件路径、游戏目录等信息时，查 [private/paths.md](private/paths.md)。该文件不存在时，参照 [private.example/](private.example/) 提示用户补充，不要自己猜测路径。
5. **任务内容变化时**：重新执行第 2、3 步，重新判断需要的技能和子代理。

## 目录结构

| 路径 | 作用 | 是否公开 |
| --- | --- | --- |
| `AGENTS.md` | 启动入口（本文件） | 公开 |
| `CLAUDE.md` | 让 Claude Code 自动加载本文件 | 公开 |
| `rules/` | 通用工作守则，每个任务都加载 | 公开 |
| `skills/` | 按任务选用的方法，`INDEX.md` 为路由表 | 公开 |
| `agents/` | 子代理定义：`INDEX.md` 为清单，每个代理一个子目录 | 公开 |
| `scripts/` | 子代理统一调用脚本及各后端实现 | 公开 |
| `private/` | **敏感内容**：密钥、本机路径等，已被 `.gitignore` 忽略 | 不公开 |
| `private.example/` | `private/` 的模板，供他人复制后自行填写 | 公开 |
| `output/` | 子代理默认输出目录，已被忽略 | 不公开 |

## 维护约定

- 新增技能：复制 [skills/_template/](skills/_template/)，并在 [skills/INDEX.md](skills/INDEX.md) 登记。
- 新增子代理：复制 [agents/_template/](agents/_template/)，并在 [agents/INDEX.md](agents/INDEX.md) 登记。
- 密钥、账号、本机绝对路径一律只写进 `private/`；公开文件里只用占位名引用（如 `DST_DATA_DIR`），具体值在 [private/paths.md](private/paths.md) 中查找。
