## 组件集合

新视觉主题应声明 `account-link-elements/v1`，在 ZIP 内携带它的编译脚本，并组合这些 Web Components：

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

组件源码统一在独立模板仓库维护，构建时复制到每个 v3 模板 ZIP。系统只注入 `window.PromotionBridge`，不会注入或替换组件脚本。主题通过 CSS 变量和公开的 `::part()` 调整外观；需要修改组件行为时，应修改模板仓库共享源码并重新构建各模板。

## 手机号输入

手机号组件根据浏览器本地化给出初始国家，同时始终允许用户手动覆盖。渠道的目标国家不是手机号国家码来源。用户可见号码只显示数字，不带前导 `+`。

## 应用启动与手工引导

应用启动按钮只能在用户点击后尝试打开 WhatsApp 或 WhatsApp Business。浏览器无法保证一定拉起应用，因此模板必须保留清晰的手工绑定步骤作为后备路径。

## 多语言

生产平台会依次按浏览器 `Accept-Language`、渠道国家和 `defaultLocale` 自动解析语言，并在返回 HTML 前注入 `resolvedLocale` 与首屏文案。白标模板不应重复显示语言切换器。模板仓库预览工具可以手动选择语言，用于检查各语言和 RTL 效果。

标准组件文案内置支持 `en`、`zh-CN`、`hi`、`id`、`pt-BR`、`es`、`ru`、`ur`、`de`、`tr`、`ar`、`fa`、`bn`、`it` 和 `fr`。模板自己的营销文案仍需在每个声明语言中完整提供。

## RTL 与无障碍

- 阿拉伯语、波斯语和乌尔都语页面应正确使用 RTL 布局；
- 输入、按钮、可选语言切换和错误提示必须可用键盘操作；
- 文本与背景保持可读对比度；
- 状态变化同时提供文字，不只依赖颜色；
- 手工步骤图标可以换主题，但不能删除必要的替代说明。
