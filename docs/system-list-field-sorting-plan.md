# 全系统列表字段排序与筛选确认稿

本文用于确认并留档页面行为；已完成的系统管理和账号中心仍保留在文档中。

## 统一规则

- 接口统一使用 `sortBy` 和 `sortOrder=asc|desc`，每个接口只接受本文列出的白名单字段。
- 未传排序参数时使用本文的“默认排序”；同值时固定追加唯一 `id`，时间倒序配 `id desc`，名称正序配 `id asc`。
- 空值无论正序还是倒序都放在最后。
- 切换排序或筛选后回到第 1 页。
- 表格页点击表头排序；素材、模板等卡片页使用一个紧凑的“排序方式”下拉框。
- “操作”、权限详情、凭据、备注、组合展示内容等含义不单一的列不排序。
- 为避免查询过重，普通管理页默认只排序直接字段；账号数、使用数、成功率等聚合列，仅在页面表格中逐项确认后开放排序。
- 下表中“现”表示现有筛选继续保留，“新”表示准备补充。
- “已确认”表示默认排序、筛选和可排序字段均已逐项确认；没有确认的页面统一标记为“待确认”。
- 新增页面列或调整列位置时，统一记录在“新增/调整列”中；没有列调整的页面留空。

## 一、系统管理

| 页面 | 默认排序 | 筛选字段 | 可排序字段（页面列名 → `sortBy`） | 确认状态 | 新增/调整列 |
| --- | --- | --- | --- | --- | --- |
| 用户管理 | 用户 ID 倒序：`id desc` | 新：角色 `groupId`、启停状态 `enabled`、账号类型 `isAdmin`、二步验证 `mfaEnabled` | 用户 → `id`（默认倒序）；角色 → `groupName`；账号类型 → `isAdmin`；二步验证 → `mfaEnabled`；最近登录 → `lastLoginAt`；创建时间 → `createdAt`；更新时间 → `updatedAt` | 已确认 | 在“创建时间”后新增“更新时间”列 → `updatedAt` |
| 角色管理 | 角色 ID 正序：`id asc` | 新：类型 `isBuiltin`、启停状态 `enabled` | 角色 → `id`（默认正序）；类型 → `isBuiltin`；成员数 → `userCount`；创建时间 → `createdAt`；更新时间 → `updatedAt` | 已确认 |  |

说明：系统配置和开发文档都是固定、小规模配置清单，本期不增加分页排序和筛选。

## 二、账号中心

| 页面 / 子列表 | 默认排序 | 筛选字段 | 可排序字段（页面列名 → `sortBy`） | 确认状态 | 新增/调整列 |
| --- | --- | --- | --- | --- | --- |
| 账号管理 | 账号 ID 倒序：`id desc` | 现：账号状态 `status`、来源 `source`、分组 `groupId`、号码国家 `countryCode`、协议 `protocolId`（同一筛选项显示“协议名称 · ID”，支持按名称或 ID 搜索）、资料同步 `metadataStatus`、资料完整度 `qualityKnown`；新：访问国家 `visitorCountryCode`、代理国家 `proxyCountryCode`、账号类型 `accountType`、系统 `deviceOs` | 账号 → `id`；号码国家 → `countryCode`；访问国家 → `visitorCountryCode`；代理国家 → `proxyCountryCode`；类型 → `accountType`；系统 → `deviceOs`；来源 → `source`；好友数 → `friendCount`；群组数 → `groupCount`；评分 → `qualityScore`；分组 → `groupName`；协议 → `protocolId`（按协议 ID，不按名称）；发送数据 → `sentCount`（单勾状态与双勾状态合计，每条消息只计一次）；创建时间 → `createdAt`；更新时间 → `updatedAt` | 已确认 | 补回现有展示遗漏：“协议”列 → `protocolName/protocolType`；新增“创建时间”列 → `createdAt`；其后新增“更新时间”列 → `updatedAt`；批量操作增加账号导出 |
| 账号导出 | 不适用 | 不适用 | 不适用 | 已确认：删除页面 | 导出功能迁移到账号管理的批量操作；不做历史兼容 |
| 账号分组 | 分组 ID 倒序：`id desc` | 不新增；保留分组名称/备注搜索 | 分组 → `id`（默认倒序）；账号总数 → `accountCount`；有效账号 → `validAccountCount`；异常账号 → `abnormalAccountCount`；有效率 → `validRate`；评分 → `averageScore`（分组内账号平均评分）；创建时间 → `createdAt`；更新时间 → `updatedAt` | 已确认 | “说明”列改名为“备注”；“账号概况”拆分为“账号总数”“有效账号”“异常账号”“有效率”四列；删除“资料情况”列；新增“评分”列；在“创建时间”后新增“更新时间”列 |
| 账号接入记录 | 记录时间倒序：`createdAt desc` | 现：接入状态 `status`；新：接入类型 `pairingType`、分组 `groupId`、渠道 `channelId`、模板 `templateId`、协议 `protocolId`、访问 IP `sourceIp`、号码国家 `countryCode`、访问国家 `visitorCountryCode`、入池结果 `admissionStatus`、资料同步 `metadataStatus` | 号码/账号 ID → `accountId`；接入状态 → `status`；接入类型 → `pairingType`；号码国家 → `countryCode`；访问国家 → `visitorCountryCode`；渠道 → `channelId`（按渠道 ID）；入池结果 → `admissionStatus`；资料同步 → `metadataStatus`；记录时间 → `createdAt` | 已确认 | 协议列在协议名称下副显协议 ID |
| 账号详情－好友 | 最近联系倒序：`lastInteractionAt desc` | 现：好友来源 `source`；不新增 | 好友 → `phone`（按号码）；来源 → `source`；最近联系 → `lastInteractionAt`；同步时间 → `syncedAt` | 已确认 |  |
| 账号详情－群组 | 最近联系倒序：`lastInteractionAt desc` | 新：可发送 `canSend`、群组类型 `communityType` | 群组 → `groupJid`（按群组 ID，不按名称）；人数 → `size`；类型 → `communityType`；我的权限 → `ownRole`；最近联系 → `lastInteractionAt`；同步时间 → `syncedAt` | 已确认 |  |
| 账号详情－生命周期 | 发生时间倒序：`occurredAt desc` | 新：原状态 `fromState`、目标状态 `toState`、原因 `reason` | 发生时间 → `occurredAt`；原状态 → `fromState`；目标状态 → `toState`；原因 → `reason`；服务码 → `providerCode` | 已确认 | 将现有“状态变化”拆分为“原状态”和“目标状态”两列；原状态、目标状态和原因统一显示中文映射 |
| 账号统计－每日明细 | 日期正序：`date asc` | 现：日期范围；不新增 | 仅日期 → `date`。该表与趋势图共用数据，默认保持时间顺序，不开放其他表头排序 | 已确认 |  |

## 三、资源与协议

| 页面 / 子列表 | 默认排序 | 筛选字段 | 可排序字段（页面列名 → `sortBy`） | 确认状态 | 新增/调整列 |
| --- | --- | --- | --- | --- | --- |
| IP 代理管理 | 代理 ID 倒序：`id desc` | 现：协议 `protocol`、国家 `countryCode`、健康状态 `healthStatus`；新：供应商 `provider` | 代理 → `id`；协议 → `protocol`；国家/地区 → `countryCode`；供应商 → `provider`；健康状态 → `healthStatus`；创建时间 → `createdAt`；更新时间 → `updatedAt` | 已确认 | “国家 / 地区”列删除国家代码副显示；代理详情抽屉改为与账号管理详情抽屉一致的宽版；删除详情抽屉中的“账号绑定”和“已绑定账号”区域 |
| IP 代理－已绑定账号 | 不适用 | 不适用 | 不适用 | 已确认：删除子表 | 代理重绑统一使用 IP 代理管理的批量重绑；账号与代理关系通过账号管理的代理筛选和排序查看 |
| 协议中心－协议定义 | 协议 ID 倒序：`id desc` | 不新增；保留协议、仓库、版本或 ID 搜索 | 协议 → `id`；实现仓库 → `packageName`；当前版本 → `version`；远程版本 → `remoteLatestVersion`；构建状态 → `buildStatus`；节点数 → `nodeCount`；契约版本 → `contractVersion`；创建时间 → `createdAt` | 已确认 |
| 协议中心－节点管理 | 节点 ID 倒序：`id desc` | 新：绑定协议 `protocolDefinitionId`、进号开关 `ingressEnabled`、营销开关 `marketingEnabled` | 节点名称 → `id`；绑定协议 → `protocolName`；进号开关 → `ingressEnabled`；营销开关 → `marketingEnabled`；账号总量 → `accountTotal`；有效数/率 → `validAccounts`（按有效数）；在线数/率 → `onlineAccounts`（按在线数）；创建时间 → `createdAt` | 已确认 |
| 协议中心－路由策略 | 路由策略 ID 倒序：`id desc` | 新：包含节点 `protocolNodeId`、状态 `status`（可回退/无可用成员） | 路由策略 → `id`；创建时间 → `createdAt`；更新时间 → `updatedAt` | 已确认 | 新增“创建时间”列；其后新增“更新时间”列 |

## 四、超链营销

| 页面 / 子列表 | 默认排序 | 筛选字段 | 可排序字段（页面列名 → `sortBy`） | 确认状态 | 新增/调整列 |
| --- | --- | --- | --- | --- | --- |
| 超链模板 | 更新时间倒序：`updatedAt desc` | 现：模板状态 `enabled`、页头类型 `headerType`；新：关联素材 `materialId`、推广渠道 `promotionChannelId` | 模板名称 → `name`；模板状态 → `enabled`；页头类型 → `headerType`；更新时间 → `updatedAt` | 待确认 |
| 超链任务 | 创建时间倒序：`createdAt desc` | 现：任务状态 `status`；新：模板 `templateId`、账号分组 `accountGroupId` | 任务 → `name`；任务状态 → `status`；创建时间 → `createdAt`；开始时间 → `startedAt`；完成时间 → `completedAt` | 待确认 |
| 超链任务－执行明细 | 最近更新倒序：`updatedAt desc` | 新：执行状态 `status`、消息状态 `messageStatus`、发送账号 `accountId` | 目标号码 → `phone`；执行状态 → `status`；消息状态 → `messageStatus`；发送账号 → `accountName`；尝试次数 → `attemptCount`；最近更新 → `updatedAt` | 待确认 |
| 数据包 | 更新时间倒序：`updatedAt desc` | 新：状态 `status`、是否已被任务使用 `inUse` | 数据包 → `name`；当前版本 → `revision`；状态 → `status`；更新时间 → `updatedAt` | 待确认 |
| 超链策略 | 更新时间倒序：`updatedAt desc` | 新：启停状态 `enabled`、账号不足处理 `noAccountAction` | 策略 → `name`；账号槽位 → `concurrency`；单账号峰值 → `maxQps`；重试次数 → `retryLimit`；更新时间 → `updatedAt` | 待确认 |
| 直接短链 | 创建时间倒序：`createdAt desc` | 现：Bitly 账号 `providerAccountId`；新：启停状态 `enabled` | Bitly 短链接 → `title`；点击数 → `clickCount`；账号 → `providerAccountName`；创建时间 → `createdAt` | 待确认 |
| 直接短链－Bitly 账号池 | 账号名称正序：`name asc` | 新：启停状态 `enabled`、连接状态 `status` | 账号名称 → `name`；短域名 → `shortDomain`；连接状态 → `status` | 待确认 |
| 市场洞察－国家明细 | 封号率倒序：`banRate desc` | 现：日期范围、账号来源国家 `sourceCountry`、发送目标国家 `targetCountry`；不新增 | 账号来源国家 → `sourceCountry`；发送目标国家 → `targetCountry`；发送 → `sent`；双勾送达 → `delivered`；送达率 → `deliveryRate`；失败 → `failed`；异常账号 → `abnormalAccounts`；封号账号 → `bannedAccounts`；封号率 → `banRate` | 待确认 |

## 五、推广管理

| 页面 / 子列表 | 默认排序 | 筛选字段 | 可排序字段（页面列名 → `sortBy`） | 确认状态 | 新增/调整列 |
| --- | --- | --- | --- | --- | --- |
| 推广模板－本地模板 | 推广模板 ID 倒序：`id desc` | 新：状态 `status`、来源 `repositorySource` | 模板 → `id`；来源 → `repositorySource`；资源数 → `assetCount`；集成数 → `integrationCount`；使用数 → `channelCount`；创建时间 → `createdAt`；更新时间 → `updatedAt`。版本本期不排序 | 已确认 |
| 推广模板－远程仓库 | 仓库编号正序：`sequence asc` | 新：本地状态 `localStatus` | 远程模板 → `sequence`；仓库编号 → `sequence`；资源数 → `assetCount`；本地状态 → `localStatus` | 已确认 |
| 推广集成－本地集成 | 推广集成 ID 倒序：`id desc` | 新：类型 `integrationType`、源域名 `sourceDomainId` | 集成 → `id`；集成标识 → `integrationKey`；类型 → `integrationType`；源域名 → `sourceDomainName`；资源数量 → `assetCount`；模板数量 → `templateCount`；回传数量 → `eventCount`；创建时间 → `createdAt`；更新时间 → `updatedAt` | 已确认 |
| 推广集成－远程仓库 | 仓库编号正序：`sequence asc` | 新：类型 `integrationType`、本地状态 `localStatus` | 远程集成 → `sequence`；仓库编号 → `sequence`；类型 → `integrationType`；资源数 → `assetCount`；本地状态 → `localStatus` | 已确认 |
| 推广集成－事件记录 | 时间倒序：`occurredAt desc`（同一时间按 `id desc`） | 新：事件类型 `eventType`、渠道 `channelId`、来源 `source`、指纹 `fingerprintQuality` | 不开放表头排序，固定按时间序列展示 | 已确认 | “事件”列副显示 ID |
| 推广渠道 | 推广渠道 ID 倒序：`id desc` | 新：投放国家 `countryCode`、平台 `channelType`、模板 `templateId`、账号分组 `accountGroupId`、Pixel `pixelId`、FB 域名状态 `metaDomainStatus`、语言 `locale` | 渠道 → `id`；投放国家 → `countryCode`；平台 → `channelType`；模板 → `templateName`；账号入库分组 → `accountGroupName`；访问地址 → `hostname`；Pixel → `pixelName`；语言 → `locale`；创建时间 → `createdAt`；更新时间 → `updatedAt` | 已确认 | 删除页面顶部的渠道选择和“查看渠道数据”，并删除整个“渠道数据与号码”抽屉 |
| 推广渠道－Pixel 管理 | Pixel 记录 ID 倒序：`id desc` | 新：启停状态 `enabled` | Pixel 名称 → `id`；Pixel ID → `pixelId`；启停状态 → `enabled` | 已确认 | Pixel 新建/编辑表单按系统标准抽屉表单规范重构，统一字段分组、标签、间距和底部操作区 |
| 推广渠道－Facebook 日投放数据 | 不适用 | 不适用 | 不适用 | 已确认：删除子表 | 随“渠道数据与号码”抽屉一并删除；投放数据统一在数据中心的渠道统计和每日明细中查看 |
| 推广渠道－号码留资 | 不适用 | 不适用 | 不适用 | 已确认：删除子表 | 随“渠道数据与号码”抽屉一并删除 |

## 六、域名、统计与监控

| 页面 / 子列表 | 默认排序 | 筛选字段 | 可排序字段（页面列名 → `sortBy`） | 确认状态 | 新增/调整列 |
| --- | --- | --- | --- | --- | --- |
| 域名管理－系统域名 | 系统域名 ID 倒序：`id desc` | 新：来源 `source`、就绪状态 `ready`、接入状态 `onboardingStatus`、到期范围 `expiresBefore` | 域名 → `id`；来源 → `source`；就绪状态 → `ready`；到期时间 → `expiresAt`；最近验证 → `lastVerifiedAt`；接入状态 → `onboardingStatus` | 已确认 |
| 域名管理－Cloudflare 域名 | Cloudflare 域名 ID 倒序：`id desc` | 新：来源 `source`、Cloudflare 状态 `providerStatus`、接入状态 `onboardingStatus` | 域名 → `id`；来源 → `source`；Cloudflare 状态 → `providerStatus`；接入状态 → `onboardingStatus`；创建时间 → `createdAt`；更新时间 → `updatedAt` | 已确认 | 新增“创建时间”“更新时间”列；远程清单持久化为带稳定 ID 的本地缓存实体，进入页面先显示缓存并自动刷新，同时提供手动刷新按钮；刷新失败时保留并展示上次成功缓存 |
| 域名管理－NameSilo 域名 | NameSilo 域名 ID 倒序：`id desc` | 新：来源 `source`、NameSilo 状态 `providerStatus`、系统订单状态 `orderStatus`、接入状态 `onboardingStatus`、到期范围 `expiresBefore` | 域名 → `id`；来源 → `source`；NameSilo 状态 → `providerStatus`；创建时间 → `createdAt`；更新时间 → `updatedAt`；到期时间 → `expiresAt`；系统订单 → `orderStatus`；接入状态 → `onboardingStatus` | 已确认 | 新增“更新时间”列；远程清单持久化为带稳定 ID 的本地缓存实体，进入页面先显示缓存并自动刷新，同时提供手动刷新按钮；刷新失败时保留并展示上次成功缓存 |
| 渠道统计 | 渠道 ID 倒序：`id desc` | 现：日期范围、渠道 `channelId`、模板 `templateId`、国家 `countryCode`；新：平台 `channelType` | 渠道 → `id`；国家 → `countryCode`；平台 → `channelType`；登录请求 → `loginRequestUv`（按人数）；登录成功 → `loginSuccessUv`（按人数）；请求登录率 → `requestRate`；登录成功率 → `successRate`；访客上号率 → `visitorSuccessRate`；获号成本 → `costPerSuccess`；裂变成功 → `fissionLoginSuccessUv`（按人数）；模板 → `templateName`；创建时间 → `createdAt`；更新时间 → `updatedAt` | 已确认 | 排序控件只放在主表表头，展开的每日明细子表不做排序；新增“平台”“创建时间”“更新时间”列；删除“创建人”列 |
| 推广趋势 | 日期正序：`date asc` | 现：日期范围、渠道 `channelId`；不新增 | 仅日期 → `date`。该表与折线图共用数据，不开放其他排序 | 已确认 |
| 推广监控 | 监控记录 ID 倒序：`id desc` | 现：日期范围、记录来源 `source`、事件类型 `eventType`、流量来源 `trafficSource`、访问国家 `visitorCountryCode`、渠道 `channelId`、模板 `templateId`；新：访问 IP `sourceIp`、集成 `integrationId`、设备类型 `deviceType` | 访问 ID/访客 ID → `id`；访问国家 → `visitorCountryCode`；事件 → `eventType`；记录来源 → `source`；渠道 → `channelName`；模板 → `templateName`；集成 → `integrationName`；设备 → `deviceType`；流量来源 → `trafficSource`；记录时间 → `occurredAt` | 已确认 |

## 不纳入本次修改

- 首页最近任务、系统配置、开发文档：固定或摘要数据，不做完整列表排序。
- 尚未上线的好友营销、拉群营销占位页面：等真实数据结构确定后再接统一协议。
- 操作列、敏感凭据、权限详情、长备注以及多指标组合列：不提供排序。
- 不增加高级筛选 DSL、保存筛选方案、多列组合排序或自定义索引管理界面。

## 建议实施顺序

1. 先落实统一 `sortBy/sortOrder` 协议、空值和并列规则。
2. 账号管理、推广渠道、渠道统计、IP 管理、用户管理优先。
3. 模板/素材/超链资源、协议中心、域名随后完成。
4. 抽屉子列表和外部仓库列表最后补齐。
