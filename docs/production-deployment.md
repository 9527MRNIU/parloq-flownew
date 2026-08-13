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

## 唯一写入控制面

生产写操作一律通过宝塔 API：

- Docker 编排登记、启动和日常人工管理：宝塔 Docker/容器编排；
- 镜像归档上传：宝塔 File API；
- 版本切换、迁移和健康验收：宝塔临时计划任务 API；
- 建站与反代：宝塔 Site API；
- 证书：宝塔 SSL API；
- 自定义 Nginx 片段：宝塔 File API，使用版本号和 Parloq marker；
- Nginx 检查及 reload：宝塔 System API。

禁止用 SSH/SCP 直接写远端文件、直接执行 Docker/Compose、直接修改 Nginx
或直接改宝塔 SQLite。SSH 只用于两件事：只读诊断，以及把本机端口加密转发
到面板的 `127.0.0.1:10049`。真正的变更请求仍由宝塔 API 完成并留下宝塔日志。

本机连接记录在仓库根目录的未跟踪文件 `.env.baota.local`：

```dotenv
BAOTA_SSH_HOST=root@216.106.185.81
BAOTA_PANEL_REMOTE_PORT=10049
BAOTA_TOKEN_SOURCE=remote-api-json
```

该文件不保存 API Key。客户端通过一次只读 SSH 调用读取服务器已配置的 Token
哈希，随后所有写操作走宝塔 API。文件被 `.gitignore` 排除，不要提交任何密钥。
若本地文件丢失，可从 `deploy/baota.env.example` 复制恢复，不需要用户重新说明
服务器连接方式。

## 当前架构与隔离

生产栈有独立 PostgreSQL、Redis、API、任务 Worker、Baileys 网关和静态 Web。
数据库与 Redis 不发布宿主端口，只有 Web 映射到 `127.0.0.1:18100`。持久化目录：

- `/data/parloq-flow/postgres`
- `/data/parloq-flow/redis`

`migrate` 服务属于 Compose profile `migration`。常规 `up` 不会创建它，因此宝塔
不会因为一个 `Exited (0)` 的迁移容器把整个 `parloq-flow` 误显示为停止。发布
脚本会显式执行一次 `--profile migration ... run --rm migrate`。

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

发布命令：

```bash
bash deploy/release-production.sh
```

脚本会：

1. 检查工作树干净、当前为 `main`、HEAD 已推送到 `origin/main`；
2. 用 `deploy/baota_api.py status` 核对网站、反代和 Docker 编排均已登记；
3. 在本机为 `linux/amd64` 构建带完整 Git revision 的三个不可变镜像；
4. 导出 tar，计算 SHA-256，通过宝塔 File API 分片上传；
5. 创建一次性宝塔任务，远端复核 SHA-256 并加载镜像；
6. 备份 `.env`，只更新 API/Web/Baileys 三个镜像变量；
7. 校验 Compose，运行一次迁移，再更新四个应用服务；
8. 验证回环健康和四个应用容器的镜像 revision；
9. 客户端轮询宝塔状态文件，成功后删除临时任务、归档和状态文件；
10. 最后验证公网 `https://center.parloq.com/healthz`。

任何步骤失败都会写入明确状态；若已经切换 `.env`，任务会恢复备份并尝试重建
上一版应用服务。数据库和 Redis 不会重建，也不会删除任何数据。失败的任务保留
在宝塔计划任务中供排查。

## 人工验证与回滚

人工验证应在宝塔里确认：

- Docker → 容器编排 → `parloq-flow` 为运行中且常驻容器数为 6；
- 网站 → `center.parloq.com` 的反代为 `parloq-flow`；
- SSL 证书已部署且 HTTPS 有效；
- `https://center.parloq.com/healthz` 返回 `{"status":"ok"}`；
- 旧 `waba` 的 21 个常驻容器数量没有变化。

回滚使用发布前的 `.env.backup-<commit>-<UTC>`，只恢复三个镜像变量并通过
宝塔临时任务执行应用服务更新。不要回滚/清空数据库；遇到不可向后兼容迁移时，
必须先单独制定数据库回滚方案。
