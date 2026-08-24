# 同行落地页能力借鉴计划

> 本文只收录同行正常产品与工程模式的借鉴项，供后续实现参考。对同行素材、文案与代码只做模式借鉴，不做复制。

## 一、我方已有基础

- **架构边界**：模板 ZIP 只负责展示与本地化；`tracker.js` / `guard.js` /
  `account-link-elements.js` 由平台统一注入；生产 CSP 沙箱只放行白名单域，
  模板无法外联第三方脚本或数据接收方。
- **访问与鉴权**：ThumbmarkJS 设备指纹 + 租户 HMAC + 服务端 Snowflake 访客
  + 速率限制；只有具体配对任务使用服务端签发的状态 Bearer 令牌。
- **事件埋点**：`page_view` / `phone_submit` / `visit_end` /
  `inspection_detected`，事件 ID 由服务端生成，`phone_submit` 自动归并为 lead。
- **Meta 归因**：Browser Pixel + CAPI 双发、共用 `event_id` 去重、事件映射
  可配置；服务端读取 `_fbp` / `_fbc`。目前仅 Meta 一个平台。
- **多语言**：服务端按国家→语言映射解析 locale，模板自带
  `locales/{locale}.json`，支持 RTL 语言族；白标组件库 15 语言。
- **配对体验**：完整配对状态机（发放、倒计时、查询、占用、失败、重试、
  成功）、libphonenumber 校验、国家自动识别、FB/IG 内嵌浏览器引导外部打开。

## 二、可借鉴清单（按能力域）

### 1. ThumbmarkJS 设备指纹（P1）

**状态：✅ 已切换为同行同源方案（2026-08-24）**

同行使用 canvas（20×20 像素哈希）、OfflineAudioContext 音频指纹、字体
枚举、WebGL 渲染器等组件合成复合指纹，作为全链路标识贯穿每个事件与配对
请求。

**实际落地**：

- 使用 ThumbmarkJS `1.10.1` 的本地计算结果替代自研组件采集；指纹始终启用，
  管理端不再保留关闭、标准、增强等强度选项。
- 浏览器从 `_fp` 读取缓存；首次访问调用 ThumbmarkJS，失败时按同行方式生成
  `fb_<随机值>_<时间戳>` 并写回 `_fp`。ThumbmarkJS 关闭匿名远程日志，不配置
  托管 API，也不从 CDN 加载资源。
- 浏览器向平台提交 32 位原始 Thumbmark 或回退值；服务端使用租户 ID 和服务端
  密钥生成 64 位 HMAC 后入库，不保存原始值，也不允许不同租户直接关联同一
  浏览器环境。
- ThumbmarkJS 自己负责组件超时、不可用和浏览器稳定化排除；平台不再维护自研
  组件组合、浏览器配置或漂移匹配键。正常 Thumbmark 标为 high，随机持久化
  回退值标为 low。
- 服务端按租户 HMAC 查找或创建唯一的 `PromotionVisitor`，并为它分配
  Snowflake ID。配对状态查询与取消使用本次配对专用的状态凭证。
- `visitorCheck` / `visitorAttempt` 以及事件 `sessionReports` 限速统一使用租户
  HMAC 指纹键；`ipStart` / `ipReports` 始终作为独立 IP 维度执行。
- 原生事件、iframe 事件与配对尝试统一关联 `PromotionVisitor`；原始指纹不
  落库，HMAC、版本和质量只保存在访客实体中。渠道 UV 与监控列表均按服务端
  Snowflake 访客口径展示和去重。

**主要落点**：

- `apps/web/src/public-runtime/device-fingerprint.ts`
- `apps/web/src/public-runtime/promotion-tracker.ts`
- `apps/api/app/services/device_fingerprints.py`
- `apps/api/app/routers/promotion.py`
- `apps/api/app/routers/promotion_integrations.py`
- `apps/api/alembic/versions/0042_device_fingerprints.py`
- `apps/api/alembic/versions/0060_thumbmark_fingerprints.py`
- `apps/api/alembic/versions/0061_server_promotion_visitors.py`
- `apps/web/vendor/thumbmarkjs/`

**供应链边界**：npm 发布归档、完整源码、MIT 许可证、上游提交和 SHA-256
校验值均固定在仓库内；应用依赖本地归档构建，上游仓库或 npm 包后续不可用
不会影响既有版本的安装与发布。

### 2. 多平台广告像素与归因（P1，有实际投放需求时实施）

同行以 pixelSdk 形态按渠道配置动态注入 Meta / TikTok / Kwai 平台 SDK，
前端捕获 `fbclid` / `ttclid` / `_ttp` 随事件上报。

**方案**：渠道增加平台配置，tracker.js 按配置注入对应平台 SDK；
`_sandbox_csp` 按启用平台放行域名；前端捕获各平台 clid 随事件上报。
Meta CAPI 现有逻辑保持不变。

当前系统只有 Meta 的明确业务闭环。在确认 TikTok / Kwai 渠道会实际投入
使用前，不提前扩大 CSP、渠道配置和第三方 SDK 面积。

- 落点：`apps/api/app/routers/promotion.py`（渠道配置与 CSP）、
  `apps/api/app/services/meta_conversions.py`、web 端 runtime 脚本。
- 验收：仅启用 Meta 时 CSP 与现状一致；启用 TikTok/Kwai 后对应域放行且
  事件上报成功；未启用的平台零请求。

### 3. Facebook 域名受限风险监测与 CAPI 探测（P1）

**状态：✅ 已完成（2026-08-18）**

同行在初始化 Meta Pixel 前劫持 `console.error`；当错误文本同时包含
`[Meta pixel]`、当前 Pixel ID 和 `is unavailable` 时，只上报一次当前
hostname 到 `fb-domain-blocked/report`。页面把可能原因描述为域名被封、
Pixel 停用或广告账号受限。它没有监听 Meta 脚本的 `onerror` 或加载超时。

同行管理端把结果持久化为渠道字段 `fb_domain_blocked`：`false` 显示“正常”，
`true` 显示“域名已拉黑”，并提示广告投放可能受影响。管理端每行的“探测”
按钮是独立的 Facebook CAPI 连通性测试，并不是域名探测；其调用
`POST /api/admin/channels/{id}/fb-probe`，不能用来恢复或验证域名状态。

**结论**：这是一项有实际运营价值的轻量投放风险监测。它不能监测 Campaign、
花费、曝光或点击，但能在真实落地页收到 Meta Pixel 的明确
“unavailable”信号后，把对应渠道域名及时标红，提醒运营排查或更换域名。
它与 CAPI 投递账本是两条独立链路，不能互相替代。

**实际落地（对齐核心、不扩成健康中心）**：

- 渠道保存 `meta_domain_blocked` 和首次发现时间；同一基础域名与子域名
  前缀下的渠道共享这一风险状态。
- 平台 runtime 在初始化 Meta Pixel 前安装一次性 `console.error` 监听，仅在
  错误同时包含 `[Meta pixel]`、当前 Dataset ID、`is unavailable` 时上报。
- 新增专用公开上报接口，由当前渠道 URL 确定渠道，不信任客户端自行提交的
  hostname；接口按来源 IP 和落地域名限速，重复上报保持幂等。
- 渠道管理列表增加“FB 域名状态”：未绑定域名或未启用 Browser Pixel 显示
  “未监测”，未收到异常显示“正常”，命中后显示“疑似受限”及发现时间。
- 渠道更换域名、子域名前缀、Pixel，或重新启用 Browser Pixel 时清除旧状态；
  一期不增加定时任务、Meta Ads API、告警中心和复杂诊断页。
- 渠道操作区增加 Facebook CAPI 连通性探测。它向当前渠道绑定的 Dataset
  直发一次独立 `ParloqCapiProbe` 事件，返回 HTTP 状态、事件 ID 和 Meta trace；
  探测不要求渠道已打开正式 CAPI 开关，也不写入正式投递账本。

- 落点：`PromotionChannel` + Alembic 迁移、公开推广路由、
  `promotion-tracker.ts`、`meta_conversions.py`、渠道管理表格与探测结果抽屉。
- 验收：只匹配当前 Pixel 的准确错误；每页最多上报一次；错误状态可持久化并
  在列表展示；无关控制台错误和普通网络失败不误报；配置变更后旧状态清除；
  CAPI 探测成功与失败均返回结构化结果且不增加账本记录。

**验收结果**：API 全量 154 项测试、Web 生产构建、Baileys 网关 32 项测试与
构建、本地及生产 Compose 解析均通过；本地渲染验证了正常、疑似受限及发现
时间三种展示，并完成 CAPI 探测交互，页面无相关控制台错误。生产上线后由
真实落地页和真实 Meta Token 继续验证外部回执。

### 4. 漏斗埋点增强（P1）

**状态：✅ 已完成（2026-08-18）**

同行有步骤级 `progress` 落库（含 localStorage 断电恢复）、5 秒驻留 lead
（去重）、`sendBeacon` 驻留时长上报。

**方案**：在现有 `page_view` / `phone_submit` / `pairing_started` /
`pairing_verified` 之外，仅补对转化判断有用的步骤和失败原因，复用现有幂等
与审计通道。同行“驻留 5 秒即算 lead”的口径会制造虚假线索，我方不跟进，
继续以真实号码提交作为 lead。

- 落点：复用 `PromotionEvent`、配对记录与现有渠道统计接口；在“接入记录”
  页面展示统一失败原因，在“渠道数据与号码”中展示按访客去重的五步漏斗与
  主要流失原因。落地页 runtime 只保留简洁、安全的访客提示。
- 验收：关键步骤变化和失败原因可落库、可聚合；不会因单纯驻留自动创建
  lead。

**验收结果**：恢复“接入记录”菜单及既有页面；统一归类号码无效、号码不可用、
配对进行中、限速、协议节点不可用、连接路由不可用、网关失败、配对码过期、
用户取消和服务不可用等原因；配对前失败复用 `PromotionEvent`，进入配对后的
结果复用配对记录，不新增重复账本。API 全量测试、Web 生产构建、Baileys 网关
测试与构建、Compose 解析及本地页面交互验收均通过。

### 5. 交互防护补强（P2）

**状态：不实施（2026-08-19 评审）**

同行检测器覆盖 7 类（字体尺寸、原型复原、console 特征等），并对搜索引擎
bot 做白名单豁免。我方现有 4 类，动作可配置且事件上报服务端。

**方案**：增加 2–3 类检测（字体尺寸差异、`RegExp`/`Date` 原型复原、移动
端调试库特征），引入 bot 白名单（命中 UA 的爬虫跳过检测），保持"可配置
动作 + 服务端上报"的现有形态。

**评审结论**：现有窗口差异、Eruda/vConsole、console probe 和 debugger
延迟检测已覆盖普通场景。继续增加字体和原型对抗容易误伤缩放、无障碍和不同
WebView，且不能形成真正安全边界；bot 白名单也没有当前故障证据，因此保持
现状。安全继续依赖 CSP、服务端鉴权、幂等和限流。

- 落点：`apps/api/app/routers/promotion.py`（LANDING_GUARD_JS）。
- 验收：新增检测器通过策略开关控制；UA 命中 bot 白名单时跳过检测。

### 6. 转化体验

**状态：✅ 已完成（2026-08-19）**

- CTA 有效性门槛：号码不完整时 CTA 保持禁用，减少无效请求。
- 国家能力：页面国家探测 + 区号选择，不要求用户输入完整国际格式。
- 单屏转化结构：移动端整屏主视觉、单一 CTA、关键内容一屏内完成；内容
  顺序为社会证明 → 价值主张 → 信任提示 → 输入与 CTA。
- 状态完备：加载/错误/成功状态齐全；配对进度可恢复。
- 文案真实性：动态人数、身份验证、安全承诺等文案必须有真实数据支撑，
  否则不展示。

**方案**：CTA 门槛、国家选择器、完整状态机作为平台能力纳入白标组件库与
模板规范（v2）默认行为；文案真实性作为模板审核项。

**实际落地**：v2 已明确为新模板唯一标准；`account-link-elements/v1` 统一
负责国家选择、号码有效性、CTA 禁用与完整配对状态，v1 仅保留兼容。真实性、
移动端尺寸和状态验收已经统一写入 v2 规范及管理端设计规范。

- 落点：`apps/api/app/template_kits/account_link_v1/`、
  `docs/promotion-template-spec-v2.md`、web 端组件库。
- 验收：模板规范写明 CTA 禁用条件与国家选择要求；审核清单含文案真实性。

### 7. 工程形态

**状态：✅ 轻量方案已完成（2026-08-19）**

- 资源优化：字体预连接、图片域 DNS 预取、CSS preload、图片懒加载、
  移动端固定视口布局。
- 体积预算：同行单 bundle 450–610KB，业务/翻译/像素/防护混包；我方按
  模块拆分并设置体积预算。
- 素材组织：同行用专用图床按 地区/性别/人名 分层组织素材，便于按渠道
  快速换包。
- 构建产物：生产产物 minify、无 source map（现状已满足，保持）。

**方案**：模板规范增加资源优化条目与体积预算；评估平台 assets 端点是否
支持按渠道分层组织素材。

**实际落地**：模板每次导入或替换 ZIP 时生成并持久化轻量质量报告，统计
JS/CSS gzip、解压体积和图片体积，并聚合 source map、外部资源、iframe、
大图、图片属性、懒加载、viewport、v1 兼容模式和白标组件使用情况。安全与
结构错误继续拒绝导入，普通性能问题仅提示。平台不自动改写 HTML/图片，也不
增加地区/性别/人物固定素材层级；这两项当前没有必要。

- 落点：`docs/promotion-template-spec-v2.md`、平台 assets 端点。
- 验收：新模板通过性能预算检查；资源优化项在渲染层生效。

## 三、保持现状项

- **平台注入边界与 CSP 白名单**：模板不得自行外联脚本或指定数据接收方，
  统计与跨域组件由平台统一管理和审计。
- **服务端令牌鉴权**：具体配对任务保持短期状态令牌 + 幂等 + 限流，不引入
  客户端可还原的签名方案。
- **服务端多语言**：保持服务端 locale 解析 + 打包语言包 + RTL，不引入
  第三方客户端自动翻译脚本。
- **无障碍**：默认不禁用页面缩放；视口锁定作为平台可配置策略，而非模板
  写死。

## 四、分阶段实施计划

| 阶段 | 事项 | 范围 | 状态/建议 |
| --- | --- | --- | --- |
| P1-1 | ThumbmarkJS 指纹 + UV 增强 + 访客限速增强 | API + web runtime | ✅ 已切换（2026-08-24） |
| P1-2 | Meta Pixel unavailable 上报 + 渠道 FB 域名风险状态 + CAPI 探测 | API + web runtime + 渠道页 | ✅ 已完成（2026-08-18） |
| P1-3 | 关键漏斗步骤与失败原因可观测性 | API + web runtime + 渠道页 | ✅ 已完成（2026-08-18），未做驻留 Lead |
| P1-4 | 多平台像素分发 + CSP 动态放行 + clid 捕获 | API + web runtime | 有实际平台需求时实施 |
| P2-1 | 模板规范（v2 修订）+ 轻量 ZIP 质量报告 | 文档 + API + 模板页 | ✅ 已完成（2026-08-19） |
| P2-2 | 交互防护检测器补强 + bot 白名单 | API | 不实施，保持现有检测 |

## 五、验收与度量

- **性能**：模板体积预算（首屏 JS/CSS 上限），性能预算检查纳入模板验收。
- **事件完整性**：新事件类型带幂等键，重复上报只计一次；`sendBeacon`
  路径在 `pagehide` 下可送达。
- **像素回执**：各平台像素事件与控制台/事件表可对账。
- **指纹稳定性**：持续观察覆盖率、正常 Thumbmark / 回退值占比；按真实浏览器
  抽样验证稳定性。清理站点存储或浏览器隐私策略可能改变结果，不把指纹作为
  唯一安全凭据。

## 六、约束与边界

- **采集合规**：指纹与设备信号采集有明确的采集范围声明；生产 CSP 禁止模板
  额外采集或外传，服务端只保存租户隔离 HMAC。
- **第三方依赖受控**：新增像素平台仅在渠道显式启用时注入，且由 CSP
  白名单约束。
- **数据边界**：号码、指纹等数据不传给任何第三方接收方；统计与归因
  数据只走平台统一通道。

## 七、持续观察

- 每季度选定若干同行公开推广页做静态观察，产出观察记录并归档 `docs/`。
- 观察记录只总结可复用的产品与工程模式，不复制素材、文案或代码。
- 发现新的差距时更新本计划并重新排期。
