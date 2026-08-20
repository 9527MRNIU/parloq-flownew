import {
  ActivityIcon,
  BookOpenIcon,
  ChevronLeftIcon,
  CopyIcon,
  DownloadIcon,
  EyeIcon,
  ExternalLinkIcon,
  Globe2Icon,
  LoaderCircleIcon,
  MonitorIcon,
  PauseIcon,
  PencilIcon,
  PlayIcon,
  PlusIcon,
  RefreshCwIcon,
  Settings2Icon,
  SmartphoneIcon,
  TabletIcon,
  Trash2Icon,
  UploadCloudIcon,
} from "lucide-react";
import * as CountryFlags from "country-flag-icons/react/3x2";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type FormEvent,
  type SVGProps,
} from "react";
import type { IconType } from "react-icons";
import {
  SiFacebook,
  SiGoogle,
  SiInstagram,
  SiMeta,
  SiTiktok,
  SiYoutube,
} from "react-icons/si";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  apiDownload,
  apiRequest,
  formatDateTime,
  formatLocalDateInput,
  unwrapList,
} from "../api/client";
import {
  Badge,
  Button,
  DatePickerField,
  Drawer,
  EmptyState,
  IconButton,
  Input,
  SearchableSelect,
  SelectField,
  Spinner,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  confirmAction,
  toast,
} from "../components/ui";
import {
  ListPagination,
  ListTableCard,
  ListToolbar,
  StandardListPage,
  useClientPagination,
} from "../components/list-page";
import { EntityPrimaryCell } from "../components/entity-primary-cell";
import { RepositorySourceTabs } from "../components/repository-source-tabs";
import {
  DrawerFieldLabel,
  DrawerFormField,
  DrawerFormSection,
} from "../components/drawer-form";
import { useAuth } from "../auth/AuthContext";
import { countryOptions } from "../lib/countries";
import { entityRowKey, snowflakeId } from "../lib/entity-identifiers";
import { formatPhoneDisplay } from "../lib/utils";
import {
  formatRepositorySize,
  localRepositorySourceRow,
  remotePromotionArtifactRow,
  type LocalRepositorySource,
  type RemotePromotionArtifact,
  type RepositoryView,
} from "../lib/promotion-repository";
import {
  TEMPLATE_DESIGN_SECTIONS,
  templateAiCreationPrompt,
} from "../content/promotion-template-design";

const CHANNEL_RANDOM_CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789";

const COUNTRY_NAME_BY_CODE = new Map(
  countryOptions.map((option) => [
    option.value,
    option.label.split(" · ")[0] || option.value,
  ]),
);

const PLATFORM_CONFIG: Record<
  string,
  { label: string; icon: IconType; color: string }
> = {
  facebook: { label: "Facebook", icon: SiFacebook, color: "#0866ff" },
  google: { label: "Google", icon: SiGoogle, color: "#4285f4" },
  instagram: { label: "Instagram", icon: SiInstagram, color: "#e4405f" },
  meta: { label: "Meta", icon: SiMeta, color: "#0467df" },
  tiktok: { label: "TikTok", icon: SiTiktok, color: "#000000" },
  youtube: { label: "YouTube", icon: SiYoutube, color: "#ff0000" },
};

function countryDisplayName(code: string): string {
  const normalized = code.trim().toUpperCase();
  return COUNTRY_NAME_BY_CODE.get(normalized) || normalized || "-";
}

function CountryFlag({ code }: { code: string }) {
  const normalized = code.trim().toUpperCase();
  const Flag = (
    CountryFlags as unknown as Record<
      string,
      ComponentType<SVGProps<SVGSVGElement>>
    >
  )[normalized];

  if (!Flag) {
    return <Globe2Icon aria-hidden="true" className="h-4 w-6 text-muted-foreground" />;
  }

  return (
    <Flag
      aria-hidden="true"
      className="block h-4 w-6 shrink-0 overflow-hidden rounded-[2px] shadow-sm ring-1 ring-black/10"
    />
  );
}

function platformDisplayName(platform: string): string {
  const normalized = platform.trim().toLowerCase();
  return PLATFORM_CONFIG[normalized]?.label || platform || "-";
}

function PlatformLogo({ platform }: { platform: string }) {
  const normalized = platform.trim().toLowerCase();
  const config = PLATFORM_CONFIG[normalized];

  if (config) {
    const Icon = config.icon;
    return (
      <Icon
        aria-hidden="true"
        className="h-5 w-5 shrink-0"
        color={config.color}
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted text-[10px] text-muted-foreground"
    >
      {platform.trim().slice(0, 1).toUpperCase() || "-"}
    </span>
  );
}

function randomChannelCode(existing: Iterable<string>, length = 8): string {
  const reserved = new Set(Array.from(existing, (value) => value.toLowerCase()));
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const random = new Uint8Array(length);
    globalThis.crypto.getRandomValues(random);
    const code = Array.from(
      random,
      (value) =>
        CHANNEL_RANDOM_CODE_ALPHABET[
          value % CHANNEL_RANDOM_CODE_ALPHABET.length
        ],
    ).join("");
    if (!reserved.has(code)) return code;
  }
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

const field = (row: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) if (row[key] != null) return String(row[key]);
  return "";
};
const object = (input: unknown) =>
  input && typeof input === "object" ? (input as Record<string, unknown>) : {};
type PromotionTemplate = {
  id: string;
  readKey: string;
  name: string;
  description: string;
  version: string;
  status: string;
  previewUrl: string;
  assetCount: number;
  channelCount: number;
  defaultLocale: string;
  supportedLocales: string[];
  integrationIds: string[];
  repositorySource: LocalRepositorySource | null;
  qualityReport: TemplateQualityReport;
  createdAt?: string;
  updatedAt?: string;
};
type TemplateQualityWarning = {
  code: string;
  message: string;
  paths: string[];
};
type TemplateQualityReport = {
  status: "passed" | "warnings" | "unchecked";
  metrics: {
    expandedBytes: number;
    assetCount: number;
    jsGzipBytes: number;
    cssGzipBytes: number;
    imageBytes: number;
    imageCount: number;
  };
  warnings: TemplateQualityWarning[];
};
type RuntimeIntegrationOption = {
  id: string;
  name: string;
  type: "script" | "iframe";
  entryCount: number;
  enabled: boolean;
};
type TemplatePreviewDevice = "desktop" | "tablet" | "mobile";
type TemplatePreviewState =
  | "input"
  | "code_issued"
  | "waiting_phone"
  | "reconnecting"
  | "verified_syncing"
  | "ready"
  | "failed"
  | "expired"
  | "cancelled";
const TEMPLATE_PREVIEW_DEVICES = [
  {
    value: "desktop",
    label: "桌面",
    dimensions: "1024 × 768",
    width: 1024,
    height: 768,
    Icon: MonitorIcon,
  },
  {
    value: "tablet",
    label: "平板",
    dimensions: "768 × 1024",
    width: 768,
    height: 1024,
    Icon: TabletIcon,
  },
  {
    value: "mobile",
    label: "手机",
    dimensions: "390 × 844",
    width: 390,
    height: 844,
    Icon: SmartphoneIcon,
  },
] as const;
const TEMPLATE_PREVIEW_STATES: ReadonlyArray<{
  value: TemplatePreviewState;
  label: string;
  description: string;
}> = [
  { value: "input", label: "号码输入", description: "重置并查看绑定前状态" },
  { value: "code_issued", label: "配对码已生成", description: "生成配对码后暂停" },
  { value: "waiting_phone", label: "等待手机", description: "等待用户在手机确认" },
  { value: "reconnecting", label: "重新连接", description: "网关正在完成安全连接" },
  { value: "verified_syncing", label: "成功·同步中", description: "已验证，资料仍在同步" },
  { value: "ready", label: "同步完成", description: "账号资料初始化完成" },
  { value: "failed", label: "绑定失败", description: "展示可重试失败状态" },
  { value: "expired", label: "配对码过期", description: "展示过期状态" },
  { value: "cancelled", label: "用户取消", description: "展示取消状态" },
];
const TEMPLATE_PREVIEW_AUTOPLAY: TemplatePreviewState[] = [
  "code_issued",
  "waiting_phone",
  "reconnecting",
  "verified_syncing",
  "ready",
];
type PromotionChannel = {
  id: string;
  readKey: string;
  name: string;
  platform: string;
  countryCode: string;
  templateId: string;
  templateName: string;
  accountGroupId: string;
  accountGroupName: string;
  protocolNodeId: string;
  protocolNodeName: string;
  protocolPoolId: string;
  protocolPoolName: string;
  domainId: string;
  baseHostname: string;
  subdomainPrefix: string;
  hostname: string;
  slug: string;
  publicUrl: string;
  pixelId: string;
  pixelName: string;
  metaBrowserPixelEnabled: boolean;
  metaCapiEnabled: boolean;
  metaCapiProbeReady: boolean;
  metaDomainMonitored: boolean;
  metaDomainBlocked: boolean;
  metaDomainBlockedAt: string;
  metaEventMapping: MetaEventMapping;
  inAppBrowserMode: "allow" | "guide_external";
  newAccountMarketingEnabled: boolean;
  effectiveConfig: Record<string, unknown>;
  enabled: boolean;
  localeMode: string;
  locale: string;
  goLiveAt?: string;
  createdAt?: string;
  visits: number;
  clicks: number;
  leads: number;
  updatedAt?: string;
};
type Option = { id: string; label: string; locales?: string[] };
type TemplateOption = Option & {
  schema: string;
  runtime: string;
  pairingContract: string;
};
type ProtocolOption = Option & {
  health: string;
  healthReason: string;
};
type PixelOption = Option & {
  readKey: string;
  name: string;
  datasetId: string;
  enabled: boolean;
  tokenMasked: string;
  tokenConfigured: boolean;
};
type MetaEventMapping = {
  page_view: string;
  phone_submit: string;
  pairing_started: string;
  pairing_verified: string;
};
type MetaCapiProbeResult = {
  ok: boolean;
  datasetId: string;
  eventName: string;
  eventId: string;
  providerTraceId: string;
  httpStatus?: number;
  sendError: string;
};
type PairingFunnelStep = {
  key: string;
  count: number;
  visitorRate: number;
  stepRate: number;
};
type PairingFailureReason = {
  code: string;
  label: string;
  count: number;
  share: number;
};
const pairingFunnelLabels: Record<string, string> = {
  visitors: "可识别访客",
  phoneSubmitted: "提交号码",
  checksPassed: "通过配对检查",
  pairingStarted: "获得配对码",
  verified: "验证成功",
};
const defaultMetaEventMapping: MetaEventMapping = {
  page_view: "PageView",
  phone_submit: "Lead",
  pairing_started: "InitiateCheckout",
  pairing_verified: "CompleteRegistration",
};
const metaEventOptions = [
  { value: "", label: "不上报" },
  { value: "PageView", label: "浏览页面 (PageView)" },
  { value: "ViewContent", label: "浏览内容 (ViewContent)" },
  { value: "Search", label: "搜索 (Search)" },
  { value: "AddToCart", label: "加入购物车 (AddToCart)" },
  { value: "AddToWishlist", label: "加入心愿单 (AddToWishlist)" },
  { value: "InitiateCheckout", label: "发起结账 (InitiateCheckout)" },
  { value: "AddPaymentInfo", label: "添加支付信息 (AddPaymentInfo)" },
  { value: "Purchase", label: "购买 (Purchase)" },
  { value: "Lead", label: "潜在客户 (Lead)" },
  { value: "CompleteRegistration", label: "完成注册 (CompleteRegistration)" },
  { value: "Contact", label: "联系 (Contact)" },
  { value: "Subscribe", label: "订阅 (Subscribe)" },
];
type AdMetric = {
  id: string;
  readKey: string;
  date: string;
  spend: number;
  impressions: number;
  clicks: number;
  updatedAt: string;
};
type TemplateProtectionMode = "basic" | "enhanced" | "strict";
type TemplateDevtoolsAction = "log" | "block" | "blank";
type TemplateDeviceSignals = "off" | "standard" | "enhanced" | "fingerprint";
type EventRateLimitRuleForm = {
  maxRequests: string;
  windowSeconds: string;
};
type EventRateLimitPolicyForm = {
  sessionReports: EventRateLimitRuleForm;
  ipReports: EventRateLimitRuleForm;
  channelReports: EventRateLimitRuleForm;
  metaDomainReports: EventRateLimitRuleForm;
};
type TemplatePolicy = {
  protectionMode: TemplateProtectionMode;
  devtoolsAction: TemplateDevtoolsAction;
  lockViewportZoom: boolean;
  deviceSignals: TemplateDeviceSignals;
  eventRateLimitPolicy: EventRateLimitPolicyForm;
};

const defaultTemplatePolicy: TemplatePolicy = {
  protectionMode: "strict",
  devtoolsAction: "blank",
  lockViewportZoom: true,
  deviceSignals: "fingerprint",
  eventRateLimitPolicy: {
    sessionReports: { maxRequests: "60", windowSeconds: "60" },
    ipReports: { maxRequests: "600", windowSeconds: "60" },
    channelReports: { maxRequests: "10000", windowSeconds: "60" },
    metaDomainReports: { maxRequests: "5", windowSeconds: "600" },
  },
};

const EVENT_RATE_LIMIT_FIELDS: Array<[
  keyof EventRateLimitPolicyForm,
  string,
  string,
]> = [
  ["sessionReports", "单会话数据回传", "同一个签名运行会话内，主模板或单个 iframe 集成允许的数据回传请求数。"],
  ["ipReports", "同一 IP 数据回传", "同一渠道下，单个来源 IP 对主模板或单个 iframe 集成发起的数据回传请求数。"],
  ["channelReports", "单渠道回传总量", "单个渠道对主模板或单个 iframe 集成的回传总量；不同集成之间分别计数。"],
  ["metaDomainReports", "Facebook 域名异常回传", "同一落地域名、同一来源 IP 上报 Facebook Pixel 域名异常的请求数。"],
];

function qualityNumber(row: Record<string, unknown>, key: string) {
  const value = Number(row[key] ?? 0);
  return Number.isFinite(value) ? value : 0;
}

function templateQualityReport(input: unknown): TemplateQualityReport {
  const row = object(input);
  const rawStatus = field(row, "status");
  const metrics = object(row.metrics);
  const rawWarnings = Array.isArray(row.warnings) ? row.warnings : [];
  return {
    status: ["passed", "warnings", "unchecked"].includes(rawStatus)
      ? (rawStatus as TemplateQualityReport["status"])
      : "unchecked",
    metrics: {
      expandedBytes: qualityNumber(metrics, "expandedBytes"),
      assetCount: qualityNumber(metrics, "assetCount"),
      jsGzipBytes: qualityNumber(metrics, "jsGzipBytes"),
      cssGzipBytes: qualityNumber(metrics, "cssGzipBytes"),
      imageBytes: qualityNumber(metrics, "imageBytes"),
      imageCount: qualityNumber(metrics, "imageCount"),
    },
    warnings: rawWarnings.map((input) => {
      const warning = object(input);
      return {
        code: field(warning, "code"),
        message: field(warning, "message"),
        paths: Array.isArray(warning.paths) ? warning.paths.map(String) : [],
      };
    }),
  };
}

function formatTemplateBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function eventRateLimitRuleForm(
  input: unknown,
  fallback: EventRateLimitRuleForm,
): EventRateLimitRuleForm {
  const row = object(input);
  const maxRequests = Number(row.maxRequests ?? row.max_requests);
  const windowSeconds = Number(row.windowSeconds ?? row.window_seconds);
  return {
    maxRequests:
      Number.isInteger(maxRequests) && maxRequests > 0
        ? String(maxRequests)
        : fallback.maxRequests,
    windowSeconds:
      Number.isInteger(windowSeconds) && windowSeconds > 0
        ? String(windowSeconds)
        : fallback.windowSeconds,
  };
}

function validEventRateLimitPolicy(policy: EventRateLimitPolicyForm) {
  return Object.values(policy).every((rule) => {
    const maxRequests = Number(rule.maxRequests);
    const windowSeconds = Number(rule.windowSeconds);
    return (
      Number.isInteger(maxRequests) &&
      maxRequests >= 1 &&
      maxRequests <= 1_000_000 &&
      Number.isInteger(windowSeconds) &&
      windowSeconds >= 1 &&
      windowSeconds <= 86_400
    );
  });
}

function eventRateLimitPayload(policy: EventRateLimitPolicyForm) {
  return Object.fromEntries(
    Object.entries(policy).map(([key, rule]) => [
      key,
      {
        maxRequests: Number(rule.maxRequests),
        windowSeconds: Number(rule.windowSeconds),
      },
    ]),
  );
}

function templatePolicyRow(input: unknown): TemplatePolicy {
  const row = object(input);
  const protectionMode = field(row, "protectionMode", "protection_mode");
  const devtoolsAction = field(row, "devtoolsAction", "devtools_action");
  const deviceSignals = field(row, "deviceSignals", "device_signals");
  const eventRateLimitPolicy = object(
    row.eventRateLimitPolicy ?? row.event_rate_limit_policy,
  );
  return {
    protectionMode: ["basic", "enhanced", "strict"].includes(protectionMode)
      ? (protectionMode as TemplateProtectionMode)
      : defaultTemplatePolicy.protectionMode,
    devtoolsAction: ["log", "block", "blank"].includes(devtoolsAction)
      ? (devtoolsAction as TemplateDevtoolsAction)
      : defaultTemplatePolicy.devtoolsAction,
    lockViewportZoom: Boolean(
      row.lockViewportZoom ??
        row.lock_viewport_zoom ??
        defaultTemplatePolicy.lockViewportZoom,
    ),
    deviceSignals: ["off", "standard", "enhanced", "fingerprint"].includes(deviceSignals)
      ? (deviceSignals as TemplateDeviceSignals)
      : defaultTemplatePolicy.deviceSignals,
    eventRateLimitPolicy: {
      sessionReports: eventRateLimitRuleForm(
        eventRateLimitPolicy.sessionReports ?? eventRateLimitPolicy.session_reports,
        defaultTemplatePolicy.eventRateLimitPolicy.sessionReports,
      ),
      ipReports: eventRateLimitRuleForm(
        eventRateLimitPolicy.ipReports ?? eventRateLimitPolicy.ip_reports,
        defaultTemplatePolicy.eventRateLimitPolicy.ipReports,
      ),
      channelReports: eventRateLimitRuleForm(
        eventRateLimitPolicy.channelReports ?? eventRateLimitPolicy.channel_reports,
        defaultTemplatePolicy.eventRateLimitPolicy.channelReports,
      ),
      metaDomainReports: eventRateLimitRuleForm(
        eventRateLimitPolicy.metaDomainReports ?? eventRateLimitPolicy.meta_domain_reports,
        defaultTemplatePolicy.eventRateLimitPolicy.metaDomainReports,
      ),
    },
  };
}
function templateRow(input: unknown): PromotionTemplate {
  const row = object(input);
  const id = snowflakeId(row, "id");
  const manifest = object(row.manifest);
  const rowLocales = row.supportedLocales || row.supported_locales;
  const locales = Array.isArray(rowLocales)
    ? rowLocales.map(String)
    : Array.isArray(manifest.supportedLocales)
      ? manifest.supportedLocales.map(String)
      : [String(row.defaultLocale || manifest.defaultLocale || "zh-CN")];
  const defaultLocale = String(
    row.defaultLocale ||
      row.default_locale ||
      manifest.defaultLocale ||
      locales[0] ||
      "zh-CN",
  );
  const rawVersion =
    field(row, "version", "versionName", "version_name") || "v1";
  const rawIntegrationIds = row.integrationIds || row.integration_ids;
  return {
    id,
    readKey: entityRowKey(row, id, "promotion-template", `${field(row, "name")}:${field(row, "updatedAt", "updated_at")}`),
    name: field(row, "name"),
    description: field(row, "description"),
    version: `${rawVersion} · ${defaultLocale} / ${locales.length} 语言`,
    status:
      field(row, "status") || (row.enabled === false ? "disabled" : "ready"),
    previewUrl:
      field(row, "previewUrl", "preview_url") ||
      (id ? `/api/promotion/templates/${id}/preview` : ""),
    assetCount: Number(row.assetCount ?? row.asset_count ?? 0),
    channelCount: Number(row.channelCount ?? row.channel_count ?? 0),
    integrationIds: Array.isArray(rawIntegrationIds)
      ? rawIntegrationIds.map(String)
      : [],
    repositorySource: localRepositorySourceRow(
      row.repositorySource ?? row.repository_source,
    ),
    qualityReport: templateQualityReport(
      row.qualityReport ?? row.quality_report,
    ),
    defaultLocale,
    supportedLocales: locales,
    createdAt: field(row, "createdAt", "created_at"),
    updatedAt: field(row, "updatedAt", "updated_at"),
  };
}
function runtimeIntegrationRow(input: unknown): RuntimeIntegrationOption {
  const row = object(input);
  const id = snowflakeId(row, "id");
  const entryPaths = row.entryPaths || row.entry_paths;
  return {
    id,
    name: field(row, "name"),
    type: field(row, "type") === "script" ? "script" : "iframe",
    entryCount: Array.isArray(entryPaths) ? entryPaths.length : 0,
    enabled: row.enabled !== false && row.domainReady !== false,
  };
}
function RuntimeIntegrationSwitches({
  integrations,
  selectedIds,
  disabled,
  onToggle,
}: {
  integrations: RuntimeIntegrationOption[];
  selectedIds: string[];
  disabled?: boolean;
  onToggle: (integrationId: string) => void;
}) {
  return (
    <DrawerFormSection
      title="运行时集成"
      description="由平台统一托管并注入。iframe 会挂载到 body 末尾，脚本按包内入口顺序加载。"
    >
      {integrations.length ? (
        integrations.map((integration) => (
          <label className="switch-row" key={integration.id}>
            <span>
              <strong>{integration.name}</strong>
              <small>
                {integration.type === "iframe" ? "iframe" : "JavaScript"} ·{" "}
                {integration.entryCount} 个入口
              </small>
            </span>
            <Switch
              checked={selectedIds.includes(integration.id)}
              disabled={disabled || !integration.enabled}
              onCheckedChange={() => onToggle(integration.id)}
              aria-label={`${integration.name}集成`}
            />
          </label>
        ))
      ) : (
        <div className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
          还没有可用集成，请先在集成管理中创建并启用。
        </div>
      )}
    </DrawerFormSection>
  );
}
function channelRow(input: unknown): PromotionChannel {
  const row = object(input);
  const id = snowflakeId(row, "id");
  const stats = object(row.stats);
  const status = field(row, "status") || "draft";
  const hostname = field(row, "hostname", "domain");
  const slug = field(row, "slug");
  const mapping = object(row.metaEventMapping || row.meta_event_mapping);
  return {
    id,
    readKey: entityRowKey(row, id, "promotion-channel", `${field(row, "name")}:${field(row, "slug")}`),
    name: field(row, "name"),
    platform: field(row, "type", "platform") || "facebook",
    countryCode: field(row, "countryCode", "country_code"),
    templateId: snowflakeId(row, "templateId", "template_id"),
    templateName: field(row, "templateName", "template_name"),
    accountGroupId: snowflakeId(row, "accountGroupId", "account_group_id"),
    accountGroupName: field(row, "accountGroupName", "account_group_name"),
    protocolNodeId: snowflakeId(row, "protocolNodeId", "protocol_node_id"),
    protocolNodeName: field(row, "protocolNodeName", "protocol_node_name"),
    protocolPoolId: snowflakeId(row, "protocolPoolId", "protocol_pool_id"),
    protocolPoolName: field(row, "protocolPoolName", "protocol_pool_name"),
    domainId: snowflakeId(row, "domainId", "domain_id"),
    baseHostname: field(row, "baseHostname", "base_hostname"),
    subdomainPrefix: field(row, "subdomainPrefix", "subdomain_prefix"),
    hostname,
    slug,
    publicUrl:
      field(row, "publicUrl", "public_url") ||
      (hostname && slug ? `https://${hostname}/${slug}` : ""),
    pixelId: snowflakeId(row, "pixelId", "pixel_id"),
    pixelName: field(row, "pixelName", "pixel_name", "datasetId", "dataset_id"),
    metaBrowserPixelEnabled: Boolean(
      row.metaBrowserPixelEnabled ?? row.meta_browser_pixel_enabled ?? false,
    ),
    metaCapiEnabled: Boolean(
      row.metaCapiEnabled ?? row.meta_capi_enabled ?? false,
    ),
    metaCapiProbeReady: Boolean(
      row.metaCapiProbeReady ?? row.meta_capi_probe_ready ?? false,
    ),
    metaDomainMonitored: Boolean(
      row.metaDomainMonitored ?? row.meta_domain_monitored ?? false,
    ),
    metaDomainBlocked: Boolean(
      row.metaDomainBlocked ?? row.meta_domain_blocked ?? false,
    ),
    metaDomainBlockedAt: field(
      row,
      "metaDomainBlockedAt",
      "meta_domain_blocked_at",
    ),
    metaEventMapping: {
      page_view: String(mapping.page_view ?? defaultMetaEventMapping.page_view),
      phone_submit: String(mapping.phone_submit ?? defaultMetaEventMapping.phone_submit),
      pairing_started: String(
        mapping.pairing_started ?? defaultMetaEventMapping.pairing_started,
      ),
      pairing_verified: String(
        mapping.pairing_verified ?? defaultMetaEventMapping.pairing_verified,
      ),
    },
    inAppBrowserMode: (field(
      row,
      "inAppBrowserMode",
      "in_app_browser_mode",
    ) || "allow") as "allow" | "guide_external",
    newAccountMarketingEnabled: Boolean(
      row.newAccountMarketingEnabled ?? row.new_account_marketing_enabled ?? true,
    ),
    effectiveConfig: object(row.effectiveConfig || row.effective_config),
    enabled: Boolean(row.enabled ?? status === "active"),
    localeMode: field(row, "localeMode", "locale_mode") || "auto",
    locale: field(row, "locale"),
    goLiveAt: field(row, "launchAt", "launch_at", "goLiveAt", "go_live_at"),
    createdAt: field(row, "createdAt", "created_at"),
    visits: Number(row.visits ?? stats.visits ?? 0),
    clicks: Number(row.clicks ?? stats.clicks ?? 0),
    leads: Number(row.leads ?? stats.leads ?? 0),
    updatedAt: field(row, "updatedAt", "updated_at"),
  };
}
function pixelRow(input: unknown): PixelOption {
  const row = object(input);
  const name = field(row, "name") || "Meta Pixel";
  const datasetId = field(
    row,
    "datasetId",
    "dataset_id",
  );
  const id = snowflakeId(row, "id");
  return {
    id,
    readKey: entityRowKey(row, id, "meta-pixel", `${name}:${datasetId}`),
    name,
    datasetId,
    label: `${name} · ${datasetId}`,
    enabled: Boolean(row.enabled ?? true),
    tokenMasked: field(row, "capiTokenMasked", "capi_token_masked"),
    tokenConfigured: Boolean(
      row.capiTokenConfigured ??
        row.capi_token_configured ??
        field(row, "capiTokenMasked", "capi_token_masked"),
    ),
  };
}
function metricRow(input: unknown): AdMetric {
  const row = object(input);
  const id = snowflakeId(row, "id");
  return {
    id,
    readKey: entityRowKey(row, id, "promotion-ad-metric", `${field(row, "date", "metricDate", "metric_date")}:${field(row, "updatedAt", "updated_at")}`),
    date: field(row, "date", "metricDate", "metric_date"),
    spend: Number(row.spend || 0),
    impressions: Number(row.impressions || 0),
    clicks: Number(row.clicks || 0),
    updatedAt: field(row, "updatedAt", "updated_at"),
  };
}

function TemplatePreviewWorkspace({
  template,
  initialDevice = "mobile",
  initialLocale,
  standalone = false,
}: {
  template: PromotionTemplate;
  initialDevice?: TemplatePreviewDevice;
  initialLocale?: string;
  standalone?: boolean;
}) {
  const [device, setDevice] =
    useState<TemplatePreviewDevice>(initialDevice);
  const [previewState, setPreviewState] =
    useState<TemplatePreviewState>("input");
  const [locale, setLocale] = useState(
    template.supportedLocales.includes(String(initialLocale))
      ? String(initialLocale)
      : template.defaultLocale,
  );
  const [started, setStarted] = useState(false);
  const [autoplay, setAutoplay] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const frameRef = useRef<HTMLIFrameElement>(null);

  const postPreviewState = useCallback((state: TemplatePreviewState) => {
    if (state === "input") return;
    frameRef.current?.contentWindow?.postMessage(
      { type: "promotion-preview:set-state", state },
      "*",
    );
  }, []);

  const resetPreview = useCallback(() => {
    setAutoplay(false);
    setStarted(false);
    setPreviewState("input");
    setReloadKey((current) => current + 1);
  }, []);

  const selectPreviewState = useCallback(
    (state: TemplatePreviewState) => {
      if (state === "input") {
        resetPreview();
        return;
      }
      if (!started) return;
      setPreviewState(state);
      postPreviewState(state);
    },
    [postPreviewState, resetPreview, started],
  );

  useEffect(() => {
    const receivePreviewEvent = (event: MessageEvent) => {
      if (event.source !== frameRef.current?.contentWindow) return;
      const data = object(event.data);
      if (data.type === "promotion-preview:pairing-started") {
        setStarted(true);
        setPreviewState("code_issued");
      }
      if (data.type === "promotion-preview:reset") {
        setStarted(false);
        setAutoplay(false);
        setPreviewState("input");
      }
      if (data.type === "promotion-preview:locale-change") {
        const requestedLocale = String(data.locale || "");
        if (!template.supportedLocales.includes(requestedLocale)) return;
        setStarted(false);
        setAutoplay(false);
        setPreviewState("input");
        setLocale(requestedLocale);
        setReloadKey((current) => current + 1);
      }
    };
    window.addEventListener("message", receivePreviewEvent);
    return () => window.removeEventListener("message", receivePreviewEvent);
  }, [template.supportedLocales]);

  useEffect(() => {
    if (!autoplay || !started) return;
    const currentIndex = TEMPLATE_PREVIEW_AUTOPLAY.indexOf(previewState);
    if (currentIndex < 0) {
      selectPreviewState("code_issued");
      return;
    }
    const next = TEMPLATE_PREVIEW_AUTOPLAY[currentIndex + 1];
    if (!next) {
      setAutoplay(false);
      return;
    }
    const timer = window.setTimeout(() => selectPreviewState(next), 2800);
    return () => window.clearTimeout(timer);
  }, [autoplay, previewState, selectPreviewState, started]);

  const selectedDevice =
    TEMPLATE_PREVIEW_DEVICES.find(({ value }) => value === device) ||
    TEMPLATE_PREVIEW_DEVICES[2];
  const previewUrl = new URL(template.previewUrl, window.location.origin);
  previewUrl.searchParams.set("device", device);
  previewUrl.searchParams.set("lang", locale);

  return (
    <div
      className={`template-device-preview${standalone ? " is-standalone" : ""}`}
    >
      <div className="template-device-preview__toolbar">
        <div
          className="template-device-preview__switcher"
          role="group"
          aria-label="预览设备"
        >
          {TEMPLATE_PREVIEW_DEVICES.map(
            ({ value, label, dimensions, Icon }) => (
              <Button
                key={value}
                size="sm"
                variant={device === value ? "default" : "outline"}
                aria-pressed={device === value}
                onClick={() => {
                  setDevice(value);
                  setAutoplay(false);
                  setStarted(false);
                  setPreviewState("input");
                  setReloadKey((current) => current + 1);
                }}
              >
                <Icon size={15} />
                {label}
                <span className="template-device-preview__dimensions">
                  {dimensions}
                </span>
              </Button>
            ),
          )}
        </div>
        <div className="template-device-preview__toolbar-actions">
          <Button
            size="sm"
            variant="outline"
            disabled={!started}
            onClick={() => setAutoplay((current) => !current)}
          >
            {autoplay ? <PauseIcon size={15} /> : <PlayIcon size={15} />}
            {autoplay ? "暂停演示" : "自动演示"}
          </Button>
          <Button size="sm" variant="outline" onClick={resetPreview}>
            <RefreshCwIcon size={15} />
            重置
          </Button>
          {!standalone ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                const url = new URL(
                  `/promotion/templates/${template.id}/preview`,
                  window.location.origin,
                );
                url.searchParams.set("device", device);
                url.searchParams.set("lang", locale);
                window.open(url.toString(), "_blank", "noopener,noreferrer");
              }}
            >
              <ExternalLinkIcon size={15} />
              新窗口打开
            </Button>
          ) : null}
        </div>
      </div>

      <div className="template-device-preview__flow-bar">
        <div className="template-device-preview__flow-heading">
          <strong>绑定流程</strong>
          <span>
            {started
              ? "手动选择状态，页面不会自动跳到成功。"
              : "先在预览中输入号码并点击开始绑定。"}
          </span>
        </div>
        <div
          className="template-device-preview__states"
          role="group"
          aria-label="绑定流程预览状态"
        >
          {TEMPLATE_PREVIEW_STATES.map(({ value, label, description }) => (
            <Button
              key={value}
              size="xs"
              variant={previewState === value ? "default" : "outline"}
              aria-pressed={previewState === value}
              aria-label={`${label}：${description}`}
              disabled={value !== "input" && !started}
              onClick={() => selectPreviewState(value)}
            >
              {label}
            </Button>
          ))}
        </div>
      </div>

      <div className="template-device-preview__stage">
        <div
          className="template-device-preview__device"
          data-device={device}
          style={{ width: selectedDevice.width }}
        >
          <div className="template-device-preview__chrome">
            <span>{selectedDevice.label}预览</span>
            <span>
              {selectedDevice.width} × {selectedDevice.height}
            </span>
          </div>
          <iframe
            ref={frameRef}
            className="template-device-preview__frame"
            src={previewUrl.toString()}
            title={`${template.name} · ${selectedDevice.label}预览`}
            width={selectedDevice.width}
            height={selectedDevice.height}
            key={`${template.id}:${device}:${reloadKey}`}
            sandbox="allow-scripts allow-forms allow-top-navigation-by-user-activation"
            referrerPolicy="no-referrer"
            onLoad={() => {
              setStarted(false);
              setAutoplay(false);
              setPreviewState("input");
            }}
          />
        </div>
      </div>
    </div>
  );
}

export function PromotionTemplatePreviewPage() {
  const { templateId = "" } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedDevice = searchParams.get("device");
  const requestedLocale = searchParams.get("lang") || undefined;
  const initialDevice: TemplatePreviewDevice = [
    "desktop",
    "tablet",
    "mobile",
  ].includes(String(requestedDevice))
    ? (requestedDevice as TemplatePreviewDevice)
    : "mobile";
  const [template, setTemplate] = useState<PromotionTemplate | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    void apiRequest(`/api/promotion/templates/${templateId}`)
      .then((payload) => {
        if (!active) return;
        const data = object(object(payload).data ?? payload);
        setTemplate(templateRow(data.template || data));
      })
      .catch((caught) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "模板读取失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [templateId]);

  return (
    <main className="template-preview-page">
      <header className="template-preview-page__header">
        <Button variant="outline" onClick={() => navigate("/promotion/templates")}>
          <ChevronLeftIcon size={16} />
          返回模板管理
        </Button>
        <div>
          <strong>{template?.name || "模板模拟预览"}</strong>
          <span>手动检查设备适配及账号绑定的每个中间状态</span>
        </div>
        {template ? <Badge tone="neutral">{template.version.split(" · ")[0]}</Badge> : null}
      </header>
      {loading ? (
        <div className="loading-state min-h-64"><Spinner />正在读取模板…</div>
      ) : error || !template ? (
        <div className="error-state min-h-64">
          <strong>模板预览无法打开</strong>
          <span>{error || "模板不存在"}</span>
        </div>
      ) : (
        <TemplatePreviewWorkspace
          template={template}
          initialDevice={initialDevice}
          initialLocale={requestedLocale}
          standalone
        />
      )}
    </main>
  );
}

export function PromotionTemplatesPage() {
  const { can } = useAuth();
  const canManage = can("promotion.templates.manage");
  const [rows, setRows] = useState<PromotionTemplate[]>([]);
  const [view, setView] = useState<RepositoryView>("local");
  const [repositoryRows, setRepositoryRows] = useState<RemotePromotionArtifact[]>([]);
  const [repositoryLoading, setRepositoryLoading] = useState(false);
  const [repositoryRefreshing, setRepositoryRefreshing] = useState(false);
  const repositoryRefreshActive = useRef(false);
  const [repositoryError, setRepositoryError] = useState("");
  const [repositoryPending, setRepositoryPending] = useState("");
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [drawer, setDrawer] = useState(false);
  const [editing, setEditing] = useState<PromotionTemplate | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [packageInspecting, setPackageInspecting] = useState(false);
  const packageInspectionRequest = useRef(0);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [templateStatus, setTemplateStatus] = useState("active");
  const [integrations, setIntegrations] = useState<RuntimeIntegrationOption[]>([]);
  const [selectedIntegrationIds, setSelectedIntegrationIds] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [previewing, setPreviewing] = useState<PromotionTemplate | null>(null);
  const [qualityReviewing, setQualityReviewing] = useState<PromotionTemplate | null>(null);
  const [designSpecDrawer, setDesignSpecDrawer] = useState(false);
  const [policyDrawer, setPolicyDrawer] = useState(false);
  const [policy, setPolicy] = useState<TemplatePolicy>(defaultTemplatePolicy);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [policySaving, setPolicySaving] = useState(false);
  const [policyError, setPolicyError] = useState("");
  const [policyLoaded, setPolicyLoaded] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [templatePayload, channelPayload, integrationPayload] = await Promise.all([
        apiRequest("/api/promotion/templates?pageSize=100"),
        apiRequest("/api/promotion/channels?pageSize=100"),
        apiRequest("/api/promotion/integrations"),
      ]);
      const channels = unwrapList<unknown>(channelPayload).rows.map(channelRow);
      setIntegrations(
        unwrapList<unknown>(integrationPayload)
          .rows.map(runtimeIntegrationRow)
          .filter((row) => row.id),
      );
      setRows(
        unwrapList<unknown>(templatePayload)
          .rows.map(templateRow)
          .map((row) => ({
            ...row,
            channelCount: channels.filter(
              (channel) => channel.templateId === row.id,
            ).length,
          })),
      );
    } catch {
      setRows([]);
      setIntegrations([]);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const loadRepository = useCallback(async ({
    refresh = false,
    preserve = false,
  }: {
    refresh?: boolean;
    preserve?: boolean;
  } = {}) => {
    if (refresh && repositoryRefreshActive.current) {
      return { ok: false, cacheHit: true };
    }
    if (refresh) repositoryRefreshActive.current = true;
    if (preserve) setRepositoryRefreshing(true);
    else {
      setRepositoryLoading(true);
      setRepositoryError("");
    }
    try {
      const payload = await apiRequest(
        `/api/promotion/templates/repository${refresh ? "/refresh" : ""}`,
        {
          method: refresh ? "POST" : "GET",
        },
      );
      const data = object(object(payload).data ?? payload);
      setRepositoryRows(
        unwrapList<unknown>(payload).rows.map(remotePromotionArtifactRow),
      );
      setRepositoryError("");
      return { ok: true, cacheHit: data.cacheHit === true };
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "远程仓库读取失败";
      if (preserve) toast.error(`仓库刷新失败，当前显示上次缓存：${message}`);
      else {
        setRepositoryRows([]);
        setRepositoryError(message);
      }
      return { ok: false, cacheHit: false };
    } finally {
      if (refresh) repositoryRefreshActive.current = false;
      if (preserve) setRepositoryRefreshing(false);
      else setRepositoryLoading(false);
    }
  }, []);
  function changeView(next: RepositoryView) {
    setView(next);
    if (next !== "repository") return;
    void (async () => {
      const cached = await loadRepository({ preserve: repositoryRows.length > 0 });
      if (!cached.ok || !cached.cacheHit) return;
      const refreshed = await loadRepository({ refresh: true, preserve: true });
      if (refreshed.ok) await load();
    })();
  }
  const visible = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return search
      ? rows.filter((row) =>
          `${row.name} ${row.version} ${row.status}`
            .toLowerCase()
            .includes(search),
        )
      : rows;
  }, [keyword, rows]);
  const templatePagination = useClientPagination(visible, { resetKey: keyword });
  const repositoryVisible = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    if (!search) return repositoryRows;
    return repositoryRows.filter((row) =>
      `${row.sequence} ${row.name} ${row.description} ${row.slug} ${row.version}`
        .toLowerCase()
        .includes(search),
    );
  }, [keyword, repositoryRows]);
  const repositoryPagination = useClientPagination(repositoryVisible, {
    resetKey: keyword,
  });
  async function importRepositoryTemplate(row: Pick<RemotePromotionArtifact, "sequence">) {
    if (!canManage || repositoryPending) return;
    setRepositoryPending(row.sequence);
    try {
      const payload = await apiRequest(
        `/api/promotion/templates/repository/${row.sequence}/import`,
        { method: "POST" },
      );
      const data = object(object(payload).data ?? payload);
      const action = field(data, "action");
      toast.success(action === "updated" ? "远程模板已更新" : "远程模板已添加到本地");
      await Promise.all([load(), loadRepository()]);
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "远程模板导入失败");
    } finally {
      setRepositoryPending("");
    }
  }
  async function chooseTemplatePackage(next: File | null) {
    const requestId = ++packageInspectionRequest.current;
    setFile(next);
    if (!next || editing) {
      setPackageInspecting(false);
      return;
    }
    setPackageInspecting(true);
    try {
      const body = new FormData();
      body.set("file", next);
      const payload = await apiRequest(
        "/api/promotion/templates/package-metadata",
        { method: "POST", body },
      );
      if (requestId !== packageInspectionRequest.current) return;
      const data = object(object(payload).data ?? payload);
      const metadata = object(data.metadata ?? data);
      setName(field(metadata, "name"));
      setDescription(field(metadata, "description"));
    } catch (caught) {
      if (requestId !== packageInspectionRequest.current) return;
      setName("");
      setDescription("");
      toast.error(
        caught instanceof Error ? caught.message : "模板 ZIP 元数据读取失败",
      );
    } finally {
      if (requestId === packageInspectionRequest.current) {
        setPackageInspecting(false);
      }
    }
  }
  async function upload(event?: FormEvent) {
    event?.preventDefault();
    if (!name.trim() || (!editing && !file) || (editing && !editing.id)) return;
    setPending(true);
    try {
      const body = new FormData();
      if (file) body.set("file", file);
      body.set("integrationIds", JSON.stringify(selectedIntegrationIds));
      body.set("name", name.trim());
      body.set("description", description.trim());
      if (editing) body.set("status", templateStatus);
      const payload = await apiRequest(
        editing
          ? `/api/promotion/templates/${editing.id}/edit`
          : "/api/promotion/templates",
        { method: "POST", body },
      );
      const data = object(object(payload).data ?? payload);
      const imported = templateRow(data.template ?? data);
      setDrawer(false);
      setEditing(null);
      setFile(null);
      setName("");
      setDescription("");
      setSelectedIntegrationIds([]);
      if (editing) {
        toast.success(file ? "模板及资源包已更新" : "模板已保存");
      } else {
        setQualityReviewing(imported);
        toast.success(
          imported.qualityReport.status === "warnings"
            ? `模板已导入，发现 ${imported.qualityReport.warnings.length} 项优化建议`
            : "模板已导入，质量检查通过",
        );
      }
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "导入失败");
    } finally {
      setPending(false);
    }
  }
  function openImport() {
    packageInspectionRequest.current += 1;
    setPackageInspecting(false);
    setEditing(null);
    setFile(null);
    setName("");
    setDescription("");
    setTemplateStatus("active");
    setSelectedIntegrationIds([]);
    setDrawer(true);
  }
  function openEditor(row: PromotionTemplate) {
    if (!row.id) return;
    packageInspectionRequest.current += 1;
    setPackageInspecting(false);
    setEditing(row);
    setFile(null);
    setName(row.name);
    setDescription(row.description);
    setTemplateStatus(row.status === "disabled" ? "disabled" : "active");
    setSelectedIntegrationIds(row.integrationIds);
    setDrawer(true);
  }
  function toggleIntegration(
    integrationId: string,
    values: string[],
    setValues: (next: string[]) => void,
  ) {
    setValues(
      values.includes(integrationId)
        ? values.filter((value) => value !== integrationId)
        : [...values, integrationId],
    );
  }
  function openPreview(row: PromotionTemplate) {
    if (!row.previewUrl) return;
    setPreviewing(row);
  }
  async function toggle(row: PromotionTemplate) {
    if (!row.id) return;
    try {
      await apiRequest(`/api/promotion/templates/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: row.status === "disabled" ? "active" : "disabled",
        }),
      });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "操作失败");
    }
  }
  async function removeTemplate(row: PromotionTemplate) {
    if (!canManage || !row.id) return;
    if (!(await confirmAction({
      title: `删除模板“${row.name}”？`,
      description: "这是永久删除操作；如果模板仍被推广渠道使用，系统会拒绝删除。",
      confirmText: "确认删除",
      destructive: true,
    }))) return;
    try {
      await apiRequest(`/api/promotion/templates/${row.id}`, { method: "DELETE" });
      toast.success("模板已删除");
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "模板删除失败");
    }
  }
  const loadPolicy = useCallback(async () => {
    setPolicyLoading(true);
    setPolicyError("");
    setPolicyLoaded(false);
    try {
      const payload = await apiRequest("/api/promotion/template-policy");
      const data = object(object(payload).data ?? payload);
      setPolicy(templatePolicyRow(data.policy || data));
      setPolicyLoaded(true);
    } catch (caught) {
      setPolicyError(
        caught instanceof Error ? caught.message : "模板策略读取失败",
      );
    } finally {
      setPolicyLoading(false);
    }
  }, []);
  function openPolicy() {
    setPolicyDrawer(true);
    void loadPolicy();
  }
  async function copyDesignSpec() {
    try {
      await navigator.clipboard.writeText(templateAiCreationPrompt());
      toast.success("设计规范已复制，可以直接发送给 AI");
    } catch {
      toast.error("复制失败，请检查浏览器剪贴板权限");
    }
  }
  async function downloadCapabilityTheme() {
    try {
      const result = await apiDownload(
        "/api/promotion/template-kits/account-link-elements-v1.zip",
      );
      const url = URL.createObjectURL(result.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = decodeURIComponent(
        result.filename || "account-link-capability-theme-v1.zip",
      );
      anchor.click();
      URL.revokeObjectURL(url);
      toast.success("白标能力主题已下载");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "下载失败");
    }
  }
  async function savePolicy() {
    if (!canManage || !policyLoaded || policyError) return;
    setPolicySaving(true);
    try {
      const payload = await apiRequest("/api/promotion/template-policy", {
        method: "PATCH",
        body: JSON.stringify({
          ...policy,
          eventRateLimitPolicy: eventRateLimitPayload(
            policy.eventRateLimitPolicy,
          ),
        }),
      });
      const data = object(object(payload).data ?? payload);
      setPolicy(templatePolicyRow(data.policy || data));
      setPolicyDrawer(false);
      toast.success("模板策略已保存");
    } catch (caught) {
      toast.error(
        caught instanceof Error ? caught.message : "模板策略保存失败",
      );
    } finally {
      setPolicySaving(false);
    }
  }
  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder:
            view === "local"
              ? "搜索模板名称、版本或状态"
              : "搜索远程模板名称、编号或版本",
        }}
        filters={
          <RepositorySourceTabs
            value={view}
            localLabel="本地模板"
            onChange={changeView}
          />
        }
        meta={`${view === "local" ? visible.length : repositoryVisible.length} 个模板`}
        actions={
          <>
            <Button
              variant={view === "repository" ? "default" : "outline"}
              disabled={view === "repository" && (repositoryLoading || repositoryRefreshing)}
              onClick={() => {
                if (view === "local") void load();
                else void (async () => {
                  const refreshed = await loadRepository({ refresh: true, preserve: true });
                  if (refreshed.ok) await load();
                })();
              }}
            >
              {repositoryRefreshing ? <Spinner /> : <RefreshCwIcon size={16} />}
              {view === "local" ? "刷新" : "刷新仓库"}
            </Button>
            {view === "local" ? <Button variant="outline" onClick={() => setDesignSpecDrawer(true)}>
              <BookOpenIcon size={16} />
              设计规范
            </Button> : null}
            {view === "local" ? <Button variant="outline" onClick={openPolicy}>
              <Settings2Icon size={16} />
              模板策略
            </Button> : null}
            {canManage && view === "local" ? (
              <Button onClick={() => openImport()}>
                <PlusIcon size={17} />
                导入模板
              </Button>
            ) : null}
          </>
        }
      />
      <ListPagination
        page={view === "local" ? templatePagination.page : repositoryPagination.page}
        pageSize={view === "local" ? templatePagination.pageSize : repositoryPagination.pageSize}
        total={view === "local" ? templatePagination.total : repositoryPagination.total}
        disabled={view === "local" ? loading : repositoryLoading}
        onPageChange={view === "local" ? templatePagination.setPage : repositoryPagination.setPage}
        onPageSizeChange={view === "local" ? templatePagination.setPageSize : repositoryPagination.setPageSize}
      />
      <ListTableCard>
        {view === "repository" ? (
          repositoryLoading ? (
            <div className="loading-state">
              <Spinner />
            </div>
          ) : repositoryError ? (
            <EmptyState
              title="远程仓库暂不可用"
              description={repositoryError}
            />
          ) : repositoryVisible.length ? (
            <Table layout="list">
              <TableHeader>
                <TableRow>
                  <TableHead>远程模板</TableHead>
                  <TableHead>版本</TableHead>
                  <TableHead>源码目录</TableHead>
                  <TableHead>资源</TableHead>
                  <TableHead>本地状态</TableHead>
                  <TableHead adaptive>备注</TableHead>
                  <TableHead>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {repositoryPagination.rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>
                      <EntityPrimaryCell
                        title={`${row.sequence} · ${row.name}`}
                        id={row.slug}
                        status={{
                          label: "远程仓库",
                          description: "此模板来自已配置的 GitHub 私人仓库。",
                          tone: "neutral",
                          details: [
                            { label: "版本", value: row.version },
                            { label: "文件", value: row.fileCount },
                            { label: "分支", value: row.ref },
                          ],
                        }}
                      />
                    </TableCell>
                    <TableCell>
                      <Badge tone="neutral">{row.version}</Badge>
                    </TableCell>
                    <TableCell>
                      <div className="cell-main max-w-72">
                        <strong>{row.repository}</strong>
                        <span className="truncate" title={row.source}>{row.source}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="cell-main">
                        <strong>{row.fileCount} 个文件</strong>
                        <span>{formatRepositorySize(row.totalSize)}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge
                        tone={
                          row.localStatus === "current"
                            ? "success"
                            : row.localStatus === "conflict"
                              ? "danger"
                              : row.localStatus === "update"
                                ? "warning"
                                : "neutral"
                        }
                      >
                        {row.localStatus === "current"
                          ? "已添加"
                          : row.localStatus === "conflict"
                            ? "版本冲突"
                            : row.localStatus === "update"
                              ? `可更新 · ${row.localVersion}`
                              : "未添加"}
                      </Badge>
                    </TableCell>
                    <TableCell className="whitespace-normal px-4 text-muted-foreground">
                      <span className="line-clamp-2 break-words" title={row.description || undefined}>
                        {row.description || "暂无备注"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-center gap-2">
                        <Button variant="outline" size="sm" asChild>
                          <a href={row.sourceUrl} target="_blank" rel="noreferrer">
                            源码
                          </a>
                        </Button>
                        {canManage ? (
                          <Button
                            size="sm"
                            variant={row.localStatus === "current" ? "outline" : "default"}
                            disabled={
                              row.localStatus === "current" ||
                              row.localStatus === "conflict" ||
                              Boolean(repositoryPending)
                            }
                            onClick={() => void importRepositoryTemplate(row)}
                          >
                            {repositoryPending === row.sequence ? <Spinner /> : null}
                            {row.localStatus === "update" ? "更新" : row.localStatus === "current" ? "已添加" : "添加到本地"}
                          </Button>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState
              title="远程仓库没有模板"
              description="当前目录清单中没有可用的远程模板。"
            />
          )
        ) : loading ? (
          <div className="loading-state">
            <Spinner />
          </div>
        ) : visible.length ? (
          <Table layout="list">
            <TableHeader>
              <TableRow>
                <TableHead>模板</TableHead>
                <TableHead>版本</TableHead>
                <TableHead>语言</TableHead>
                <TableHead>资源</TableHead>
                <TableHead>集成</TableHead>
                <TableHead>使用渠道</TableHead>
                <TableHead adaptive>备注</TableHead>
                <TableHead>创建时间</TableHead>
                <TableHead>更新时间</TableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {templatePagination.rows.map((row) => (
                <TableRow key={row.readKey}>
                  <TableCell>
                    <EntityPrimaryCell
                      title={row.name}
                      id={row.id}
                      status={{
                        label: row.status === "ready" || row.status === "active"
                          ? "可用"
                          : row.status === "disabled"
                            ? "已停用"
                            : "处理中",
                        description: row.status === "ready" || row.status === "active"
                          ? "模板已通过校验，可以用于推广渠道。"
                          : row.status === "disabled"
                            ? "模板已停用，现有渠道应停止继续使用。"
                            : "模板资源仍在校验或处理过程中。",
                        tone: row.status === "ready" || row.status === "active"
                          ? "success"
                          : row.status === "disabled"
                            ? "neutral"
                            : "warning",
                        details: [
                          { label: "版本", value: row.version.split(" · ")[0] },
                          { label: "语言", value: `${row.defaultLocale} · ${row.supportedLocales.length} 种` },
                          { label: "渠道", value: row.channelCount },
                        ],
                      }}
                    />
                  </TableCell>
                  <TableCell>
                    <Badge tone="neutral">{row.version.split(" · ")[0]}</Badge>
                  </TableCell>
                  <TableCell>
                    <div className="grid min-w-0 justify-items-center gap-1">
                      <strong>{row.defaultLocale}</strong>
                      <span className="text-xs text-muted-foreground">
                        {row.supportedLocales.length} 种语言
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="grid min-w-0 justify-items-center gap-1">
                      <strong>{row.assetCount} 个文件</strong>
                      <Badge
                        tone={
                          row.qualityReport.status === "passed"
                            ? "success"
                            : row.qualityReport.status === "warnings"
                              ? "warning"
                              : "neutral"
                        }
                      >
                        {row.qualityReport.status === "passed"
                          ? "检查通过"
                          : row.qualityReport.status === "warnings"
                            ? `${row.qualityReport.warnings.length} 项建议`
                            : "未检查"}
                      </Badge>
                    </div>
                  </TableCell>
                  <TableCell>{row.integrationIds.length} 个</TableCell>
                  <TableCell>{row.channelCount} 个渠道</TableCell>
                  <TableCell className="whitespace-normal px-4 text-muted-foreground">
                    <span className="line-clamp-2 break-words" title={row.description || undefined}>
                      {row.description || "暂无备注"}
                    </span>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(row.createdAt)}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(row.updatedAt)}
                  </TableCell>
                  <TableCell>
                    <div className="flex min-w-max items-center justify-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!row.previewUrl}
                        onClick={() => openPreview(row)}
                      >
                        预览
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setQualityReviewing(row)}
                      >
                        质量报告
                      </Button>
                      {canManage ? (
                        <>
                          {row.repositorySource?.localStatus === "update" ? (
                            <Button
                              size="sm"
                              disabled={Boolean(repositoryPending)}
                              onClick={() => void importRepositoryTemplate(row.repositorySource!)}
                            >
                              {repositoryPending === row.repositorySource.sequence ? <Spinner /> : null}
                              更新
                            </Button>
                          ) : row.repositorySource?.localStatus === "conflict" ? (
                            <Button size="sm" variant="outline" disabled>
                              版本冲突
                            </Button>
                          ) : null}
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={!row.id}
                            onClick={() => openEditor(row)}
                          >
                            编辑
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={!row.id}
                            onClick={() => void toggle(row)}
                          >
                            {row.status === "disabled" ? "启用" : "停用"}
                          </Button>
                          <Button
                            variant="destructive"
                            size="sm"
                            disabled={!row.id}
                            onClick={() => void removeTemplate(row)}
                          >
                            删除
                          </Button>
                        </>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <EmptyState
            title="还没有推广模板"
            description="导入一个符合规范的 ZIP 包开始创建 Facebook 推广渠道。"
          />
        )}
      </ListTableCard>
      <Drawer
        open={Boolean(previewing)}
        onClose={() => setPreviewing(null)}
        title={previewing ? `模拟预览 · ${previewing.name}` : "模拟预览"}
        description="快捷切换预览视口；只影响管理端模拟效果，不会改变模板文件或真实渠道页面。"
      >
        {previewing ? (
          <TemplatePreviewWorkspace template={previewing} />
        ) : null}
      </Drawer>
      <Drawer
        open={Boolean(qualityReviewing)}
        onClose={() => setQualityReviewing(null)}
        title={
          qualityReviewing
            ? `质量报告 · ${qualityReviewing.name}`
            : "模板质量报告"
        }
        description="导入时进行轻量静态检查；普通性能建议不会阻止模板使用。"
        footer={
          <Button variant="outline" onClick={() => setQualityReviewing(null)}>
            关闭
          </Button>
        }
      >
        {qualityReviewing ? (
          <div className="drawer-form">
            <div className="rounded-lg border bg-muted/30 p-3">
              <div className="flex items-center justify-between gap-3">
                <strong>检查结果</strong>
                <Badge
                  tone={
                    qualityReviewing.qualityReport.status === "passed"
                      ? "success"
                      : qualityReviewing.qualityReport.status === "warnings"
                        ? "warning"
                        : "neutral"
                  }
                >
                  {qualityReviewing.qualityReport.status === "passed"
                    ? "通过"
                    : qualityReviewing.qualityReport.status === "warnings"
                      ? `${qualityReviewing.qualityReport.warnings.length} 项建议`
                      : "历史版本未检查"}
                </Badge>
              </div>
            </div>
            {qualityReviewing.qualityReport.status !== "unchecked" ? (
              <div className="grid grid-cols-2 gap-3">
                {[
                  ["解压体积", formatTemplateBytes(qualityReviewing.qualityReport.metrics.expandedBytes)],
                  ["JS gzip", formatTemplateBytes(qualityReviewing.qualityReport.metrics.jsGzipBytes)],
                  ["CSS gzip", formatTemplateBytes(qualityReviewing.qualityReport.metrics.cssGzipBytes)],
                  ["图片", `${qualityReviewing.qualityReport.metrics.imageCount} 张 · ${formatTemplateBytes(qualityReviewing.qualityReport.metrics.imageBytes)}`],
                ].map(([label, value]) => (
                  <div className="rounded-lg border p-3" key={label}>
                    <small className="text-muted-foreground">{label}</small>
                    <strong className="mt-1 block">{value}</strong>
                  </div>
                ))}
              </div>
            ) : null}
            {qualityReviewing.qualityReport.warnings.length ? (
              <div className="space-y-3">
                {qualityReviewing.qualityReport.warnings.map((warning) => (
                  <div className="rounded-lg border border-amber-600/20 bg-amber-600/5 p-3" key={warning.code}>
                    <strong>{warning.message}</strong>
                    {warning.paths.length ? (
                      <small className="mt-1 block break-all text-muted-foreground">
                        {warning.paths.join("、")}
                      </small>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : qualityReviewing.qualityReport.status === "passed" ? (
              <div className="rounded-lg border border-emerald-600/20 bg-emerald-600/5 p-3 text-sm">
                未发现需要提示的结构、资源或性能问题。
              </div>
            ) : (
              <div className="rounded-lg border bg-muted/30 p-3 text-sm text-muted-foreground">
                这是质量检查功能上线前导入的历史版本；替换 ZIP 后会自动生成报告。
              </div>
            )}
          </div>
        ) : null}
      </Drawer>
      <Drawer
        open={designSpecDrawer}
        onClose={() => setDesignSpecDrawer(false)}
        title="推广模板设计规范"
        description="面向设计、开发和 AI 生成的 v2 白标组件主题标准。可下载能力主题或复制完整 AI 提示词。"
        footer={
          <>
            <Button
              variant="outline"
              onClick={() => setDesignSpecDrawer(false)}
            >
              关闭
            </Button>
            <Button variant="outline" onClick={() => void downloadCapabilityTheme()}>
              <DownloadIcon size={16} />
              下载白标能力主题
            </Button>
            <Button onClick={() => void copyDesignSpec()}>
              <CopyIcon size={16} />
              复制给 AI
            </Button>
          </>
        }
      >
        <div className="template-design-spec">
          <div className="template-design-spec__intro">
            <strong>使用方式</strong>
            <p>
              下载白标能力主题后，只改布局、CSS、品牌内容和资源；也可以复制完整规范给
              AI，再补充品牌名称、视觉风格、主色、目标国家和文案语气。
            </p>
          </div>
          {TEMPLATE_DESIGN_SECTIONS.map((section) => (
            <section className="template-design-spec__section" key={section.title}>
              <h3>{section.title}</h3>
              {section.description ? <p>{section.description}</p> : null}
              <ul className={section.checklist ? "is-checklist" : undefined}>
                {section.bullets.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              {section.code ? (
                <pre>
                  <code>{section.code}</code>
                </pre>
              ) : null}
            </section>
          ))}
        </div>
      </Drawer>
      <Drawer
        open={policyDrawer}
        onClose={() => !policySaving && setPolicyDrawer(false)}
        title="模板策略"
        description="统一设置推广运行时的前端防护、匿名设备环境信号与数据回传限速。"
        footer={
          <>
            <Button
              variant="outline"
              disabled={policySaving}
              onClick={() => setPolicyDrawer(false)}
            >
              {canManage ? "取消" : "关闭"}
            </Button>
            {canManage ? (
              <Button
                disabled={
                  policyLoading ||
                  policySaving ||
                  !policyLoaded ||
                  Boolean(policyError) ||
                  !validEventRateLimitPolicy(policy.eventRateLimitPolicy)
                }
                onClick={() => void savePolicy()}
              >
                {policySaving ? <Spinner /> : <Settings2Icon size={16} />}
                保存策略
              </Button>
            ) : null}
          </>
        }
      >
        {policyLoading ? (
          <div className="loading-state min-h-64">
            <Spinner />
            正在读取模板策略…
          </div>
        ) : policyError ? (
          <div className="error-state min-h-64">
            <strong>模板策略读取失败</strong>
            <span>{policyError}</span>
            <Button variant="outline" onClick={() => void loadPolicy()}>
              <RefreshCwIcon size={16} />
              重新读取
            </Button>
          </div>
        ) : policyLoaded ? (
          <div className="drawer-form">
            {!canManage ? (
              <div className="rounded-lg border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
                当前账号只有查看权限，不能修改模板策略。
              </div>
            ) : null}
            <label className="field">
              <DrawerFieldLabel required>防护级别</DrawerFieldLabel>
              <SelectField
                value={policy.protectionMode}
                disabled={!canManage || policySaving}
                onValueChange={(value) =>
                  setPolicy((current) => ({
                    ...current,
                    protectionMode: value as TemplateProtectionMode,
                  }))
                }
                options={[
                  { value: "basic", label: "基础防护" },
                  { value: "enhanced", label: "增强防护" },
                  { value: "strict", label: "严格防护" },
                ]}
              />
              <small>
                {policy.protectionMode === "basic"
                  ? "基础：限制右键菜单和常用开发者工具快捷键。"
                  : policy.protectionMode === "enhanced"
                    ? "增强：在基础防护上增加窗口尺寸检测、Eruda / vConsole 检测及 console 副作用检测。"
                    : "严格：在增强防护上增加执行耗时与 debugger 停顿检测。"}
              </small>
            </label>
            <label className="field">
              <DrawerFieldLabel required>检测到开发者工具时</DrawerFieldLabel>
              <SelectField
                value={policy.devtoolsAction}
                disabled={
                  !canManage ||
                  policySaving ||
                  policy.protectionMode === "basic"
                }
                onValueChange={(value) =>
                  setPolicy((current) => ({
                    ...current,
                    devtoolsAction: value as TemplateDevtoolsAction,
                  }))
                }
                options={[
                  { value: "log", label: "仅记录" },
                  { value: "block", label: "阻止交互" },
                  { value: "blank", label: "显示空白页" },
                ]}
              />
              <small>
                此动作仅用于增强或严格防护；基础模式不会执行开发者工具处置动作。
              </small>
            </label>
            <label className="switch-row">
              <span>
                <strong>锁定视口缩放</strong>
                <small>限制页面手势缩放，减少布局被意外放大或缩小。</small>
              </span>
              <Switch
                checked={policy.lockViewportZoom}
                disabled={!canManage || policySaving}
                onCheckedChange={(checked) =>
                  setPolicy((current) => ({
                    ...current,
                    lockViewportZoom: checked,
                  }))
                }
                aria-label="锁定视口缩放"
              />
            </label>
            <label className="field">
              <DrawerFieldLabel required>设备环境信号</DrawerFieldLabel>
              <SelectField
                value={policy.deviceSignals}
                disabled={!canManage || policySaving}
                onValueChange={(value) =>
                  setPolicy((current) => ({
                    ...current,
                    deviceSignals: value as TemplateDeviceSignals,
                  }))
                }
                options={[
                  { value: "off", label: "关闭" },
                  { value: "standard", label: "标准" },
                  { value: "enhanced", label: "增强" },
                  { value: "fingerprint", label: "复合设备指纹" },
                ]}
              />
              <small>
                复合设备指纹使用 Canvas、音频、字体、WebGL
                等匿名哈希增强跨会话访客识别，不采集原始渲染数据、WhatsApp
                号码或账号凭据。
              </small>
            </label>
            <div className="rounded-lg border border-amber-600/20 bg-amber-600/5 p-3 text-sm text-muted-foreground">
              设备指纹由平台公共运行时统一采集，并在服务端按租户隔离；模板不能自行采集、保存或外传原始指纹信号。
            </div>
            {EVENT_RATE_LIMIT_FIELDS.map(([key, label, description]) => (
              <div className="field" key={key}>
                <span>{label}</span>
                <div className="grid min-w-0 grid-cols-2 gap-2">
                  <label className="grid min-w-0 gap-1 text-xs text-muted-foreground">
                    <DrawerFieldLabel required>最多请求</DrawerFieldLabel>
                    <Input
                      type="number"
                      min={1}
                      max={1_000_000}
                      disabled={!canManage || policySaving}
                      value={policy.eventRateLimitPolicy[key].maxRequests}
                      onChange={(event) =>
                        setPolicy((current) => ({
                          ...current,
                          eventRateLimitPolicy: {
                            ...current.eventRateLimitPolicy,
                            [key]: {
                              ...current.eventRateLimitPolicy[key],
                              maxRequests: event.target.value,
                            },
                          },
                        }))
                      }
                    />
                  </label>
                  <label className="grid min-w-0 gap-1 text-xs text-muted-foreground">
                    <DrawerFieldLabel required>统计窗口（秒）</DrawerFieldLabel>
                    <Input
                      type="number"
                      min={1}
                      max={86_400}
                      disabled={!canManage || policySaving}
                      value={policy.eventRateLimitPolicy[key].windowSeconds}
                      onChange={(event) =>
                        setPolicy((current) => ({
                          ...current,
                          eventRateLimitPolicy: {
                            ...current.eventRateLimitPolicy,
                            [key]: {
                              ...current.eventRateLimitPolicy[key],
                              windowSeconds: event.target.value,
                            },
                          },
                        }))
                      }
                    />
                  </label>
                </div>
                <small>{description}</small>
              </div>
            ))}
          </div>
        ) : null}
      </Drawer>
      <Drawer
        open={drawer}
        onClose={() => !pending && setDrawer(false)}
        title={editing ? `编辑模板 · ${editing.name}` : "导入推广模板"}
        description={
          editing
            ? "统一修改名称、内部说明、启用状态和集成；如需更新资源，可同时选择新的 ZIP。"
            : "上传 ZIP 模板文件并创建新的可用版本；导入完成后会生成轻量质量报告。"
        }
        footer={
          <>
            <Button variant="outline" onClick={() => setDrawer(false)}>
              取消
            </Button>
            <Button
              disabled={pending || packageInspecting || !name.trim() || (!editing && !file)}
              onClick={() => void upload()}
            >
              {pending ? (
                <LoaderCircleIcon className="spin" size={16} />
              ) : (
                <UploadCloudIcon size={16} />
              )}
              {editing ? "保存模板" : "开始导入"}
            </Button>
          </>
        }
      >
        <form className="drawer-form" onSubmit={upload}>
          <label className="upload-zone">
            <Input
              type="file"
              accept=".zip,application/zip"
              onChange={(event) =>
                void chooseTemplatePackage(event.target.files?.[0] || null)
              }
            />
            <UploadCloudIcon size={27} />
            <strong>
              <DrawerFieldLabel required={!editing}>
                {file?.name || (editing ? "可选：选择新的模板 ZIP" : "选择模板 ZIP 文件")}
              </DrawerFieldLabel>
            </strong>
            <span>
              {packageInspecting
                ? "正在读取包内名称和说明…"
                : editing
                  ? "不选择则只保存管理信息和集成配置；选择后同时替换模板资源"
                  : "仅支持 .zip，最大 20 MB；包内元数据会自动填写且可修改"}
            </span>
          </label>
          <label className="field">
            <DrawerFieldLabel required>模板名称</DrawerFieldLabel>
            <Input
              value={name}
              maxLength={120}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：FB 美区夏季促销"
            />
          </label>
          <label className="field">
            <DrawerFieldLabel>内部说明</DrawerFieldLabel>
            <Input
              value={description}
              maxLength={2000}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="说明模板适用场景"
            />
          </label>
          {editing ? (
            <label className="switch-row">
              <span>
                <strong>启用模板</strong>
                <small>停用后模板不可用于新的推广渠道。</small>
              </span>
              <Switch
                checked={templateStatus !== "disabled"}
                onCheckedChange={(checked) =>
                  setTemplateStatus(checked ? "active" : "disabled")
                }
                aria-label="启用模板"
              />
            </label>
          ) : null}
          <RuntimeIntegrationSwitches
            integrations={integrations}
            selectedIds={selectedIntegrationIds}
            disabled={pending}
            onToggle={(integrationId) =>
              toggleIntegration(
                integrationId,
                selectedIntegrationIds,
                setSelectedIntegrationIds,
              )
            }
          />
        </form>
      </Drawer>
    </StandardListPage>
  );
}

export function PromotionChannelsPage() {
  const { can } = useAuth();
  const canManage = can("promotion.channels.manage");
  const canManageMetrics = can("promotion.statistics.manage");
  const [rows, setRows] = useState<PromotionChannel[]>([]);
  const [templates, setTemplates] = useState<TemplateOption[]>([]);
  const [accountGroups, setAccountGroups] = useState<Option[]>([]);
  const [protocolNodes, setProtocolNodes] = useState<ProtocolOption[]>([]);
  const [protocolPools, setProtocolPools] = useState<ProtocolOption[]>([]);
  const [domains, setDomains] = useState<Option[]>([]);
  const [pixels, setPixels] = useState<PixelOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [drawer, setDrawer] = useState(false);
  const [editing, setEditing] = useState<PromotionChannel | null>(null);
  const [pending, setPending] = useState(false);
  const [pixelDrawer, setPixelDrawer] = useState(false);
  const [pixelPending, setPixelPending] = useState(false);
  const [pixelForm, setPixelForm] = useState({
    name: "",
    datasetId: "",
    capiToken: "",
  });
  const [capiProbeOpen, setCapiProbeOpen] = useState(false);
  const [capiProbePending, setCapiProbePending] = useState(false);
  const [capiProbeChannelId, setCapiProbeChannelId] = useState("");
  const [capiProbeResult, setCapiProbeResult] =
    useState<MetaCapiProbeResult | null>(null);
  const [insightOpen, setInsightOpen] = useState(false);
  const [insightChannelId, setInsightChannelId] = useState("");
  const [insightLoading, setInsightLoading] = useState(false);
  const [insightStats, setInsightStats] = useState<Record<string, number>>({});
  const [pairingFunnel, setPairingFunnel] = useState<PairingFunnelStep[]>([]);
  const [pairingFailureTotal, setPairingFailureTotal] = useState(0);
  const [pairingFailures, setPairingFailures] = useState<
    PairingFailureReason[]
  >([]);
  const [metaDeliverySummary, setMetaDeliverySummary] = useState<
    Record<string, number>
  >({});
  const [insightLeads, setInsightLeads] = useState<
    Array<Record<string, unknown>>
  >([]);
  const [metrics, setMetrics] = useState<AdMetric[]>([]);
  const [metricDrawer, setMetricDrawer] = useState(false);
  const [metricEditing, setMetricEditing] = useState<AdMetric | null>(null);
  const [metricPending, setMetricPending] = useState(false);
  const [metricForm, setMetricForm] = useState({
    date: formatLocalDateInput(),
    spend: "",
    impressions: "",
    clicks: "",
  });
  const [form, setForm] = useState({
    name: "",
    countryCode: "US",
    templateId: "",
    accountGroupId: "",
    protocolRouteType: "node" as "node" | "pool",
    protocolRouteId: "",
    domainId: "",
    subdomainPrefix: "",
    slug: "",
    pixelId: "",
    metaBrowserPixelEnabled: false,
    metaCapiEnabled: false,
    metaEventMapping: { ...defaultMetaEventMapping },
    inAppBrowserMode: "guide_external" as "allow" | "guide_external",
    newAccountMarketingEnabled: true,
    localeMode: "auto",
    locale: "",
    goLiveAt: "",
    enabled: true,
  });
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [c, t, d, p, g, pn, pp] = await Promise.all([
        apiRequest("/api/promotion/channels?pageSize=100"),
        apiRequest("/api/promotion/templates?pageSize=100"),
        apiRequest("/api/domains/available-for-channels"),
        apiRequest("/api/meta-pixels?pageSize=100"),
        apiRequest("/api/account-groups?pageSize=100"),
        apiRequest("/api/protocol-nodes?pageSize=100"),
        apiRequest("/api/protocol-pools?pageSize=100"),
      ]);
      setRows(unwrapList<unknown>(c).rows.map(channelRow));
      setTemplates(
        unwrapList<unknown>(t).rows.map((input) => {
          const row = object(input);
          const manifest = object(row.manifest);
          const rawLocales = row.supportedLocales || row.supported_locales;
          const locales = Array.isArray(rawLocales)
            ? rawLocales.map(String)
            : Array.isArray(manifest.supportedLocales)
              ? manifest.supportedLocales.map(String)
              : [String(row.defaultLocale || manifest.defaultLocale || "en")];
          return {
            id: snowflakeId(row, "id"),
            label: `${field(row, "name")} · ${field(row, "version") || "v1"}`,
            locales,
            schema: field(manifest, "schema") || "promotion-template/v1",
            runtime: field(manifest, "runtime") || "promotion-browser-bridge/v1",
            pairingContract:
              field(object(manifest.requirements), "pairingContract") ||
              "promotion-public-pairing/v1",
          };
        }).filter((row) => row.id),
      );
      setDomains(
        unwrapList<unknown>(d).rows.map((input) => {
          const row = object(input);
          return {
            id: snowflakeId(row, "id"),
            label: field(row, "hostname"),
          };
        }).filter((row) => row.id),
      );
      setPixels(unwrapList<unknown>(p).rows.map(pixelRow));
      setAccountGroups(
        unwrapList<unknown>(g).rows
          .map((input) => {
            const row = object(input);
            const id = snowflakeId(row, "id");
            return { id, label: field(row, "name") || id };
          })
          .filter((row) => row.id),
      );
      setProtocolNodes(
        unwrapList<unknown>(pn).rows.map((input) => {
          const row = object(input); const id = snowflakeId(row, "id");
          return {
            id,
            label: field(row, "name") || id,
            health: field(row, "healthStatus", "health_status") || "offline",
            healthReason: field(row, "healthReason", "health_reason"),
          };
        }).filter((row) => row.id),
      );
      setProtocolPools(
        unwrapList<unknown>(pp).rows.map((input) => {
          const row = object(input); const id = snowflakeId(row, "id");
          const members = Array.isArray(row.members) ? row.members.map(object) : [];
          const available = members.some((member) => Boolean(member.available));
          return {
            id,
            label: field(row, "name") || id,
            health: available ? "available" : "offline",
            healthReason: available ? "" : "协议池中没有可接入节点",
          };
        }).filter((row) => row.id),
      );
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const visible = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return search
      ? rows.filter((row) =>
          `${row.name} ${row.countryCode} ${countryDisplayName(row.countryCode)} ${row.platform} ${platformDisplayName(row.platform)} ${row.hostname} ${row.slug} ${row.accountGroupName}`
            .toLowerCase()
            .includes(search),
        )
      : rows;
  }, [keyword, rows]);
  const channelPagination = useClientPagination(visible, { resetKey: keyword });
  const pixelPagination = useClientPagination(pixels, {
    resetKey: String(pixelDrawer),
  });
  const metricPagination = useClientPagination(metrics, {
    resetKey: insightChannelId,
  });
  const leadPagination = useClientPagination(insightLeads, {
    resetKey: insightChannelId,
  });
  function open(row?: PromotionChannel) {
    if (row && !row.id) return;
    setEditing(row || null);
    setForm(
      row
        ? {
            name: row.name,
            countryCode: row.countryCode,
            templateId: row.templateId,
            accountGroupId: row.accountGroupId,
            protocolRouteType: row.protocolPoolId ? "pool" : "node",
            protocolRouteId: row.protocolPoolId || row.protocolNodeId,
            domainId: row.domainId,
            subdomainPrefix: row.subdomainPrefix,
            slug: row.slug,
            pixelId: row.pixelId,
            metaBrowserPixelEnabled: row.metaBrowserPixelEnabled,
            metaCapiEnabled: row.metaCapiEnabled,
            metaEventMapping: { ...row.metaEventMapping },
            inAppBrowserMode: row.inAppBrowserMode,
            newAccountMarketingEnabled: row.newAccountMarketingEnabled,
            localeMode: row.localeMode,
            locale: row.locale,
            goLiveAt: row.goLiveAt?.slice(0, 16) || "",
            enabled: row.enabled,
          }
        : {
            name: "",
            countryCode: "US",
            templateId: templates[0]?.id || "",
            accountGroupId: accountGroups[0]?.id || "",
            protocolRouteType: "node",
            protocolRouteId: protocolNodes[0]?.id || "",
            domainId: "",
            subdomainPrefix: "",
            slug: randomChannelCode(rows.map((item) => item.slug)),
            pixelId: "",
            metaBrowserPixelEnabled: false,
            metaCapiEnabled: false,
            metaEventMapping: { ...defaultMetaEventMapping },
            inAppBrowserMode: "guide_external",
            newAccountMarketingEnabled: true,
            localeMode: "auto",
            locale: "",
            goLiveAt: "",
            enabled: true,
          },
    );
    setDrawer(true);
  }
  async function save() {
    if (
      !form.name.trim() ||
      !form.templateId ||
      !form.accountGroupId ||
      !form.protocolRouteId ||
      !form.domainId ||
      !form.slug.trim() ||
      (editing && !editing.id)
    )
      return;
    setPending(true);
    try {
      const body = {
        type: "facebook",
        name: form.name.trim(),
        countryCode: form.countryCode.toUpperCase(),
        templateId: form.templateId,
        accountGroupId: form.accountGroupId,
        protocolNodeId: form.protocolRouteType === "node" ? form.protocolRouteId : null,
        protocolPoolId: form.protocolRouteType === "pool" ? form.protocolRouteId : null,
        domainId: form.domainId || undefined,
        subdomainPrefix: form.subdomainPrefix || undefined,
        slug: form.slug.trim(),
        pixelId: form.pixelId || null,
        metaBrowserPixelEnabled: Boolean(
          form.pixelId && form.metaBrowserPixelEnabled,
        ),
        metaCapiEnabled: Boolean(form.pixelId && form.metaCapiEnabled),
        metaEventMapping: form.metaEventMapping,
        inAppBrowserMode: form.inAppBrowserMode,
        newAccountMarketingEnabled: form.newAccountMarketingEnabled,
        localeMode: form.localeMode,
        locale:
          form.localeMode === "fixed" ? form.locale || undefined : undefined,
        status: form.enabled ? "active" : "draft",
        launchAt: form.goLiveAt
          ? new Date(form.goLiveAt).toISOString()
          : undefined,
      };
      await apiRequest(
        editing
          ? `/api/promotion/channels/${editing.id}`
          : "/api/promotion/channels",
        { method: editing ? "PATCH" : "POST", body: JSON.stringify(body) },
      );
      setDrawer(false);
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setPending(false);
    }
  }
  const selectedDomain = domains.find((row) => row.id === form.domainId);
  const previewHostname = selectedDomain
    ? `${form.subdomainPrefix ? `${form.subdomainPrefix}.` : ""}${selectedDomain.label}`
    : "";
  const previewPublicUrl = previewHostname
    ? `https://${previewHostname}/${form.slug || "短码"}`
    : "";
  const selectedTemplate = templates.find((row) => row.id === form.templateId);
  const selectedRoute = (form.protocolRouteType === "node"
    ? protocolNodes
    : protocolPools
  ).find((row) => row.id === form.protocolRouteId);
  const selectedPixel = pixels.find((row) => row.id === form.pixelId);
  const capiProbeChannel = rows.find(
    (row) => row.id === capiProbeChannelId,
  );
  async function copyPublicUrl(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      toast.success("访问地址已复制");
    } catch {
      toast.error("复制失败，请手动复制");
    }
  }
  async function toggle(row: PromotionChannel) {
    if (!row.id) return;
    try {
      await apiRequest(`/api/promotion/channels/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: row.enabled ? "paused" : "active" }),
      });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "操作失败");
    }
  }
  async function probeCapi(row: PromotionChannel) {
    if (!row.id) return;
    setCapiProbeChannelId(row.id);
    setCapiProbeResult(null);
    setCapiProbeOpen(true);
    setCapiProbePending(true);
    try {
      const response = object(
        await apiRequest(
          `/api/promotion/channels/${row.id}/meta-capi-probe`,
          { method: "POST" },
        ),
      );
      const result = object(response.data);
      setCapiProbeResult({
        ok: Boolean(result.ok),
        datasetId: field(result, "datasetId"),
        eventName: field(result, "eventName"),
        eventId: field(result, "eventId"),
        providerTraceId: field(result, "providerTraceId"),
        httpStatus:
          result.httpStatus == null ? undefined : Number(result.httpStatus),
        sendError: field(result, "sendError"),
      });
    } catch (caught) {
      setCapiProbeResult({
        ok: false,
        datasetId: "",
        eventName: "ParloqCapiProbe",
        eventId: "",
        providerTraceId: "",
        sendError:
          caught instanceof Error ? caught.message : "CAPI 探测请求失败",
      });
    } finally {
      setCapiProbePending(false);
    }
  }
  async function openInsights() {
    if (!insightChannelId) return;
    setInsightOpen(true);
    setInsightLoading(true);
    const [statsPayload, leadsPayload, metricsPayload, metaPayload] = await Promise.all([
      apiRequest(`/api/promotion/channels/${insightChannelId}/stats`).catch(
        () => null,
      ),
      apiRequest(
        `/api/promotion/channels/${insightChannelId}/leads?pageSize=100`,
      ).catch(() => null),
      apiRequest(
        `/api/promotion/ad-metrics?promotionChannelId=${encodeURIComponent(insightChannelId)}&pageSize=100`,
      ).catch(() => null),
      apiRequest(
        `/api/promotion/channels/${insightChannelId}/meta-deliveries?pageSize=1`,
      ).catch(() => null),
    ]);
    const statsData = ((
      statsPayload as { data?: Record<string, unknown> } | null
    )?.data || {}) as Record<string, unknown>;
    const stats = (statsData.totals ||
      statsData.stats ||
      statsData.summary ||
      statsData) as Record<string, unknown>;
    const pairingFunnelData = object(statsData.pairingFunnel);
    const pairingFailureData = object(statsData.pairingFailures);
    const funnelSteps = Array.isArray(pairingFunnelData.steps)
      ? pairingFunnelData.steps.map(object)
      : [];
    const failureReasons = Array.isArray(pairingFailureData.reasons)
      ? pairingFailureData.reasons.map(object)
      : [];
    setInsightStats({
      visits: Number(stats.visits ?? stats.pageView ?? stats.pageViews ?? 0),
      visitors: Number(stats.uv ?? stats.visitors ?? 0),
      fingerprintCoverageRate:
        Number(stats.fingerprintCoverageRate ?? 0) * 100,
      completedVisits: Number(stats.visitEnd ?? stats.completedVisits ?? 0),
      leads: Number(
        stats.uniqueLeads ??
          stats.leads ??
          stats.phoneSubmit ??
          stats.phoneSubmits ??
          0,
      ),
      submissions: Number(stats.phoneSubmit ?? stats.phoneSubmits ?? 0),
    });
    setPairingFunnel(
      funnelSteps.map((step) => ({
        key: field(step, "key"),
        count: Number(step.count || 0),
        visitorRate: Number(step.visitorRate || 0),
        stepRate: Number(step.stepRate || 0),
      })),
    );
    setPairingFailureTotal(Number(pairingFailureData.total || 0));
    setPairingFailures(
      failureReasons.map((reason) => ({
        code: field(reason, "code"),
        label: field(reason, "label") || "其他失败",
        count: Number(reason.count || 0),
        share: Number(reason.share || 0),
      })),
    );
    setInsightLeads(
      leadsPayload
        ? unwrapList<Record<string, unknown>>(leadsPayload).rows
        : [],
    );
    setMetrics(
      metricsPayload
        ? unwrapList<unknown>(metricsPayload).rows.map(metricRow)
        : [],
    );
    const metaData = object(
      (metaPayload as { data?: unknown } | null)?.data || metaPayload,
    );
    const metaSummary = object(metaData.summary);
    setMetaDeliverySummary({
      pending: Number(metaSummary.pending || 0),
      retry: Number(metaSummary.retry || 0),
      delivered: Number(metaSummary.delivered || 0),
      failed: Number(metaSummary.failed || 0),
    });
    setInsightLoading(false);
  }
  function openMetric(row?: AdMetric) {
    if (row && !row.id) return;
    setMetricEditing(row || null);
    setMetricForm(
      row
        ? {
            date: row.date,
            spend: String(row.spend),
            impressions: String(row.impressions),
            clicks: String(row.clicks),
          }
        : {
            date: formatLocalDateInput(),
            spend: "",
            impressions: "",
            clicks: "",
          },
    );
    setMetricDrawer(true);
  }
  async function saveMetric() {
    if (!insightChannelId || !metricForm.date || (metricEditing && !metricEditing.id)) return;
    setMetricPending(true);
    try {
      const body = {
        date: metricForm.date,
        promotionChannelId: insightChannelId,
        spend: Number(metricForm.spend || 0),
        impressions: Number(metricForm.impressions || 0),
        clicks: Number(metricForm.clicks || 0),
      };
      await apiRequest(
        metricEditing
          ? `/api/promotion/ad-metrics/${metricEditing.id}`
          : "/api/promotion/ad-metrics",
        {
          method: metricEditing ? "PATCH" : "POST",
          body: JSON.stringify(body),
        },
      );
      setMetricDrawer(false);
      await openInsights();
    } catch (caught) {
      toast.error(
        caught instanceof Error ? caught.message : "保存日投放数据失败",
      );
    } finally {
      setMetricPending(false);
    }
  }
  async function removeMetric(row: AdMetric) {
    if (!row.id) return;
    if (
      !(await confirmAction({
        title: `删除 ${row.date} 的 Facebook 日投放数据？`,
        description: "删除后不会影响系统自动采集的渠道事件。",
        confirmText: "确认删除",
      }))
    )
      return;
    try {
      await apiRequest(`/api/promotion/ad-metrics/${row.id}`, {
        method: "DELETE",
      });
      await openInsights();
    } catch (caught) {
      toast.error(
        caught instanceof Error ? caught.message : "删除日投放数据失败",
      );
    }
  }
  async function createPixel() {
    if (!pixelForm.name.trim() || !pixelForm.datasetId.trim()) return;
    setPixelPending(true);
    try {
      await apiRequest("/api/meta-pixels", {
        method: "POST",
        body: JSON.stringify({
          name: pixelForm.name.trim(),
          datasetId: pixelForm.datasetId.trim(),
          capiToken: pixelForm.capiToken.trim() || undefined,
          enabled: true,
        }),
      });
      setPixelForm({ name: "", datasetId: "", capiToken: "" });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "保存 Pixel 失败");
    } finally {
      setPixelPending(false);
    }
  }
  async function togglePixel(row: PixelOption) {
    if (!row.id) return;
    try {
      await apiRequest(`/api/meta-pixels/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !row.enabled }),
      });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "更新 Pixel 失败");
    }
  }
  async function removePixel(row: PixelOption) {
    if (!row.id) return;
    if (
      !(await confirmAction({
        title: `删除 Pixel“${row.name}”？`,
        description: "删除后无法恢复，相关 CAPI 投递记录会一并删除，已有渠道将解除 Pixel 绑定。",
        confirmText: "确认删除",
        destructive: true,
      }))
    )
      return;
    try {
      await apiRequest(`/api/meta-pixels/${row.id}`, { method: "DELETE" });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "删除 Pixel 失败");
    }
  }
  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: "搜索渠道、国家、域名或 Slug",
        }}
        filters={
          <div className="channel-data-bar">
            <SelectField
              className="w-[280px]"
              value={insightChannelId}
              onValueChange={setInsightChannelId}
              placeholder="选择渠道查看数据和号码"
              options={rows.filter((row) => row.id).map((row) => ({ value: row.id, label: row.name }))}
            />
            <Button
              variant="outline"
              disabled={!insightChannelId}
              onClick={() => void openInsights()}
            >
              <EyeIcon size={16} />
              查看渠道数据
            </Button>
          </div>
        }
        meta={`${visible.length} 个渠道`}
        actions={
          <>
            <Button variant="outline" onClick={() => void load()}>
              <RefreshCwIcon size={16} />
              刷新
            </Button>
            {canManage ? (
              <>
                <Button variant="outline" onClick={() => setPixelDrawer(true)}>
                  <Settings2Icon size={17} />
                  Pixel 管理
                </Button>
                <Button onClick={() => open()}>
                  <PlusIcon size={17} />
                  新建渠道
                </Button>
              </>
            ) : null}
          </>
        }
      />
      <ListPagination
        page={channelPagination.page}
        pageSize={channelPagination.pageSize}
        total={channelPagination.total}
        disabled={loading}
        onPageChange={channelPagination.setPage}
        onPageSizeChange={channelPagination.setPageSize}
      />
      <ListTableCard>
        {loading ? (
          <div className="loading-state">
            <Spinner />
          </div>
        ) : visible.length ? (
          <Table layout="list">
            <TableHeader>
              <TableRow>
                <TableHead>渠道</TableHead>
                <TableHead>国家</TableHead>
                <TableHead>平台</TableHead>
                <TableHead>模板</TableHead>
                <TableHead>账号入库分组</TableHead>
                <TableHead adaptive>访问地址</TableHead>
                <TableHead>Pixel</TableHead>
                <TableHead>FB 域名状态</TableHead>
                <TableHead>语言</TableHead>
                <TableHead>创建时间</TableHead>
                <TableHead>更新时间</TableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {channelPagination.rows.map((row) => (
                <TableRow key={row.readKey}>
                  <TableCell>
                    <EntityPrimaryCell
                      title={row.name}
                      id={row.id}
                      status={{
                        label: row.enabled ? "启用" : "停用",
                        description: row.enabled
                          ? "渠道已启用，到达上线时间后可以通过访问地址对外提供页面。"
                          : "渠道已停用，访问地址不应继续承接流量。",
                        tone: row.enabled ? "success" : "neutral",
                        details: [
                          { label: "国家", value: row.countryCode || "-" },
                          { label: "域名", value: row.hostname || "未绑定" },
                          { label: "模板", value: row.templateName || row.templateId || "-" },
                          { label: "入库分组", value: row.accountGroupName || "未配置" },
                          { label: "协议路由", value: row.protocolPoolName ? `池：${row.protocolPoolName}` : row.protocolNodeName || "未配置" },
                        ],
                      }}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="flex min-w-max items-center justify-center gap-2">
                      <CountryFlag code={row.countryCode} />
                      <span>{countryDisplayName(row.countryCode)}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex min-w-max items-center justify-center gap-2">
                      <PlatformLogo platform={row.platform} />
                      <span>{platformDisplayName(row.platform)}</span>
                    </div>
                  </TableCell>
                  <TableCell>{row.templateName || row.templateId}</TableCell>
                  <TableCell>
                    <div className="cell-main mx-auto">
                      <strong>{row.accountGroupName || "未配置"}</strong>
                      <span>{row.accountGroupId || "-"}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="cell-main mx-auto">
                      <strong title={row.hostname || undefined}>{row.hostname || "-"}</strong>
                      <span className="inline-link">
                        /{row.slug}
                        {row.publicUrl ? (
                          <>
                            <IconButton
                              label="打开访问地址"
                              className="mini-icon"
                              onClick={() =>
                                window.open(row.publicUrl, "_blank", "noopener,noreferrer")
                              }
                            >
                              <ExternalLinkIcon size={14} />
                            </IconButton>
                            <IconButton
                              label="复制访问地址"
                              className="mini-icon"
                              onClick={() => void copyPublicUrl(row.publicUrl)}
                            >
                              <CopyIcon size={14} />
                            </IconButton>
                          </>
                        ) : null}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex min-w-max flex-col items-center gap-1.5">
                      {row.pixelId ? (
                        <>
                          <span className="text-foreground">{row.pixelName || "已绑定 Pixel"}</span>
                          <span className="flex flex-wrap justify-center gap-1">
                            {row.metaBrowserPixelEnabled ? (
                              <Badge tone="success">浏览器</Badge>
                            ) : null}
                            {row.metaCapiEnabled ? <Badge tone="success">CAPI</Badge> : null}
                            {!row.metaBrowserPixelEnabled && !row.metaCapiEnabled ? (
                              <Badge tone="neutral">未上报</Badge>
                            ) : null}
                          </span>
                        </>
                      ) : (
                        <Badge tone="neutral">未绑定</Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="cell-main">
                      {!row.metaDomainMonitored ? (
                        <Badge tone="neutral">未监测</Badge>
                      ) : row.metaDomainBlocked ? (
                        <Badge tone="danger">疑似受限</Badge>
                      ) : (
                        <Badge tone="success">正常</Badge>
                      )}
                      <span>
                        {row.metaDomainBlockedAt
                          ? `发现于 ${formatDateTime(row.metaDomainBlockedAt)}`
                          : row.metaDomainMonitored
                            ? "尚未发现 Meta 不可用提示"
                            : "需绑定并启用浏览器 Pixel"}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    {row.localeMode === "fixed" ? row.locale || "固定" : "自动"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(row.createdAt)}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(row.updatedAt)}
                  </TableCell>
                  <TableCell>
                    <div className="flex min-w-max items-center justify-end gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!row.publicUrl}
                        title="打开真实渠道页；提交号码会创建账号并占用 IP"
                        onClick={() =>
                          window.open(row.publicUrl, "_blank", "noopener,noreferrer")
                        }
                      >
                        访问页面
                      </Button>
                      {canManage ? (
                        <>
                          <Button
                            variant="outline"
                            size="sm"
                            title={
                              row.metaCapiProbeReady
                                ? "探测 Facebook CAPI 连通性"
                                : "需先配置可用的 CAPI Token"
                            }
                            disabled={!row.metaCapiProbeReady}
                            onClick={() => void probeCapi(row)}
                          >
                            探测 CAPI
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={!row.id}
                            onClick={() => open(row)}
                          >
                            编辑
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={!row.id}
                            onClick={() => void toggle(row)}
                          >
                            {row.enabled ? "停用" : "启用"}
                          </Button>
                        </>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <EmptyState
            title="还没有推广渠道"
            description="新建 Facebook 渠道并绑定模板、域名和 Pixel。"
          />
        )}
      </ListTableCard>
      <Drawer
        open={drawer}
        onClose={() => !pending && setDrawer(false)}
        title={editing ? "编辑推广渠道" : "新建推广渠道"}
        description="一个渠道对应一个国家、访问路径和模板版本。"
        footer={
          <>
            <Button variant="outline" onClick={() => setDrawer(false)}>
              取消
            </Button>
            <Button
              disabled={
                pending ||
                !form.name.trim() ||
                !form.countryCode ||
                !form.templateId ||
                !form.accountGroupId ||
                !form.protocolRouteId ||
                !form.domainId ||
                !form.slug.trim()
              }
              onClick={() => void save()}
            >
              {pending ? <Spinner /> : null}保存渠道
            </Button>
          </>
        }
      >
        <div className="drawer-form">
          <DrawerFormSection title="基础信息">
          <label className="field">
            <DrawerFieldLabel required>渠道名称</DrawerFieldLabel>
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="例如：FB-US-Summer"
            />
          </label>
          <div className="form-grid">
            <label className="field">
              <DrawerFieldLabel>平台</DrawerFieldLabel>
              <Input value="Facebook" disabled />
            </label>
            <div className="field">
              <DrawerFieldLabel required>投放国家</DrawerFieldLabel>
              <SearchableSelect
                value={form.countryCode}
                onValueChange={(value) =>
                  setForm({ ...form, countryCode: value })
                }
                options={countryOptions}
                placeholder="选择投放国家"
                searchPlaceholder="搜索国家、地区或代码"
                emptyText="没有匹配的国家或地区"
                ariaLabel="投放国家"
              />
            </div>
          </div>
          <label className="field">
            <DrawerFieldLabel required>推广模板</DrawerFieldLabel>
            <SelectField
              className="w-full"
              value={form.templateId}
              onValueChange={(value) =>
                setForm({ ...form, templateId: value, locale: "" })
              }
              options={templates.map((row) => ({
                value: row.id,
                label: row.label,
              }))}
            />
          </label>
          <DrawerFormField
            label="账号入库分组"
            hint="通过此渠道成功链接的账号会自动进入该分组；发送任务实时使用分组内当前可用账号。"
            required
          >
            <SelectField
              className="w-full"
              value={form.accountGroupId}
              onValueChange={(value) =>
                setForm({ ...form, accountGroupId: value })
              }
              placeholder="选择账号入库分组"
              options={accountGroups.map((row) => ({
                value: row.id,
                label: row.label,
              }))}
            />
          </DrawerFormField>
          </DrawerFormSection>
          <DrawerFormSection
            title="新账号协议路由"
            description="切换只影响之后新建的接入任务；存量账号和进行中的配对保持原节点。直接节点不可用时默认拒绝，只有选择协议池才按优先级回退。"
          >
            <div className="form-grid">
              <label className="field">
                <DrawerFieldLabel required>路由类型</DrawerFieldLabel>
                <SelectField className="w-full" value={form.protocolRouteType} onValueChange={(value) => {
                  const routeType = value as "node" | "pool";
                  setForm({ ...form, protocolRouteType: routeType, protocolRouteId: routeType === "node" ? protocolNodes[0]?.id || "" : protocolPools[0]?.id || "" });
                }} options={[{ value: "node", label: "指定协议节点（不可用即拒绝）" }, { value: "pool", label: "协议池（显式回退）" }]} />
              </label>
              <label className="field">
                <DrawerFieldLabel required>{form.protocolRouteType === "node" ? "协议节点" : "协议池"}</DrawerFieldLabel>
                <SelectField className="w-full" value={form.protocolRouteId} onValueChange={(value) => setForm({ ...form, protocolRouteId: value })} placeholder={form.protocolRouteType === "node" ? "选择协议节点" : "选择协议池"} options={(form.protocolRouteType === "node" ? protocolNodes : protocolPools).map((row) => ({ value: row.id, label: row.label }))} />
              </label>
            </div>
            <div className="mt-3 grid gap-2 rounded-md bg-muted/35 p-3 text-xs text-muted-foreground">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={selectedTemplate?.runtime === "promotion-browser-bridge/v2" ? "success" : "warning"}>
                  {selectedTemplate?.runtime || "未选择模板运行时"}
                </Badge>
                <Badge tone={selectedRoute?.health === "available" ? "success" : "warning"}>
                  {selectedRoute?.health === "available" ? "路由可接入" : "路由当前不可接入"}
                </Badge>
                <Badge tone={form.protocolRouteType === "pool" ? "success" : "neutral"}>
                  {form.protocolRouteType === "pool" ? "显式池回退" : "节点不可用即拒绝"}
                </Badge>
              </div>
              <span>
                模板声明 {selectedTemplate?.pairingContract || "-"}；保存时后端会校验协议路由兼容性。{selectedRoute?.healthReason ? ` 当前原因：${selectedRoute.healthReason}` : ""}
              </span>
            </div>
          </DrawerFormSection>
          <DrawerFormSection title="访问与语言">
          <div className="form-grid">
            <label className="field">
              <DrawerFieldLabel required>语言模式</DrawerFieldLabel>
              <SelectField
                className="w-full"
                value={form.localeMode}
                onValueChange={(value) =>
                  setForm({ ...form, localeMode: value, locale: "" })
                }
                options={[
                  { value: "auto", label: "自动（国家 / 浏览器）" },
                  { value: "fixed", label: "固定语言" },
                ]}
              />
            </label>
            {form.localeMode === "fixed" ? (
              <label className="field">
                <DrawerFieldLabel required>固定语言</DrawerFieldLabel>
                <SelectField
                  className="w-full"
                  value={form.locale}
                  onValueChange={(value) => setForm({ ...form, locale: value })}
                  options={(
                    templates.find((row) => row.id === form.templateId)
                      ?.locales || []
                  ).map((locale) => ({ value: locale, label: locale }))}
                />
              </label>
            ) : (
              <label className="field">
                <DrawerFieldLabel>语言解析</DrawerFieldLabel>
                <Input disabled value="投放国家 → 浏览器语言 → 模板默认" />
              </label>
            )}
          </div>
          <div className="form-grid">
            <label className="field">
              <DrawerFieldLabel required>基础域名</DrawerFieldLabel>
              <SelectField
                className="w-full"
                value={form.domainId}
                placeholder="请选择落地页域名"
                onValueChange={(value) => setForm({ ...form, domainId: value })}
                options={domains.map((row) => ({
                  value: row.id,
                  label: row.label,
                }))}
              />
            </label>
            <label className="field">
              <DrawerFieldLabel>子域名前缀</DrawerFieldLabel>
              <div className="flex gap-2">
                <Input
                  value={form.subdomainPrefix}
                  maxLength={63}
                  placeholder="例如：cn；不填使用根域名"
                  onChange={(event) =>
                    setForm({
                      ...form,
                      subdomainPrefix: event.target.value
                        .toLowerCase()
                        .replace(/[^a-z0-9-]/g, "")
                        .replace(/^-+/, "")
                        .slice(0, 63),
                    })
                  }
                />
                <IconButton
                  label="重新生成随机子域名前缀"
                  onClick={() =>
                    setForm({
                      ...form,
                      subdomainPrefix: randomChannelCode(
                        rows
                          .filter(
                            (item) =>
                              item.id !== editing?.id &&
                              (!form.domainId || item.domainId === form.domainId),
                          )
                          .map((item) => item.subdomainPrefix)
                          .filter(Boolean),
                      ),
                    })
                  }
                >
                  <RefreshCwIcon size={16} />
                </IconButton>
              </div>
            </label>
          </div>
          <div className="form-grid">
            <DrawerFormField
              label="访问短码（Slug）"
              hint="新建时自动生成 8 位随机短码，也可以手动修改。"
              required
            >
              <div className="flex gap-2">
                <Input
                  value={form.slug}
                  maxLength={120}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      slug: e.target.value
                        .toLowerCase()
                        .replace(/[^a-z0-9-]/g, ""),
                    })
                  }
                />
                <IconButton
                  label="重新生成随机短码"
                  onClick={() =>
                    setForm({
                      ...form,
                      slug: randomChannelCode(
                        rows
                          .filter((item) => item.id !== editing?.id)
                          .map((item) => item.slug),
                      ),
                    })
                  }
                >
                  <RefreshCwIcon size={16} />
                </IconButton>
              </div>
            </DrawerFormField>
            <DrawerFormField
              label="最终访问地址"
              hint="子域名需要该基础域名已配置通配符 DNS 和证书。"
            >
              <Input
                value={previewPublicUrl}
                readOnly
                placeholder="选择基础域名后生成"
              />
            </DrawerFormField>
          </div>
          </DrawerFormSection>
          <DrawerFormSection
            title="Meta 事件与投放归因"
            description="浏览器 Pixel 与服务端 CAPI 共用 eventId 去重。模板不携带 Pixel ID、Token 或事件 SDK，全部由渠道运行时注入。"
          >
            <label className="field">
              <DrawerFieldLabel>Meta Pixel / Dataset</DrawerFieldLabel>
              <SelectField
                className="w-full"
                value={form.pixelId}
                clearable
                onValueChange={(value) =>
                  setForm({
                    ...form,
                    pixelId: value,
                    metaBrowserPixelEnabled: Boolean(value),
                    metaCapiEnabled: value ? form.metaCapiEnabled : false,
                  })
                }
                placeholder="不绑定"
                options={pixels
                  .filter((row) => row.enabled && row.id)
                  .map((row) => ({ value: row.id, label: row.label }))}
              />
            </label>
            <div className="mt-3 grid gap-2">
              <DrawerFormField
                label="浏览器 Pixel"
                hint="在公开落地页加载 Meta Pixel，并按下方映射发送浏览器事件。"
              >
                <div className="flex h-8 items-center">
                  <Switch
                    checked={form.metaBrowserPixelEnabled}
                    disabled={!form.pixelId}
                    onCheckedChange={(checked) =>
                      setForm({ ...form, metaBrowserPixelEnabled: checked })
                    }
                    aria-label="启用浏览器 Pixel"
                  />
                </div>
              </DrawerFormField>
              <DrawerFormField
                label="服务端 Conversions API"
                hint={
                  selectedPixel?.tokenConfigured
                    ? "异步投递、失败重试，并保留可审计账本。"
                    : "当前 Pixel 未配置 CAPI Token，需先在 Pixel 管理中保存。"
                }
              >
                <div className="flex h-8 items-center">
                  <Switch
                    checked={form.metaCapiEnabled}
                    disabled={!form.pixelId || !selectedPixel?.tokenConfigured}
                    onCheckedChange={(checked) =>
                      setForm({ ...form, metaCapiEnabled: checked })
                    }
                    aria-label="启用 Meta CAPI"
                  />
                </div>
              </DrawerFormField>
            </div>
            <div className="form-grid mt-3">
              {(
                [
                  ["page_view", "页面访问"],
                  ["phone_submit", "提交号码"],
                  ["pairing_started", "生成配对码"],
                  ["pairing_verified", "账号链接成功"],
                ] as Array<[keyof MetaEventMapping, string]>
              ).map(([key, label]) => (
                <label className="field" key={key}>
                  <DrawerFieldLabel required>{label}上报事件</DrawerFieldLabel>
                  <SelectField
                    className="w-full"
                    value={form.metaEventMapping[key]}
                    onValueChange={(value) =>
                      setForm({
                        ...form,
                        metaEventMapping: {
                          ...form.metaEventMapping,
                          [key]: value,
                        },
                      })
                    }
                    options={metaEventOptions}
                  />
                </label>
              ))}
            </div>
          </DrawerFormSection>
          <DrawerFormSection title="发布设置">
          <DrawerFormField
            label="Facebook / Instagram 内置浏览器"
            hint="浏览器无法可靠强制跳出 App；“提示使用系统浏览器”只展示明确引导，不虚构强制打开能力。"
            required
          >
            <SelectField
              className="w-full"
              value={form.inAppBrowserMode}
              onValueChange={(value) =>
                setForm({
                  ...form,
                  inAppBrowserMode: value as "allow" | "guide_external",
                })
              }
              options={[
                { value: "allow", label: "允许直接完成账号链接" },
                { value: "guide_external", label: "提示使用系统浏览器" },
              ]}
            />
          </DrawerFormField>
          <DrawerFormField
            label="新接入账号参与营销"
            hint="只在账号首次创建时固化；之后切换本项不会改变存量账号。"
          >
            <div className="flex h-8 items-center">
              <Switch
                checked={form.newAccountMarketingEnabled}
                onCheckedChange={(checked) =>
                  setForm({ ...form, newAccountMarketingEnabled: checked })
                }
                aria-label="新接入账号参与营销"
              />
            </div>
          </DrawerFormField>
          <label className="field">
            <DrawerFieldLabel>计划上线时间</DrawerFieldLabel>
            <Input
              type="datetime-local"
              value={form.goLiveAt}
              onChange={(e) => setForm({ ...form, goLiveAt: e.target.value })}
            />
          </label>
          <DrawerFormField
            label="启用渠道"
            hint="启用后到达上线时间即可对外访问。"
          >
            <div className="flex h-8 items-center">
              <Switch
                checked={form.enabled}
                onCheckedChange={(checked) =>
                  setForm({ ...form, enabled: checked })
                }
                aria-label="启用渠道"
              />
            </div>
          </DrawerFormField>
          </DrawerFormSection>
        </div>
      </Drawer>
      <Drawer
        open={capiProbeOpen}
        onClose={() => !capiProbePending && setCapiProbeOpen(false)}
        title="Facebook CAPI 连通性探测"
        description={capiProbeChannel?.name || ""}
        footer={
          <>
            <Button
              variant="outline"
              disabled={capiProbePending}
              onClick={() => setCapiProbeOpen(false)}
            >
              关闭
            </Button>
            <Button
              disabled={capiProbePending || !capiProbeChannel?.metaCapiProbeReady}
              onClick={() =>
                capiProbeChannel && void probeCapi(capiProbeChannel)
              }
            >
              {capiProbePending ? <Spinner /> : <ActivityIcon size={16} />}
              重新探测
            </Button>
          </>
        }
      >
        {capiProbePending ? (
          <div className="loading-state">
            <Spinner />
          </div>
        ) : capiProbeResult ? (
          <div className="drawer-form">
            <div className="pixel-create-card">
              <div className="flex items-center justify-between gap-3">
                <strong>
                  {capiProbeResult.ok ? "CAPI 连通正常" : "CAPI 探测失败"}
                </strong>
                <Badge tone={capiProbeResult.ok ? "success" : "danger"}>
                  {capiProbeResult.ok ? "成功" : "失败"}
                </Badge>
              </div>
              <small className="text-muted-foreground">
                该探测会向 Meta 发送一次独立的 ParloqCapiProbe 事件，不写入正式投递账本。
              </small>
            </div>
            <div className="channel-stat-grid">
              <div>
                <span>Dataset / Pixel ID</span>
                <strong>{capiProbeResult.datasetId || "-"}</strong>
              </div>
              <div>
                <span>HTTP 状态</span>
                <strong>{capiProbeResult.httpStatus ?? "-"}</strong>
              </div>
              <div>
                <span>探测事件</span>
                <strong>{capiProbeResult.eventName || "-"}</strong>
              </div>
              <div>
                <span>Meta Trace</span>
                <strong>{capiProbeResult.providerTraceId || "-"}</strong>
              </div>
            </div>
            <label className="field">
              <DrawerFieldLabel>事件 ID</DrawerFieldLabel>
              <Input readOnly value={capiProbeResult.eventId || "-"} />
            </label>
            {!capiProbeResult.ok ? (
              <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                {capiProbeResult.sendError || "Meta 未接受本次探测请求"}
              </div>
            ) : null}
          </div>
        ) : null}
      </Drawer>
      <Drawer
        open={pixelDrawer}
        onClose={() => !pixelPending && setPixelDrawer(false)}
        title="Meta Pixel 管理"
        description="保存 Dataset ID 与加密 CAPI Token；渠道启用 CAPI 后由异步账本投递并自动重试，Token 之后仅显示掩码。"
        footer={<Button onClick={() => setPixelDrawer(false)}>完成</Button>}
      >
        <div className="drawer-form">
          <div className="pixel-create-card">
            <strong>添加 Pixel</strong>
            <label className="field">
              <DrawerFieldLabel required>内部名称</DrawerFieldLabel>
              <Input
                value={pixelForm.name}
                onChange={(e) =>
                  setPixelForm({ ...pixelForm, name: e.target.value })
                }
                placeholder="例如：FB 主 Pixel"
              />
            </label>
            <label className="field">
              <DrawerFieldLabel required>Dataset / Pixel ID</DrawerFieldLabel>
              <Input
                value={pixelForm.datasetId}
                onChange={(e) =>
                  setPixelForm({ ...pixelForm, datasetId: e.target.value })
                }
              />
            </label>
            <label className="field">
              <DrawerFieldLabel>CAPI Token</DrawerFieldLabel>
              <Input
                type="password"
                autoComplete="new-password"
                value={pixelForm.capiToken}
                onChange={(e) =>
                  setPixelForm({ ...pixelForm, capiToken: e.target.value })
                }
                placeholder="保存后不会回显"
              />
            </label>
            <Button
              disabled={
                pixelPending ||
                !pixelForm.name.trim() ||
                !pixelForm.datasetId.trim()
              }
              onClick={() => void createPixel()}
            >
              {pixelPending ? <Spinner /> : <PlusIcon size={16} />}添加 Pixel
            </Button>
          </div>
          <div className="binding-list-header">
            <strong>已配置 Pixel</strong>
            <span>{pixels.length}</span>
          </div>
          <ListPagination
            page={pixelPagination.page}
            pageSize={pixelPagination.pageSize}
            total={pixelPagination.total}
            onPageChange={pixelPagination.setPage}
            onPageSizeChange={pixelPagination.setPageSize}
            ariaLabel="Meta Pixel 分页"
          />
          {pixels.length ? (
            <div className="pixel-list">
              {pixelPagination.rows.map((row) => (
                <div key={row.readKey}>
                  <div>
                    <strong>{row.name}</strong>
                    <span>{row.id || "等待 ID 迁移"}</span>
                    <span>
                      {row.datasetId} · {row.tokenMasked || "未配置 CAPI Token"}
                    </span>
                  </div>
                  <Badge tone={row.enabled ? "success" : "neutral"}>
                    {row.enabled ? "启用" : "停用"}
                  </Badge>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!row.id}
                    onClick={() => void togglePixel(row)}
                  >
                    {row.enabled ? "停用" : "启用"}
                  </Button>
                  <IconButton
                    label="删除 Pixel"
                    className="text-destructive"
                    disabled={!row.id}
                    onClick={() => void removePixel(row)}
                  >
                    <Trash2Icon size={15} />
                  </IconButton>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              title="暂无 Pixel"
              description="添加后即可在推广渠道中绑定。"
            />
          )}
        </div>
      </Drawer>
      <Drawer
        open={insightOpen}
        onClose={() => setInsightOpen(false)}
        title="渠道数据与号码"
        description={
          rows.find((row) => row.id === insightChannelId)?.name || ""
        }
        footer={<Button onClick={() => setInsightOpen(false)}>关闭</Button>}
      >
        {insightLoading ? (
          <div className="loading-state">
            <Spinner />
          </div>
        ) : (
          <div className="drawer-form">
            <div className="channel-stat-grid">
              <div>
                <span>页面访问</span>
                <strong>{insightStats.visits || 0}</strong>
              </div>
              <div>
                <span>设备增强 UV</span>
                <strong>{insightStats.visitors || 0}</strong>
              </div>
              <div>
                <span>指纹覆盖率</span>
                <strong>
                  {(insightStats.fingerprintCoverageRate || 0).toFixed(1)}%
                </strong>
              </div>
              <div>
                <span>完整停留会话</span>
                <strong>{insightStats.completedVisits || 0}</strong>
              </div>
              <div>
                <span>唯一号码</span>
                <strong>{insightStats.leads || 0}</strong>
              </div>
              <div>
                <span>号码提交次数</span>
                <strong>{insightStats.submissions || 0}</strong>
              </div>
            </div>
            <div className="binding-list-header">
              <strong>配对转化漏斗</strong>
              <span>按访客去重</span>
            </div>
            {pairingFunnel.length ? (
              <div className="pairing-funnel-grid">
                {pairingFunnel.map((step, index) => (
                  <div key={step.key}>
                    <span>
                      {index + 1}. {pairingFunnelLabels[step.key] || step.key}
                    </span>
                    <strong>{step.count}</strong>
                    <small>
                      {index === 0
                        ? "漏斗起点"
                        : `上一步转化 ${(step.stepRate * 100).toFixed(1)}%`}
                      {index > 0
                        ? ` · 访问转化 ${(step.visitorRate * 100).toFixed(1)}%`
                        : ""}
                    </small>
                  </div>
                ))}
              </div>
            ) : (
              <div className="compact-empty">暂无配对漏斗数据。</div>
            )}
            <div className="binding-list-header">
              <strong>主要流失原因</strong>
              <span>{pairingFailureTotal}</span>
            </div>
            {pairingFailures.length ? (
              <div className="pairing-failure-list">
                {pairingFailures.map((reason) => (
                  <div key={reason.code}>
                    <strong>{reason.label}</strong>
                    <span>{reason.count} 次</span>
                    <small>{(reason.share * 100).toFixed(1)}%</small>
                  </div>
                ))}
              </div>
            ) : (
              <div className="compact-empty">当前没有配对失败记录。</div>
            )}
            <div className="binding-list-header">
              <strong>Meta CAPI 投递账本</strong>
              <span>Browser / CAPI 使用相同 eventId 去重</span>
            </div>
            <div className="channel-stat-grid">
              <div><span>已送达</span><strong>{metaDeliverySummary.delivered || 0}</strong></div>
              <div><span>待投递</span><strong>{metaDeliverySummary.pending || 0}</strong></div>
              <div><span>重试中</span><strong>{metaDeliverySummary.retry || 0}</strong></div>
              <div><span>最终失败</span><strong>{metaDeliverySummary.failed || 0}</strong></div>
            </div>
            <div className="binding-list-header">
              <strong>Facebook 日投放数据</strong>
              {canManageMetrics ? (
                <Button variant="outline" onClick={() => openMetric()}>
                  <PlusIcon size={15} />
                  录入日数据
                </Button>
              ) : null}
            </div>
            <ListPagination
              page={metricPagination.page}
              pageSize={metricPagination.pageSize}
              total={metricPagination.total}
              onPageChange={metricPagination.setPage}
              onPageSizeChange={metricPagination.setPageSize}
              ariaLabel="Facebook 日投放数据分页"
            />
            {metrics.length ? (
              <div className="metric-list">
                {metricPagination.rows.map((metric) => (
                  <div key={metric.readKey}>
                    <strong>{metric.date}</strong>
                    <span>{metric.id || "等待 ID 迁移"}</span>
                    <span>${metric.spend.toFixed(2)}</span>
                    <span>{metric.impressions.toLocaleString()} 展示</span>
                    <span>{metric.clicks.toLocaleString()} 点击</span>
                    {canManageMetrics ? (
                      <>
                        <IconButton
                          label="编辑日投放数据"
                          disabled={!metric.id}
                          onClick={() => openMetric(metric)}
                        >
                          <PencilIcon size={14} />
                        </IconButton>
                        <IconButton
                          label="删除日投放数据"
                          className="text-destructive"
                          disabled={!metric.id}
                          onClick={() => void removeMetric(metric)}
                        >
                          <Trash2Icon size={14} />
                        </IconButton>
                      </>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <div className="compact-empty">
                尚未录入 Facebook 花费、展示与点击数据。
              </div>
            )}
            <div className="binding-list-header">
              <strong>号码留资</strong>
              <span>{insightLeads.length}</span>
            </div>
            <ListPagination
              page={leadPagination.page}
              pageSize={leadPagination.pageSize}
              total={leadPagination.total}
              onPageChange={leadPagination.setPage}
              onPageSizeChange={leadPagination.setPageSize}
              ariaLabel="渠道号码留资分页"
            />
            {insightLeads.length ? (
              <div className="lead-list">
                {leadPagination.rows.map((lead, index) => (
                  <div key={String(lead.id || index)}>
                    <strong>
                      {formatPhoneDisplay(
                        lead.phone || lead.phoneNumber || "-",
                      )}
                    </strong>
                    <span>{String(lead.countryCode || "-")}</span>
                    <small>
                      {formatDateTime(
                        String(lead.lastSeenAt || lead.createdAt || ""),
                      )}
                    </small>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                title="暂无号码"
                description="访客提交手机号后会自动进入这里。"
              />
            )}
          </div>
        )}
      </Drawer>
      <Drawer
        open={metricDrawer}
        onClose={() => !metricPending && setMetricDrawer(false)}
        title={metricEditing ? "编辑 Facebook 日数据" : "录入 Facebook 日数据"}
        description={
          rows.find((row) => row.id === insightChannelId)?.name || ""
        }
        footer={
          <>
            <Button variant="outline" onClick={() => setMetricDrawer(false)}>
              取消
            </Button>
            <Button
              disabled={metricPending || !metricForm.date}
              onClick={() => void saveMetric()}
            >
              {metricPending ? <Spinner /> : null}保存
            </Button>
          </>
        }
      >
        <div className="drawer-form">
          <label className="field">
            <DrawerFieldLabel required>日期</DrawerFieldLabel>
            <DatePickerField
              ariaLabel="广告数据日期"
              value={metricForm.date}
              onValueChange={(date) =>
                setMetricForm({ ...metricForm, date })
              }
            />
          </label>
          <div className="form-grid">
            <label className="field">
              <DrawerFieldLabel>花费（USD）</DrawerFieldLabel>
              <Input
                type="number"
                min="0"
                step="0.01"
                value={metricForm.spend}
                onChange={(event) =>
                  setMetricForm({ ...metricForm, spend: event.target.value })
                }
              />
            </label>
            <label className="field">
              <DrawerFieldLabel>展示</DrawerFieldLabel>
              <Input
                type="number"
                min="0"
                value={metricForm.impressions}
                onChange={(event) =>
                  setMetricForm({
                    ...metricForm,
                    impressions: event.target.value,
                  })
                }
              />
            </label>
            <label className="field">
              <DrawerFieldLabel>点击</DrawerFieldLabel>
              <Input
                type="number"
                min="0"
                value={metricForm.clicks}
                onChange={(event) =>
                  setMetricForm({ ...metricForm, clicks: event.target.value })
                }
              />
            </label>
          </div>
          <div className="metric-preview">
            <span>
              CTR{" "}
              <strong>
                {Number(metricForm.impressions)
                  ? `${((Number(metricForm.clicks) / Number(metricForm.impressions)) * 100).toFixed(2)}%`
                  : "-"}
              </strong>
            </span>
            <span>
              CPC{" "}
              <strong>
                {Number(metricForm.clicks)
                  ? `$${(Number(metricForm.spend) / Number(metricForm.clicks)).toFixed(2)}`
                  : "-"}
              </strong>
            </span>
          </div>
        </div>
      </Drawer>
    </StandardListPage>
  );
}
