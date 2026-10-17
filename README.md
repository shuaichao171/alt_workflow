# alt_workflow

一套给 AI 编程助手（Claude Code、Codex 等）使用的个人工作流：入口文件 + 通用守则 + 按任务选用的技能 + 可调用的子代理。

## 工作方式

```
AGENTS.md（启动入口）
 ├─ rules/        通用守则：每个任务都加载
 ├─ skills/       技能：按 INDEX.md 路由表挑选最少数量
 ├─ agents/       子代理：画图 painter、识图 vision……AI 按需自行调用
 │    └─ scripts/call_agent.py 统一调用，按 agent.json 依次尝试后端
 └─ private/      密钥、本机路径（不公开）
```

AI 读到 `AGENTS.md` 后：加载 `rules/` → 根据任务查 `skills/INDEX.md` 选技能 → 需要额外能力时查 `agents/INDEX.md` 调用子代理 → 需要本机路径时查 `private/paths.md`。

## 快速开始

1. 复制模板并填写自己的配置：
   ```
   cp -r private.example private
   ```
   - `private/secrets.json`：OpenAI 兼容接口的地址和密钥。只用 Codex 后端的话可以不填，未配置的后端会被自动跳过。
   - `private/paths.md`：本机软件、游戏目录等路径。
2. 需要 Codex 后端时，安装并登录 Codex CLI：`npm i -g @openai/codex`，然后运行 `codex` 登录。
3. 检查子代理是否可用：
   ```
   python scripts/call_agent.py --list
   ```

## 接入其他项目

工作流内部全部使用相对路径，所以整个文件夹可以放在任何位置。让某个项目使用它，在该项目的 `AGENTS.md`（或 `CLAUDE.md`）里加一句：

```
开始工作前，先阅读并遵循 <alt_workflow 所在目录>/AGENTS.md。
```

也可以把这句话写进全局配置（如 `~/.claude/AGENTS.md`、`~/.codex/AGENTS.md`），让所有项目默认使用。

## 扩展

- **技能**：复制 `skills/_template/`，在 `skills/INDEX.md` 登记。
- **子代理**：复制 `agents/_template/`，在 `agents/INDEX.md` 登记；需要新的调用方式时在 `scripts/backends/` 加后端。
- 脚本只依赖 Python 3.9+ 标准库；图片检查与 `--fix-alpha` 需要 Pillow。

## 公开前检查

- `private/`、`output/` 已在 `.gitignore` 中；`git status` 里不应出现这两个目录下的文件。
- 新增的敏感配置同步加到 `private.example/`（只放占位值）。
