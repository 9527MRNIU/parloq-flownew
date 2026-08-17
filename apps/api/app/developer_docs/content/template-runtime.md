## 受支持的调用入口

v2 模板只通过平台注入的 `window.PromotionBridge` 调用账号接入能力：

```ts
interface PromotionBridgeV2 {
  version: "promotion-browser-bridge/v2"
  submitPhone(
    phone: string,
    metadata?: Record<string, string | number | boolean | null>
  ): Promise<Response>
  getPairingStatus(pairing: PairingHandle): Promise<Response>
  cancelPairing(pairing: PairingHandle): Promise<Response>
}
```

运行时配置位于 ID 为 `promotion-runtime-config` 的元素中。模板不应依赖其中未写入契约的内部字段。

## 开始配对

```js
const response = await window.PromotionBridge.submitPhone(phone, {
  placement: "hero-form"
});
const result = await response.json();
const pairing = result.data.pairing;
```

`pairing` 包含 `pairingCode`、`attemptId`、`pairingStatus`、`expiresAt` 以及查询 / 取消所需的不透明句柄字段。模板必须保存整个对象并原样传回桥接方法。

开始请求可能返回 `account_already_linked`、`number_unavailable`、`pairing_in_progress` 或 `rate_limited`。页面可以显示对应的中性提示，但不能借错误类别推断租户或账号详情。

## 查询状态

```js
const response = await window.PromotionBridge.getPairingStatus(pairing);
const { data } = await response.json();
```

| `pairingStatus` | 页面行为 |
| --- | --- |
| `code_issued` | 展示配对码并开始轮询 |
| `waiting_phone` | 继续等待手机确认 |
| `reconnecting` | 展示恢复中状态，按 `nextPollAfterMs` 继续轮询 |
| `verified` | 只有同时满足 `verified === true` 才进入成功流程 |
| `failed` | 停止轮询，展示失败与重新开始入口 |
| `expired` | 停止轮询，提示配对码过期 |
| `cancelled` | 停止轮询，返回可重新开始状态 |

`accountState` 只用于诊断，不能用作配对成功判断。配对成功后，`initializationStatus` 还可能是 `pending`、`syncing`、`ready`、`failed` 或 `unsupported`；资料初始化失败不会把已经验证的配对改成失败。

## 取消配对

```js
await window.PromotionBridge.cancelPairing(pairing);
```

取消后停止当前轮询并回到可重新输入号码的状态。模板不能自行拼接状态 URL、把状态令牌放进 URL，或构造 `Authorization` 请求头；这些都由桥接运行时处理。

## 轮询建议

优先使用响应中的 `nextPollAfterMs`，否则使用约 2 秒间隔。页面隐藏或进入终态后停止轮询，避免多个定时器同时查询同一次尝试。

