# 同行落地页安全分析与取证档案（2026-08-17）

> [!CAUTION]
> `evidence/` 包含恶意漏洞利用与凭证窃取代码，仅供静态分析和证据留存。
> 严禁执行、导入、构建、在浏览器中打开、部署或通过 Web 服务公开这些样本。

本目录汇总 2026-08-17 对五个同行落地页的技术分析、攻击链报告与原始取证材料。
分析过程中未执行对方脚本。

## 文档导航

- [技术对比摘要](./technical-review.md)
- [详细技术评审](./technical-review-detailed.md)
- [攻击链详细报告](./attack-chain-report.md)
- [WhatsApp 设备恢复令牌消费场景验证](./whatsapp-token-consumption-analysis.md)
- [隐藏 iframe 技术形态总结](./hidden-iframe-pattern-summary.md)

## 目录结构

```text
2026-08-17/
├── README.md
├── technical-review.md
├── technical-review-detailed.md
├── attack-chain-report.md
└── evidence/
    ├── SHA256SUMS.txt
    ├── chain/
    └── pages/
```

## 取证样本

### `evidence/chain/`：C2 攻击链

来源域为 `v1.io92jujjs33.com`。目录包含入口路由、分阶段利用代码、加密载荷及
静态解密产物，覆盖 JavaScriptCore 利用、沙箱逃逸、提权衔接和最终数据提取阶段。

主要文件：

| 文件 | 作用 |
| --- | --- |
| `router.js` | iOS 版本门控与入口分流 |
| `ds_rce_loader.js` | 攻击阶段编排与 Worker 消息协议 |
| `ds_rce_module.js`、`ds_rce_worker.js` | JavaScriptCore 利用与原生调用衔接 |
| `ds_sbx0.js`、`ds_sbx1.js` | 沙箱逃逸与提权衔接 |
| `ds_pe.js` | 权限、文件和最终载荷处理 |
| `extract.js.enc` | AES-256-ECB 加密的最终载荷 |
| `extract_decrypted.js` | 仅供静态审阅的解密产物 |

### `evidence/pages/`：落地页与前端 bundle

- `site1_myloveday.html` 与 `site1_inline_0..5.js`：静态页面及内联脚本。
- `site2_c.html`、`site3_d.html`、`site4_a.html`、`site5_b.html`：四个落地页入口。
- `a_js.js`、`b_js.js`、`c_js.js`、`d_js.js`：对应的混淆前端 bundle。
- `iframe.html`：隐藏 iframe 外壳。

## 完整性校验

`evidence/SHA256SUMS.txt` 记录全部样本哈希。只做哈希校验时，可在仓库根目录运行：

```bash
cd docs/security/peer-landing-analysis/2026-08-17/evidence
shasum -a 256 -c SHA256SUMS.txt
```

该命令只读取并计算文件哈希，不会执行样本。

## 解密记录

- 密文：`evidence/chain/extract.js.enc`
- 算法：AES-256-ECB，PKCS7
- 密钥来源：`evidence/chain/ds_pe.js` 中的 `DARKSWORD_PAYLOAD_KEY`
- 解密结果：`evidence/chain/extract_decrypted.js`

## 安全处置

1. 移交安全团队或执法机构时，保留整个目录及 `evidence/SHA256SUMS.txt`。
2. 复核时仅使用隔离环境进行静态分析，不要 `eval`、导入或加载任何样本。
3. 报告中的域名状态仅代表取证时观察结果，不代表当前状态。
