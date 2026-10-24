# 06 · 宝塔与 Nginx

> 服务器上的对外入口一律由宿主机 Nginx（宝塔面板装的那种）反代，容器只绑 `127.0.0.1`。

## 目录（占位名见 private/paths.md）

| 用途 | 占位名 |
| --- | --- |
| nginx vhost 目录 | `VPS_BT_VHOST_DIR` |
| 证书目录 | `VPS_BT_CERT_DIR` |

```bash
ssh <别名> 'ls -1 <VPS_BT_VHOST_DIR>'
ssh <别名> 'ls -1 <VPS_BT_CERT_DIR>'
ssh <别名> 'nginx -t && nginx -s reload'
```

## 反代要点（SSE / 流式必须照抄）

- `proxy_buffering off;` + `proxy_request_buffering off;` + `proxy_read_timeout 900s;`
  再补 `add_header X-Accel-Buffering no;`——否则流式接口会"一次性吐完"或提前断开。
- `proxy_set_header Upgrade/Connection`（websocket 站点需要）。
- 反代目标写 `http://127.0.0.1:<宿主端口>`；同机容器互访则用容器名 + compose 网络。

## 坑：宝塔会重写 vhost

在宝塔面板里对同名站点**点过「保存」**，就会用面板模板重写该 vhost 文件，手工加的反代与 SSE 参数会丢。
处理办法：

1. 改完在面板外留一份备份（形如 `*.conf.bak-pre-acme`）；
2. 丢了就照模板补回，再 `nginx -t && nginx -s reload`；
3. 长期方案：把反代参数写进面板的"配置文件"里保存，而不是只改磁盘文件。

## HTTPS 证书（acme.sh / Let's Encrypt，实测通过）

```bash
# 1) webroot 目录要能被 80 端口访问到
mkdir -p /www/wwwroot/<域名>/.well-known/acme-challenge
# 2) 签发（ECC）
curl -s https://get.acme.sh | sh -s email=<邮箱>
~/.acme.sh/acme.sh --set-default-ca --server letsencrypt
~/.acme.sh/acme.sh --issue -d <域名> -w /www/wwwroot/<域名>
# 3) 装到宝塔证书目录并自动续期
~/.acme.sh/acme.sh --install-cert -d <域名> --ecc \
  --key-file       <VPS_BT_CERT_DIR>/<域名>/privkey.pem \
  --fullchain-file <VPS_BT_CERT_DIR>/<域名>/fullchain.pem \
  --reloadcmd      "nginx -s reload"
# 4) 先有证书再启用 HTTPS vhost，否则 nginx 起不来
```

- 80 端口保留 `/.well-known/acme-challenge/` 直出（不跳转），其余 301 到 443。
- 续期状态：`~/.acme.sh/acme.sh --list`。

## 排查顺序

1. `curl -s http://127.0.0.1:<宿主端口>/health`（绕开 Nginx，先证明容器没问题）
2. `curl -sI https://<域名>/health`（再证明 Nginx/证书没问题）
3. 看 nginx error log 与 `docker logs`，确认是 502（后端没起）还是 504（超时/缓冲设置）。
4. 公网 DNS / CDN（如 Cloudflare 橙云）会掩盖源站问题：源站没证书时 SSL 模式必须是 Flexible。
