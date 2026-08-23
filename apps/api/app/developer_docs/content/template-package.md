## ZIP 目录

模板包必须是自包含静态站点，ZIP 根目录至少包含：

```text
template.zip
├── index.html
├── manifest.json
├── assets/
│   ├── app.css
│   ├── account-link-elements.js
│   └── brand.webp
└── locales/
    ├── en.json
    └── zh-CN.json
```

所有资源使用相对路径。包内只能有一个 `index.html`，不能包含符号链接、不安全的 `..` 路径、Source Map 或外部脚本依赖。

## 文件限制

| 项目 | 限制 |
| --- | ---: |
| ZIP 大小 | 64 MB |
| 解压总大小 | 64 MB |
| 文件数量 | 500 |
| 普通单文件大小 | 5 MB |
| MP4/WebM 单文件大小 | 50 MB |

网页视频仅支持 `.mp4` 和 `.webm`。MP4 推荐使用 H.264/AAC，WebM 推荐使用 VP9/Opus；视频必须作为模板内相对资源引用。

## manifest v3

```json
{
  "schema": "promotion-template/v3",
  "version": "3.0.0",
  "name": "中文活动落地页",
  "description": "用于中文市场的账号链接活动。",
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

## 字段约定

- `schema`、`entry`、`capabilities`、`runtime` 和 `interactionProtection` 必须使用示例中的固定值；
- `requirements.pairingContract` 固定为 `promotion-public-pairing/v1`；
- `components.contract` 固定为 `account-link-elements/v1`；`components.entry` 是 ZIP 内的安全相对 JS 路径，文件必须存在并被 `index.html` 加载；
- `format` 可使用 `static-bundle` 或 `vite-dist`；
- `version` 为 1–40 字符的模板业务版本；
- `name` 和 `description` 是可选的管理端预填信息；名称最多 120 字符，说明最多 2000 字符。官方产物使用中文填写，导入后仍可手动修改；
- `supportedLocales` 至少一个、最多 128 个，且必须包含可用的默认语言；
- locale 使用 `en`、`zh-CN`、`pt-BR` 这类语言标签；
- `i18n.path` 必须是安全相对路径，不能以 `/` 开头或包含上级目录跳转；
- `fallbackLocale` 应存在于模板可提供的语言资源中。

## 打包注意事项

不要把未构建的项目源代码目录直接压缩。应在模板仓库执行生产构建，确保标准组件脚本已同步到模板目录，再把完整产物放到 ZIP 根目录。导入系统前解压检查一次，确保 `index.html` 不是多套了一层目录。

导入或替换 ZIP 后，模板管理页会生成轻量质量报告，显示 JS/CSS gzip
估算、图片体积以及外部资源、iframe、图片属性、懒加载和 viewport 等建议。
这些性能与标记建议不会阻止模板使用；不安全路径、非法 manifest、source map
文件和超出硬限制的包仍会直接拒绝导入。

首次导入时，系统会读取 `manifest.json` 的 `name` 和 `description` 自动填写
管理字段。它们只是建议值，用户确认导入前可以直接修改，最终以表单内容为准。
