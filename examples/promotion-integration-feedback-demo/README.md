# iframe 独立回传测试集成

该示例用于验证 iframe 不依赖主模板的完整链路：获取运行上下文、自动上报
`page_view` 和 `ready`，以及通过按钮上报 `completed`、`failed`。

在仓库根目录执行以下命令生成可导入资源包：

```bash
cd examples/promotion-integration-feedback-demo
zip -r ../promotion-integration-feedback-demo.zip integration.json index.html assets scripts
```

本地测试源域名使用 `integration-feedback.localhost`。导入后需要绑定到一个模板和
启用渠道，普通模板预览不会签发 iframe 运行令牌。
