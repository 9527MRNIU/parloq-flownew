## ZIP 目录

模板包必须是自包含静态站点，ZIP 根目录至少包含：

```text
template.zip
├── index.html
├── manifest.json
├── assets/
│   ├── app.css
│   └── brand.webp
└── locales/
    ├── en.json
    └── zh-CN.json
```

所有资源使用相对路径。包内只能有一个 `index.html`，不能包含符号链接、不安全的 `..` 路径、Source Map 或外部脚本依赖。

## 文件限制

| 项目 | 限制 |
| --- | ---: |
| ZIP 大小 | 20 MB |
| 解压总大小 | 50 MB |
| 文件数量 | 500 |
| 单文件大小 | 5 MB |

## manifest v2

```json
{
  "schema": "promotion-template/v2",
  "version": "2.0.0",
  "entry": "index.html",
  "format": "static-bundle",
  "capabilities": ["phone-pairing"],
  "runtime": "promotion-browser-bridge/v2",
  "requirements": {
    "pairingContract": "promotion-public-pairing/v1",
    "componentKit": "account-link-elements/v1"
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
- `format` 可使用 `static-bundle` 或 `vite-dist`；
- `version` 为 1–40 字符的模板业务版本；
- `supportedLocales` 至少一个、最多 128 个，且必须包含可用的默认语言；
- locale 使用 `en`、`zh-CN`、`pt-BR` 这类语言标签；
- `i18n.path` 必须是安全相对路径，不能以 `/` 开头或包含上级目录跳转；
- `fallbackLocale` 应存在于模板可提供的语言资源中。

## 打包注意事项

不要把项目源代码目录直接压缩。应先执行生产构建，再把构建产物中的文件放到 ZIP 根目录。导入系统前解压检查一次，确保 `index.html` 不是多套了一层目录。

