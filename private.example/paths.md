# 本机路径（模板）

复制本目录为 `private/`，把下表路径改成你自己机器上的位置。公开文件里只用左列的占位名。

## 软件与工具

| 占位名 | 说明 | 路径 |
| --- | --- | --- |
| `IDA_PRO_DIR` | IDA Pro | `<安装目录>` |
| `KTOOLS_DIR` | ktools 4.4 | `<安装目录>` |
| `FMOD_DESIGNER_DIR` | FMOD Designer | `<安装目录>` |
| `DST_MOD_TOOLS_DIR` | 《饥荒》动画贴图打包工具目录 | `<安装目录>` |
| `OPENSPINE_DIR` | OpenSpine | `<安装目录>` |
| `POWERSHELL_DIR` | PowerShell | `<安装目录>` |
| `BLENDER_DIR` | Blender | `<安装目录>` |

## 《饥荒》

| 占位名 | 说明 | 路径 |
| --- | --- | --- |
| `DST_DATA_DIR` | 《饥荒联机版》数据目录 | `<Steam>\steamapps\common\Don't Starve Together\data` |
| `DS_GAME_DIR` | 《饥荒》单机版目录 | `<Steam>\steamapps\common\dont_starve` |
| `DST_CLIENT_LOG` | 《饥荒联机版》客户端日志 | `<文档>\Klei\DoNotStarveTogether\client_log.txt` |
| `DST_GAME_HOME` | 《饥荒联机版》安装根目录（`DST_DATA_DIR` 的上两级） | `<Steam>\steamapps\common\Don't Starve Together` |
| `DST_SCML_ANALYZER` | 已审核的 SCML 分析器脚本（animation/ 流程用） | `<脚本路径>` |
| `DS_LOG` | 《饥荒》单机版日志 | `<文档>\Klei\DoNotStarve\log.txt` |
| `DS_STEAM_CLOUD_DIR` | 《饥荒》单机版 Steam 云存档目录 | `<Steam>\userdata\<账号 ID>\219740` |
| `DS_PORT_KIT_DIR` | 早期移植技能包（port-tools.py、DST Mod Tool、详细工具命令；ds-porting/ 流程引用，可选） | `<目录>` |

## 服务器（VPS）

| 占位名 | 说明 | 路径 |
| --- | --- | --- |
| `VPS_LA_ALIAS` | 服务器 SSH 别名（配合 `~/.ssh/config` 使用） | `<别名，如 vps-la>` |
| `VPS_DOCKER_ROOT` | 服务器上 docker 项目根目录 | `<如 /www/wwwroot/docker>` |
| `VPS_LOOMY_SRC_DIR` | loomy-proxy 源码目录（推包目标） | `<VPS_DOCKER_ROOT>/loomy-proxy-src` |
| `VPS_LOOMY_DEPLOY_DIR` | loomy-proxy 部署目录（`.env`/`config`/`data`/`backups`） | `<VPS_DOCKER_ROOT>/loomy-proxy-deploy` |
| `VPS_SUB2API_DEPLOY_DIR` | sub2api 部署目录 | `<VPS_DOCKER_ROOT>/sub2api-deploy` |
| `VPS_BT_VHOST_DIR` | 宝塔 Nginx vhost 目录 | `<如 /www/server/panel/vhost/nginx>` |
| `VPS_BT_CERT_DIR` | 宝塔证书目录 | `<如 /www/server/panel/vhost/cert>` |

> 连接凭据（host / port / user / password / ssh_alias）写在 `secrets.json` 的服务器条目里，不写在本文件。
