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

## 产物落位（重要）

工作流目录只放 **规则、技能、子代理**；任务的产物不要落在工作流里。

- 任务产物（脚本、报告、中间文件、生成物）一律放在**被操作的目标项目目录**内，用一个不会与项目本体混淆的子目录承载：

  ```
  <目标项目>/
   └─ _ai_work/          # 下划线开头，明确不是项目源码/配置
       ├─ README.md      # 任务报告
       ├─ *.py           # 任务脚本
       └─ out/           # 中间与最终产物
  ```

- `output/` 只用于**工作流自身调用的子代理**（生图、识图等）产生的临时输出；它不是任务工作区，任务结束时清理自己产生的文件。
- 不能确定产物该放哪里时，先问用户，不要默认丢进工作流目录。
- 需要跨任务复用一个固定工作目录时，把路径登记到 `private/paths.md`，公开文件里用占位名引用。

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
   python scripts/call_agent.py --doctor   # 更全面的环境自检（Pillow、private 配置、子模块）
   ```

4. 需要连服务器时（可选）：在 `private/secrets.json` 填好服务器条目，先跑只读自检 `python scripts/server.py doctor`；
   方法与铁律见 `skills/server-ops/SKILL.md`（部署更新、数据迁移、备份回滚、验证清单、Nginx/宝塔）。

## 接入其他项目

工作流内部全部使用相对路径，所以整个文件夹可以放在任何位置。让某个项目使用它，在该项目的 `AGENTS.md`（或 `CLAUDE.md`）里加一句：

```
开始工作前，先阅读并遵循 <alt_workflow 所在目录>/AGENTS.md。
```

也可以把这句话写进全局配置（如 `~/.claude/AGENTS.md`、`~/.codex/AGENTS.md`），让所有项目默认使用。

## 扩展

- **技能**：复制 `skills/_template/`，在 `skills/INDEX.md` 登记。
- **子代理**：复制 `agents/_template/`，在 `agents/INDEX.md` 登记；需要新的调用方式时在 `scripts/backends/` 加后端。
- Python 脚本使用 Python 3.9+ 标准库；图片检查与 `--fix-alpha` 需要 Pillow。
- **服务器运维**：技能在 `skills/server-ops/`，服务事实档案在 `skills/server-ops/services/`；配套 `scripts/server.py`（只读优先，写操作要 `--yes`，凭据只从 `private/secrets.json` 读、不回显）。
- **饥荒工坊上传**：技能在 `skills/steam-workshop-upload/`，配套 `scripts/workshop.ps1`；包含精简 C# 核心和 Klei 的 32 位 `steam_api.dll`，支持按名字查本人已发布列表（匹配出的 ID 必须获得用户明确确认）、AI 选择文件、离线清单、单机/联机上传和结果回查。需要 .NET 10 SDK 与 x86 运行时，不需要完整上传器。任务配置、快照和构建产物放在目标项目的 `_ai_work/workshop/`。

## 公开前检查

- `skills/dst-modding/mod-skills/` 是 Git 子模块（见 `.gitmodules`）。修改它时先在子模块目录里提交并推送，再回到本仓库提交新的子模块指针；只推本仓库会让别人拉到不存在的提交。
- 克隆本仓库用 `git clone --recursive`，已克隆的用 `git submodule update --init`。
- `private/`、`output/` 已在 `.gitignore` 中；提交前运行 `python scripts/check_public.py` 自动检查（两个目录未被跟踪、公开文件无真实密钥）。
- 新增的敏感配置同步加到 `private.example/`（只放占位值）。
