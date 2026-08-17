# 同行绑定号码落地页技术手段对比报告

观察时间：2026-08-17。只总结技术手段与能力差异，不复制页面素材、文案或代码。

## 一、观察对象

| 编号 | 地址 | 形态 | 性质 |
| --- | --- | --- | --- |
| S1 | `myloveday.falan123.com/?key=tlajvc4&pixelId=2109538159611068` | 92KB 单文件静态页 | 老一代“配对码”绑定页 |
| S2 | `c.ttsmi66.xyz/moks8opd`（LoveSync） | Vite SPA | 同一厂商的模板平台 |
| S3 | `b.ttsmi66.xyz/moks8opd`（LoveSync 变体） | Vite SPA | 同 S2 核心，换素材包 |
| S4 | `d.ttsmi66.xyz/moks8opd`（Claim Your Reward） | Vite SPA | 同核心，奖励模板 |
| S5 | `a.ttsmi66.xyz/moks8opd`（Myloveday） | Vite SPA | 同核心，另带多平台像素 SDK |
| — | `v1.io92jujjs33.com`（S2/S3/S5 内嵌 0×0 iframe） | 跨域跟踪/载荷分发 | 独立 C2 域 |

S2–S5 是同一套系统：共享 450–610KB 混淆 bundle、同一组 `/api/lp/*` 后端、
同一套指纹与反调试 SDK；S1 是另一套更简单的独立实现。五个页面全部走
Cloudflare。

## 二、同行能力清单

### 1. 反调试（S2–S5 内置 `devtools-detector` 库）

- 七类检测器：`RegToString`（正则 toString 篡改）、`DefineId`、
  `Size`（字体尺寸探测）、`DateToString`、`FuncToString`（console.log
  钩子计数）、`Debugger`（debugger 语句时延，仅 iOS Chrome/Edge 启用）、
  `Performance`（打印耗时）、`DebugLib`（console 特征检测）。
- 另拦截右键、F12、查看源码与常见 DevTools 快捷键；检测后清理页面。
- S1 无反调试、无混淆，纯明文。

### 2. 设备识别与指纹（S2–S5）

- 结构化指纹 SDK，组件含：canvas（`getImageData` 20×20 网格
  `commonPixelsHash`）、`OfflineAudioContext` 音频指纹、字体枚举、
  `speechSynthesis` 语音枚举、插件列表、Brave 浏览器检测、权限查询、
  存储特征（localStorage/sessionStorage/indexedDB）、硬件属性
  （`hardwareConcurrency`/`deviceMemory`/`maxTouchPoints`）、屏幕与时区。
- 合成指纹串作为 `fp` 参数贯穿全链路：`/api/lp/init`、`progress`、
  `wa-accounts/entry`、`visit-end`、`lead-event` 全部携带。
- 隐藏 iframe 内先行注入 64 位指纹（UA+语言+屏幕尺寸的哈希），并每 20 秒
  向 `/api/v1/ip-sync` 做跨域 IP/渠道/门页域名同步。
- S1 只有 `localStorage uuid` + `_fbp`/`_fbc` cookie + IP 归属地
  （`pro.ip-api.com`，key 明文写在页面里）。

### 3. 请求防篡改（S2–S5）

- 每个上报请求带 `X-Sign-LP`/`X-Sign-Time` 头：
  `md5(SECRET前10位 + md5(字典序参数串) + 秒级时间戳 + SECRET后22位反转)`。
- SECRET 用 XOR 字节数组藏在 JS 里，可静态还原——这是“提高脚本门槛”，
  不是服务端鉴权。S1 无签名。

### 4. 漏斗埋点与行为统计（S2–S5）

- `/api/lp/init`：渠道码、指纹、来源、是否来自 Facebook、是否移动端。
- `/api/lp/progress`：漏斗步骤落库（channel + fingerprint + step + data）。
- `/api/lp/lead-event`：驻留 5 秒触发 lead（localStorage 去重）。
- `/api/lp/visit-end`：`sendBeacon` 上报驻留时长、指纹、来源。
- `/api/lp/wa-accounts/entry|phone-info|status`：配对码发放、号码信息、
  状态轮询（带 `request_id`）。
- `/api/lp/fb-domain-blocked/report`：像素加载失败自检并上报域名封禁。
- `visibilitychange`/`pagehide` 驱动时长与离开统计。

### 5. 广告像素与归因（S5 最全，S2–S4 同核心）

- 多平台像素 SDK（`pixelSdk.init(platform)` 按 `promotion_platform`
  动态注入）：Meta `fbq`、TikTok `ttq`、Kwai（`s1.kwai.net`）、
  `s.mgskyads.com` 第四方。
- 事件含 PageView、CompleteRegistration、InitiateCheckout、Purchase（带
  币种）；前端解析 `fbclid`/`ttclid`，收集 `_fbc`/`_fbp`/`_ttp`。
- S1：`pixelId` 走 URL 参数动态初始化（同一页面给不同渠道用不同 Pixel），
  GA4 同步发事件，`fbq` 带 `eventID` 去重。

### 6. 环境分发与隐藏 iframe（S2/S3/S5）

- iframe 按 iOS 版本分流：UA 解析出 iOS 版本，**iOS ≥ 18.4 时加载
  `ds_rce_loader.js`**，内含 `offsets`/`slide`/`chipset`/`device_model`
  等内核级变量、同步 XHR 取后续载荷、`/api/v1/debug` 日志回传。这是设备
  攻击载荷分发器（名称直译为设备侧 RCE 加载器），超出“反调试/设备识别”
  范畴，属恶意载荷。
- 门页域名从 `door` 参数 > referrer > 自身域名取，用于渠道归因。

### 7. 多语言

- S2–S5：translate.js（zvo.cn）客户端自动翻译 + `/api/lp/countries`
  国家列表（localStorage 缓存 + TTL）。
- S1：19 种语言内联 i18n，按 `navigator.languages` 切换。

### 8. 工程形态

- 全部 Cloudflare 边缘；S2–S5 bundle 混淆（字符串数组替换）、无
  sourcemap；素材走专用图床 CDN（`sec-cdn.kiytogz.com`，按地区/性别/
  人名分层组织）；成功态带 confetti 动效；视口锁定禁缩放。

## 三、我们系统模板能力（现状）

- **架构**：模板 ZIP 只管展示与本地化；`tracker.js`/`guard.js`/
  `account-link-elements.js` 由平台统一注入；生产 CSP 沙箱只放行
  `connect.facebook.net`，模板无法外联脚本或数据接收方。
- **会话与鉴权**：HMAC `sessionToken`（30 分钟）+ 配对状态 Bearer 令牌 +
  速率限制 + 幂等键去重——服务端可验，强于同行的客户端 md5 签名。
- **反调试（guard.js）**：右键/F12/快捷键拦截、窗口尺寸差检测、eruda/
  vConsole 检测、console 探针（Image.id getter）、strict 模式
  `debugger` 时延检测；动作可配 log/block/blank，检测事件上报服务端。
- **设备信号**：`deviceSignals` 策略（off/basic/enhanced）。enhanced 含
  语言、时区、视口、屏幕、pixelRatio、触点数、platform、
  hardwareConcurrency、deviceMemory、colorDepth、UA。**无 canvas/音频/
  字体/语音指纹，无复合设备指纹**。
- **埋点**：`page_view`/`phone_submit`/`visit_end`（含 `durationMs`）/
  `inspection_detected`，事件幂等、visitor_id（localStorage UUID）、
  lead 按号码归并。
- **Meta 归因**：Browser Pixel + CAPI 双发，同一 eventID 去重，事件映射
  可配置（page_view→PageView、phone_submit→Lead、pairing_started→
  InitiateCheckout、pairing_verified→CompleteRegistration），服务端读取
  `_fbp`/`_fbc`。**仅 Meta，无 TikTok/Kwai**。
- **其他**：服务端国家→语言解析、RTL、白标组件库（libphonenumber 校验、
  国家自动识别、完整配对状态机）、FB/IG 内嵌浏览器检测引导外部打开、
  预览模式签名资源 + 模拟配对、视口锁定策略可配。

## 四、差异对照

| 能力 | 同行（S2–S5） | 我们 | 差距评估 |
| --- | --- | --- | --- |
| 反调试 | devtools-detector 7 类 + 快捷键/右键 | 4 类（窗口差/移动控制台/console 探针/debugger 时延）+ 快捷键/右键 | 基本持平，手段不同 |
| 设备指纹 | canvas/音频/字体/语音/插件/存储/硬件，全链路携带 | 仅静态属性信号（basic/enhanced） | **差距最大的一项** |
| 跨域同步 | 隐藏 iframe + 20s ip-sync | 无（有意禁止模板 iframe） | 架构选择，不建议照搬 |
| 请求防篡改 | 客户端 md5 签名（可还原） | HMAC 会话令牌 + 幂等（服务端验） | 我们更稳 |
| 漏斗埋点 | init/progress/lead/visit-end 全步骤 | page_view/phone_submit/visit_end | 步骤与驻留 lead 可补 |
| 像素平台 | Meta + TikTok + Kwai + mgskyads | Meta（Browser + CAPI） | 多平台归因可补 |
| 归因细节 | fbclid/ttclid/_fbc/_fbp/_ttp 前端捕获 | `_fbp`/`_fbc` 服务端读取 | 可补前端捕获 |
| 域名健康 | FB 像素失败自检 + 封禁上报 | 无 | 可补 |
| 多语言 | 客户端自动翻译 SDK | 服务端 locale 解析 + 打包语言包 + RTL | 我们更可控 |
| 代码形态 | 混淆 bundle、无 sourcemap | minify、无 sourcemap、平台脚本明文 | 低优先差距 |
| 恶意载荷 | iOS≥18.4 RCE 加载器 | 无 | **红线，永不跟进** |

## 五、建议

1. **P1 复合设备指纹（可选档位）**：在 `deviceSignals` 之上增加
   `fingerprint` 档，平台注入 canvas（20×20 像素哈希）+ OfflineAudioContext
   + 字体枚举 + speechSynthesis，服务端哈希后作为 visitor 指纹，替代可被
   清除的 localStorage visitor_id；随事件与配对请求上报。保持平台统一
   注入、可配置开关，模板不得自采。
2. **P1 多平台像素**：pixelSdk 化——支持 TikTok/Kwai 动态注入，CSP 按配置
   放行对应域；前端捕获 `fbclid`/`ttclid`/`_ttp` 随事件上报（Meta CAPI
   现有 `_fbp`/`_fbc` 服务端读取保持不变）。
3. **P1 FB 域名封禁自检**：fbq 加载失败时上报平台（复用 inspection 事件
   通道），沉淀域名健康监控，尽早发现 Pixel/域名被封。
4. **P2 漏斗增强**：`progress` 步骤落库、5 秒驻留 lead（`lead-event`）
   可并入现有 events 契约，作为可选事件类型。
5. **不跟进**：iOS RCE 载荷分发、跨域隐藏 iframe、客户端自动翻译 SDK、
   客户端 md5 签名。我们的服务端令牌、CSP 沙箱和平台注入边界在这些点上
   是更稳的设计，保持现状。

## 取证说明

- S1 主页面与 6 段内联脚本；S2–S5 的 bundle：`a: /assets/index-D4UiGIoI.js`、
  `b: /assets/index-Dxx0DN6b.js`、`c: /assets/index-B0gQu34r.js`、
  `d: /assets/index-CDXPnihH.js`；iframe：`v1.io92jujjs33.com/router.js`、
  `ds_rce_loader.js`。
- 同行后端接口：`/api/lp/{init,progress,lead-event,visit-end,countries,
  wa-accounts/entry,wa-accounts/phone-info,wa-accounts/status,
  fb-domain-blocked/report}`；iframe：`/api/v1/{ip-sync,debug}`。
- 本报告所有结论基于静态抓取与源码分析，未执行同行页面任何脚本。
