# Promotion template specification v3

状态：当前系统唯一支持的推广模板格式（`promotion-template/v3`）。

机器可读 Schema：[`schemas/promotion-template-v3.schema.json`](schemas/promotion-template-v3.schema.json)。

## 责任边界

v3 ZIP 负责完整的访问者前端，包括 HTML、CSS、本地媒体、多语言资源和已编译的账号关联组件。平台继续负责渠道识别、鉴权、配对、路由、统计持久化、账号存储、沙箱和 CSP。

模板 JavaScript 只能调用平台注入的 `window.PromotionBridge`，不得携带 API 路径、访问令牌、网关地址、协议 ID、外部脚本或管理系统品牌。

## Manifest

```json
{
  "schema": "promotion-template/v3",
  "version": "1.0.0",
  "name": "标准账号关联模板",
  "description": "自带前端组件并通过平台安全桥接完成账号关联。",
  "entry": "index.html",
  "format": "static-bundle",
  "capabilities": ["phone-pairing"],
  "runtime": "promotion-browser-bridge/v2",
  "requirements": {
    "pairingContract": "promotion-public-pairing/v1"
  },
  "components": {
    "contract": "account-link-elements/v1",
    "entry": "assets/account-link-elements.js"
  },
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

`components.entry` 必须是安全相对 JavaScript 路径，对应文件必须存在于 ZIP 中，并由 `index.html` 明确加载。系统不会下载、替换或注入另一份组件实现。

## 组件组合

```html
<account-link-flow>
  <phone-number-field></phone-number-field>
  <account-link-submit></account-link-submit>
  <pairing-code-panel></pairing-code-panel>
  <app-launch-actions></app-launch-actions>
  <account-link-status></account-link-status>
  <account-initialization-status></account-initialization-status>
</account-link-flow>
```

组件负责国家搜索、国旗、号码格式化、无障碍控件和配对状态展示。生产平台依次按浏览器 `Accept-Language`、渠道国家和 `defaultLocale` 自动解析语言；白标模板不重复显示语言选择。模板仓库预览工具可以手动选择语言，仅用于检查各语言效果。组件不接收密钥，只通过 `PromotionBridge` 的 `submitPhone`、`getPairingStatus` 和 `cancelPairing` 方法访问平台能力。

## 打包与安全

- ZIP 包含唯一 `index.html`、`manifest.json`、声明的组件入口和所有相对资源；
- ZIP 最大 20 MB，解压后最大 50 MB，最多 500 个文件，单文件最大 5 MB；
- 禁止 Source Map、源码文件、外部资源、直接 API 路径、凭据和平台标识；
- 用户可见号码不显示前导加号；
- 15 个基础语言必须完整，阿拉伯语、波斯语和乌尔都语保持 RTL。

平台导入、存储并原样提供模板组件，只注入运行配置、`PromotionBridge`、统计和交互保护。
