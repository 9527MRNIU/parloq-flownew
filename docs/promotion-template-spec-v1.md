# Parloq 推广模板规范 v1

状态：当前版本（`parloq-promotion-template/v1`）

机器可读 schema：[`schemas/parloq-promotion-template-v1.schema.json`](schemas/parloq-promotion-template-v1.schema.json)

本规范用于设计、开发、验收和导入 Parloq 推广落地页。模板只负责界面和交互表达；渠道归因、号码提交、Baileys 配对、状态查询、Pixel、访问统计和生产页交互保护均由平台注入。

## 1. 设计原则

- 模板不得直接调用 Parloq 私有 API，也不得保存号码。
- 模板通过 `parloq-browser-bridge/v1` 完成号码提交和配对。
- 模板必须同时支持真实渠道渲染和无副作用的后台预览。
- 模板 ZIP 必须自包含。字体、图片、CSS、JavaScript 和语言包都随包提供。
- 模板 ZIP 不得自行加入第三方统计、隐藏 iframe、指纹采集或外部脚本；平台可按租户策略统一注入设备识别与匿名关联组件。
- “禁右键/快捷键”只用于降低普通访问者的随手查看成本，不能作为凭据或源码保护手段。

## 2. ZIP 目录

ZIP 可以直接包含文件，也可以有一层构建目录（例如 `dist/`）。解压后的模板根目录必须符合：

```text
index.html                  必须，且只能有一个
manifest.json               建议；缺失时平台按 v1 默认值处理
assets/
  app.js
  app.css
  images/...
  fonts/...
locales/
  en.json
  zh-CN.json
```

路径要求：

- 入口固定为 `index.html`。
- 页面引用资源必须使用相对路径，例如 `assets/app.css`。
- Vite 项目应设置相对资源基址，产物不得依赖部署根路径。
- 不允许 `..`、绝对文件系统路径、符号链接或多个 `index.html`。
- 单个文件不超过 5 MB，ZIP 不超过 20 MB，解压总量不超过 50 MB，文件数不超过 500。
- 不上传 source map；生产构建必须关闭 `sourcemap`。

## 3. manifest.json

推荐完整示例：

```json
{
  "schema": "parloq-promotion-template/v1",
  "version": "1.0.0",
  "entry": "index.html",
  "format": "static-bundle",
  "capabilities": ["phone-pairing"],
  "runtime": "parloq-browser-bridge/v1",
  "interactionProtection": "platform",
  "defaultLocale": "en",
  "supportedLocales": ["en", "zh-CN"],
  "i18n": {
    "mode": "bundled",
    "path": "locales/{locale}.json",
    "fallbackLocale": "en"
  }
}
```

字段约束：

| 字段 | 规则 |
| --- | --- |
| `schema` | 固定为 `parloq-promotion-template/v1` |
| `version` | 模板自己的语义版本，建议使用 `x.y.z` |
| `entry` | 固定为 `index.html` |
| `format` | `static-bundle` 或 `vite-dist` |
| `capabilities` | v1 必须包含且只能包含 `phone-pairing` |
| `runtime` | 固定为 `parloq-browser-bridge/v1`，平台会归一化 |
| `interactionProtection` | 固定为 `platform`，模板不得重复引入防调试库 |
| `defaultLocale` | BCP 47 风格语言码，例如 `en`、`zh-CN` |
| `supportedLocales` | 包含默认语言、去重，最多 128 项 |
| `i18n.path` | 相对路径，可用 `{locale}` 占位符 |

## 4. 平台运行时

平台在 `<head>` 中注入：

```html
<script type="application/json" id="parloq-promotion-config">...</script>
```

配置中可用的稳定字段：

```ts
interface ParloqPromotionConfigV1 {
  previewMode?: boolean
  countryCode?: string
  defaultLocale: string
  supportedLocales: string[]
  resolvedLocale: string
  trafficSource?: 'direct' | 'fission'
  pixelDatasetId?: string | null
}
```

模板必须容忍未知字段，也不得依赖未列入本规范的字段。

平台同时提供：

```ts
window.parloqSubmitPhone(
  phone: string,
  metadata?: Record<string, string | number | boolean | null>
): Promise<Response>
```

成功响应：

```json
{
  "data": {
    "pairing": {
      "pairingCode": "12345678",
      "expiresAt": "2026-08-13T10:00:00Z",
      "statusUrl": "/api/public/promotion/channels/example/pairing/wa_x/status",
      "statusToken": "signed-token"
    }
  }
}
```

模板应使用返回的 `statusUrl` 和 `statusToken` 轮询，直至成功、过期或失败。不得自行拼接账号、渠道或配对 API。

## 5. 标准表单实现

推荐 HTML：

```html
<form id="lead-form" data-parloq-manual novalidate>
  <label for="phone">WhatsApp number</label>
  <input id="phone" name="phone" type="tel" inputmode="tel" autocomplete="tel" required />
  <button type="submit">Continue</button>
  <p id="form-status" role="status" aria-live="polite"></p>
</form>
```

关键要求：

- 使用 `type="tel"` 和 `autocomplete="tel"`。
- 自己处理提交时，表单必须带 `data-parloq-manual`，避免平台自动追踪器重复提交。
- 提交时立即禁用按钮并显示加载态；失败必须显示可理解、可重试的信息。
- 号码至少包含 7 位数字；最终格式校验和租户冲突校验由服务端完成。
- 不得把号码写入 URL、日志、Cookie 或本地存储。
- 不得使用原生 `action` 把表单提交到其他服务。

推荐流程：

```text
输入号码 → 前端基础校验 → 提交中 → 显示配对码
         → 轮询状态 → 已连接 / 已过期 / 失败可重试
```

## 6. 后台预览

后台模板预览使用与生产相同的桥接接口，但平台返回模拟配对码和模拟成功状态：

- 不记录推广事件；
- 不创建账号；
- 不分配 IP；
- 不连接 Baileys；
- 可以完整检查按钮、加载态、配对码页和成功态。

模板不得通过 hostname、URL 路径或 User-Agent 判断预览环境；只读取 `previewMode`。

## 7. 多语言

- 默认使用 `resolvedLocale`，找不到语言包时回退 `defaultLocale`。
- 语言包请求使用相对路径和 `credentials: 'omit'`。
- `ar` 等 RTL 语言必须设置 `document.documentElement.dir = 'rtl'`。
- 页面初始 HTML 必须包含默认语言文案，不能在 JavaScript 执行前完全空白。
- 文案不得以图片承载，按钮和错误信息必须可翻译。

## 8. 前端体验基线

- 移动端优先，至少验收 360×800、390×844、768×1024 和 1440×900。
- 页面应适配安全区域：`env(safe-area-inset-*)`。
- 首屏只保留一个主 CTA，CTA 在号码有效前明确禁用。
- 输入、选择和按钮触控区域不小于 44×44 CSS px。
- 页面必须有加载、禁用、错误、配对中、成功、过期和重试状态。
- 使用信任提示时必须准确，不得虚构加密、人数、身份验证或隐私承诺。
- 动画尊重 `prefers-reduced-motion`。
- 键盘操作、焦点样式、label、`aria-live` 和颜色对比度必须可用。
- 禁止通过 `user-scalable=no` 阻止无障碍缩放。

性能目标：

- 首屏压缩传输目标不超过 1.5 MB。
- JavaScript gzip 目标不超过 250 KB，CSS gzip 目标不超过 80 KB。
- 首屏图片使用 WebP/AVIF，提供尺寸，非首屏图片懒加载。
- 不依赖运行时 CDN 字体；字体放入 `assets/fonts/` 并使用 `font-display: swap`。
- 避免布局抖动，慢网下也必须保留可读的静态首屏。

## 9. 平台模板策略与生产页交互保护

模板管理中的“模板策略”是租户级公共默认值，由平台应用到该租户的所有推广模板；模板代码不得覆盖。渠道特有的国家、设备和流量筛选规则属于渠道策略，优先级高于模板公共策略。

公共策略包含：

- `basic`：禁用桌面右键、F12、查看源码及常见开发者工具快捷键；
- `enhanced`：在基础模式上检测窗口内外尺寸、Eruda/vConsole 和控制台序列化副作用；
- `strict`：在增强模式上检测执行耗时和 `debugger` 停顿；
- 检测动作：仅记录、阻断配对或清空页面；
- 视口缩放：允许无障碍缩放，或锁定为单屏转化布局；
- 设备信号：关闭、标准环境信号或增强环境信号。

平台预览默认使用模拟配对码，不创建账号、不分配 IP、不连接 Baileys。真实链路验收必须从测试渠道进入，并明确标记产生真实账号和资源占用。

平台在后台预览页和真实渠道页统一：

- 禁用鼠标右键菜单；
- 拦截 F12、查看源码和常见开发者工具快捷键；
- 保留手机长按、输入框选择、复制和粘贴能力；
- 使用 CSP 限制脚本、连接、图片和表单目标；
- 不允许模板访问后台 Cookie、存储或管理接口。

模板作者不得自行引入另一套 DevTools 检测。增强/严格检测、阻断或清空页面由平台策略统一实施，避免不同模板重复计时、互相干扰或无法审计。

真正的安全规则是：密钥、协议凭据、渠道鉴权逻辑和租户数据永远不下发到模板。

## 10. 禁止事项

- 模板自行携带的外部 JavaScript、未知第三方 SDK、隐藏 iframe 或跨域数据回传；平台托管并声明的数据关联组件除外；
- source map、明文密钥、访问令牌、固定渠道签名；
- 把号码写入 URL、日志、localStorage、sessionStorage 或 analytics metadata；
- 绕过 `parloqSubmitPhone` 直接调用账号/网关 API；
- 阻断输入框粘贴、系统返回或屏幕阅读器；页面缩放只能由平台策略控制；
- 虚构在线人数、账户安全结果或平台未提供的身份信息；
- 模板自行注入 Meta Pixel；Pixel 由渠道配置和平台运行时统一注入。

## 11. 交付验收清单

- [ ] ZIP 可导入，manifest 通过 v1 校验
- [ ] 所有资源为相对路径且无外部依赖
- [ ] 后台预览能完成模拟提交、配对码和成功状态
- [ ] 真实测试渠道能产生 `page_view`、`phone_submit` 和配对状态
- [ ] 连续点击不会重复提交
- [ ] 错误、超时和过期后可重试
- [ ] 所有语言包完整，RTL 正常
- [ ] 四个规定尺寸无横向滚动、遮挡或不可点击元素
- [ ] 键盘、焦点、label 和 `aria-live` 验收通过
- [ ] 生产构建已压缩且不包含 source map
- [ ] 无外部脚本、隐藏 iframe、密钥或号码持久化
- [ ] 正式渠道右键和常见查看源码快捷键已由平台拦截

## 12. 版本兼容

v1 只承诺 `phone-pairing`。新增能力必须发布新 schema 或向后兼容字段；模板不得自行假设未文档化的接口。平台可在不改变桥接契约的前提下升级统计、风控、协议实现和交互保护。
