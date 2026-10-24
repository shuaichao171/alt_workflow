# 服务档案 · loomy-proxy

> Loomy（讯飞 iModel）反代网关：把账号池暴露成 OpenAI / Anthropic 兼容 API，自带管理台与下游密钥。
> 源码仓库：本机 `E:/ai-work2/LoomyProxy`（目录名会变，以实际工作副本为准）。

## 部署形态

| 项 | 值 |
| --- | --- |
| 部署目录 | `VPS_LOOMY_DEPLOY_DIR`（含 `.env` / `config/` / `data/` / `secrets/` / `backups/`） |
| 源码目录 | `VPS_LOOMY_SRC_DIR`（推包目标，`deploy/install.sh` 从这里同步到 `app/`） |
| 容器名 | `loomy-proxy`，镜像 `node:24-alpine`（源码挂载模式，不 build） |
| 端口 | 宿主 `127.0.0.1:8787` → 容器 `8787`，对外由 Nginx 反代 |
| 网络 | 默认网络 + `sub2api-deploy_sub2api-network`（compose override，容器名互访） |
| 挂载 | `./app`→`/app`、`./config`→`/app/config`、`./data`→`/app/data`、`./secrets`→`/app/secrets:ro` |
| 健康检查 | `GET /health`（返回账号数、积分、模型数） |

## 数据文件（都在 `data/`）

| 文件 | 内容 | 注意 |
| --- | --- | --- |
| `accounts.json` | 账号池（含 `session`，属凭据） | 内存态整表覆盖，见下 |
| `keys.json` | 下游密钥（`sk-loomy-…`，明文只显示一次） | 同上 |
| `usage.jsonl` | 请求/用量流水（会持续增长） | 排查用 `--since`，别整文件打印 |
| `login-audit.jsonl` | 短信登录审计（只含手机号掩码） | 查发码配额与异常登录 |
| `models.json` | 模型目录缓存 | 可 `POST /admin/api/models/refresh` |

## 管理 API 速查（宿主机上 `curl 127.0.0.1:8787`，密码取自 `.env` 的 `LOOMY_PROXY_ADMIN_PASSWORD`）

| 动作 | 接口 |
| --- | --- |
| 账号列表 / 汇总 | `GET /admin/api/accounts` |
| **加账号（服务在跑时必须用这个）** | `POST /admin/api/accounts` `{name,session,userid,phone,nickname}` |
| 校验单个账号 | `POST /admin/api/accounts/<id>/check` |
| 刷新单个/全部积分 | `POST /admin/api/accounts/<id>/points`、`POST /admin/api/points/refresh` |
| 删除账号 / 启停 | `DELETE /admin/api/accounts/<id>`、`PATCH /admin/api/accounts/<id>` |
| 建 / 删下游密钥 | `POST /admin/api/keys`、`DELETE /admin/api/keys/<id>` |
| 刷新模型目录 | `POST /admin/api/models/refresh` |
| 短信登录（会真发短信） | `POST /admin/api/login/send-code` → `POST /admin/api/login/verify` |

鉴权：设了管理密码就必须带 `Authorization: Bearer <管理密码>`；未设且本机访问则放行。

## 更新流程

见 [../02-部署与更新.md](../02-部署与更新.md)。要点复述：

1. 本机 `tar`（排除 `.git` `data` `node_modules` `secrets` `config/config.json`）→ `scp` → 服务器 `rsync -a --delete` 到 `VPS_LOOMY_SRC_DIR`；
2. `cd deploy && bash install.sh --network auto`；
3. **`docker-compose restart`**（`up -d` 不会重载源码）；
4. `curl /health` 等 `healthy`；
5. 按 [../05-验证清单.md](../05-验证清单.md) 验收。

回滚：`data/` 不动，重同步旧源码后 `docker-compose restart`；数据回滚见 [../04-备份与回滚.md](../04-备份与回滚.md)。

## 依赖方 / 被依赖

- 下游调用方：同机 `sub2api`（分组 `lommy`，容器内 base_url `http://loomy-proxy:8787/v1`），
  以及直连域名的客户端（下游密钥名如 `public-url`）。
- **重启会波及 sub2api**：见 [../07-踩坑与实测结论.md](../07-踩坑与实测结论.md) 与 [sub2api.md](sub2api.md)。
- 上游：`https://loomyad.xunfei.cn/api/v1`（对话/模型）、`https://account.xfinfr.com`（短信登录签名）。

## 运维注意

- **服务在跑时不要用 CLI 改 `data/`**（`docker exec … cli.js key create` 会"创建成功但校验 401"）。
- 加账号优先走管理 API；短信登录会真发短信，同号/同 IP 有每小时发码上限。
- 改完凭据后跟依赖方确认一次真实请求是否 200，而不是只看 `/health`。
