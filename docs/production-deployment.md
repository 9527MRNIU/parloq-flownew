# Parloq Flow 生产部署记录

本文档记录 Parloq Flow 在现有生产服务器上的独立部署方式，避免每次重新
确认 SSH、目录、端口和发布流程。真实密码、Token、代理凭据和 WhatsApp
会话不得写入仓库。

## 固定信息

| 项目 | 值 |
| --- | --- |
| 生产服务器 | `216.106.185.81` |
| SSH | `ssh -o BatchMode=yes root@216.106.185.81` |
| 管理域名 | `https://center.parloq.com` |
| Compose project | `parloq-flow` |
| Compose 目录 | `/www/server/panel/data/compose/parloq-flow` |
| Compose 文件 | `/www/server/panel/data/compose/parloq-flow/docker-compose.yaml` |
| 环境文件 | `/www/server/panel/data/compose/parloq-flow/.env` |
| 持久化目录 | `/data/parloq-flow` |
| 宿主机回环端口 | `127.0.0.1:18100` |
| Nginx vhost | `/www/server/panel/vhost/nginx/center.parloq.com.conf` |

旧 WABA 系统使用 `app.parloq.com`、Compose project `waba`、端口
`8000/8002` 和 `/data/waba`。这些资源不是本项目的一部分，任何 Parloq
Flow 部署都不能修改或复用它们。

## 架构和隔离

生产 Compose 包含独立 PostgreSQL、Redis、迁移任务、API、任务 Worker、
Baileys 网关和静态 Web 服务。数据库与 Redis 不发布宿主机端口；只有 Web
服务发布到 `127.0.0.1:18100`，再由宝塔 Nginx 提供公网 HTTPS。

数据使用以下宿主机目录：

- `/data/parloq-flow/postgres`
- `/data/parloq-flow/redis`

不要执行 `docker compose down -v`，也不要把 `/data/waba` 当成本项目数据。

## DNS 和证书

`parloq.com` 使用 Cloudflare DNS。`center.parloq.com` 应在 Cloudflare 中指向
生产源站 `216.106.185.81` 并保持代理开启。仓库里的 Nginx 模板复用现有
`parloq.com` 通配符证书和 Cloudflare 源站限制。

客户推广域名不使用系统主域名。每个客户域名应：

1. CNAME 到 `center.parloq.com`，或按运营要求使用等价的源站记录；
2. 在服务器增加只包含该域名的 Nginx vhost；
3. 申请对应证书；
4. 将请求代理到 `127.0.0.1:18100` 并保留原始 `Host`；
5. 再在后台执行域名验证和渠道绑定。

不要安装捕获所有域名的 `default_server`，共享服务器上还有其他站点。

## 首次部署

首次部署前，本地代码应已测试、提交并推送。构建并导出三个不可变镜像：

```bash
bash deploy/build-production-images.sh
```

服务器初始化目录：

```bash
install -d -m 700 /www/server/panel/data/compose/parloq-flow
install -d -m 700 /data/parloq-flow/postgres /data/parloq-flow/redis
```

把 `deploy/docker-compose.production.yml` 安装为服务器的
`docker-compose.yaml`，把 `deploy/production.env.example` 复制成 `.env`，
用独立随机值替换所有 `change-me-*`，并设置权限为 `600`。三个镜像变量应
使用本次提交 SHA。不得从旧项目复制数据库密码或应用密钥。

安装 `deploy/nginx.center.parloq.com.conf` 前先执行 `nginx -t`；安装后再次
检查并 reload。由于现有 `parloq.com *.parloq.com` vhost 属于旧系统，新的
精确 `center.parloq.com` server block 必须独立存在。

启动顺序：

```bash
cd /www/server/panel/data/compose/parloq-flow
docker compose --env-file .env -f docker-compose.yaml config --quiet
docker compose --env-file .env -f docker-compose.yaml up -d postgres redis
docker compose --env-file .env -f docker-compose.yaml run --interactive=false -T --rm migrate
docker compose --env-file .env -f docker-compose.yaml up -d --no-deps wa-gateway api api-worker web
docker compose --env-file .env -f docker-compose.yaml ps
curl -fsS http://127.0.0.1:18100/healthz
```

## 常规发布：本地构建并直接上传

常规发布使用：

```bash
bash deploy/release-production.sh
```

脚本会检查干净工作树与已推送的 `main`，构建 `linux/amd64` 镜像，导出压缩
包，做本地和远端 SHA-256 校验，加载镜像，备份 `.env`，只更新三个镜像
变量，执行迁移并重建应用服务。它不会覆盖生产 Compose/Nginx，不会重建
数据库，也不会删除数据。

## 验证

```bash
ssh -o BatchMode=yes root@216.106.185.81
cd /www/server/panel/data/compose/parloq-flow
docker compose --env-file .env -f docker-compose.yaml ps
docker compose --env-file .env -f docker-compose.yaml logs --tail=200 api web wa-gateway api-worker
curl -fsS http://127.0.0.1:18100/healthz
curl -fsS https://center.parloq.com/healthz
```

还应检查每个应用容器的 `org.opencontainers.image.revision` 与目标提交一致、
重启次数没有增加、迁移任务成功，以及最近日志没有数据库/网关错误。

## 回滚

`.env` 每次发布前会备份为 `.env.backup-<commit>-<UTC时间>`。回滚时恢复
上一个版本的三个镜像变量，然后只重建应用服务：

```bash
docker compose --env-file .env -f docker-compose.yaml up -d --no-deps \
  wa-gateway api api-worker web
```

不要为了回滚应用镜像而回滚或清空数据库。若迁移不可向后兼容，应先停止
发布并单独制定数据库回滚方案。
