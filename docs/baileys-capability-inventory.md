# Baileys 6.7.24 能力总表

> 依据 Parloq Flow 当前锁定的 `@whiskeysockets/baileys` 6.7.24 整理。
> 除纯工具函数外，以下查询、发送和管理能力都需要活动的 `WASocket`，并不是未登录公开查询接口。

## 1. Baileys 能力与 Parloq 接入状态

| 大类 | 小类/能力 | Baileys 接口或事件 | Parloq 状态 | 当前用途或说明 |
| --- | --- | --- | --- | --- |
| 连接与会话 | 创建 WhatsApp Web 连接 | `makeWASocket()` | 已接入 | 每个账号由网关管理独立 Socket |
| 连接与会话 | 手机号配对码 | `requestPairingCode()` | 已接入 | 当前落地页使用的配对方式 |
| 连接与会话 | 二维码配对 | `connection.update` 中的 QR | 未产品化 | Baileys 支持，当前页面未提供 |
| 连接与会话 | 保存登录凭证 | `creds.update` | 已接入 | 持久化凭证和 Signal 密钥 |
| 连接与会话 | 恢复登录会话 | `auth`、保存的凭证 | 已接入 | 无需重新配对即可恢复连接 |
| 连接与会话 | 识别账号平台 | `AuthenticationCreds.platform`、`creds.update` | 底层已保存，业务未提取 | 配对成功时 Baileys 保存手机平台原始值；可归一化为 Android、iOS、其他或未知 |
| 连接与会话 | 识别个人版/商业版 | `isWABusinessPlatform(platform)` | 未接入业务表 | Baileys 6.7.24 明确将 `smba`、`smbi` 判断为 WhatsApp Business；分别对应 Android、iOS |
| 连接与会话 | 连接状态与断线原因 | `connection.update` | 已接入 | 驱动账号状态机、断线重连和管理端在线/离线显示 |
| 连接与会话 | 连接后向 WhatsApp 显示在线 | `markOnlineOnConnect` | 已接入，可配置 | 协议节点提供“关闭在线”开关且默认开启；开启时传 `false`，关闭该开关时传 `true`，不影响 Parloq 管理端判断连接状态 |
| 连接与会话 | 主动发布在线、离线或输入状态 | `sendPresenceUpdate()` | 未直接接入 | Baileys 支持 `available`、`unavailable`、`composing`、`recording`、`paused` 等 Presence 状态 |
| 连接与会话 | 主动登出 | `logout()` | 已接入删除链路 | 不单独暴露；删除账号时用于退出 WhatsApp 并清理登录会话 |
| 连接与会话 | 关闭连接 | `end()` | 已接入 | 关闭 Socket，不等同于登出 |
| 连接与会话 | 等待连接状态 | `waitForConnectionUpdate()` | 未直接调用 | 当前通过 `connection.update` 事件加 Promise、超时和配对稳定窗口实现扩展等待逻辑 |
| 连接与会话 | 固定代理 | Socket `agent`、`fetchAgent` | 已接入 | Parloq 在 Baileys 之上增加代理分配和健康管理 |
| 消息发送 | 文本消息 | `sendMessage()` | 已接入 | 支持普通文本和模板文本 |
| 消息发送 | 引用消息 | `sendMessage()` | Baileys 支持，未完整产品化 | 可引用原消息发送 |
| 消息发送 | 提及用户 | `sendMessage()` | Baileys 支持，未完整产品化 | 需要目标 JID |
| 消息发送 | 转发消息 | `sendMessage()` | Baileys 支持，未完整产品化 | 可转发已有消息对象 |
| 消息发送 | 位置消息 | `sendMessage()` | 已接入 | 支持经纬度位置 |
| 消息发送 | 联系人名片 | `sendMessage()` | 已接入 | 支持联系人/电话内容 |
| 消息发送 | 图片 | `sendMessage()` | 已接入 | 使用受控媒体素材 |
| 消息发送 | 视频 | `sendMessage()` | 已接入 | 使用受控媒体素材 |
| 消息发送 | 音频 | `sendMessage()` | 已接入 | 使用受控媒体素材 |
| 消息发送 | 文档 | `sendMessage()` | 已接入 | 使用受控媒体素材 |
| 消息发送 | GIF | `sendMessage()` | 未产品化 | Baileys 支持 |
| 消息发送 | 贴纸 | `sendMessage()` | 未产品化 | Baileys 支持 |
| 消息发送 | 一次性查看媒体 | `sendMessage()` | 未产品化 | Baileys 支持 |
| 消息发送 | 投票 | `sendMessage()` | 未产品化 | Baileys 支持 |
| 消息发送 | 表情回应 | `sendMessage()` | 未产品化 | Baileys 支持 |
| 消息发送 | 快捷回复按钮 | `relayMessage()` | 已接入 | Parloq 组装原生交互消息 |
| 消息发送 | URL 按钮 | `relayMessage()` | 已接入 | Parloq 组装原生交互消息 |
| 消息发送 | 编辑消息 | `sendMessage()` | 未产品化 | Baileys 支持 |
| 消息发送 | 撤回消息 | `sendMessage()` | 未产品化 | Baileys 支持 |
| 消息发送 | 置顶消息 | `sendMessage()` | 未产品化 | Baileys 支持 |
| 消息发送 | 消失消息 | `sendMessage()`、`chatModify()` | 未产品化 | Baileys 支持 |
| 消息接收 | 接收新消息 | `messages.upsert` | 未接入 | 当前没有入站消息产品链路 |
| 消息接收 | 消息更新 | `messages.update` | 部分接入 | 用于更新出站消息送达状态 |
| 消息接收 | 消息删除 | `messages.delete` | 未接入 | Baileys 支持 |
| 消息接收 | 表情回应事件 | `messages.reaction` | 未接入 | Baileys 支持 |
| 消息接收 | 用户回执 | `message-receipt.update` | 未完整接入 | 当前主要处理出站送达状态 |
| 消息接收 | 请求历史消息 | `fetchMessageHistory()` | 未产品化 | 需要已登录会话 |
| 消息接收 | 占位消息重传 | `requestPlaceholderResend()` | 未产品化 | Baileys 内部恢复能力 |
| 媒体 | 上传媒体 | `waUploadToServer` | 已接入 | 出站媒体发送使用 |
| 媒体 | 刷新媒体连接 | `refreshMediaConn()` | 已接入底层链路 | Baileys 内部上传所需 |
| 媒体 | 下载媒体 | `downloadMediaMessage()` | 未接入 | 未做入站媒体归档 |
| 媒体 | 媒体重传 | `updateMediaMessage()` | 未产品化 | Baileys 支持 |
| 历史同步 | 请求完整历史 | `syncFullHistory` | 部分接入 | 作为 Parloq“好友同步” `contacts` 的内部取数机制；实际下发范围由 WhatsApp 决定 |
| 历史同步 | 选择是否处理历史同步通知 | `shouldSyncHistoryMessage()` | 部分接入 | 与“好友同步” `contacts` 使用同一判断；处理联系人资源后丢弃聊天列表和消息正文 |
| 历史同步 | 接收首次历史 | `messaging-history.set` | 部分接入 | 当前只统计聊天、联系人和历史消息数量 |
| 历史同步 | 识别有过联系的对象 | 历史 `messages`、在线 `messages.upsert` | 未接入 | 只提取一对一联系对象和最后联系时间，不保存聊天列表或消息正文 |
| 联系人 | 联系人新增/更新事件 | `contacts.upsert`、`contacts.update` | 部分接入 | 当前只统计联系人增量数量 |
| 联系人 | 判断本账号已保存的联系人 | `Contact.name` | 未接入业务表 | `name` 是本账号保存的名称；`notify` 是对方自己的显示名，不能作为已保存好友的证据 |
| 联系人 | 新增或修改联系人 | `addOrEditContact()` | 未接入 | Baileys 支持 |
| 联系人 | 删除联系人 | `removeContact()` | 未接入 | Baileys 支持 |
| 聊天 | 聊天新增/更新/删除事件 | `chats.upsert/update/delete` | 未接入 | Baileys 支持 |
| 聊天 | 归档、静音、已读、置顶等 | `chatModify()` | 未接入 | Baileys 支持 |
| 账号查询 | 判断号码是否存在 | `onWhatsApp()` | 未作为通用能力接入 | 必须通过另一个已登录账号查询 |
| 账号查询 | 拉取头像 | `profilePictureUrl(jid)` | 已接入 | 查询当前登录账号自己的头像链接，经固定代理下载并缓存到账号资料中 |
| 账号查询 | 查询 About/资料状态 | `fetchStatus(jid)` | 已删除 | 不再属于 Parloq 资料同步项 |
| 账号查询 | 查询商业资料 | `getBusinessProfile(jid)` | 已删除 | 不再属于 Parloq 资料同步项 |
| 账号查询 | 查询消失消息期限 | `fetchDisappearingDuration()` | 未接入 | Baileys 支持 |
| 账号查询 | 查询在线/输入状态 | `presenceSubscribe()`、`presence.update` | 未接入 | 受对方隐私设置影响 |
| 账号修改 | 修改账号名称 | `updateProfileName()` | 未接入 | Baileys 支持 |
| 账号修改 | 修改 About/资料状态 | `updateProfileStatus()` | 未接入 | Baileys 支持 |
| 账号修改 | 设置头像 | `updateProfilePicture()` | 未接入 | Baileys 支持 |
| 账号修改 | 删除头像 | `removeProfilePicture()` | 未接入 | Baileys 支持 |
| 隐私 | 读取隐私设置 | `fetchPrivacySettings()` | 已删除 | 不再属于 Parloq 资料同步项 |
| 隐私 | 读取黑名单 | `fetchBlocklist()` | 已删除 | 不再属于 Parloq 资料同步项 |
| 隐私 | 屏蔽/解除屏蔽 | `updateBlockStatus()` | 未接入 | Baileys 支持 |
| 隐私 | 修改最后上线时间权限 | `updateLastSeenPrivacy()` | 未接入 | Baileys 支持 |
| 隐私 | 修改在线状态权限 | `updateOnlinePrivacy()` | 未接入 | Baileys 支持 |
| 隐私 | 修改头像可见权限 | `updateProfilePicturePrivacy()` | 未接入 | Baileys 支持 |
| 隐私 | 修改 About 可见权限 | `updateStatusPrivacy()` | 未接入 | Baileys 支持 |
| 隐私 | 修改已读回执 | `updateReadReceiptsPrivacy()` | 未接入 | Baileys 支持 |
| 隐私 | 修改被拉群权限 | `updateGroupsAddPrivacy()` | 未接入 | Baileys 支持 |
| 隐私 | 修改通话/消息权限 | `updateCallPrivacy()`、`updateMessagesPrivacy()` | 未接入 | Baileys 支持 |
| 隐私 | 修改默认消失消息 | `updateDefaultDisappearingMode()` | 未接入 | Baileys 支持 |
| 群组 | 查询单个群资料 | `groupMetadata()` | 未直接接入 | Baileys 支持 |
| 群组 | 查询全部参与群 | `groupFetchAllParticipating()` | 已接入 | 用于群组详情，并直接计算群组数量 |
| 群组 | 统计参与群数量 | `groupFetchAllParticipating()` | 已接入 | Parloq 计算并保存 `groupCount` |
| 群组 | 跨群去重成员数 | 全部 `GroupMetadata.participants`、LID/JID 映射 | 未接入 | 排除本账号并归一身份，只保存去重后的聚合数量用于评分 |
| 群组 | 保存群 ID、名称和人数 | `groupFetchAllParticipating()` | 部分接入 | 只存网关元数据，主系统未消费 |
| 群组 | 创建/退出群组 | `groupCreate()`、`groupLeave()` | 未接入 | Baileys 支持 |
| 群组 | 修改群名称/描述/设置 | `groupUpdateSubject()` 等 | 未接入 | Baileys 支持 |
| 群组 | 添加/移除/升降级成员 | `groupParticipantsUpdate()` | 未接入 | Baileys 支持 |
| 群组 | 获取/撤销/接受邀请 | `groupInviteCode()` 等 | 未接入 | Baileys 支持 |
| 群组 | 查询/处理入群审批 | `groupRequestParticipantsList/Update()` | 未接入 | Baileys 支持 |
| 社群 | 创建、查询、退出社群 | `communityCreate/Metadata/Leave()` | 未接入 | Baileys 支持 |
| 社群 | 社群成员、邀请和审批 | `communityParticipantsUpdate()` 等 | 未接入 | Baileys 支持 |
| 商业能力 | 查询商品目录 | `getCatalog()`、`getCollections()` | 未接入 | Baileys 支持 |
| 商业能力 | 查询订单 | `getOrderDetails()` | 未接入 | Baileys 支持 |
| 商业能力 | 创建/修改/删除商品 | `productCreate/Update/Delete()` | 未接入 | Baileys 支持 |
| Newsletter | 创建/更新/删除频道 | `newsletterCreate/Update/Delete()` | 未接入 | Baileys 支持 |
| Newsletter | 关注/取消关注/静音 | `newsletterFollow/Unfollow/Mute()` | 未接入 | Baileys 支持 |
| Newsletter | 查询频道和消息 | `newsletterMetadata/FetchMessages()` | 未接入 | Baileys 支持 |
| Newsletter | 频道消息回应 | `newsletterReactMessage()` | 未接入 | Baileys 支持 |
| 回执 | 标记已读和发送回执 | `readMessages()`、`sendReceipt(s)()` | 部分接入 | 用于消息发送链路 |
| 通话 | 接收通话事件 | `call` | 未接入 | Baileys 支持 |
| 通话 | 拒绝通话 | `rejectCall()` | 未接入 | Baileys 支持 |
| 标签 | 创建和管理聊天/消息标签 | `addLabel()`、`addChatLabel()` 等 | 未接入 | Baileys 支持 |
| 底层协议 | 发送 Binary Node | `query()`、`sendNode()` | 底层使用 | 不向管理后台开放 |
| 底层协议 | 发送原始 WebSocket 数据 | `sendRawMessage()` | 未直接开放 | Baileys 支持 |
| 底层协议 | USync 查询 | `executeUSyncQuery()` | 底层使用 | 不向管理后台开放 |
| 底层协议 | Signal 会话和 PreKey | `assertSessions()`、`uploadPreKeys()` | 已接入底层链路 | 维持加密会话所需 |
| 底层协议 | App State 重新同步 | `resyncAppState()`、`appPatch()` | 未产品化 | Baileys 支持 |

## 2. 账户同步开关规划

| 同步开关 | Baileys 能力 | 当前保存结果 | 主系统是否消费 | 数据/资源成本 | 当前默认 | 建议 |
| --- | --- | --- | --- | --- | --- | --- |
| 头像 `avatar` | `profilePictureUrl(ownJid)` | `hasAvatar` | 是 | 低 | 开 | 保留，默认开启 |
| 群组同步 `groupDetails` | `groupFetchAllParticipating()`、历史/实时聊天事件 | `groupCount`、群 ID、名称、人数、权限、最近联系时间、跨群去重成员数 | 是，明细已落主系统资源表 | 中，需要读取全部参与群和成员身份；最近联系时间不保存消息正文 | 开 | 已删除 `groupSummary`；服务概览、评分和后续群组营销 |
| 好友同步 `contacts` | `syncFullHistory`、`shouldSyncHistoryMessage()`、历史包、联系人事件、LID/JID 映射、新消息事件 | 好友并集清单、来源、身份映射和最后联系时间 | 是，明细已落主系统资源表 | 中高，仅显式资料同步请求历史 | 开 | 好友为已保存联系人和有过一对一联系的对象并集；历史同步只作为内部实现 |
| 聊天列表 `chats` | 聊天历史事件 | 只统计数量 | 否 | 高 | 关 | 删除开关及配套，不建设聊天列表资源 |
| 消息历史 `messageHistory` | 历史消息集合 | 只统计数量 | 否 | 很高 | 关 | 删除开关及配套，不保存消息正文 |

## 3. 已确认规划

| 决策 | 同步开关 | 默认值 |
| --- | --- | --- |
| 保留 | 关闭在线 `closeOnline` | 开 |
| 保留 | 头像 `avatar` | 开 |
| 删除，能力合并到群组同步 | 群组概览 `groupSummary` | — |
| 保留，兼顾概览、评分和群组营销 | 群组同步 `groupDetails` | 开，继承原 `groupSummary` 策略 |
| 不新增产品开关，仅作为内部取数机制 | 历史同步 | — |
| 保留现有字段并升级语义 | 好友同步 `contacts` | 开 |
| 删除 | 聊天列表 `chats` | — |
| 删除 | 消息历史 `messageHistory` | — |

产品不暴露独立历史开关。开启“好友同步” `contacts` 或“群组同步” `groupDetails` 后，网关只在显式资料同步任务中临时启用历史摘要处理，日常连接和发信重连不请求完整历史；群基础资料仍通过独立群组接口获取，历史摘要只用于补充最近联系时间。

群组营销和好友营销的具体接口、同步字段、落库范围及任务前置条件见 [接入账户模型升级方案](./account-model-lightweight-upgrade.md)。
