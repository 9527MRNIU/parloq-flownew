# 推广模板账号配对链路

本文档说明推广落地页中“提交号码 → 获取配对码 → 等待手机确认 → 完成接入”
的当前业务链路。内容以模板开发和问题排查需要为准，不展开内部表结构细节。

当前契约版本为 `promotion-browser-bridge/v2`，本文档最后按 2026-08-24 的
`main` 分支实现核对。

## 一、先看结论

模板只调用平台注入的 `window.PromotionBridge`：

```text
模板页面
  └─ submitPhone(phone)
       └─ Parloq API：校验渠道、号码、限速、协议、分组和代理
            └─ WhatsApp 网关：申请配对码并维持临时连接
                 └─ 用户在手机 WhatsApp 中输入配对码

模板页面
  └─ getPairingStatus(pairing)，按服务端建议间隔轮询
       ├─ waiting_phone / reconnecting：继续等待
       ├─ verified：配对成功，停止轮询
       └─ expired / cancelled / failed：终止本次配对，可重新开始

配对成功后
  └─ Worker 异步同步头像、资料、群组摘要等信息
```

最重要的判断规则只有一条：

```text
pairingStatus === "verified" && verified === true
```

只有同时满足这两个条件，模板才能显示“账号接入成功”。不要根据
`accountState`、旧字段 `state` 或 `initializationStatus` 自行推断配对成功。

## 二、各部分负责什么

| 部分 | 职责 |
| --- | --- |
| 模板 | 收集号码、展示配对码、倒计时、轮询状态和展示结果 |
| `PromotionBridge` | 组织请求、采集设备指纹和基础客户端环境、管理配对状态凭证并解析统一错误 |
| Parloq API | 验证渠道、执行限速、选择协议节点、绑定分组与代理、保存配对尝试 |
| WhatsApp 网关 | 创建临时配对连接、申请配对码、确认手机授权、报告断线和终态 |
| Worker | 配对成功后异步同步账号资料，不阻塞“配对成功”结果 |

模板不能直接请求账号中心或 WhatsApp 网关，也不能自己拼接状态 URL 或鉴权头。

## 三、页面打开时准备了什么

服务端渲染落地页时会注入：

- `pairingStartUrl`：开始配对地址；
- 渠道、语言、模板策略和营销事件配置；
- `window.PromotionBridge` 三个方法。

平台运行时始终采集时区、视口、屏幕尺寸、像素比和触控点数量等基础客户端环境，
并使用仓库内固定版本的 ThumbmarkJS 1.10.1 计算设备指纹。指纹缓存在 `_fp`；如果
浏览器不支持或计算失败，则生成低可信度的降级标识。

原始指纹会随页面行为和开始配对请求提交。API 立即把它转换成租户隔离的 HMAC，
原始值不落库；随后查找或创建服务端 `PromotionVisitor`，其对外标识是 Snowflake
ID。访问事件、iframe 集成事件、配对尝试、UV、限速和 Meta 回传都关联这个服务端
访客实体。

iframe 集成同样复用 `_fp`，只从 URL fragment 接收非敏感的渠道 slug 和直推/裂变
来源；每次上报时由服务端重新验证域名、渠道、模板与集成绑定。这些步骤均由平台
运行时自动完成，模板不需要读取或保存身份字段。

## 四、请求开始配对

### 4.1 模板调用

```js
const response = await window.PromotionBridge.submitPhone(phone, {
  placement: "hero-form"
});
const result = await response.json();
const pairing = result.data.pairing;
```

正常响应会返回 `Response`。开始配对返回非 2xx 时，Bridge 会读取服务端错误并
抛出 `AccountLinkError`，模板应使用 `try/catch` 处理：

```js
try {
  const response = await window.PromotionBridge.submitPhone(phone);
  const pairing = (await response.json()).data.pairing;
} catch (error) {
  // error.code / error.message / error.retryable / error.status
}
```

Bridge 实际发送：

```http
POST /api/public/promotion/channels/{slug}/pairing/start
Content-Type: text/plain;charset=UTF-8
```

裂变入口使用独立的
`/api/public/promotion/channels/{slug}/fission/pairing/start`，由服务端路由确定
流量来源，不接受客户端自行声明来源。

请求体是 JSON：

```json
{
  "phone": "+4915123456789",
  "deviceFingerprint": "ThumbmarkJS 指纹或低可信度降级值",
  "metadata": {
    "placement": "hero-form",
    "clientContext": {
      "timeZone": "Europe/Berlin",
      "viewport": [390, 844],
      "screen": [390, 844],
      "pixelRatio": 3,
      "touchPoints": 5
    }
  }
}
```

`Content-Type` 虽然是 `text/plain`，正文仍然是 JSON。这是平台运行时的请求方式，
模板只调用 Bridge 即可。

请求体不携带 User-Agent、访问 IP 或访问国家。API 从 HTTP 请求头和可信反向代理
提供的信息中读取这些数据，避免把客户端自报值当成可信网络信息。

### 4.2 服务端依次处理

正常情况下，API 按以下顺序执行：

1. 校验并标准化手机号码；
2. 根据请求路径确认直推或裂变来源，并确认渠道有效；
3. 把原始指纹转换成租户 HMAC，查找或创建服务端 Snowflake 访客；
4. 保存一次服务端 `phone_submit` 记录，并更新对应号码线索；
5. 按租户指纹访客、访问 IP 执行提交前限速；
6. 保存 `pairing_check`，表示请求进入业务检查阶段；
7. 检查号码是否已经存在、已经接入或正在由其他访问者配对；
8. 为新接入选择渠道配置的协议节点或协议池；重新认证则沿用账号原协议；
9. 确认新账号需要进入的账号分组；
10. 按租户指纹访客、号码和渠道执行创建配对尝试前的第二层限速；
11. 为账号分配并固定一条代理线路；
12. 创建 `AccountPairingAttempt`，固化本次分组、协议节点、同步策略和过期时间；
13. 调用 WhatsApp 网关创建或更新网关账号，并申请配对码；
14. 保存 `pairing_started`，把配对状态更新为 `waiting_phone`；
15. 返回配对码、状态地址、取消地址和本次配对专用的状态凭证。

创建配对尝试后，即使管理员随后修改渠道的默认分组、协议节点或同步策略，本次
配对仍然使用开始时已经固化的配置。

### 4.3 正常响应

```json
{
  "data": {
    "pairing": {
      "pairingCode": "4827-1639",
      "attemptId": "配对尝试ID",
      "pairingStatus": "waiting_phone",
      "expiresAt": "2026-08-24T12:03:00Z",
      "statusUrl": "/api/public/promotion/channels/.../status",
      "cancelUrl": "/api/public/promotion/channels/.../cancel",
      "statusToken": "本次配对的状态凭证",
      "statusTokenHeader": "Authorization",
      "statusTokenScheme": "Bearer"
    },
    "metaEvent": null
  }
}
```

模板应该保存完整的 `pairing` 对象，并原样交给 Bridge 的状态查询和取消方法。
不要只保存配对码，也不要把 `statusToken` 放进 URL。

配对码通常有效约 3 分钟。服务端会校验网关返回的过期时间，只接受合理范围内
的值，异常时回退到 3 分钟。

## 五、轮询配对状态

### 5.1 模板调用

```js
const response = await window.PromotionBridge.getPairingStatus(pairing);
const { data } = await response.json();
```

Bridge 会自动发送：

```http
GET {pairing.statusUrl}
Authorization: Bearer {pairing.statusToken}
```

状态凭证只属于当前渠道、账号和配对尝试。状态查询不接受 URL 查询参数中的
Token，Bridge 会使用 `no-store` 缓存策略。与开始配对不同，状态查询和取消
方法会原样返回 HTTP `Response`，模板需要先检查 `response.ok`。

### 5.2 状态响应

```json
{
  "data": {
    "pairingStatus": "waiting_phone",
    "verified": false,
    "attemptId": "配对尝试ID",
    "expiresAt": "2026-08-24T12:03:00Z",
    "accountState": "pairing",
    "initializationStatus": "pending",
    "reasonCode": null,
    "providerCode": null,
    "retryable": false,
    "nextPollAfterMs": 2000
  }
}
```

模板应优先使用 `nextPollAfterMs`，不要写死高频轮询。

### 5.3 每种配对状态如何处理

| `pairingStatus` | 含义 | 模板处理 |
| --- | --- | --- |
| `code_issued` | 配对码已经生成的短暂内部阶段 | 展示配对码并开始轮询；正常生产响应通常会直接进入 `waiting_phone` |
| `waiting_phone` | 等待用户在手机 WhatsApp 中输入并确认配对码 | 保持配对码和倒计时，约 2 秒后继续轮询 |
| `reconnecting` | 配对临时连接正在恢复，但仍在有效期内 | 显示“正在恢复连接”，约 3 秒后继续轮询，不得显示成功 |
| `verified` | 手机授权已经由网关确认 | 只有 `verified === true` 时显示成功并停止配对轮询 |
| `expired` | 配对码过期 | 停止轮询，提示重新获取配对码 |
| `cancelled` | 用户主动取消 | 停止轮询，返回可重新输入号码的状态 |
| `failed` | 网关断线、会话失败、账号受限或其他终止原因 | 停止轮询，显示中性失败信息并允许重新开始 |

服务端判定状态时遵循以下原则：

- 已经落库的终态不会被后续网关状态覆盖；
- 网关明确验证成功时，即使刚好超过倒计时，也优先认定为 `verified`；
- 未验证且超过有效期时认定为 `expired`；
- 配对期间连接中断且临时会话已经不可恢复时认定为 `failed`；
- 查询网关临时失败时，API 使用已保存状态兜底，不会直接把配对判成成功。

## 六、手机确认成功之后

当状态首次变为 `verified` 时，API 会：

1. 把配对尝试标记为 `verified` 并记录确认时间；
2. 把账号校验状态改为 `ready`，正式入池状态改为 `active`；
3. 使用本次配对开始时固化的账号分组和协议节点；
4. 保存 `pair_success` 业务事件；
5. 对首次接入按渠道配置生成 Browser Pixel / CAPI 成功事件；
6. 创建账号资料同步任务；
7. 通知对应账号分组重新检查等待可用账号的任务。

### 配对成功与资料同步是两个阶段

`pairingStatus=verified` 表示 WhatsApp 配对已经成功。随后
`initializationStatus` 可能是：

| `initializationStatus` | 含义 | 模板建议 |
| --- | --- | --- |
| `pending` | 已创建资料同步任务，尚未开始 | 可显示“账号已连接，正在初始化” |
| `syncing` | Worker 正在同步资料 | 可继续显示初始化提示 |
| `ready` | 资料同步完成 | 显示完整完成状态 |
| `unsupported` | 当前协议不支持部分同步能力 | 配对仍然成功，不要求重新绑定 |
| `failed` | 资料同步失败 | 配对仍然成功；显示中性提示，由管理端重试同步 |

资料同步失败不会把已经成功的配对改回 `failed`，模板不能要求用户重新输入
配对码。

## 七、取消配对

模板调用：

```js
await window.PromotionBridge.cancelPairing(pairing);
```

Bridge 实际发送：

```http
POST {pairing.cancelUrl}
Authorization: Bearer {pairing.statusToken}
```

活动配对被取消时，系统会：

- 通知网关停止临时连接；
- 清除尚未验证的临时认证数据；
- 把配对尝试标记为 `cancelled`；
- 把未完成的新账号标记为放弃接入；
- 返回：

```json
{
  "data": {
    "pairingStatus": "cancelled",
    "cancelled": true
  }
}
```

配对已经进入终态时，取消请求不会重新改变其业务结果。状态查询和取消接口允许
渠道暂停后继续使用，避免用户已经拿到配对码后突然无法完成或取消。

## 八、开始配对常见错误

统一错误主体为：

```json
{
  "error": {
    "code": "rate_limited",
    "message": "绑定请求过于频繁，请稍后再试",
    "retryable": true,
    "retryAfterSeconds": 17
  }
}
```

`retryAfterSeconds` 只在需要等待后重试时出现。

上述是 API 的完整错误响应。当前 Bridge 抛出的 `AccountLinkError` 会保留
`code`、`message`、`retryable` 和 HTTP `status`，但不会保留
`retryAfterSeconds`。因此现有模板只能显示通用的“稍后重试”；如果以后需要精确
倒计时，应先扩展 Bridge 的错误对象。

| HTTP | `error.code` | 触发情况 | 模板处理 |
| --- | --- | --- | --- |
| 422 | `invalid_phone` | 号码无法标准化为有效国际号码 | 保留输入界面，提示用户修正号码 |
| 409 | `number_unavailable` | 号码属于其他租户、并发创建冲突或当前不可接入 | 显示中性“号码暂不可用”，不要泄露号码归属 |
| 409 | `account_already_linked` | 号码已经绑定并可用 | 告知无需重复绑定，不要继续请求新配对码 |
| 409 | `pairing_in_progress` | 其他渠道或其他访问者正在配对同一号码 | 提示已有进行中的请求，稍后再试 |
| 409 | `protocol_unavailable` | 渠道没有可用协议节点，或原账号协议不可用 | 显示服务暂不可用，允许稍后重试 |
| 409 | `protocol_capacity_limited` | 协议节点并发配对达到上限 | 显示当前繁忙，允许稍后重试 |
| 409 | `channel_configuration_unavailable` | 新账号接入分组缺失或不可用 | 显示渠道暂不可用，停止自动重试 |
| 409 | `connection_route_unavailable` | 无法为账号分配固定代理线路 | 显示连接线路繁忙，允许稍后重试 |
| 429 | `rate_limited` | 指纹访客、IP、号码或渠道达到限速 | 显示稍后重试；API 已返回等待时间，但当前 Bridge 尚未透传 |
| 502 | `gateway_failed` | 网关创建账号或申请配对码失败 | 显示服务暂时不可用，允许重新开始 |
| 503 | `service_temporarily_unavailable` | 限速或依赖服务暂时不可用 | 显示服务暂不可用，稍后再试 |

## 九、模板推荐决策逻辑

```js
if (pairingStatus === "verified" && verified === true) {
  stopPolling();
  showConnected(initializationStatus);
} else if (["expired", "cancelled", "failed"].includes(pairingStatus)) {
  stopPolling();
  showRetryState(pairingStatus, reasonCode);
} else {
  scheduleNextPoll(nextPollAfterMs || 2000);
}
```

模板还应遵守：

- 一个提交动作只调用一次 `submitPhone`，不要用重复提交代替状态轮询；
- 页面隐藏、用户取消或进入终态后停止轮询；
- 保存完整 `pairing` 对象，不解析其中的不透明凭证；
- 仅向用户展示中性错误，不显示协议节点、代理、网关或租户信息；
- `accountState` 只用于排查，不能驱动模板成功页面；
- `reasonCode` 和 `providerCode` 可用于诊断或映射中性文案，不能直接原样暴露。

## 十、监控记录如何对应

| 阶段 | 主要记录 |
| --- | --- |
| 号码提交被接受 | `promotion_events.phone_submit` 和号码线索 |
| 进入业务检查 | `promotion_events.pairing_check` |
| 创建配对码成功 | `promotion_events.pairing_started` + `account_pairing_attempts` |
| 创建尝试前失败 | `promotion_events.pairing_failed` |
| 创建尝试后失败、过期或取消 | `account_pairing_attempts` 的终态和原因 |
| 手机确认成功 | `promotion_events.pair_success` + 配对尝试 `verified` |
| 后续资料同步 | `account_metadata_sync_jobs` |

因此，访问监控主要看到页面行为和业务节点；接入记录以
`AccountPairingAttempt` 为主，负责展示一次真实配对尝试从开始到终态的结果。
两类记录显示的访客 ID 都来自同一个服务端 `PromotionVisitor` Snowflake ID；UV 也
按渠道与该访客 ID 去重，不再混用浏览器 UUID 和指纹两种口径。
访问 IP、访问国家、浏览器和系统信息均取自服务端收到的 HTTP 请求，并随配对事件
和配对尝试保存；它们不依赖模板在 `clientContext` 中主动上报。

## 十一、重新认证的区别

已接入账号如果进入 `reauth_required`，再次从原渠道提交同一号码会创建
`reauthentication` 类型的配对尝试。它与首次接入的页面状态和请求方式一致，
但会保留账号原有的租户、分组、协议节点、代理和来源信息，不会按照渠道当前
默认配置把账号迁移到其他位置。重新认证成功后会再次触发资料同步，但不会重复
计算首次接入的营销资格。
