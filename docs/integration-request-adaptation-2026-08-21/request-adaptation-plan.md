# 集成请求封装说明

更新日期：2026-08-24
状态：以当前 iframe 集成运行时实现为准

## 1. 当前运行时契约

平台为启用反馈能力的 iframe 集成注入 `window.PromotionIntegrationBridge`：

```ts
type PromotionIntegrationBridge = {
  version: "promotion-integration-bridge/v2";
  ready(): Promise<{
    integration: { id: string };
    channel: { slug: string; trafficSource: "direct" | "fission" };
    eventUrl: string;
  }>;
  report(eventType: string, metadata?: Record<string, unknown>): Promise<Response>;
};
```

集成只需要等待 `ready()`，然后通过 `report()` 提交业务事件。平台运行时负责采集
ThumbmarkJS 指纹和基础客户端环境，并发送以下请求：

```json
{
  "eventType": "whatsapp_upload",
  "deviceFingerprint": "32 位 Thumbmark 或低可信度降级值",
  "occurredAt": "2026-08-24T12:00:00Z",
  "metadata": {
    "schemaVersion": 1,
    "callbackPath": "/api/v1/whatsapp/upload",
    "payload": "集成业务载荷",
    "clientContext": {
      "timeZone": "Asia/Shanghai",
      "viewport": [390, 844],
      "screen": [390, 844],
      "pixelRatio": 3,
      "touchPoints": 5
    }
  }
}
```

API 接收请求后会重新验证集成、渠道、模板、域名和事件声明，把原始指纹转换为租户
HMAC 并关联服务端 `PromotionVisitor`。访问 IP、国家、User-Agent、事件 ID 和接收
时间均由服务端确定。

## 2. 请求封装原则

被接入的脚本不再直接请求原业务接收地址，而是把原接口语义作为 metadata 交给
Bridge：

```js
await window.PromotionIntegrationBridge.report("ip_sync", {
  schemaVersion: 1,
  callbackPath: "/api/v1/ip-sync",
  requestKind: "periodic",
  payload: buildIpSyncBody(),
});
```

- `callbackPath` 只描述原协议语义，不作为实际网络目标；
- `payload` 保留原业务结构，Parloq 接入层不解释 Telegram、WhatsApp 或设备字段；
- 渠道身份来自当前 iframe 路径和服务端绑定，不接受业务载荷自行指定；
- 集成事件必须在 `integration.json.feedback.events` 中声明；
- `page_view` 和 `visit_end` 由平台运行时自动上报，集成脚本不重复实现。

当前适配事件包括：

| 原接口语义 | `eventType` |
| --- | --- |
| IP 周期回传 | `ip_sync` |
| 调试信息 | `integration_debug` |
| 设备激活 | `device_activate` |
| 应用列表 | `device_apps` |
| Telegram 数据 | `telegram_upload` |
| WhatsApp 数据 | `whatsapp_upload` |

## 3. 载荷与网络规则

- 单条集成 metadata 上限为 `1 MiB`；
- 完整请求上限为 `1 MiB + 64 KiB`，超限返回 `413`；
- 一个原始业务请求对应一条完整事件，不截断、不自动分片；
- 生产请求只允许 HTTPS，并正常校验证书链；
- `Content-Length` 按 UTF-8 字节长度计算；
- 接受整个 `2xx`，只对连接错误、超时、`408`、`429` 和 `5xx` 重试；
- `429` 优先遵循 `Retry-After`，其他重试使用有上限的退避；
- 管理列表只返回大载荷摘要和大小，详情接口再读取完整 metadata。

## 4. 实现边界

当前 Bridge 源码位于：

- `apps/web/src/public-runtime/promotion-integration-frame.ts`
- `apps/web/src/public-runtime/device-fingerprint.ts`
- `apps/api/app/routers/promotion_integrations.py`
- `apps/api/app/business_schemas.py`

`docs/integration-request-adaptation-2026-08-21/` 下的 ZIP、diff、patch 和验证输出是
当时的实施留档，不代表当前运行时契约，也不得直接作为新集成的导入模板。新适配必须
以本说明和上述源码为准。

## 5. 验收标准

1. iframe 只能向平台生成的 `eventUrl` 回传；
2. 服务端能根据路径恢复并验证正确的集成、渠道、模板和流量来源；
3. 同一设备指纹在租户内关联同一个服务端访客；
4. 原业务载荷以单条事件完整保存，重试不会静默截断数据；
5. 超限请求明确返回 `413`，未声明事件明确返回 `422`；
6. 管理列表不会内联大载荷，单条详情可以读取完整内容。
