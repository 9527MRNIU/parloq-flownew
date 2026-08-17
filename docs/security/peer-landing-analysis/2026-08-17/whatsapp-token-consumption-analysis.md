# WhatsApp 设备恢复令牌消费场景验证报告（2026-08-17）

> 本文回答一个问题：同行攻击链偷走的 WhatsApp 令牌（iOS `rc1.dat` 的
> `recoveryTokenData` / `cck.dat`）到底用在哪里。方法：在用户自己的
> 已 root Pixel 4（Magisk）上对 WhatsApp 2.26.31.77（个人版
> `com.whatsapp` + 商务版 `com.whatsapp.w4b`）做**只读**取证 +
> APK 静态反编译，全程未执行 App 内任何注册/迁移操作，未触发任何网络请求。
>
> 反编译产物在仓库内 `.wa-re/jadx-out/`（git 已忽略，仅本地留存）。

## 一、结论

令牌（rc 文件家族）的消费点在客户端代码中**只有两处已坐实**：

1. **注册/验证请求**：令牌解密后随注册请求发往 WhatsApp 注册服务器
   `v.whatsapp.net`（`sendClientFunnelLog`），证明"此设备是该账号的
   注册设备"。
2. **个人版↔商务版直接迁移（direct migration）**：两个 App 之间用广播
   交接令牌，接收方写入 `rc2`，再通过 GraphQL
   `RegAccountTransferVerifyTokenMutation` 交给服务端校验，官方字符串
   `did_successfully_skip_sms_verification` 表明通过后**跳过短信验证**。

令牌的性质：**注册验证体系的设备侧常备凭证**，不是 Web 会话密钥、不是
聊天 E2E 密钥、不是 passkey。

## 二、令牌全景（设备实证）

### 2.1 文件与存储

| 存储位置 | 内容 | 证据 |
| --- | --- | --- |
| `files/rc2`（两个 App 都有） | 加密的恢复令牌 | 个人版与商务版各 69 字节，内容不同 |
| `files/backup_token` / `backup_token_v2` | 加密的备份/迁移令牌 | BackupTokenUtils 写入 |
| prefs `token_used_for_migration` / `_proto` | 迁移令牌（prefs 形态） | reg_prefs.xml 键名 |
| prefs `token_used_during_reg` | 注册期间令牌键 | reg_prefs.xml 键名 |
| prefs `reg_passkey_*` | Passkey（**另一套机制**，与 rc 家族无关） | reg_prefs.xml 键名 |

### 2.2 rc2 的加密结构（`X/C00L.java`，classes.dex）

- 外层：Java 对象序列化（魔数 `AC ED 00 05`，`[B` byte[] 描述符），
  序列化内容恰为 42 字节；
- 内层格式：`2 字节头 + 4 字节盐 + 16 字节 IV + AES/OFB/NoPadding 密文`；
- 密钥派生：PBKDF（常量前缀 `AbstractC10780eE.A0a` + **账号串**，即
  cc+号码的哈希）——**这就是同行 iOS 攻击链"手机号 + token 成对偷"
  的原因：解密令牌必须拿到账号串**；
- 读取失败日志原文：`recovery token header mismatch` ——
  WhatsApp 自己的日志就叫它 recovery token；
- 读写函数：`C00L.A0I`（读+解密）、`C00L.A09`（加密+写）、
  `C00L.A0G`（生成新令牌）。

## 三、消费点 1：注册/验证请求 → v.whatsapp.net

`X/IWc.java`（RegistrationHttpManager）方法 `A0p`
（日志名 `RegistrationHttpManager/sendClientFunnelLog`）：

```java
byte[] r4 = r1.A0w(r13, r14);   // A0w: 读 rc2 → 解密令牌；无则生成并写入
...
X.GLA.A1E(r2, r4);              // 令牌放入请求参数 map
```

参数键常量 `AbstractC10820eE.A0b` 为 XOR(18) 混淆字符串，解码：

```
zffba(==d<ezsfasbb<|wf  →  https://v.whatsapp.net
```

即令牌随注册漏斗日志请求发给 WhatsApp 注册服务器。另在 `A0P`
（设备信息上报）中携带 `hasinrc` 标志（rc2 是否存在）。

## 四、消费点 2：个人版↔商务版直接迁移（免短信验证）

全链路（dex 反编译坐实）：

```
个人版 App（提供方）
  └─ 广播 action：com.whatsapp.registration.directmigration.recoveryTokenAction
       resultExtras：
         key_recovery_token   ← 恢复令牌
         key_backup_token     ← 备份令牌
          │
          ▼
商务版 App（请求方）ProcessProviderMigrationInfo 接收
  X/C3925Iiy.java（dex9）/ X/C41380Iiy.java（全量）
  ├─ 日志：ProcessProviderMigrationInfo/received-token
  ├─ C00L.A09(context, 账号串, byteArray) → 写回 rc2
  └─ BackupTokenUtils（X/IWG.java）保存 backup_token / token_used_for_migration
          │
          ▼
AccountTransferManager.A02
  └─ GraphQL：RegAccountTransferVerifyTokenMutation
       输入字段："token"
       客户端标识："whatsapp-android-mex"
          │
          ▼
服务端验证通过 → did_successfully_skip_sms_verification
```

相关类：`MigrationStartTransferActivity`、`MigrationProviderOrderedBroadcastReceiver`、
`MigrationRequesterBroadcastReceiver`、`initialMigrationInfoAction`、
`setMigrationStateOnProviderSide`（均在
`com.whatsapp.registration.directmigration` / `app.directmigration` 包）。

## 五、生成点

- `X/RunnableC42230JEq.java` default 分支：注册流程中
  `C00L.A09(ctx, 账号串, C00L.A0G())` —— 生成新令牌写 rc2；
- `IWc.A0w`：注册 HTTP 需要令牌时，rc2 缺失则现场生成补写。

## 六、明确排除（撤回过的推断）

| 说法 | 处置 |
| --- | --- |
| silent_auth / SIMPLE_RECOVERY 消费该令牌 | **撤回**。`X/C9M3.java` 只是"指标 ID→字符串"映射表；silent auth 资格检查走 SIM/运营商 SDK（`isDeviceEligibleForSilentAuth2/failed sim check`），未找到读 rc2 的代码 |
| 是 Web 会话密钥 / Baileys 凭据 | 排除。Web companion 凭据是另一层（`companion_devices.db`、Signal 身份密钥） |
| 是聊天 E2E 密钥 | 排除。未触碰 `msgstore`/`axolotl`/Signal 密钥 |
| 是 passkey | 排除。passkey 在 Keystore/iCloud Keychain，另有 `reg_passkey_*` 键 |
| 可直接接入 Baileys | 排除。Baileys 无"恢复令牌注册"入口；令牌属于注册/验证层上游 |

## 七、与同行攻击链的对应

- iOS 侧：`rc1.dat`（field 2 = `recoveryTokenData`）、`cck.dat`
  （AppGroup 32B）、`OwnJabberID`（shared plist）；
- Android 侧：`rc2`（files/，42 字节 payload 以 `00 02` field-2 标记开头，
  与 iOS 同族）、`backup_token`、JID；
- 成对偷号码的原因坐实：rc2 解密密钥由"常量 + 账号串"派生，单独令牌
  无法使用；
- 攻击者拿到"手机号 + 令牌"后，可复刻消费点 1/2 的客户端请求
  （注册验证 / 迁移验证），向 WhatsApp 服务器自证设备归属。服务端
  接受之后的后续行为超出客户端可验证范围。

## 八、代码引用索引

| 主题 | 位置 |
| --- | --- |
| rc2 读写/加密/生成 | `X/C00L.java`（A09 写、A0I 读、A0G 生成、A0K 密钥派生） |
| rc2 存在检查与删除 | `X/GL9.java`（A1T/A1F）、`X/JGO.java:154` |
| 注册请求消费令牌 | `X/IWc.java`（A0p:820 调 A0w、A0w:1286、A0P:1134 hasinrc） |
| 迁移广播接收 | `X/C3925Iiy.java`（dex9）/ `X/C41380Iiy.java`（全量） |
| 令牌保存 | `X/IWG.java`（BackupTokenUtils，token_used_for_migration 等） |
| 迁移验证 GraphQL | `com/whatsapp/registration/ui/AccountTransferManager.java:123` |
| 键常量解码 | `X/AbstractC10820eE.java:49`（`A0b` → `https://v.whatsapp.net`） |
| 撤销依据 | `X/C9M3.java`（纯指标名映射，无令牌消费） |

反编译产物：`.wa-re/jadx-out/`（dex1、dex9、full 共 57812 类，git 忽略）。
取证过程记录：`.wa-re/README.md`。

## 九、未决事项

1. 服务端对"注册验证/迁移验证"请求的附加风控（设备信誉、恢复频控）
   不可见——令牌能复刻客户端请求，但服务端接受程度无法静态验证；
2. iOS 侧 `rc1.dat`/`cck.dat` 与 Android `rc2` 的字段级等价性，需要
   iOS 二进制才能闭环（当前只有结构同族证据）。
