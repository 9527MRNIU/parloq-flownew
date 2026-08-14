export type TemplateDesignSection = {
  title: string;
  description?: string;
  bullets: string[];
  code?: string;
  checklist?: boolean;
};

export const TEMPLATE_FILE_TREE = `index.html
manifest.json
assets/
  app.css
  app.js
  images/...
  fonts/...
locales/
  en.json
  zh-CN.json
  ...`;

export const TEMPLATE_MANIFEST_EXAMPLE = `{
  "schema": "parloq-promotion-template/v1",
  "version": "1.0.0",
  "entry": "index.html",
  "format": "static-bundle",
  "capabilities": ["phone-pairing"],
  "runtime": "parloq-browser-bridge/v1",
  "interactionProtection": "platform",
  "defaultLocale": "en",
  "supportedLocales": ["en", "zh-CN"],
  "i18n": {
    "mode": "bundled",
    "path": "locales/{locale}.json",
    "fallbackLocale": "en"
  }
}`;

export const TEMPLATE_RUNTIME_EXAMPLE = `const response = await window.parloqSubmitPhone(phone, {
  template: "template-name",
  locale: resolvedLocale
});
const payload = await response.json();
const pairing = payload?.data?.pairing;

// 展示 pairing.pairingCode，并使用平台返回的
// pairing.statusUrl + pairing.statusToken 轮询状态。
// 只有 pairingStatus === "verified" 且 verified === true
// 才能显示成功；不得根据 accountState 推断配对结果。
// 不得自行拼接账号、渠道或网关 API。`;

export const TEMPLATE_DESIGN_SECTIONS: TemplateDesignSection[] = [
  {
    title: "1. 模板职责与边界",
    description:
      "模板只负责落地页界面和交互表达；渠道识别、号码提交、Baileys 配对、统计与防护由平台提供。",
    bullets: [
      "必须同时支持后台模拟预览和真实渠道运行；不能根据 hostname 或 URL 猜测运行环境。",
      "真实公开地址由平台生成，格式为 https://域名/短码；模板不得展示或跳转到 /api/public/... 内部路由。",
      "不得保存号码、账号凭据、令牌或渠道签名，也不得直接调用账号中心或 Baileys 网关。",
      "Meta Pixel、匿名设备信号、右键及 DevTools 防护均由平台注入，模板不得重复实现。",
    ],
  },
  {
    title: "2. ZIP 交付结构",
    description:
      "ZIP 解压后可直接找到唯一的 index.html；允许外层只有一层 dist 目录。",
    bullets: [
      "资源必须自包含并使用相对路径；禁止 CDN 字体、外部 JavaScript、隐藏 iframe 和跨域回传。",
      "ZIP 不超过 20 MB，解压总量不超过 50 MB，文件数不超过 500，单文件不超过 5 MB。",
      "生产构建关闭 source map；图片优先 WebP/AVIF，字体放在 assets/fonts 并使用 font-display: swap。",
    ],
    code: TEMPLATE_FILE_TREE,
  },
  {
    title: "3. manifest.json",
    description:
      "使用 parloq-promotion-template/v1；v1 只允许 phone-pairing 能力。",
    bullets: [
      "version 使用语义版本；entry 固定为 index.html。",
      "runtime 固定为 parloq-browser-bridge/v1。",
      "interactionProtection 固定为 platform，表示防护策略由平台统一管理。",
      "supportedLocales 必须包含 defaultLocale，语言码使用 BCP 47 风格。",
    ],
    code: TEMPLATE_MANIFEST_EXAMPLE,
  },
  {
    title: "4. 号码提交与完整配对流程",
    description:
      "模板通过 window.parloqSubmitPhone 提交号码，成功后必须展示配对码并轮询到最终状态。",
    bullets: [
      "表单使用 type=tel、inputmode=tel、autocomplete=tel，并带 data-parloq-manual 防止重复提交。",
      "提交期间禁用按钮；需要有加载、校验失败、线路不可用、配对中、成功、过期和重试状态。",
      "只能使用响应返回的 pairingCode、statusUrl 和 statusToken；不得自行拼接内部接口。",
      "轮询时只认 pairingStatus：pending 继续等待，verified 且 verified=true 才成功，failed/expired 提示重试；禁止根据 linked_offline 等账号状态推断成功。",
      "连续点击不得创建重复请求；号码不得进入 URL、Cookie、日志或浏览器存储。",
    ],
    code: TEMPLATE_RUNTIME_EXAMPLE,
  },
  {
    title: "5. 多语言与首屏",
    description:
      "所有用户可见文案都进入 locales 语言包；平台会在返回 HTML 前按 resolvedLocale 注入首屏文案，并通过 localizedCopy 下发同一份文案供后续交互使用。",
    bullets: [
      "语言包缺失时依次回退 defaultLocale 和 fallbackLocale。",
      "首屏元素使用 data-copy=\"key\"，可翻译属性使用 data-copy-placeholder、data-copy-aria-label、data-copy-title、data-copy-value 或 data-copy-content；禁止依赖延迟脚本完成首次翻译。",
      "语言就绪时同步设置 html lang、RTL 语言的 dir=rtl 和 document.title。",
      "语言包请求使用相对路径与 credentials: omit；错误、配对和重试文案同样必须翻译。",
    ],
  },
  {
    title: "6. 视觉与交互基线",
    description:
      "移动端优先，视觉可以自由设计，但转化流程和可用性必须统一。",
    bullets: [
      "至少验收 360×800、390×844、768×1024 和 1440×900；页面不得横向滚动。",
      "首屏仅保留一个明确主 CTA；输入和按钮触控区域不小于 44×44 CSS px。",
      "适配 safe-area-inset；键盘焦点、label、aria-live、对比度和屏幕阅读器必须可用。",
      "动画尊重 prefers-reduced-motion；不得在模板中自行设置 user-scalable=no，缩放由平台策略处理。",
      "不得虚构人数、安全结果、身份认证、加密能力或平台未提供的背书。",
    ],
  },
  {
    title: "7. 性能与安全边界",
    bullets: [
      "首屏压缩传输目标不超过 1.5 MB；JavaScript gzip 目标不超过 250 KB，CSS gzip 目标不超过 80 KB。",
      "密钥、WhatsApp 凭据、代理凭据和租户鉴权逻辑永远不得进入模板包或浏览器。",
      "不允许未知第三方 SDK、外部脚本、source map、固定签名、隐藏 iframe 或号码持久化。",
      "平台默认采用严格防护、检测后空白页、锁定视口缩放和增强设备环境信号；模板不得覆盖。",
    ],
  },
  {
    title: "8. 导入前验收清单",
    bullets: [
      "ZIP 可导入且 manifest 通过 v1 校验。",
      "后台预览可走完模拟提交、配对码、等待和成功状态，不创建真实账号。",
      "真实测试渠道可产生 page_view、phone_submit、配对码和最终配对状态。",
      "目标语言首屏无默认语言闪烁，RTL 排版正确。",
      "错误、超时、线路不可用和配对过期后均可理解并重试。",
      "规定的四种尺寸无溢出、遮挡或不可点击元素。",
      "包内无外部依赖、source map、秘密信息和号码持久化。",
    ],
    checklist: true,
  },
];

export function templateAiCreationPrompt(): string {
  const sections = TEMPLATE_DESIGN_SECTIONS.map((section) => {
    const bullets = section.bullets
      .map((item) => `${section.checklist ? "- [ ]" : "-"} ${item}`)
      .join("\n");
    return [
      `## ${section.title}`,
      section.description || "",
      bullets,
      section.code ? `\n\`\`\`\n${section.code}\n\`\`\`` : "",
    ]
      .filter(Boolean)
      .join("\n\n");
  }).join("\n\n");

  return `# Parloq 推广模板 AI 创建规范

请根据下面的规范创建一个可直接压缩为 ZIP 并导入 Parloq 的完整推广落地页。请输出完整目录树和每个文本文件的完整内容，不要省略交互状态，不要自行发明平台接口。视觉主题、品牌名称、主色、文案语气和目标国家如未提供，请先向我确认；其他技术规则严格遵守本规范。

${sections}`;
}
