# 推广运行时集成规范 v1

本规范定义推广模板之外的平台统一注入能力。模板包保持自包含，外部
JavaScript 和 iframe 由“集成管理”登记源域名、资源路径和版本，再按模板绑定。

## 1. 集成来源

- 每个集成必须绑定域名管理中已经完成注册、DNS、SSL 和托管验证的域名。
- 集成只保存源域名引用和站内绝对资源路径，不保存可绕过域名绑定的完整 URL。
- 最终资源地址固定使用 `https://源域名/资源路径`。
- 源域名或集成被停用后，所有模板立即停止注入该集成。

## 2. 支持类型

第一版支持：

- `script`：外部 JavaScript，使用 `defer` 加载；可选配置 SRI 完整性校验。
- `iframe`：静态内联 iframe，由平台挂载到模板 `body` 末尾。

## 3. iframe 输出

iframe 不由 JavaScript 动态创建，不添加 `id` 或 `class`。平台在业务挂载点之后、
`</body>` 之前输出：

```html
<iframe
  src="https://integration.example.com/runtime/frame"
  style="
    position: fixed;
    top: 0;
    left: -1000px;
    width: 0;
    height: 0;
    border: 0;
  "
></iframe>
```

隐藏方式固定为移出视口、零尺寸和无边框，不使用 `display: none`，保证浏览器加载
iframe 内容。

## 4. 注入与 CSP

- 平台先注入外部 JavaScript，再注入 iframe，iframe 保持在 `body` 末尾。
- 后台预览、公开渠道页和裂变页使用同一份模板集成绑定。
- CSP 根据当前模板实际生效的集成动态增加 `script-src`、`frame-src` 和
  `connect-src` 源域名。
- 公开渠道仅在存在生效集成时为 CSP sandbox 增加 `allow-same-origin`，使 iframe
  和外部脚本可以使用各自来源的 Worker 与 storage；后台预览仍保持不透明来源隔离。
- 未绑定 iframe 的模板继续使用 `frame-src 'none'`。
- 模板 HTML 中自行携带的外部脚本或 iframe 不属于平台集成，不应被放行。

## 5. 生效条件

一个集成只有同时满足以下条件才会注入：

1. 集成已启用且未归档；
2. 模板绑定已启用；
3. 源域名已启用且注册、DNS、SSL、托管状态全部有效。

模板替换版本时保留当前集成绑定；导入和替换抽屉可以同步调整绑定。集成管理中的
全局停用是即时停止分发的总开关。
