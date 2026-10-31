# 服务器运维

> 何时使用：在远程服务器（VPS / 云主机）上做部署、更新、容器与数据迁移、备份回滚、Nginx / 宝塔配置、只读巡检与排障时。

## 铁律（动手前先读完）

1. **只读侦察 → 备份 → 变更 → 验证**，四步不跳。事实没查清之前不要写任何东西。
2. 生产变更前先说清楚：改什么、影响哪些服务、预计停机多久，**等用户确认再执行**。
3. 凭据（SSH 密钥、AK/SK、session、管理台密码、下游密钥）只从 `private/secrets.json` 由脚本读取；
   不打印、不复述、不写进日志与提交信息、不进公开文件。
4. 含明文凭据的中间文件（迁移载荷、导出包、临时脚本）**用完立刻删**，本机与服务器两端都清。
5. 改前必须备份并记下备份路径 + md5；交付时必须给出回滚命令。
6. **服务在跑时不要直改它的内存态数据文件**，见下文「数据一致性陷阱」。
7. 变更后必须验证：健康检查 → 管理 API → 端到端真实请求 → 依赖方 → 日志无新错误。
8. 新踩的坑与实测结论带日期写进 [07-踩坑与实测结论.md](07-踩坑与实测结论.md)，不要只留在会话里。

## 文档索引

| 文件 | 什么时候读 |
| --- | --- |
| [01-连接与只读巡检.md](01-连接与只读巡检.md) | 第一次连服务器、日常巡检、排障前收集事实 |
| [02-部署与更新.md](02-部署与更新.md) | 推代码、跑安装脚本、重启容器 |
| [03-数据与凭据迁移.md](03-数据与凭据迁移.md) | 迁移账号/密钥/配置，或把本机数据搬到服务器 |
| [04-备份与回滚.md](04-备份与回滚.md) | 任何写操作之前、需要回滚时 |
| [05-验证清单.md](05-验证清单.md) | 变更之后（分层验收，命令可直接照抄） |
| [06-宝塔与-Nginx.md](06-宝塔与-Nginx.md) | 域名 / 反代 / 证书 / SSE 相关 |
| [07-踩坑与实测结论.md](07-踩坑与实测结论.md) | 动手前扫一眼，避免重复踩坑 |
| [services/](services/) | 具体服务的事实档案：目录、容器、数据文件、管理 API、依赖方 |

## 环境与凭据

- 连接信息：`private/secrets.json` → `vps_la`（`host` / `port` / `user` / `ssh_alias` / `key_path`）。只用密钥认证，不保存 SSH 密码（脚本也不支持密码登录）。
  **不要读值、不要在回复里复述**；交给 `scripts/server.py` 或 `ssh <别名>` 用。
- 服务器目录：占位名写在 `private/paths.md` 的「服务器」小节（`VPS_DOCKER_ROOT`、`VPS_LOOMY_DEPLOY_DIR`、
  `VPS_BT_VHOST_DIR` …）；本文件与子文件里一律只用占位名。
- 统一用 `ssh <alias>`（别名定义在 `~/.ssh/config`）与密钥认证，不要在文档里散落 IP。
- 本机是 Windows + MSYS：**没有 `rsync` / `sshpass`**。推包用本机 `tar` + `scp`，到服务器侧再用 `rsync --delete`。
  Git Bash 还会改写命令里的 POSIX 路径参数（把 `/www/...` 变成 Git 安装目录下的路径），
  所以远程路径一律交给 `scripts/server.py`（它会还原），手工执行 ssh/scp 时加 `MSYS_NO_PATHCONV=1` 前缀。

## 常用入口

命令中的 `scripts/` 相对于工作流根目录；在其他项目里工作时写成 `python <工作流根目录>/scripts/server.py …`。

```bash
# 只读，随时可跑
python scripts/server.py doctor                 # 本机依赖 + 连通性 + 服务器基线 + 容器状态
python scripts/server.py ps
python scripts/server.py health --port 8787
python scripts/server.py logs --container loomy-proxy --tail 100

# 写操作：默认只打印要执行的命令，必须加 --yes 才真跑
python scripts/server.py exec    --yes -- 'cd <VPS_LOOMY_DEPLOY_DIR> && docker-compose ps'
python scripts/server.py backup  --yes --dir <VPS_LOOMY_DEPLOY_DIR> --files data/accounts.json data/keys.json
python scripts/server.py push    --yes --src E:/path/to/project --dest <VPS_LOOMY_SRC_DIR>
```

脚本只用标准库 + 本机 `ssh` / `scp` / `tar`，`--help` 看全部参数。

## 数据一致性陷阱（通用）

带状态的服务常把 `data/*.json` **整表读进内存**，之后每次写盘都是**整表覆盖**：

- 服务在跑 → 增删改一律走**管理台 / 管理 API**（进程内改，再落盘）；
- 必须直接改文件 → **先停容器**，改完再起；否则新数据会被内存快照抹掉
  （症状：`list` 里看得见，过一会儿就没了）。

## 新增服务器 / 服务

1. `private/secrets.json` 加一条连接凭据，并在 `private.example/secrets.json` 加同名占位条目。
2. `private/paths.md` 与 `private.example/paths.md` 的「服务器」小节补目录占位名。
3. `services/<服务名>.md` 建档案（目录、容器、数据文件、管理 API、依赖方、更新与回滚），并在本文「文档索引」里挂上。
4. `python scripts/server.py doctor` 确认能连上并看到该服务。
