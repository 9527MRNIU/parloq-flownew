# 推广运行时集成规范 v1

本规范定义推广模板之外、由平台统一托管和注入的 JavaScript 与 iframe
资源。模板继续保持自包含；运行时集成可以从 GitHub 私人仓库直接添加，也可以
使用 ZIP 离线导入。添加时绑定已验证源域名，再按模板启用。

## 0. GitHub 仓库导入

系统配置保存 GitHub Fine-grained Token、私人仓库、分支和
`artifacts/catalog.json` 路径。集成管理切换到“远程仓库”后，系统按照目录清单
读取每个项目的 `source` 源码目录和 `integration.json`，不依赖 `dist/*.zip` 或
GitHub Release。

首次添加远程集成时选择源域名和启用状态；后续更新保留本地名称、说明、源域名、
启用状态、模板绑定和回传记录。同一版本的仓库内容发生变化时拒绝覆盖，必须先更新
`integration.json` 的 `version`。ZIP 入口继续用于离线文件和第三方交付。

## 1. ZIP 文件结构

平台不要求固定目录名，允许文件位于 ZIP 根目录、任意子目录，或统一包在一层
外部目录中。系统会忽略 macOS 生成的 `__MACOSX` 和 `.DS_Store`。

没有 `integration.json` 时自动识别：

- 找到唯一 `index.html`，或 ZIP 中只有一个 HTML 文件：识别为 iframe 集成；
- 没有 HTML、但存在一个或多个 `.js` / `.mjs`：识别为 script 集成，所有脚本
  按规范化路径稳定排序后依次注入；
- iframe 包可包含任意数量的 JavaScript、CSS、图片和字体，由 HTML 使用相对路径
  引用，不会被额外注入到父页面；
- 多个 HTML 无法确定入口时拒绝导入，并提示使用可选清单指定入口。

单个或多个纯 JavaScript 文件都可以直接压缩为 ZIP 导入，不需要为了满足格式
额外创建 HTML 或清单。

## 2. 可选 integration.json

仅在需要明确类型、版本、iframe 运行方式、HTML 入口或脚本加载顺序时提供清单。清单可使用单个
`entry`，也可使用有序的 `entries`：

```json
{
  "schemaVersion": 1,
  "type": "script",
  "version": "2.0.0",
  "integrationKey": "visitor-link-v1",
  "name": "统一访客关联",
  "description": "为推广模板提供统一的访客关联能力。",
  "entries": [
    "scripts/bootstrap.js",
    { "path": "scripts/runtime.mjs", "scriptType": "module" }
  ]
}
```

- `type` 支持 `script` 和 `iframe`；
- `integrationKey`、`name` 和 `description` 可用于自动填写导入表单，导入前仍可手动修改；机器标识使用小写字母、数字、点、下划线和连字符，名称与说明使用中文；
- `integrationKey` 最多 80 字符，`name` 最多 120 字符，`description` 最多 2000 字符；
- script 支持多个 `.js` / `.mjs` 入口，数组顺序就是注入顺序；
- `scriptType` 支持 `classic` 和 `module`，省略时 `.mjs` 自动识别为 module；
- iframe 可以指定一个 `.html` / `.htm` 入口，也可以指定一个或多个纯 `.js` /
  `.mjs` 入口，但两类入口不能混用；
- 纯 JavaScript iframe 不需要 `index.html`。平台会生成同源 HTML 壳，先注入
  `PromotionIntegrationBridge` runtime，再按 `entries` 顺序加载 classic/module 脚本；
- `version` 可省略，平台会使用 ZIP 的 SHA-256 摘要生成稳定版本。

纯 JavaScript iframe 清单示例：

```json
{
  "schemaVersion": 1,
  "type": "iframe",
  "version": "1.0.0",
  "entries": [
    "ds_net.js",
    { "path": "ds_net_native.mjs", "scriptType": "module" }
  ],
  "feedback": {
    "enabled": true,
    "events": ["ip_sync", "device_activate"]
  }
}
```

没有清单的纯 JavaScript 包仍自动识别为 `script`；需要 iframe 隔离运行时，必须在
清单中显式设置 `"type": "iframe"`。

需要向平台回传数据的 iframe 可增加可选 `feedback`。普通 iframe 不声明此项，
加载行为与之前完全相同：

```json
{
  "schemaVersion": 1,
  "type": "iframe",
  "version": "1.0.0",
  "entry": "index.html",
  "feedback": {
    "enabled": true,
    "events": ["ready", "completed", "failed"]
  }
}
```

- 平台固定提供 `page_view` 和 `visit_end`，无需重复声明；
- 自定义事件名称使用小写字母、数字、点、下划线或连字符，最多 32 个；
- 数据回传当前只用于 iframe。script 集成仍按原方式注入，不获得独立运行会话。

## 3. 托管和资源地址

- 每个集成必须选择已经完成注册、DNS、SSL 和托管验证的源域名；
- 本地 Compose 使用 `http://*.localhost:5173` 验证完整链路；生产环境固定使用源域名的 HTTPS 入口；
- ZIP 解压后的文件存入平台资源表，不需要人工部署目录或填写资源路径；
- 平台按集成 ID、版本和包内路径生成不可变资源地址：

```text
https://源域名/api/public/promotion/integrations/{集成ID}/{版本}/{包内路径}
```

纯 JavaScript iframe 的管理端 `entryPaths` 仍显示真实脚本入口；`sourceUrls` 只返回
平台生成的 `__parloq_iframe__.html` 虚拟入口。虚拟入口不会写入资源表，也不能由集成包占用。

- 资源只允许从所选源域名读取，使用错误 Host、旧版本、已停用集成或不可用域名
  时返回 404；
- 版本 URL 使用一年不可变缓存。上传新版本时先完整校验 ZIP，再在一个数据库事务
  中替换资源，失败不会影响当前版本；
- 手工设置 `version` 时，不同内容不能复用当前版本号，避免不可变缓存继续命中旧文件；
- script 入口由平台逐个计算 SHA-384 SRI，管理端不需要手工填写完整性摘要。

## 4. 包限制

- ZIP 最大 20 MB；
- 解压后总量最大 50 MB；
- 最多 500 个文件；
- 单文件最大 5 MB；
- 禁止绝对路径、`..` 路径穿越、符号链接、重复路径和未允许的文件扩展名。

## 5. 注入与 CSP

- 平台先按集成及入口顺序注入全部 script，再注入 iframe；
- classic script 使用 `defer` 并保持声明顺序，module 入口使用 `type="module"`；
- 纯 JavaScript iframe 在父页面只注入一次；业务脚本在平台生成的同源 iframe 壳内
  按清单顺序加载；
- iframe 仍以静态标签挂载在模板 `body` 末尾，使用移出视口、零尺寸和无边框的
  隐藏方式；
- 后台预览、公开渠道页和裂变页使用同一份模板集成绑定；
- CSP 根据实际生效的集成源域名动态增加 `script-src`、`frame-src` 和
  `connect-src`；
- 模板 HTML 自行携带的外部脚本或 iframe 不属于平台集成，不会被额外放行。

## 6. 生效条件

一个集成只有同时满足以下条件才会注入：

1. 集成已启用且未归档；
2. 模板绑定已启用；
3. 源域名已启用且注册、DNS、SSL、托管状态全部有效；
4. 当前资源包存在至少一个有效入口。

模板替换版本时保留当前集成绑定。集成管理中的全局停用是即时停止分发的总开关。

## 7. iframe 独立运行与回传

启用 `feedback` 后，iframe 仍是绑定源域名的独立页面，不读取主模板，也不通过
`postMessage` 或主模板转发数据：

1. 平台给 iframe URL 附加一个 30 分钟有效、绑定集成版本、模板和渠道的短期令牌；
2. iframe 在自己的域名下使用令牌获取渠道、版本、可用事件和指纹策略；
3. iframe 独立生成访客 ID、采集设备指纹，并直接向同域平台接口回传；
4. 平台按集成、渠道和幂等键持久化原始事件，管理端“集成管理”可查看事件统计和明细。

平台会自动上报 iframe 的 `page_view` 和 `visit_end`。包内脚本可调用：

```js
await window.PromotionIntegrationBridge.ready();
await window.PromotionIntegrationBridge.report("completed", {
  result: "ok"
});
```

只有 `feedback.events` 已声明的自定义事件可以写入。元数据必须是普通 JSON 对象，
单次最大 1 MiB；令牌过期、集成停用、模板解绑或源域名失效后会立即拒绝上报。

iframe 回传使用“模板策略”中的公开数据回传限速。平台分别按 iframe 集成、渠道、
会话和来源 IP 计数，不与主模板事件或协议配对接口共用额度。超过额度时接口返回
`429`、稳定错误码 `report_rate_limited` 和 `Retry-After`，集成脚本应停止本轮重试，
等待指定秒数后再发送。Redis 限速服务暂时不可用时平台按可用性优先继续接收事件，
并在服务端记录告警。
