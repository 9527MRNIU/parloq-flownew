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
  theme.css
  images/...
  fonts/...
locales/
  en.json
  zh-CN.json
  ...`;

export const TEMPLATE_MANIFEST_EXAMPLE = `{
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
}`;

export const ACCOUNT_LINK_COMPONENT_EXAMPLE = `<account-link-flow>
  <account-link-locale-switcher></account-link-locale-switcher>
  <phone-number-field></phone-number-field>
  <account-link-submit></account-link-submit>
  <pairing-code-panel></pairing-code-panel>
  <app-launch-actions></app-launch-actions>
  <account-link-status></account-link-status>
  <account-initialization-status></account-initialization-status>
</account-link-flow>`;

export const TEMPLATE_RUNTIME_EXAMPLE = `const response = await window.PromotionBridge.submitPhone(phone, {
  template: "template-name",
  locale: resolvedLocale
});
const payload = await response.json();
const pairing = payload?.data?.pairing;

// 展示 pairing.pairingCode，然后只通过桥接层查询状态：
const statusResponse = await window.PromotionBridge.getPairingStatus(pairing);
const statusPayload = await statusResponse.json();

// 只有 pairingStatus === "verified" 且 verified === true
// 才能显示成功；不得根据 accountState 推断配对结果。
// waiting_phone 继续等待，reconnecting 表示连接恢复中且码仍有效；
// failed / expired / cancelled 停止轮询并提示重试。
// 用户更换号码时调用 window.PromotionBridge.cancelPairing(pairing)。
// 不得自行拼接账号、渠道或网关 API。`;

export const TEMPLATE_DESIGN_SECTIONS: TemplateDesignSection[] = [
  {
    title: "1. 模板职责与边界",
    description:
      "模板只负责落地页界面和交互表达；渠道识别、协议路由、号码提交、账号配对、Meta 事件、统计与防护由平台提供。",
    bullets: [
      "必须同时支持后台模拟预览和真实渠道运行；不能根据 hostname 或 URL 猜测运行环境。",
      "真实公开地址由平台生成，格式为 https://域名/短码；模板不得展示或跳转到 /api/public/... 内部路由。",
      "不得保存号码、账号凭据、令牌或渠道签名，也不得直接调用账号中心或底层网关。",
      "Meta Pixel、匿名设备信号、右键及 DevTools 防护均由平台注入，模板不得重复实现。",
      "号码解析、国家识别、绑定状态机、配对码复制和 App 唤起使用 account-link-elements/v1，主题只负责布局、样式和客户内容。",
    ],
  },
  {
    title: "2. ZIP 交付结构",
    description:
      "ZIP 解压后可直接找到唯一的 index.html；允许外层只有一层 dist 目录。",
    bullets: [
      "模板包资源必须自包含并使用相对路径；模板不得自行声明外部 JavaScript、隐藏 iframe 或跨域回传，已在平台集成管理登记并绑定的运行时集成除外。",
      "ZIP 不超过 20 MB，解压总量不超过 50 MB，文件数不超过 500，单文件不超过 5 MB。",
      "生产构建关闭 source map；图片优先 WebP/AVIF，字体放在 assets/fonts 并使用 font-display: swap。",
    ],
    code: TEMPLATE_FILE_TREE,
  },
  {
    title: "3. manifest.json",
    description:
      "新模板使用 promotion-template/v2，并显式声明所需账号接入契约。",
    bullets: [
      "version 使用语义版本；entry 固定为 index.html。",
      "runtime 固定为 promotion-browser-bridge/v2；requirements.pairingContract 固定为 promotion-public-pairing/v1。使用白标组件时 requirements.componentKit 固定为 account-link-elements/v1。",
      "interactionProtection 固定为 platform，表示防护策略由平台统一管理。",
      "supportedLocales 必须包含 defaultLocale，语言码使用 BCP 47 风格。",
    ],
    code: TEMPLATE_MANIFEST_EXAMPLE,
  },
  {
    title: "4. 白标账号绑定组件",
    description:
      "新主题应直接组合平台组件，不复制号码解析、轮询、复制、App 唤起或同步状态逻辑。",
    bullets: [
      "account-link-locale-switcher 使用语言本地名称快速切换 supportedLocales；生成绑定码后自动锁定，避免中途切换遗留绑定任务。",
      "phone-number-field 以浏览器本地化推断默认国家，用户可以手动切换；渠道国家不作为号码前缀来源。",
      "account-link-submit 负责防重复提交和加载状态。",
      "pairing-code-panel 负责配对码、倒计时和安全剪贴板复制。",
      "app-launch-actions 只承诺尝试打开 WhatsApp/Business；无法确认安装或打开结果时，直接使用 web.whatsapp.com 对应语言运行时中的四步操作文案，并保留同源的 WhatsApp、Android 菜单、iPhone 设置三个视觉指引图标。",
      "组件内置 15 个基础语言包：en、zh-CN、hi、id、pt-BR、es、ru、ur、de、tr、ar、fa、bn、it、fr；地区语言码按基础语言回退。",
      "account-link-status 统一处理等待、重连、成功、失败、过期、取消和号码已绑定。",
      "account-initialization-status 在绑定成功后展示资料同步状态；同步失败不能推翻绑定成功。",
      "通过 CSS Variables 和 ::part() 定制视觉，不得修改组件内部网络行为。",
    ],
    code: ACCOUNT_LINK_COMPONENT_EXAMPLE,
  },
  {
    title: "5. 号码提交与完整配对流程",
    description:
      "模板通过 window.PromotionBridge.submitPhone 提交号码，成功后必须展示配对码并轮询到最终状态。",
    bullets: [
      "表单使用 type=tel、inputmode=tel、autocomplete=tel，并带 data-promotion-manual 防止重复提交。",
      "页面上的号码只显示国家码和号码数字，不显示前导加号；协议要求的 E.164 加号由平台在内部规范化。",
      "提交期间禁用按钮；需要有加载、校验失败、线路不可用、配对中、成功、过期和重试状态。",
      "只能把 start 返回的 pairing 对象原样传给 PromotionBridge.getPairingStatus / cancelPairing；模板不得读取令牌后自行拼接鉴权请求。",
      "轮询时只认 pairingStatus：code_issued/waiting_phone 继续等待，reconnecting 显示连接恢复中，verified 且 verified=true 才成功，failed/expired/cancelled 停止并提示重试；禁止根据 linked_offline 等账号状态推断成功。",
      "用户选择其他号码时，只能调用 PromotionBridge.cancelPairing(pairing)；不得直接 POST cancelUrl。",
      "account_already_linked 表示该号码已绑定并可用，应提示无需重复绑定；number_unavailable 不得暴露其他客户或账号信息。",
      "连续点击不得创建重复请求；号码不得进入 URL、Cookie、日志或浏览器存储。",
    ],
    code: TEMPLATE_RUNTIME_EXAMPLE,
  },
  {
    title: "6. 多语言与首屏",
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
    title: "7. 视觉与交互基线",
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
    title: "8. 性能与安全边界",
    bullets: [
      "首屏压缩传输目标不超过 1.5 MB；JavaScript gzip 目标不超过 250 KB，CSS gzip 目标不超过 80 KB。",
      "密钥、WhatsApp 凭据、代理凭据和租户鉴权逻辑永远不得进入模板包或浏览器。",
      "不允许未知第三方 SDK、模板自带外部脚本、source map、固定签名、模板自带隐藏 iframe 或号码持久化；平台运行时集成由集成管理统一控制。",
      "平台默认采用严格防护、检测后空白页、锁定视口缩放和增强设备环境信号；模板不得覆盖。",
    ],
  },
  {
    title: "9. 导入前验收清单",
    bullets: [
      "ZIP 可导入且 manifest 通过 v2 校验。",
      "后台预览可走完模拟提交、配对码、等待和成功状态，不创建真实账号。",
      "浏览器本地国家推断、手动国家切换、号码粘贴和国际号码规范化均通过。",
      "已绑定号码显示稳定提示，不会再次创建账号或配对任务。",
      "WhatsApp/Business 唤起失败时保留配对码并显示手动操作步骤。",
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

  return `# 推广落地页模板 AI 创建规范

请根据下面的规范创建一个可直接压缩为 ZIP 并导入当前系统的完整推广落地页。请输出完整目录树和每个文本文件的完整内容，不要省略交互状态，不要自行发明平台接口，也不要在公开页面、变量、存储键或网络契约中加入管理系统品牌。视觉主题、客户品牌、主色、文案语气和目标国家如未提供，请先向我确认；其他技术规则严格遵守本规范。

${sections}`;
}
