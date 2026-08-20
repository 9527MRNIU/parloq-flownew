# Parloq Flow 生产部署记录

这份文件是本项目的长期部署交接记录。以后不需要用户再次说明服务器、域名、
目录和连接方式。真实密码、Token、代理凭据及 WhatsApp 会话不得写入仓库。

## 固定资源与当前登记

| 项目 | 值 |
| --- | --- |
| 生产服务器 | `216.106.185.81` |
| 宝塔面板 | `https://bt2.felixweb.top:10049` |
| 宝塔版本 | `11.8.1`（2026-08-14 核验） |
| 管理域名 | `https://center.parloq.com` |
| Compose project | `parloq-flow` |
| 宝塔 Compose ID | `1`（2026-08-14 核验） |
| Compose 目录 | `/www/server/panel/data/compose/parloq-flow` |
| Compose 文件 | `/www/server/panel/data/compose/parloq-flow/docker-compose.yaml` |
| 环境文件 | `/www/server/panel/data/compose/parloq-flow/.env` |
| 持久化目录 | `/data/parloq-flow` |
| 宿主机回环端口 | `127.0.0.1:18100` |
| 宝塔网站 | `center.parloq.com`，ID `38`（2026-08-14 核验） |
| 宝塔反代 | `parloq-flow` → `http://127.0.0.1:18100` |

旧 WABA 系统使用 `app.parloq.com`、Compose project `waba`、端口
`8000/8002` 和 `/data/waba`。这些不是本项目资源，禁止修改、重建、删除或
复用。宝塔把旧 `waba` 显示为「已停止」是因为它有一个成功退出的一次性
`migrate` 容器；实际 21 个常驻容器仍在运行。不要为了修正显示状态去改旧栈。

## 管理边界

应用更新直接在生产服务器本机执行，同时继续沿用宝塔登记的 Compose 项目：

- Docker 编排登记、启动和日常人工管理：宝塔 Docker/容器编排；
- 应用构建与更新：生产服务器仓库中的一键脚本直接执行 Docker Compose；
- 私有源码认证：Compose 目录中的只读 GitHub Token 文件；
- 建站与反代：宝塔 Site API；
- 证书：宝塔 SSL API；
- 自定义 Nginx 片段：宝塔 File API，使用版本号和 Parloq marker；
- Nginx 检查及 reload：宝塔 System API。

发布脚本与 Docker 位于同一台服务器，不通过宝塔 API，也不通过 SSH 绕一圈连接
自己。脚本直接维护宝塔登记目录中的 Compose 和 `.env`，因此宝塔前端仍能识别、
查看日志并管理同一个 `parloq-flow` 项目。网站、反代、证书和 Nginx 等基础设施
操作仍使用宝塔 API，禁止直接修改宝塔 SQLite。

本机连接记录在仓库根目录的未跟踪文件 `.env.baota.local`：

```dotenv
BAOTA_SSH_HOST=root@216.106.185.81
BAOTA_PANEL_REMOTE_PORT=10049
BAOTA_TOKEN_SOURCE=remote-api-json
```

该文件仅供站点、反代、证书等基础设施维护工具使用，与日常应用更新无关。它不
保存 API Key，并被 `.gitignore` 排除。若本地文件丢失，可从
`deploy/baota.env.example` 复制恢复。

## 当前架构与隔离

生产栈有独立 PostgreSQL、Redis、API、任务 Worker、Baileys 网关和静态 Web。
数据库与 Redis 不发布宿主端口，只有 Web 映射到 `127.0.0.1:18100`。持久化目录：

- `/data/parloq-flow/postgres`
- `/data/parloq-flow/redis`

API 容器设置 `AUTO_MIGRATE=true`，启动时先执行 Alembic，再开始监听端口。这样
宝塔普通 `up` 即可完成迁移，仍然只有 6 个常驻服务，不会因为一次性迁移容器
显示为停止。`migration` profile 仅保留为应急迁移入口。

不得执行 `docker compose down -v`，不得在宝塔点击「删除编排」，不得删除
`/data/parloq-flow`。宝塔的删除编排流程可能连带 volumes。

## 站点、反代与证书

`center.parloq.com` 已是独立宝塔网站，并有宝塔反代记录。创建时使用的接口口径：

1. `/site?action=AddSite` 创建 `center.parloq.com`；
2. `/site?action=CreateProxy` 创建 `parloq-flow`，回源
   `http://127.0.0.1:18100`，保留 `$http_host`；
3. `/ssl?action=get_cert_list` 找到覆盖 `*.parloq.com` 与 `parloq.com` 的最新证书；
4. `/ssl?action=SetBatchCertToSite` 把证书部署给该站点；
5. `/files?action=GetFileBody|SaveFileBody` 用 `st_mtime` 乐观锁写入 Parloq marker；
6. `/system?action=ServiceAdmin` 先 `nginx test`，成功后 `reload`。

2026-08-14 部署的通配符证书到期日为 2026-10-12。它已复制到宝塔标准目录
`/www/server/panel/vhost/cert/center.parloq.com`，可在面板 SSL 页管理。

自定义片段只拥有以下 marker 内容，不整体覆盖宝塔 vhost 或代理文件：

- vhost：Cloudflare-only 源站限制、12 MB 请求体、安全响应头；
- proxy：`X-Forwarded-*`、10 秒连接超时、120 秒收发超时、关闭请求缓冲。

参考内容在 `deploy/nginx.center.parloq.com.conf`，该文件不能直接安装成 vhost。

客户推广落地页域名由客户单独绑定。每个域名必须创建独立宝塔网站、反代和
证书，并保留原始 Host；禁止 default_server 捕获共享服务器上的其他站点。

## 常规发布

第一次在生产服务器执行发布命令时，如果尚未配置 GitHub Token，终端会提示输入
一次，输入内容不会回显。Token 随后直接保存为服务器文件
`/www/server/panel/data/compose/parloq-flow/github-token`，权限为 `600`，本地不保留
其他副本。后续发布不会再次询问：

```bash
bash deploy/release-production.sh
```

如果生产 `.env` 尚未包含 `MANAGEMENT_ORIGIN`，同一次首次发布还会提示输入管理
后台域名，并规范化为 `https://域名` 后原子写回
`/www/server/panel/data/compose/parloq-flow/.env`。该文件权限保持 `600`；后续发布
直接复用。不同服务器可以保存不同管理域名，无需修改或重新维护 Web Nginx 源码。
管理站点可使用宝塔默认的 `Host=127.0.0.1` 回环反代；容器会使用保存的管理域名
完成内部路由。客户推广域名仍必须保留原始 Host，不能使用该管理入口标记。

脚本使用 Token 执行 `git fetch`，以 fast-forward 方式更新服务器仓库到
`origin/main`，然后以服务器本机 `/root/parloq-flow` 的源码目录作为 build
context，使用 BuildKit 缓存构建三个镜像并直接更新宝塔登记的 Compose 项目。
全程不调用宝塔 API、不重复下载构建源码，也不创建宝塔计划任务。

发布完成前，脚本会同时验证容器健康、配置域名的 SPA 首页、登录安全接口以及宝塔
默认转发 Host 模式。任一检查失败都会触发原镜像和 Compose 配置恢复。

容器、revision 和健康检查全部成功后，脚本才会清理历史构建产物。API、Web、
Baileys 三个组件分别保留最近 3 个 `server`/旧 `local` Git SHA 镜像，并额外保护
所有正在运行的镜像；不会匹配或删除 WABA 镜像。BuildKit 仅清理超过 7 天的缓存，
清理失败只输出警告，不改变本次发布的成功状态。

服务器上的 `github-token` 权限为 `600`，仅由更新脚本的 Git 凭据助手读取；Token
不进入 Compose、镜像、构建参数或 Git URL。

## 人工验证与回滚

人工验证应在宝塔里确认：

- Docker → 容器编排 → `parloq-flow` 为运行中且常驻容器数为 6；
- 网站 → `center.parloq.com` 的反代为 `parloq-flow`；
- SSL 证书已部署且 HTTPS 有效；
- `https://center.parloq.com/healthz` 返回 `{"status":"ok"}`；
- `https://center.parloq.com/readyz` 返回 `{"status":"ready", ...}`，且数据库、Redis、Worker 检查均通过；
- 旧 `waba` 的 21 个常驻容器数量没有变化。

每次构建使用带 commit 短 SHA 的本地镜像标签，失败时任务恢复发布前的 `.env`
和 Compose 文件并重新启用上一版镜像。不要回滚/清空数据库；遇到不可向后兼容
迁移时，必须先单独制定数据库回滚方案。
