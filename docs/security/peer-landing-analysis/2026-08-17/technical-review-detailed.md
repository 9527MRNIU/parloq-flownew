# 同行绑定号码落地页技术手段详细报告（2026-08-17）

> 本文是 [技术对比摘要](./technical-review.md) 的详细版，含逐站分析、
> 代码级证据与双方实现对照。所有结论基于对公开页面的静态抓取与源码阅读，
> 未执行过对方任何脚本。不复制页面素材、文案或代码。
>
> 第八节提到的攻击链已在同日完整取证并解密最终载荷，专文见
> [攻击链详细报告](./attack-chain-report.md)。

## 一、观察对象与取证来源

| 编号 | 地址 | 形态 | 取证产物 |
| --- | --- | --- | --- |
| S1 | `myloveday.falan123.com/?key=tlajvc4&pixelId=2109538159611068` | 92KB 单文件静态页 + 6 段内联脚本 | 整页 HTML、内联脚本 0–5 |
| S2 | `c.ttsmi66.xyz/moks8opd`（LoveSync） | Vite SPA | `index.html`、`/assets/index-B0gQu34r.js`（610KB） |
| S3 | `b.ttsmi66.xyz/moks8opd`（LoveSync 变体） | Vite SPA | `index.html`、`/assets/index-Dxx0DN6b.js`（607KB） |
| S4 | `d.ttsmi66.xyz/moks8opd`（Claim Your Reward） | Vite SPA | `index.html`、`/assets/index-CDXPnihH.js`（455KB） |
| S5 | `a.ttsmi66.xyz/moks8opd`（Myloveday） | Vite SPA | `index.html`、`/assets/index-D4UiGIoI.js`（460KB） |
| C2 | `v1.io92jujjs33.com`（S2/S3/S5 内嵌 0×0 iframe） | 跨域跟踪 + 载荷分发 | `router.js`、`ds_rce_loader.js`（13.5KB） |

五个页面全部位于 Cloudflare 边缘（响应头 `server: cloudflare`）。S2–S5 是
同一套系统：共享同一 SDK 核心（指纹、反调试、埋点、像素、配对状态机），
bundle 之间高度同构，差异只在模板视图与素材；S1 是另一套更老、更简单的
独立实现。

---

## 二、逐站分析

### S1：myloveday.falan123.com（静态“配对码”页）

技术栈：原生 HTML/CSS/JS + Swiper 轮播 + `intl-tel-input` +
`libphonenumber-js`。**无反调试、无设备指纹、无混淆**，全部明文。

- **像素**：`pixelId` 从 URL 参数动态读取，`fbq('init', pixelId)` +
  `PageView`，并追加 1×1 noscript 图
  `https://www.facebook.com/tr?id={pixelId}&ev=PageView&noscript=1`。
  同一页面可被任意渠道用不同 Pixel 复用。同时加载 GA4
  （`G-W502876YFS`），事件同步双发。
- **事件**：`CompleteRegistration`（点继续，`external_id`=uuid，`eventID`
  =uuid 去重）、`SubmitApplication`（复制配对码）、`Subscribe`（首次绑定
  成功且无 referral 时）。GA 侧同名事件携带 `uuid`。
- **设备/归因标识**：`localStorage.uuid`（自生成 UUID，去横线）、
  `localStorage.key`（渠道 key）、`localStorage.referral`（URL 参数持久化）、
  `localStorage.bindWsSign`（绑定成功标记）、`localStorage.phone`。
  读取 `_fbp`/`_fbc` cookie 随请求上报。
- **IP 归属**：`pro.ip-api.com/json/?key=X8nNh9l0HcVYntp`（**key 明文写在
  页面里**），失败回退 `ipapi.co/json/`，结果用于 intl-tel-input 默认国家。
- **号码校验**：客户端 `parsePhoneNumberFromString` 校验有效性；
  国家列表内注入自定义搜索框（`iti__search-field`）。
- **配对契约**：
  - `POST /webws/api/pair-code`，body：`{key, uuid, code:"77773333",
    countryISO, phoneNumber, countryCode, referral, sourceExtend:{ip, fbc,
    fbp, url}}`；
  - `GET /webws/api/result?key=&uuid=&phone=&fbp=&fbc=` 轮询绑定结果，
    倒计时 10s、最多 6 次重试，成功后跳 `share/index.html`。
- **多语言**：19 种语言全量内联在 JS 对象里，按 `navigator.languages`
  自动选择，`window.onload` 切换文案。

### S2–S5：ttsmi66.xyz 模板平台

技术栈：Vue 3 + Vite（`VITE_API_BASE`）+ rolldown 打包，字符串数组
混淆（每段函数带 `_0x…` 位移解码器 + 自校验指令），无 sourcemap。

**共享 SDK 核心能力**（四个 bundle 全部包含）：

| 模块 | 实现 | 证据 |
| --- | --- | --- |
| 指纹 | thumbmarkjs 指纹 SDK（bundle 内仍保留 `api.thumbmarkjs.com` 常量与 `stabilize:['private','iframe']` 配置，应为自建分支） | 组件对象 `$={audio,canvas,fonts,hardware,locales,math,screen,system,timezone,…}` |
| 反调试 | devtools-detector 库（7 类检测器 + 快捷键/右键/复制粘贴拦截） | 检测器枚举 `RegToString/DefineId/Size/DateToString/FuncToString/Debugger/Performance/DebugLib` |
| 埋点 | `useProgress`/`useLeadEvent`/`useVisitTimer`/`useLogin` 组合式函数 | `_prog_`、`_lp_lead_reported`、`DWELL_MS=5e3` |
| 像素 | `pixelSdk`（Meta/TikTok/Kwai/mgskyads 四平台） | `pixelSdk.init(platform,config)`、`trackInitiateCheckout/trackCompleteRegistration` |
| 翻译 | translate.js（zvo.cn）自动翻译 + 全量国家→语言映射 | `COUNTRY_LANG_MAP={AD:'catalan',…}`、`autoDetectLanguage()` |
| 签名 | 全请求 `X-Sign-LP`/`X-Sign-Time` md5 签名 | `_bsh()` 与 XOR 混淆的 `SECRET` |

**API 契约**（同源 `/api/lp/*`）：

```
GET  /api/lp/init?c={channel}&fp={fingerprint}&y=1&source={}&from_facebook=1&is_mobile=1
GET  /api/lp/countries                      （localStorage 缓存 + TTL）
POST /api/lp/progress                       {channel_code, fingerprint, step, data}
POST /api/lp/lead-event                     {channel_code, fingerprint, is_fission, fbp, fbc, event_source_url}
POST /api/lp/visit-end（sendBeacon）        {duration_sec, fingerprint, from_facebook, is_mobile, channel_code, sign_time, sign_lp}
POST /api/lp/wa-accounts/entry              {channel_code, phone, is_fission, fingerprint, pairing_code?, fbp, fbc, event_source_url, client_ip_address}
GET  /api/lp/wa-accounts/phone-info?phone=
GET  /api/lp/wa-accounts/status?phone=&channel_code=&request_id=
POST /api/lp/fb-domain-blocked/report       {domain}
```

四个模板差异：

- **S2/S3（LoveSync）**：假资料约会模板，素材走专用图床 CDN
  `sec-cdn.kiytogz.com`（按 `地区/性别/姓名/序号.jpg` 分层组织，bundle
  内出现 674–715 次），带 confetti 成功动效，`randomuser.me` 占位头像。
- **S4（Claim Your Reward）**：奖励领取模板，`DWELL_MS` 驻留 lead 逻辑
  在 bundle 中明确出现，文案为“Verify your WhatsApp to claim your
  exclusive reward”。
- **S5（Myloveday）**：og/twitter 分享卡齐全；注释明确
  “Pixel SDK 由 `useLanding.init()` 按 `promotion_platform` 通过
  `pixelSdk.init()` 动态注入”。其“平台注入像素 + runtime 桥 + 平台级
  防护”的架构与我们 spec v2 的思路同构——该方向已被同行产品化。

---

## 三、反调试手段详解

### devtools-detector（S2–S5）

bundle 内嵌完整库，检测器全部实例化并周期轮询（`setInterval` 遍历
detectors，每轮 `detect(Xe++)`）：

1. **RegToString**：篡改 `RegExp.prototype.toString`，若被复原则认为
   有调试（经典 DevTools 反检测）。
2. **DefineId**：用 `Object.defineProperty` 挂“id”属性 + getter 计数。
3. **Size**：字体渲染尺寸差异探测（`document.createElement('a')`
   尺寸变化判定 DevTools 面板占用）。
4. **DateToString**：篡改 `Date.prototype.toString`，复原即触发。
5. **FuncToString**：`console.log` 钩子计数——`this.func.toString` 返回
   空串时计数，`2<=this.count` 判定打开。
6. **Debugger**：`debugger` 语句 + `performance.now()` 时延，仅
   `iosChrome||iosEdge` 启用（`100 < 耗时差` 判定）。
7. **Performance**：`console.log` 大对象打印耗时，`> 10*maxPrintTime`
   两次判定打开。
8. **DebugLib**：`window.eruda?._devTools?._isShow ||
   window._vcOrigConsole && #__vconsole.vc-toggle` —— 移动端调试库检测。

触发后：`console.warn("You don't have permission to use
DEVTOOL!【type=…】")`、按配置清 console、触发 `ondevtoolopen(type)`
回调（页面据此清空内容）。

**输入拦截**：`keydown` 捕获 F12（keyCode 123）、Ctrl/⌘+Shift+I/J/C、
Ctrl/⌘+U/S（macOS 判定为 `metaKey+altKey`）；`contextmenu`（非 touch）、
`selectstart`/`copy`/`cut`/`paste`（对 input/textarea/contenteditable
例外），均走 `preventDefault`。

**环境与 bot 检测**：`ke` 对象含 iframe/pc/qqBrowser/firefox/macos/edge/
oldEdge/ie/iosChrome/iosEdge/chrome/mobile 判定，以及 SEO bot 正则：
`/bot|applebot|petalbot|yandexbot|bytespider|chrome\-lighthouse|
moto g power/i`（对 UA 命中 bot 者不注入检测逻辑）。

### S1

无任何反调试。仅 `error-shake` 等 UI 反馈。

### 我们的 guard.js（对照）

`apps/api/app/routers/promotion.py` 的 `LANDING_GUARD_JS`：

- 号码输入统一去 `+`（显示政策）。
- `contextmenu` 拦截（非 touch）、F12 / Ctrl+⌘+Shift+I/J/C / Ctrl+⌘+U/S
  拦截。
- 检测项（`protectionMode` 为 strict/basic，间隔 900/1600ms）：
  - **window-gap**：`|outerWidth-innerWidth| > 180`（DevTools 停靠）；
  - **mobile-console**：`window.eruda || window.vConsole ||
    .eruda-container/#__vconsole`；
  - **console-probe**：`new Image()` 后 `Object.defineProperty(id, get)`
    ——console 若求值该对象则 getter 触发；
  - **debugger-delay**（仅 strict）：`debugger;` 后
    `performance.now() 差值 > 220ms`。
- 检测后按 `devtoolsAction` 执行 `log`/`block`/`blank`，事件
  `promotion:inspection-detected` 上报服务端；`block` 时
  `window.__promotionInspectionBlocked=true`，桥接的 `submitPhone`
  直接拒绝。

结论：双方反调试覆盖度相当（我们 4 类 vs 对方 7 类，手段不同），
我们额外把“检测”纳入可配置策略并上报服务端，对方把检测器做成通用库
并含 bot 白名单。

---

## 四、设备识别与指纹详解

### S2–S5：thumbmarkjs 指纹 SDK

配置块（bundle 内）：

```
o = { exclude:[], include:[], stabilize:['private','iframe'], logging:true,
      timeout:5e3, cache_api_call:true, cache_lifetime_in_ms:0,
      performance:false, experimental:false,
      property_name_factory: i => 'thumbmark_' + i }
```

分段排除规则：`private`（firefox/safari≥17/brave 去 canvas 等）、
`iframe`（safari 去 applePayVersion/cookieEnabled；全局去 permissions）、
`vpn`（去 ip）、`always`（brave/firefox 去 speech）。

组件明细（还原自 bundle）：

| 组件 | 采集内容 |
| --- | --- |
| `audio` | OfflineAudioContext(1 声道, 5000 样本, 44100Hz) 振荡器 1000Hz + 动态压缩器 → `sampleHash`、`maxChannelCount`、`channelCountMode` |
| `canvas` | 3 个 canvas：彩虹渐变 + 文本 `Random Text WMwmil10Oo`（23.123px Arial）+ 白色折线，`getImageData` 后 20×20 众数网格 → `commonPixelsHash` |
| `fonts` | 隐藏 iframe 内 canvas 基线字体集 + 增量探测字体 |
| `hardware` | `videocard`（WebGL 渲染器）、`architecture`、`deviceMemory`、`jsHeapSizeLimit` |
| `locales` | `navigator.language`、`Intl.DateTimeFormat().resolvedOptions().timeZone` |
| `math` | `acos(0.5)`、`asin/cos` 区间采样（浮点实现差异）、大数 `cos` |
| `system` | `applePayVersion`、`cookieEnabled`、`hardwareConcurrency` 等 |
| `timezone/screen` | 时区、屏幕尺寸/色深/触点数 |
| `speech/plugins/permissions` | 语音合成枚举、插件列表、权限查询 |
| `tls/header` | TLS 扩展、`Accept-Language`（`q` 值） |

产出指纹串后：

- `GET /api/lp/init?c=&fp=&y=&source=&from_facebook=&is_mobile=` 注册访问；
- `progress`/`wa-accounts/entry`/`lead-event`/`visit-end` 全部回传
  `fingerprint`——指纹是**全链路主键级标识**，localStorage 仅做辅助。

### C2 iframe：`router.js`

```
FINGERPRINT = 64 位哈希（UA + navigator.language + screen.width×height，
               JS 内联生成，先于后续脚本）
iOS 版本解析（3 种正则兼容 Version/、iOS/、iPhone OS x_y_z）
ver >= 180400 时加载 ds_rce_loader.js（带时间戳防缓存）
```

### S1

无指纹。设备标识仅 `localStorage.uuid`（清除存储即换人）+ `_fbp`/`_fbc`
+ IP。

### 我们（对照）

`TRACKER_JS`（`apps/api/app/routers/promotion.py`）的 `signals()`：

- `deviceSignals=off`：不采集。
- `basic`：`language`、`timeZone`、`viewport [innerWidth,innerHeight]`、
  `screen [screen.width,screen.height]`、`pixelRatio`、`touchPoints`。
- `enhanced`：加 `platform`、`hardwareConcurrency`、`deviceMemory`、
  `colorDepth`、`userAgent`。
- 信号随 `page_view` 事件的 `metadata.deviceSignals` 上报；访客标识是
  `localStorage.promotion_visitor_id`（UUID）。

**差距**：我们没有 canvas/音频/字体/语音/WebGL 指纹，没有跨会话的复合
设备 ID。对方指纹串贯穿每个请求，抗“清缓存换号”的能力明显更强。

---

## 五、请求防篡改

### 同行签名（S2–S5）

```
sign_lp = md5( SECRET[0:10]
             + md5(按 key 字典序排序的 "k=v&k=v"（值 URL 编码）)
             + String(floor(now/1000))
             + reverse(SECRET[-22:]) )
headers: X-Sign-LP: sign_lp, X-Sign-Time: 秒级时间戳
```

`SECRET` 是 XOR 字节数组（`__skd` 与 `__sks=29631` 逐字节异或还原）。
签名防“直接 curl 脚本刷接口”，但密钥在客户端、可静态还原——**增加
门槛而非鉴权**。S1 无签名。

### 我们（对照）

- 落地页会话：`sessionToken` = base64(payload) + HMAC-SHA256（服务端
  `app_secret_key`），30 分钟有效，绑定 channel 与 trafficSource；
  每个事件、配对开始都服务端验签 + 校验 `occurredAt` 时间窗。
- 配对状态：`Authorization: Bearer <token>`，token 绑定
  channel/account/attempt/visitor，服务端 HMAC 验证。
- 配对限流：`visitorCheck`（每渠道每访客）+ `ipStart`（每渠道每 IP），
  见 `services/pairing_rate_limits.py`，超额返回白标错误
  `rate_limited` + `Retry-After`。

结论：我们走“服务端可验的令牌 + 幂等 + 限流”，对方走“客户端 md5
签名”。后者更隐蔽（参数不可直接改），前者安全性更高。两者并不冲突。

---

## 六、漏斗埋点与行为统计

### 同行

- **init**：渠道码、指纹、裂变标记、来源、是否 Facebook 内打开、是否
  移动端，一并落库。
- **progress**：`useProgress` 在 localStorage 存
  `_prog_{channel}_{fp}`（断电恢复），每次步骤变化 POST
  `/api/lp/progress`（step + data 结构化数据）。
- **lead-event**：`useLeadEvent` 用 `DWELL_MS=5e3` 定时器——页面驻留
  5 秒即报 lead；`sessionStorage['_lp_lead_reported_{channel}_{fp}']`
  去重；响应 `code===0` 才算成功。
- **visit-end**：`pagehide`/`visibilitychange→hidden` 时
  `navigator.sendBeacon` 发 `duration_sec`、指纹、`from_facebook`、
  `is_mobile`，并附签名头。
- **wa-accounts/status**：带 `request_id` 轮询配对结果，`expires_sec`
  前端倒计时。
- **fb-domain-blocked/report**：像素加载失败 → 上报被封域名，页内提示
  “可能原因：域名被 Meta 黑名单 / Pixel 被停用 / 广告账号受限”。

### S1

埋点=FB/GA 事件；绑定结果靠 `/webws/api/result` 轮询（10s 倒计时，
最多 6 次）。

### 我们

- 事件端点 `/api/public/promotion/channels/{slug}/events`：事件类型
  `page_view`、`phone_submit`、`visit_end`、`inspection_detected`
  （+`pairing_check` 内部事件）；幂等键去重；`phone_submit` 自动 upsert
  lead；`visit_end` 用 `sendBeacon` 带 `durationMs`。
- `page_view` 与 `phone_submit` 事件**服务端返回 `metaEvent`
  （名称+eventID）**，前端据其对 Browser Pixel 去重（避免 CAPI 与
  Browser 双计）。
- 缺：步骤级 progress 落库、5 秒驻留 lead、FB 域名封禁上报。
- 有：`inspection_detected` 上报（对方无）、服务端 `pairing_check`
  审计事件（对方无）。

---

## 七、广告像素与归因

### 同行 pixelSdk（S5 注释最明确，四站同核心）

`pixelSdk.init(platform, config)` 按 `promotion_platform` 分发：

| 平台 | SDK | 注入 |
| --- | --- | --- |
| facebook | `fbq` | `connect.facebook.net/en_US/fbevents.js` |
| tiktok | `ttq` | `analytics.tiktok.com/i18n/pixel/events.js` |
| kwai | KwaiAnalyticsObject | `s1.kwai.net/…/pixel/events.js?sdkid=` |
| mgskyads | 第四方 tag | `s.mgskyads.com/js/tag.js?aa=` |

- 事件：`PageView`、`InitiateCheckout`、`CompleteRegistration`
  （`{value:1,currency}`，仅 kwai 分支带币种）、`EVENT_PURCHASE` 等。
- 归因：解析 `fbclid`/`ttclid`，收集 cookie `_fbc`/`_fbp`/`_ttp`；
  `getFbc()` 按平台取对应 cookie。
- 配置来自 `/api/lp/init` 返回（`promotion_platform`、`config_meta`、
  `open_in_app`），`fbGuardReady` 控制像素就绪时机；
  `__pixelSdkDebug` 支持模拟事件测试。

### S1

FB Pixel 动态 ID（URL 参数）+ GA4 双发；`fbq('track', name, {},
{eventID})` 去重。

### 我们

- Meta Browser Pixel：`tracker.js` 按渠道配置注入 `fbq` + `init`；
  事件映射可配（默认 `page_view→PageView`、`phone_submit→Lead`、
  `pairing_started→InitiateCheckout`、`pairing_verified→
  CompleteRegistration`）。
- Meta CAPI：`services/meta_conversions.py` 把事件入队
  `MetaConversionDelivery`（skip-locked 抢占、重试、mock 开关），
  `user_data` 含 `client_ip_address`、`client_user_agent`、`fbp`/`fbc`
  （服务端读 cookie，正则校验）、`ph`（号码 SHA-256）、`external_id`
  （visitor SHA-256）；Browser 与 CAPI 共用同一 `event_id`。
- **缺**：TikTok/Kwai 像素、`fbclid`/`ttclid`/`_ttp` 前端捕获、
  FB 域名封禁自检。CSP 目前只放行 `connect.facebook.net`，扩平台需同步
  改 `_sandbox_csp`。

---

## 八、隐藏 iframe 与恶意载荷（重点风险）

`v1.io92jujjs33.com` 是一个 C2 域，页面以 0×0 iframe 嵌入（`left:
-1000px`，肉眼不可见）。`router.js` 之后按 iOS 版本分流到
`ds_rce_loader.js`（**仅 iOS ≥ 18.4** 加载）。

`ds_rce_loader.js` 结构还原：

- 常量 `CHANNEL_CODE = "697098348a461b7656bdc02e5f52fca9"`；
  `C2_DOMAIN = 当前域名`；`DOOR_DOMAIN = door 参数 > referrer > 自身`。
- 同步 XHR 打 `POST /api/v1/ip-sync`，body：
  `{fingerprint: FINGERPRINT, channelCode, deviceVersion, source,
  domain}`，返回 `deviceId` 存入 `window._dsDeviceId`。
- `getDeviceVersion()` 取设备版本；`getSource()` 取渠道来源；
  日志经 `GET /log.html` 同步回传（`SERVER_LOG` 开关）。
- `prepare_dlopen_workers()` 准备 Worker 链路；
  `worker.postMessage({type:'stage1', begin, origin, ios_version,
  offsets, slide, chipset, device_model, desiredHost, …})`——把内核
  slide、偏移、芯片组、机型发给 stage1 Worker。
- 状态机文案：`worker_finished` / `worker_error` / `worker_redirect` /
  `check_attempt_failed` / `timeout`；`retryOnce` 只重试 iframe 自身，
  不重载父页；另有 `/api/v1/debug` 端点。

`dlopen` + `offsets` + `slide` + `chipset` + `device_model` 组合是
**iOS 内核/原生代码注入（RCE）链路的 stage-1 编排器**特征。这已经超出
“反调试、设备识别、防分析”范畴，属于对访问者设备的攻击载荷分发。
这类页面通常把“绑定号码”当诱饵，后端按指纹/环境决定是否投放载荷。

我们系统**完全没有、也不应有**此类能力；报告保留此项仅作风险记录与
红线圈定。

---

## 九、多语言

- **S2–S5**：translate.js（zvo.cn）客户端自动翻译：页面先按
  `navigator.language` 初判，再由 `/api/lp/countries` + 内嵌
  `COUNTRY_LANG_MAP`（国家码→语言名，覆盖全球）决定目标语言，动态
  改写 DOM。优点：一套源码覆盖所有语言；缺点：第三方脚本依赖、翻译
  质量不可控、SEO/无障碍受损。
- **S1**：19 语言内联对象，按浏览器语言切换。
- **我们**：服务端按国家→语言映射（`COUNTRY_DEFAULT_LOCALE`）解析
  locale，模板自带 `locales/{locale}.json`（bundled/runtime 两种模式），
  服务端在渲染时做文案注入（`_localize_template_html`），支持 RTL
  语言族（ar/fa/he/ps/ur）；白标组件库 15 语言。可审计、无第三方依赖。

---

## 十、工程形态对照

| 项 | 同行 | 我们 |
| --- | --- | --- |
| 边缘 | Cloudflare | 生产同样走 Cloudflare-only 入口 |
| 打包 | Vite/rolldown，字符串数组混淆，无 sourcemap | 模板 ZIP 自包含；平台脚本 esbuild minify；无 sourcemap |
| 模板边界 | 模板包内自带追踪/指纹/像素（大而全） | 模板只管展示，`tracker/guard/elements` 平台统一注入 |
| CSP | 未发现强 CSP（可加载任意第三方） | 生产 `sandbox` + 白名单（仅 FB 域），模板无法外联 |
| 素材 | 专用图床 CDN 分层目录 | 模板 ZIP 资产 + 平台 assets 端点 |
| 视口 | 模板写死 `user-scalable=no` | 平台策略 `lockViewportZoom` 可配 |
| 动效 | confetti 成功动效 | 白标组件状态 UI |
| 预览 | 未知 | 签名资源 + 模拟配对全状态演练 |

---

## 十一、差异总表（详细版）

| 能力域 | 同行（S2–S5 / S1） | 我们 | 差距 |
| --- | --- | --- | --- |
| 反调试 | devtools-detector 7 类 + 输入拦截 + bot 白名单 / S1 无 | guard.js 4 类 + 输入拦截 + 可配置动作 + 检测上报 | 基本持平；可补 2–3 类检测 |
| 复合指纹 | thumbmarkjs（canvas/audio/fonts/speech/WebGL/系统），全链路主键 | 静态属性信号（basic/enhanced） | **核心差距** |
| 访客标识 | 指纹为主 + deviceId（ip-sync 换发） | localStorage UUID | 抗清除能力弱 |
| 跨域同步 | C2 iframe + 20s ip-sync | 无（架构禁模板 iframe） | 保持现状 |
| 请求防篡改 | 客户端 md5 签名（可还原） | HMAC 会话令牌 + 幂等 + 限流 | 我们更强 |
| 漏斗埋点 | init/progress/lead(5s)/visit-end/status 全链路 | page_view/phone_submit/visit_end/inspection_detected | 缺 progress 与驻留 lead |
| 像素 | Meta+TikTok+Kwai+mgskyads；fbclid/ttclid/_ttp | Meta Browser+CAPI（eventID 双端去重） | 缺多平台与前端归因捕获 |
| 域名健康 | FB 封禁自检上报 | 无 | 缺 |
| 多语言 | 客户端自动翻译 / 19 语言内联 | 服务端 locale + 打包语言包 + RTL | 我们更可控 |
| 恶意载荷 | iOS≥18.4 RCE 分发器 | 无 | 红线，永不跟进 |
| 会话连续性 | progress/lead 均持久化 + 恢复 | 幂等事件 + 配对状态 token | 可补进度恢复 |

---

## 十二、建议落点（供实现参考）

1. **复合指纹（P1）**：新增 `deviceSignals="fingerprint"` 档，平台注入
   canvas 20×20 像素哈希 + OfflineAudioContext + 字体枚举 + WebGL
   renderer；服务端 SHA-256 后作为 `visitorFingerprint` 存事件与
   pairing 表，随 `sessionToken` 绑定校验。落点：
   `apps/api/app/routers/promotion.py`（TRACKER_JS + report_event +
   start_public_pairing）、`services/pairing_rate_limits.py`（把指纹
   并入 visitorCheck 维度）。
2. **多平台像素（P1）**：channel 增加 platform 配置，tracker.js 按配置
   注入 ttq/kwai；`_sandbox_csp` 按启用平台放行域；前端捕获
   `fbclid`/`ttclid`/`_ttp` 随事件上报；CAPI 侧保持 Meta 现状。
3. **域名健康（P1）**：`fbq` 加载失败（或 init 后 X 秒无 PageView 回执）
   时复用事件通道上报 `fb_pixel_unavailable`，控制台聚合展示。
4. **漏斗增强（P2）**：事件模型增加 `step`/`durationMs` 字段或新增
   `progress` 事件类型；前端 `useLeadEvent` 式 5 秒驻留 lead 可做成
   可选策略，默认关。
5. **红线（不跟进）**：RCE/内核载荷、跨域隐藏 iframe、客户端自动翻译
   SDK、客户端 md5 签名。我们的服务端令牌、CSP 沙箱、平台注入边界是
   更稳的设计，保持现状。

## 附录 A：同行 API 参数速查

```
init        c, fp, y, source, from_facebook, is_mobile
progress    channel_code, fingerprint, step, data
lead-event  channel_code, fingerprint, is_fission, fbp, fbc, event_source_url
visit-end   duration_sec, fingerprint, from_facebook, is_mobile,
            channel_code, sign_time, sign_lp（sendBeacon）
entry       channel_code, phone, is_fission, fingerprint, pairing_code?,
            fbp, fbc, event_source_url, client_ip_address
status      phone, channel_code, request_id?
ip-sync     fingerprint, channelCode, deviceVersion, source, domain
            → {data:{deviceId}}
```

## 附录 B：我方公开端点速查

```
GET  /api/public/promotion/channels/{slug}           渠道配置 + sessionToken
GET  /api/public/promotion/channels/{slug}/render    渲染页（注入 runtime）
GET  /api/public/promotion/channels/{slug}/fission/render
POST /api/public/promotion/channels/{slug}/events    事件（幂等）
POST /api/public/promotion/channels/{slug}/pairing/start
GET  /api/public/promotion/channels/{slug}/pairing/status
POST /api/public/promotion/channels/{slug}/pairing/cancel
GET  /api/public/promotion/{tracker.js,guard.js,account-link-elements.js}
```

## 附录 C：主要代码位置

- 同行：`a/index-D4UiGIoI.js`、`b/index-Dxx0DN6b.js`、
  `c/index-B0gQu34r.js`、`d/index-CDXPnihH.js`、
  `v1.io92jujjs33.com/{router.js,ds_rce_loader.js}`。
- 我方：`apps/api/app/routers/promotion.py`（TRACKER_JS、LANDING_GUARD_JS、
  `_session_token`、`_render_html`、`report_event`、`start_public_pairing`）、
  `apps/api/app/services/meta_conversions.py`、
  `apps/api/app/services/pairing_rate_limits.py`、
  `apps/api/app/routers/promotion_policy.py`、
  `apps/web/src/public-runtime/account-link-elements.ts`、
  `apps/api/app/template_kits/account_link_v1/`、
  `docs/promotion-template-spec-v2.md`。
