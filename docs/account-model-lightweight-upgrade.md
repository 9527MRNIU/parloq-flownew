# 接入账户模型升级方案

## 1. 升级目标

在不重构现有超链营销的前提下，让接入账户逐步支持：

- 账户评分；
- 群组营销；
- 好友营销（通讯录营销）；
- 后续其他依赖账号已有资源的营销任务。

本方案直接对接项目锁定的 `@whiskeysockets/baileys` 6.7.24。完整接口清单见 [Baileys 6.7.24 能力总表](./baileys-capability-inventory.md)。

本次坚持轻量设计：保留 `personal_accounts` 主表，不建设万能资源模型，不保存聊天列表和消息正文，也不重构已经稳定的超链营销任务。

## 2. 账户开关语义调整

`closeOnline`、`avatar`、`groupDetails`、`contacts` 继续保留。`groupDetails` 的开关名称调整为“群组同步”，`contacts` 的开关名称调整为“好友同步”。`groupSummary` 与 `groupDetails` 使用相同的 Baileys 查询，作为独立开关属于冗余，因此删除；群组同步完成后直接计算 `groupCount`。`syncFullHistory`、`shouldSyncHistoryMessage()` 和历史同步事件属于账号资源同步的内部取数机制，不再包装成独立的产品开关。`chats`、`messageHistory` 以及只为它们服务的表单、DTO、网关统计和测试夹具删除。

`closeOnline` 不改字段、不改位置、不改默认值。它虽然不是资源同步动作，但确实是账户运行模型的一项开关，继续和其他账户开关一起管理。

| 开关 | 开关名称 | 默认值 | 对应 Baileys 6.7.24 能力 | 当前/后续用途 |
| --- | --- | --- | --- | --- |
| `closeOnline` | 关闭在线 | 开 | `markOnlineOnConnect: !closeOnline` | 控制 Socket 连接后是否向 WhatsApp 发布在线状态；保持现有实现 |
| `avatar` | 头像同步 | 开 | `profilePictureUrl(ownJid, "image")` | 同步本账号头像，用于账户展示，不参与评分 |
| `groupDetails` | 群组同步 | 开 | `groupFetchAllParticipating()`、历史/实时聊天事件 | 同步群 JID、名称、人数、权限等详情，合并已下发范围内的最近联系时间，并直接计算 `groupCount`；用于账户概览、评分和群组营销 |
| `contacts` | 好友同步 | 开 | `syncFullHistory`、`shouldSyncHistoryMessage()`、历史包、`contacts.upsert/update`、`chats.phoneNumberShare`、`messages.upsert` | 接收必要的历史资源包，分类并保存好友资源、LID/JID 映射和最后联系时间；不保存聊天列表或消息正文 |

`contacts` 是 Parloq 自己封装的业务同步策略，不是 Baileys 原生开关，Baileys 也没有统一的 `syncContacts()` 接口。网关根据这个开关编排历史同步配置和多个增量事件。外部不再暴露“历史同步”开关；内部直接按下面的规则派生：

```text
needHistorySync = contacts && explicitMetadataSyncRun
```

也就是说，`contacts=true` 表示允许并处理好友资源，`groupDetails=true` 表示允许用已下发聊天摘要补充群组最近联系时间；日常连接和发信重连不会反复请求完整历史。只有首次资料同步、手动“同步资料”或节点策略变更触发的后台资料任务，才临时带上内部历史请求参数受控重建 Socket；完成后立即清除该临时参数。

群组名称、成员和权限仍通过独立群组接口获取；最近联系时间仅复用资料任务已经收到的历史聊天摘要和实时消息事件，不保存聊天或消息正文。系统不再设置独立的群组概览开关，也不增加“账号资源同步”之类的冗余总开关。

推荐的功能开关组合：

| 使用场景 | 需要开启 | 说明 |
| --- | --- | --- |
| 超链营销 | 不新增资源要求；各开关维持节点默认 | 无任务专属开关 |
| 群组营销 | `groupDetails=true`；其他开关按节点默认 | 无任务专属开关 |
| 好友营销 | `contacts=true` | 无独立历史、聊天或消息开关 |
| 账户完整评分 | `groupDetails=true`、`contacts=true` | 头像不参与评分；无独立历史、聊天或消息开关 |

好友同步开启后，网关会临时扫描历史包里的聊天对象和消息元数据，把通讯录联系人和聊天记录联系人合并为好友。处理完成后丢弃聊天列表和消息正文。

## 3. 群组营销需要对接的 Baileys 能力

### 3.1 首次同步

开启 `groupDetails` 后，网关调用：

```text
groupFetchAllParticipating()
```

Baileys 6.7.24 返回当前账户参与的全部 `GroupMetadata`。主系统第一期只保存群组营销真正需要的字段：

| 数据 | Baileys 字段 | 用途 |
| --- | --- | --- |
| 群唯一标识 | `id` | 群组营销发送目标，即群 JID |
| 群名称 | `subject` | 后台选择和任务明细展示 |
| 群人数 | `size` | 任务筛选、容量展示和统计 |
| 仅管理员发言 | `announce` | 判断当前账户是否具备发送条件 |
| 群设置受限 | `restrict` | 群资料及权限展示 |
| 社群属性 | `isCommunity`、`isCommunityAnnounce`、`linkedParent` | 区分普通群、社群和公告群 |
| 寻址模式 | `addressingMode` | 保留 Baileys 当前群寻址方式 |
| 当前账号角色 | `participants` 中本账号的 `admin`、`isAdmin`、`isSuperAdmin` | 计算当前账号是否可向公告群发送 |
| 跨群去重成员数 | 全部群的 `participants` | 排除本账号并按 JID/LID 映射归一，作为资源统计参考，不参与当前评分 |

第一期不落库完整群成员列表。网关在一次群组同步中临时汇总全部 `participants`，排除本账号，优先按手机号 JID、其次按已知 LID/JID 映射、最后按原始 ID 去重，只把 `uniqueGroupMemberCount` 聚合值写回主系统作为统计参考。当前评分直接使用每个群已保存的 `size`、`ownRole` 和 `canSend`，无需为评分增加群成员表。未来真的需要成员筛选或成员营销时，再增加群成员表。

### 3.2 增量更新

账户在线期间监听：

- `groups.upsert`：发现新群或重新加入的群；
- `groups.update`：群名称、描述、设置等发生变化；
- `group-participants.update`：成员增加、移除、升降管理员；用于更新人数和本账号角色，并把去重群成员数标记为待刷新，防抖后重新执行一次群组同步计算；
- 任务发送前数据过期时调用 `groupMetadata(groupJid)` 做单群刷新。

### 3.3 任务发送

群组营销通过现有消息内容构造能力，最终调用：

```text
sendMessage(groupJid, content)
```

每个群组任务目标必须绑定 `accountId + groupJid`。只有同步该群的账户才能发送；不能像超链营销一样随意更换一个不在群内的账户。

发送前至少检查：

1. 账户有效、允许营销且当前可连接；
2. 群资源仍为有效状态；
3. `canSend=true`；
4. 群详情没有超过允许的新鲜度；
5. 消息发送结果继续进入现有发送、送达和失败统计链路。

群组营销不需要开启 `contacts`。

## 4. 好友营销需要对接的 Baileys 能力

### 4.1 首次联系人同步

开启“好友同步” `contacts` 后，资料同步任务创建的临时 Socket 使用：

```text
syncFullHistory: true
shouldSyncHistoryMessage: notification => 接受联系人所需的历史同步类型
```

Baileys 6.7.24 的 `shouldSyncHistoryMessage()` 决定是否处理整个历史同步通知，不是单独控制消息数组。返回 `false` 会连联系人一起跳过。因此好友同步开启时必须允许 Baileys 处理相应历史包。Parloq 收到 `messaging-history.set` 后分类使用其中的数据，但不保存 `chats` 列表和消息正文。首次混合数据来自：

```text
messaging-history.set: contacts + chats + messages
```

主系统保存的联系人字段：

| 数据 | Baileys `Contact` 字段 | 用途 |
| --- | --- | --- |
| 联系人主键 | `id` | 兼容 JID 或 LID 格式 |
| 电话 JID | `jid` | 存在时作为发送和号码提取依据 |
| LID | `lid` | 保存新格式匿名标识，避免只依赖手机号 JID |
| 通讯录名称 | `name` | 当前账号在 WhatsApp 中保存的联系人名称 |
| 对方显示名称 | `notify` | 对方设置的 WhatsApp 名称 |
| 认证名称 | `verifiedName` | 商业账号可能返回的认证名称 |
| 头像状态 | `imgUrl` | 只保存 Baileys 事件给出的状态，不批量下载联系人头像 |
| 资料状态 | `status` | Baileys 返回时保存，不作为必填条件 |

这不是完整手机通讯录。Baileys 会把历史会话对象、Push Name、商业认证名称和 App State 联系人动作混在联系人相关事件里。Parloq 必须按来源和字段分类：

- **已保存联系人**：存在 `Contact.name` 或来自 `contactAction`，计入好友；
- **聊天联系人**：存在一对一历史收发记录，即使没有保存过也计入好友；
- **聊天记录联系人**：存在至少一条一对一历史或实时消息，即使没有保存过也计入好友；
- **群组、广播和系统对象**：排除，不进入联系人资源。

业务上的“好友”是通讯录联系人和聊天记录联系人取并集并去重，群组、广播和系统对象除外。即使存在 `Contact.name`，也只能称为“Baileys 已同步的已保存联系人”，不能保证覆盖手机中的完整通讯录，也不能证明对方保存了本账号。

### 4.2 增量更新

账户在线期间监听：

- `contacts.upsert`：新增或完整更新联系人；
- `contacts.update`：联系人名称、JID、头像状态等部分字段变化；
- `chats.phoneNumberShare`：出现 LID 与手机号 JID 映射时补全联系人号码关系。

联系人删除在 Baileys 6.7.24 中没有与 `contacts.upsert/update` 对等的稳定删除事件，因此需要在下一次完整联系人同步时，把本次未出现的旧联系人标记为失效，而不是立即物理删除。

### 4.3 号码校验和发送

`onWhatsApp()` 可以判断号码当前是否注册 WhatsApp，但不应在首次同步时对全部联系人逐个查询。建议只在创建任务或发送前对缺少有效 JID、数据过期或状态不确定的目标分批校验。

好友营销最终使用：

```text
sendMessage(contactJid, content)
```

发送前至少检查：

1. 联系人属于当前用户可用的账户资源；
2. 联系人有可发送的 JID，或者号码通过 `onWhatsApp()` 校验；
3. 对同一任务内的重复号码去重；
4. 账户有效、允许营销且未处于发送冷却期；
5. 发送结果进入现有消息投递统计链路。

好友营销第一期不保存聊天列表、消息正文、联系人头像、商业资料或在线状态订阅。

## 5. Baileys 对接完成标准

新增菜单或数据库空表不代表功能完成。群组营销和好友营销必须打通下面的完整链路：

1. 协议节点开关进入配对任务快照和网关账户实际策略；
2. 网关通过 Baileys 执行首次资源查询或首次历史同步；
3. 网关在本次 Socket 生命周期内监听 Baileys 增量事件并归并资源；
4. 主系统 API 接收标准化资源并写入业务表；
5. 前端能查看资源数量、同步状态、更新时间和失败原因；
6. 营销任务从已同步资源中选择真实目标，并实际调用 Baileys 发送；
7. 发送、送达、失败和账户异常进入现有统计链路。

当前账户模型升级已接通群组与好友的真实资源链路：网关返回标准化清单，主系统分别写入 `account_whatsapp_groups` 和 `account_contacts`，账号列表展示聚合数量和评分，单账号详情页可以查看真实清单。群组营销与好友营销的任务编排、发送前刷新和长期增量刷新仍属于后续任务开发范围，不能因为已有资源表和页面就视为营销任务已经完成。

## 6. 账户类型和系统类型

Baileys 6.7.24 在配对成功时会把手机平台写入 `AuthenticationCreds.platform`，项目当前已经保存整份认证凭证，但还没有把该字段提取到账户业务资料中。第一期直接在 `creds.update` 后读取并归一化，不通过消息 ID 猜测设备。

| Baileys 原始平台 | 账户类型 | 系统类型 |
| --- | --- | --- |
| `smba` | 商业版 | Android |
| `smbi` | 商业版 | iOS |
| `android` 等已知 Android 标识 | 个人版 | Android |
| `iphone`、`ios` 等已知 iOS 标识 | 个人版 | iOS |
| 其他非空值 | 未知 | 其他 |
| 空值 | 未知 | 未知 |

Baileys 自带的 `isWABusinessPlatform(platform)` 明确把 `smba`、`smbi` 判断为 WhatsApp Business。为避免未来出现新平台值时误判，未知值不强行归为个人版。

对于旧会话包或外部接入模型缺少 `AuthenticationCreds.platform` 的情况，接入参数允许携带可选的 `platformRaw`、`accountType`、`deviceOs`。取值优先级为：Baileys 实际凭证 > 接入参数 > 未知；后续 Baileys 拿到真实平台时覆盖接入提示值。

## 7. 轻量数据模型

继续保留现有 `personal_accounts`，并保留 `has_avatar`、`group_count`、`friend_count` 等字段。产品、API 和前端删除“双向互动”概念；旧库中的 `mutual_contact_count` 暂时仅作为滚动升级兼容列保留，不再读取、写入或参与评分，待确认所有环境升级完成后再单独删列。主表只补充：

- `wa_platform_raw`：Baileys 原始平台值；
- `account_type`：`personal`、`business`、`unknown`；
- `device_os`：`android`、`ios`、`other`、`unknown`；
- `unique_group_member_count`：全部有效群排除本账号后，按身份归一并跨群去重的成员数，保留为资源统计参考，不参与当前评分。

`friend_count` 是有效的通讯录联系人与聊天记录联系人并集去重数，即 `is_saved_contact=true OR has_chat_history=true`。只有 `notify`（对方自己设置的显示名），但既没有保存联系人证据、也没有一对一消息记录的对象，不计入好友数。

只新增两张业务资源表：

### `account_whatsapp_groups`

- `account_id`
- `group_jid`
- `subject`
- `size`
- `announce`
- `restrict`
- `community_type`
- `own_role`
- `can_send`
- `active`
- `synced_at`

唯一约束为 `account_id + group_jid`。

### `account_contacts`

- `account_id`
- `contact_id`
- `jid`
- `lid`
- `phone_e164`
- `saved_name`
- `notify_name`
- `verified_name`
- `source_mask`：记录历史会话、Push Name、联系人动作等来源，可组合
- `is_saved_contact`
- `has_chat_history`
- `last_interaction_at`
- `active`
- `synced_at`

唯一约束优先使用 `account_id + contact_id`；同一账号内对已解析出的 `phone_e164` 再做去重。

历史同步和在线 `messages.upsert` 只更新联系人的来源分类、`has_chat_history` 和 `last_interaction_at`，处理完即丢弃聊天列表和消息正文。这样能得到好友明细，不需要新增聊天表或消息历史表。

Baileys 只能处理 WhatsApp 实际下发的历史包，不能保证每个旧账号第一次都拿到全部曾经联系过的对象；首次历史同步不完整时，好友数和总评分都要标记“待补全”，不能伪装成完整统计。

账户主表继续保存资源同步状态、同步时间和聚合数量，供列表和任务准入快速查询。暂不增加统一资源表、群成员表、聊天表、消息历史表或复杂的资源版本系统。

## 8. 账号管理的概览与详情位置

### 8.1 账号管理列表

现有账号管理列表继续作为概览入口，保留头像列，并调整为以下核心信息：

| 列 | 展示内容 |
| --- | --- |
| 账号 | 状态、号码、名称和账号 ID |
| 头像 | 现有头像展示 |
| 类型 / 系统 | 个人版或商业版；Android、iOS、其他或未知 |
| 资源概览 | 好友数、群组数 |
| 账户评分 | 总分；数据未同步完成时显示“待补全” |
| 分组 / 代理 / 操作 | 继续保留现有管理能力 |

数量旁边显示最后同步时间或“未知”，不能把未开启同步、同步失败的数据展示成 0。

### 8.2 单账号资源详情页

好友和群组可能有几百到几千条，不适合继续塞进当前账号详情抽屉。账号列表点击“详情”后进入完整页面：

```text
/resources/accounts/manage/:accountId
```

页面不新增侧边栏菜单，仍属于“账号管理”，包含四个页签：

1. **概览**：头像、账户类型、系统类型、同步开关、同步状态、资源数量和评分明细；
2. **好友**：展示通讯录联系人和聊天记录联系人，支持按来源、名称、号码搜索，并展示 JID/LID 和最后同步时间；
3. **群组**：展示群名、群 JID、人数、当前账号角色、是否可发送、群设置和同步时间；
4. **生命周期**：迁移现有详情抽屉中的状态变化记录。

第一期群组详情不展示或落库完整成员名单。群组同步只在内存中使用 `GroupMetadata.participants` 计算跨群去重成员数；只有以后明确需要按群成员筛选或营销时才新增群成员表。

## 9. 账户评分（按当前暂定规则）

评分与任务准入分开。账户有效、允许营销、资源已同步、未处于冷却期属于硬条件；评分只用于可用账户之间排序。

按当前讨论的加法规则计算，暂不封顶。头像不参与评分。好友数量仍按通讯录与聊天记录来源并集去重；评分对每个联系人只取较高的一档，不重复计分：

| 评分项 | 分数 | 数据来源 |
| --- | --- | --- |
| 聊天记录联系人 | 每个加 1 分 | `account_contacts.has_chat_history=true` 的有效联系人 |
| 仅保存联系人 | 每个加 0.5 分 | `is_saved_contact=true AND has_chat_history=false` 的有效联系人 |
| 管理员以上且可发送的群 | 群人数每人加 1 分 | 群 `size`，且 `own_role` 为 `admin`/`superadmin`、`can_send=true` |
| 普通成员且可发送的群 | 群人数每人加 0.5 分 | 群 `size`，且 `own_role=member`、`can_send=true` |
| 不可发送的群 | 0 分 | `can_send=false`，不论当前角色 |

公式为：

```text
账户评分 = 聊天记录联系人数量
         + 仅保存联系人数量 × 0.5
         + Σ(管理员或群主且可发送的群人数)
         + Σ(普通成员且可发送的群人数 × 0.5)
```

群组评分按群分别累计，直接使用 WhatsApp 返回的群总人数；不可发送的群统一计 0 分。跨群去重成员数继续保留为资源概览统计，但不参与评分。

后端直接从好友与群组资源表批量聚合并即时计算。列表和详情接口返回总分，以及仅保存联系人、聊天记录联系人、管理员群和成员群分项；不建立评分历史表，也不单独保存可即时计算出的总分。

只有好友和群组都同步成功后，评分才标记为完整。缺少任一数据时可以展示已知分项，但总分旁必须标记“待补全”，未知项不能按 0 分参与正式排序。

## 10. 同步时机

1. 账户配对或导入验证成功后，按配对任务快照执行首次同步。
2. `avatar`、`groupDetails` 和 `contacts` 默认开启；`groupDetails` 同步并落库群详情，同时计算 `groupCount` 和 `uniqueGroupMemberCount`，并在显式资料任务中复用一次历史摘要补充群组最近联系时间。
3. “好友同步” `contacts` 只在显式资料同步任务创建 Socket 时临时启用历史同步配置，接收历史资源包并分类落库联系人；对已经在线的账户执行资料同步时，受控重建一次 Socket，日常发信连接不请求完整历史。
4. `contacts` 只聚合历史包中的联系人来源和最后联系时间，在线期间通过联系人和消息事件继续更新。
5. 在线期间通过群组和联系人事件增量更新。
6. 创建营销任务时检查对应资源同步状态；数据过期则先刷新，刷新成功后再启动任务。
7. 手动“同步资料”按账户当前实际策略刷新，不影响 `closeOnline` 的现有行为。

需要注意：`syncFullHistory` 和 `shouldSyncHistoryMessage` 在 Socket 创建时生效。对已在线账户打开“好友同步” `contacts` 后，不能只改数据库开关，必须由网关执行一次受控重连，并允许处理好友所需的历史同步类型。无论如何配置，第一期主系统都不保存聊天列表和消息正文。

## 11. 实施顺序

1. 删除冗余的 `groupSummary`，将原开关值迁移到“群组同步” `groupDetails`；群组数量改为由群组同步结果直接聚合。
2. 删除 `chats`、`messageHistory` 及配套代码，删除“双向互动”的产品/API/前端语义；旧 `mutual_contact_count` 暂留为不使用的滚动兼容列；保留现有 `contacts` 字段并将产品名称改为“好友同步”，历史同步改为网关内部实现。
3. 完成群详情落库、群成员跨群去重聚合、群组增量事件接入和账号详情“群组”页签。
4. 开发群组营销任务。
5. 完成好友明细落库、联系人增量事件接入和账号详情“好友”页签。
6. 接入历史/实时消息中的一对一联系对象识别，完成好友数量和当前暂定评分。
7. 开发好友营销任务。

超链营销继续使用现有任务、数据包和账号调度逻辑，不参与本轮重构。
