# 服务档案 · sub2api

> 一个 API 聚合/分发台（`ghcr.io/shuaichao171/sub2api`），本机服务器上它把 loomy-proxy 当上游渠道用。

## 部署形态

| 项 | 值 |
| --- | --- |
| 部署目录 | `VPS_SUB2API_DEPLOY_DIR`（含 `.env`、compose、构建/版本目录） |
| 容器 | `sub2api`（`ghcr.io/shuaichao171/sub2api:<版本>`），依赖 `sub2api-postgres`、`sub2api-redis` |
| 端口 | `0.0.0.0:8080`（经 Nginx `sub2api.<域名>.conf` 对外，证书在同名目录） |
| 网络 | `sub2api-deploy_sub2api-network`（loomy-proxy 也接在这张网上） |
| 配置 | `.env` 里有 `SERVER_PORT` / `DATABASE_PORT` / `REDIS_PORT` / `ADMIN_EMAIL` / `ADMIN_PASSWORD` |

## 与 loomy-proxy 的关系（重要）

- 渠道账号：`name=loomy-proxy`、`platform=openai`、`type=apikey`、
  `base_url=http://loomy-proxy:8787/v1`（容器名互访，不走公网）、`group=lommy`。
- 账号 id 与分组 id 会变（实测过 `3643` / `28`），**以 API 查询结果为准**，别硬编码。
- loomy-proxy 侧的用量里，这把渠道用的下游密钥名是 `sub2api`。

## 管理 API（宿主机 `curl 127.0.0.1:8080`）

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8080/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$(grep -m1 '^ADMIN_EMAIL=' .env | cut -d= -f2-)\",
       \"password\":\"$(grep -m1 '^ADMIN_PASSWORD=' .env | cut -d= -f2-)\"}" | jq -r .data.access_token)

curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/v1/admin/accounts/<id> | jq
```

| 动作 | 接口 |
| --- | --- |
| 查账号状态 | `GET /api/v1/admin/accounts/<id>` → `status` / `schedulable` / `temp_unschedulable_until` |
| 连通测试 | `POST /api/v1/admin/accounts/<id>/test`（流式回包；**可能把账号打到 error 态**） |
| 恢复状态 | `POST /api/v1/admin/accounts/<id>/recover-state` |
| 重新可调度 | `POST /api/v1/admin/accounts/<id>/schedulable` `{"schedulable":true}` |
| 错误清单 | `GET /api/v1/admin/ops/errors` |

## 已知故障模式（2026-10-24 实测）

重启 loomy-proxy 时，这次调用会失败并触发：

```
WARN openai.account_temp_unscheduled_transport
  reason: "Post \"http://loomy-proxy:8787/v1/chat/completions\": dial tcp ...
           connect: connection refused"
  until:  <报错时刻 + 10 分钟>
```

- 期间表现：`account_select_failed ... "no available OpenAI accounts supporting model: X (pool=0)"`
  → 对该分组的请求全部失败，直到临时降级到期。
- **自愈**：`temp_unschedulable_until` 到点自动清空（实测 2～3 分钟内状态即回到
  `status=active` / `schedulable=true`，随后请求恢复 200）。
- **手动兜底**（只在没自愈时用）：`recover-state` + `schedulable=true`，然后再跑一次真实请求确认。

## 运维注意

- 判据是**请求是否恢复 200**（日志里的 `account_id` 命中 + `status_code: 200`），不是只看账号状态字段。
- `POST …/test` 之后记得 `recover-state` + `schedulable`，否则一次失败的连通测试会把渠道停在不可调度。
- 升级 sub2api 是它自己的事（镜像 tag 化 + 回滚镜像），**不要和 loomy-proxy 的部署混在一次变更里**。
- 服务器内存只有 3.8G，sub2api + postgres + redis + loomy-proxy 同时在跑，
  变更前先 `docker stats --no-stream` 看一眼余量。
