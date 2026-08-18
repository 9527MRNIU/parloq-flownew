import {
  ArchiveIcon,
  BookOpenIcon,
  ChevronLeftIcon,
  CopyIcon,
  DownloadIcon,
  EyeIcon,
  ExternalLinkIcon,
  LoaderCircleIcon,
  MonitorIcon,
  PauseIcon,
  PencilIcon,
  PlayIcon,
  PlugZapIcon,
  PlusIcon,
  RefreshCwIcon,
  RocketIcon,
  Settings2Icon,
  SmartphoneIcon,
  TabletIcon,
  Trash2Icon,
  UploadCloudIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
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
  ListTableCard,
  ListToolbar,
  StandardListPage,
} from "../components/list-page";
import { EntityPrimaryCell } from "../components/entity-primary-cell";
import { DrawerFormSection } from "../components/drawer-form";
import { useAuth } from "../auth/AuthContext";
import { countryOptions } from "../lib/countries";
import { entityRowKey, snowflakeId } from "../lib/entity-identifiers";
import { formatPhoneDisplay } from "../lib/utils";
import {
  TEMPLATE_DESIGN_SECTIONS,
  templateAiCreationPrompt,
} from "../content/promotion-template-design";

const CHANNEL_SLUG_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789";

function randomChannelSlug(existing: Iterable<string>, length = 8): string {
  const reserved = new Set(Array.from(existing, (value) => value.toLowerCase()));
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const random = new Uint8Array(length);
    globalThis.crypto.getRandomValues(random);
    const slug = Array.from(
      random,
      (value) => CHANNEL_SLUG_ALPHABET[value % CHANNEL_SLUG_ALPHABET.length],
    ).join("");
    if (!reserved.has(slug)) return slug;
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
  version: string;
  status: string;
  previewUrl: string;
  assetCount: number;
  channelCount: number;
  defaultLocale: string;
  supportedLocales: string[];
  integrationIds: string[];
  updatedAt?: string;
};
type RuntimeIntegrationOption = {
  id: string;
  name: string;
  type: "script" | "iframe";
  sourceUrl: string;
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
  metaEventMapping: MetaEventMapping;
  inAppBrowserMode: "allow" | "guide_external";
  newAccountMarketingEnabled: boolean;
  effectiveConfig: Record<string, unknown>;
  enabled: boolean;
  localeMode: string;
  locale: string;
  goLiveAt?: string;
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
type TemplateDeviceSignals = "off" | "standard" | "enhanced";
type TemplatePolicy = {
  protectionMode: TemplateProtectionMode;
  devtoolsAction: TemplateDevtoolsAction;
  lockViewportZoom: boolean;
  deviceSignals: TemplateDeviceSignals;
};

const defaultTemplatePolicy: TemplatePolicy = {
  protectionMode: "strict",
  devtoolsAction: "blank",
  lockViewportZoom: true,
  deviceSignals: "enhanced",
};

function templatePolicyRow(input: unknown): TemplatePolicy {
  const row = object(input);
  const protectionMode = field(row, "protectionMode", "protection_mode");
  const devtoolsAction = field(row, "devtoolsAction", "devtools_action");
  const deviceSignals = field(row, "deviceSignals", "device_signals");
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
    deviceSignals: ["off", "standard", "enhanced"].includes(deviceSignals)
      ? (deviceSignals as TemplateDeviceSignals)
      : defaultTemplatePolicy.deviceSignals,
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
    defaultLocale,
    supportedLocales: locales,
    updatedAt: field(row, "updatedAt", "updated_at"),
  };
}
function runtimeIntegrationRow(input: unknown): RuntimeIntegrationOption {
  const row = object(input);
  const id = snowflakeId(row, "id");
  return {
    id,
    name: field(row, "name"),
    type: field(row, "type") === "script" ? "script" : "iframe",
    sourceUrl: field(row, "sourceUrl", "source_url"),
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
      description="由平台统一注入。iframe 会挂载到 body 末尾，外部脚本按登记地址加载。"
    >
      {integrations.length ? (
        integrations.map((integration) => (
          <label className="switch-row" key={integration.id}>
            <span>
              <strong>{integration.name}</strong>
              <small>
                {integration.type === "iframe" ? "iframe" : "JavaScript"} ·{" "}
                {integration.sourceUrl}
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
        {template ? <Badge tone="primary">{template.version.split(" · ")[0]}</Badge> : null}
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
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [drawer, setDrawer] = useState(false);
  const [replacing, setReplacing] = useState<PromotionTemplate | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [integrations, setIntegrations] = useState<RuntimeIntegrationOption[]>([]);
  const [selectedIntegrationIds, setSelectedIntegrationIds] = useState<string[]>([]);
  const [integrationEditing, setIntegrationEditing] = useState<PromotionTemplate | null>(null);
  const [bindingIntegrationIds, setBindingIntegrationIds] = useState<string[]>([]);
  const [bindingSaving, setBindingSaving] = useState(false);
  const [pending, setPending] = useState(false);
  const [previewing, setPreviewing] = useState<PromotionTemplate | null>(null);
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
  async function upload(event?: FormEvent) {
    event?.preventDefault();
    if (!file || !name.trim() || (replacing && !replacing.id)) return;
    setPending(true);
    try {
      const body = new FormData();
      body.set("file", file);
      body.set("integrationIds", JSON.stringify(selectedIntegrationIds));
      if (!replacing) {
        body.set("name", name.trim());
        if (description.trim()) body.set("description", description.trim());
      }
      await apiRequest(
        replacing
          ? `/api/promotion/templates/${replacing.id}/versions`
          : "/api/promotion/templates",
        { method: "POST", body },
      );
      setDrawer(false);
      setReplacing(null);
      setFile(null);
      setName("");
      setSelectedIntegrationIds([]);
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "导入失败");
    } finally {
      setPending(false);
    }
  }
  function openImport(row?: PromotionTemplate) {
    if (row && !row.id) return;
    setReplacing(row || null);
    setFile(null);
    setName(row?.name || "");
    setDescription("");
    setSelectedIntegrationIds(row?.integrationIds || []);
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
  function openIntegrationEditor(row: PromotionTemplate) {
    setIntegrationEditing(row);
    setBindingIntegrationIds(row.integrationIds);
  }
  async function saveIntegrationBindings() {
    if (!integrationEditing?.id || !canManage) return;
    setBindingSaving(true);
    try {
      await apiRequest(
        `/api/promotion/templates/${integrationEditing.id}/integrations`,
        {
          method: "PUT",
          body: JSON.stringify({ integrationIds: bindingIntegrationIds }),
        },
      );
      setIntegrationEditing(null);
      toast.success("模板集成已保存");
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "模板集成保存失败");
    } finally {
      setBindingSaving(false);
    }
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
        body: JSON.stringify(policy),
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
          placeholder: "搜索模板名称、版本或状态",
        }}
        meta={`${visible.length} 个模板`}
        actions={
          <>
            <Button variant="outline" onClick={() => void load()}>
              <RefreshCwIcon size={16} />
              刷新
            </Button>
            <Button variant="outline" onClick={() => setDesignSpecDrawer(true)}>
              <BookOpenIcon size={16} />
              设计规范
            </Button>
            <Button variant="outline" onClick={openPolicy}>
              <Settings2Icon size={16} />
              模板策略
            </Button>
            {canManage ? (
              <Button onClick={() => openImport()}>
                <PlusIcon size={17} />
                导入模板
              </Button>
            ) : null}
          </>
        }
      />
      <ListTableCard>
        {loading ? (
          <div className="loading-state">
            <Spinner />
          </div>
        ) : visible.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>模板</TableHead>
                <TableHead>版本</TableHead>
                <TableHead>语言</TableHead>
                <TableHead>资源</TableHead>
                <TableHead>集成</TableHead>
                <TableHead>使用渠道</TableHead>
                <TableHead>更新时间</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((row) => (
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
                    <Badge tone="primary">{row.version.split(" · ")[0]}</Badge>
                  </TableCell>
                  <TableCell>
                    <div className="cell-main">
                      <strong>{row.defaultLocale}</strong>
                      <span>{row.supportedLocales.length} 种语言</span>
                    </div>
                  </TableCell>
                  <TableCell>{row.assetCount} 个文件</TableCell>
                  <TableCell>{row.integrationIds.length} 个</TableCell>
                  <TableCell>{row.channelCount} 个渠道</TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(row.updatedAt)}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      <IconButton
                        label="模拟预览：不创建账号、不占用 IP"
                        disabled={!row.previewUrl}
                        onClick={() => openPreview(row)}
                      >
                        <EyeIcon size={16} />
                      </IconButton>
                      {canManage ? (
                        <>
                          <IconButton
                            label="配置集成"
                            disabled={!row.id}
                            onClick={() => openIntegrationEditor(row)}
                          >
                            <PlugZapIcon size={16} />
                          </IconButton>
                          <IconButton
                            label="替换版本"
                            disabled={!row.id}
                            onClick={() => openImport(row)}
                          >
                            <UploadCloudIcon size={16} />
                          </IconButton>
                          <IconButton
                            label={row.status === "disabled" ? "启用" : "停用"}
                            disabled={!row.id}
                            onClick={() => void toggle(row)}
                          >
                            <ArchiveIcon size={16} />
                          </IconButton>
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
        description="统一设置推广模板的前端防护、视口行为与匿名设备环境信号。"
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
                  Boolean(policyError)
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
              <span>防护级别</span>
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
              <span>检测到开发者工具时</span>
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
              <span>设备环境信号</span>
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
                ]}
              />
              <small>
                仅收集浏览器与设备环境、匿名关联信号，不采集 WhatsApp
                号码或账号凭据。
              </small>
            </label>
            <div className="rounded-lg border border-amber-600/20 bg-amber-600/5 p-3 text-sm text-muted-foreground">
              跨域访客关联和流量筛选属于推广渠道及平台侧能力，不属于模板策略，本页不提供虚构开关。
            </div>
          </div>
        ) : null}
      </Drawer>
      <Drawer
        open={Boolean(integrationEditing)}
        onClose={() => !bindingSaving && setIntegrationEditing(null)}
        title={
          integrationEditing
            ? `配置集成 · ${integrationEditing.name}`
            : "配置集成"
        }
        description="选择这个模板发布时需要统一加载的运行时集成。"
        footer={
          <>
            <Button
              variant="outline"
              disabled={bindingSaving}
              onClick={() => setIntegrationEditing(null)}
            >
              取消
            </Button>
            <Button
              disabled={bindingSaving}
              onClick={() => void saveIntegrationBindings()}
            >
              {bindingSaving ? <Spinner /> : <PlugZapIcon size={16} />}
              保存集成
            </Button>
          </>
        }
      >
        <div className="drawer-form">
          <RuntimeIntegrationSwitches
            integrations={integrations}
            selectedIds={bindingIntegrationIds}
            disabled={bindingSaving}
            onToggle={(integrationId) =>
              toggleIntegration(
                integrationId,
                bindingIntegrationIds,
                setBindingIntegrationIds,
              )
            }
          />
        </div>
      </Drawer>
      <Drawer
        open={drawer}
        onClose={() => !pending && setDrawer(false)}
        title={replacing ? `替换版本 · ${replacing.name}` : "导入推广模板"}
        description="上传 ZIP 模板文件并创建新的可用版本。"
        footer={
          <>
            <Button variant="outline" onClick={() => setDrawer(false)}>
              取消
            </Button>
            <Button
              disabled={pending || !file || !name.trim()}
              onClick={() => void upload()}
            >
              {pending ? (
                <LoaderCircleIcon className="spin" size={16} />
              ) : (
                <UploadCloudIcon size={16} />
              )}
              {replacing ? "导入新版本" : "开始导入"}
            </Button>
          </>
        }
      >
        <form className="drawer-form" onSubmit={upload}>
          <label className="upload-zone">
            <Input
              type="file"
              accept=".zip,application/zip"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            <UploadCloudIcon size={27} />
            <strong>{file?.name || "选择模板 ZIP 文件"}</strong>
            <span>仅支持 .zip，最大 20 MB</span>
          </label>
          {!replacing ? (
            <>
              <label className="field">
                <span>模板名称</span>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="例如：FB 美区夏季促销"
                />
              </label>
              <label className="field">
                <span>内部说明（可选）</span>
                <Input
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="说明模板适用场景"
                />
              </label>
            </>
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
  const [insightOpen, setInsightOpen] = useState(false);
  const [insightChannelId, setInsightChannelId] = useState("");
  const [insightLoading, setInsightLoading] = useState(false);
  const [insightStats, setInsightStats] = useState<Record<string, number>>({});
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
    inAppBrowserMode: "allow" as "allow" | "guide_external",
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
          `${row.name} ${row.countryCode} ${row.hostname} ${row.slug} ${row.accountGroupName}`
            .toLowerCase()
            .includes(search),
        )
      : rows;
  }, [keyword, rows]);
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
            slug: randomChannelSlug(rows.map((item) => item.slug)),
            pixelId: "",
            metaBrowserPixelEnabled: false,
            metaCapiEnabled: false,
            metaEventMapping: { ...defaultMetaEventMapping },
            inAppBrowserMode: "allow",
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
    setInsightStats({
      visits: Number(stats.visits ?? stats.pageView ?? stats.pageViews ?? 0),
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
        title: `归档 Pixel“${row.name}”？`,
        description: "归档后新渠道将无法继续选择该 Pixel。",
        confirmText: "确认归档",
      }))
    )
      return;
    try {
      await apiRequest(`/api/meta-pixels/${row.id}`, { method: "DELETE" });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "归档 Pixel 失败");
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
      <ListTableCard>
        {loading ? (
          <div className="loading-state">
            <Spinner />
          </div>
        ) : visible.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>渠道</TableHead>
                <TableHead>国家 / 平台</TableHead>
                <TableHead>模板</TableHead>
                <TableHead>账号入库分组</TableHead>
                <TableHead>访问地址</TableHead>
                <TableHead>Pixel</TableHead>
                <TableHead>语言</TableHead>
                <TableHead>上线时间</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((row) => (
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
                    <div className="cell-main">
                      <strong>{row.countryCode || "-"}</strong>
                      <span>Facebook</span>
                    </div>
                  </TableCell>
                  <TableCell>{row.templateName || row.templateId}</TableCell>
                  <TableCell>
                    <div className="cell-main">
                      <strong>{row.accountGroupName || "未配置"}</strong>
                      <span>{row.accountGroupId || "-"}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="cell-main">
                      <strong>{row.hostname || "-"}</strong>
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
                    <div className="cell-main">
                      <strong>{row.pixelName || "未绑定"}</strong>
                      <span className="flex flex-wrap gap-1">
                        {row.metaBrowserPixelEnabled ? <Badge tone="success">Browser</Badge> : null}
                        {row.metaCapiEnabled ? <Badge tone="success">CAPI</Badge> : null}
                        {!row.metaBrowserPixelEnabled && !row.metaCapiEnabled ? "未上报" : null}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    {row.localeMode === "fixed" ? row.locale || "固定" : "自动"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(row.goLiveAt)}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      <IconButton
                        label="打开真实渠道页：提交号码会创建账号并占用 IP"
                        onClick={() =>
                          window.open(row.publicUrl, "_blank", "noopener,noreferrer")
                        }
                      >
                        <EyeIcon size={16} />
                      </IconButton>
                      {canManage ? (
                        <>
                          <IconButton label="编辑" disabled={!row.id} onClick={() => open(row)}>
                            <PencilIcon size={16} />
                          </IconButton>
                          <IconButton
                            label={row.enabled ? "停用" : "启用"}
                            disabled={!row.id}
                            onClick={() => void toggle(row)}
                          >
                            {row.enabled ? (
                              <ArchiveIcon size={16} />
                            ) : (
                              <RocketIcon size={16} />
                            )}
                          </IconButton>
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
            <span>渠道名称</span>
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="例如：FB-US-Summer"
            />
          </label>
          <div className="form-grid">
            <label className="field">
              <span>平台</span>
              <Input value="Facebook" disabled />
            </label>
            <div className="field">
              <span>投放国家</span>
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
            <span>推广模板</span>
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
          <label className="field">
            <span>账号入库分组</span>
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
            <small className="text-muted-foreground">
              通过此渠道成功链接的账号会自动进入该分组；发送任务实时使用分组内当前可用账号。
            </small>
          </label>
          </DrawerFormSection>
          <DrawerFormSection
            title="新账号协议路由"
            description="切换只影响之后新建的接入任务；存量账号和进行中的配对保持原节点。直接节点不可用时默认拒绝，只有选择协议池才按优先级回退。"
          >
            <div className="form-grid">
              <label className="field">
                <span>路由类型</span>
                <SelectField className="w-full" value={form.protocolRouteType} onValueChange={(value) => {
                  const routeType = value as "node" | "pool";
                  setForm({ ...form, protocolRouteType: routeType, protocolRouteId: routeType === "node" ? protocolNodes[0]?.id || "" : protocolPools[0]?.id || "" });
                }} options={[{ value: "node", label: "指定协议节点（不可用即拒绝）" }, { value: "pool", label: "协议池（显式回退）" }]} />
              </label>
              <label className="field">
                <span>{form.protocolRouteType === "node" ? "协议节点" : "协议池"}</span>
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
              <span>语言模式</span>
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
                <span>固定语言</span>
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
                <span>语言解析</span>
                <Input disabled value="投放国家 → 浏览器语言 → 模板默认" />
              </label>
            )}
          </div>
          <div className="form-grid">
            <label className="field">
              <span>基础域名</span>
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
              <span>子域名前缀（可选）</span>
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
            </label>
          </div>
          <div className="form-grid">
            <label className="field">
              <span>访问短码（Slug）</span>
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
                      slug: randomChannelSlug(
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
              <small className="text-muted-foreground">
                新建时自动生成 8 位随机短码，也可以手动修改。
              </small>
            </label>
            <label className="field">
              <span>最终访问地址</span>
              <Input
                value={previewPublicUrl}
                readOnly
                placeholder="选择基础域名后生成"
              />
              <small className="text-muted-foreground">
                子域名需要该基础域名已配置通配符 DNS 和证书。
              </small>
            </label>
          </div>
          </DrawerFormSection>
          <DrawerFormSection
            title="Meta 事件与投放归因"
            description="浏览器 Pixel 与服务端 CAPI 共用 eventId 去重。模板不携带 Pixel ID、Token 或事件 SDK，全部由渠道运行时注入。"
          >
            <label className="field">
              <span>Meta Pixel / Dataset（可选）</span>
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
              <label className="switch-row">
                <span>
                  <strong>浏览器 Pixel</strong>
                  <small>在公开落地页加载 Meta Pixel，并按下方映射发送浏览器事件。</small>
                </span>
                <Switch
                  checked={form.metaBrowserPixelEnabled}
                  disabled={!form.pixelId}
                  onCheckedChange={(checked) =>
                    setForm({ ...form, metaBrowserPixelEnabled: checked })
                  }
                  aria-label="启用浏览器 Pixel"
                />
              </label>
              <label className="switch-row">
                <span>
                  <strong>服务端 Conversions API</strong>
                  <small>
                    {selectedPixel?.tokenConfigured
                      ? "异步投递、失败重试，并保留可审计账本。"
                      : "当前 Pixel 未配置 CAPI Token，需先在 Pixel 管理中保存。"}
                  </small>
                </span>
                <Switch
                  checked={form.metaCapiEnabled}
                  disabled={!form.pixelId || !selectedPixel?.tokenConfigured}
                  onCheckedChange={(checked) =>
                    setForm({ ...form, metaCapiEnabled: checked })
                  }
                  aria-label="启用 Meta CAPI"
                />
              </label>
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
                  <span>{label}上报事件</span>
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
          <label className="field">
            <span>Facebook / Instagram 内置浏览器</span>
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
            <small className="text-muted-foreground">
              浏览器无法可靠强制跳出 App；“提示使用系统浏览器”只展示明确引导，不虚构强制打开能力。
            </small>
          </label>
          <label className="switch-row">
            <span>
              <strong>新接入账号参与营销</strong>
              <small>只在账号首次创建时固化；之后切换本项不会改变存量账号。</small>
            </span>
            <Switch
              checked={form.newAccountMarketingEnabled}
              onCheckedChange={(checked) =>
                setForm({ ...form, newAccountMarketingEnabled: checked })
              }
              aria-label="新接入账号参与营销"
            />
          </label>
          <label className="field">
            <span>计划上线时间</span>
            <Input
              type="datetime-local"
              value={form.goLiveAt}
              onChange={(e) => setForm({ ...form, goLiveAt: e.target.value })}
            />
          </label>
          <label className="switch-row">
            <span>
              <strong>启用渠道</strong>
              <small>启用后到达上线时间即可对外访问。</small>
            </span>
            <Switch
              checked={form.enabled}
              onCheckedChange={(checked) =>
                setForm({ ...form, enabled: checked })
              }
            />
          </label>
          </DrawerFormSection>
        </div>
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
              <span>内部名称</span>
              <Input
                value={pixelForm.name}
                onChange={(e) =>
                  setPixelForm({ ...pixelForm, name: e.target.value })
                }
                placeholder="例如：FB 主 Pixel"
              />
            </label>
            <label className="field">
              <span>Dataset / Pixel ID</span>
              <Input
                value={pixelForm.datasetId}
                onChange={(e) =>
                  setPixelForm({ ...pixelForm, datasetId: e.target.value })
                }
              />
            </label>
            <label className="field">
              <span>CAPI Token（可选）</span>
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
          {pixels.length ? (
            <div className="pixel-list">
              {pixels.map((row) => (
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
                    label="归档 Pixel"
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
                <span>页面访客</span>
                <strong>{insightStats.visits || 0}</strong>
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
            {metrics.length ? (
              <div className="metric-list">
                {metrics.map((metric) => (
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
            {insightLeads.length ? (
              <div className="lead-list">
                {insightLeads.map((lead, index) => (
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
            <span>日期</span>
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
              <span>花费（USD）</span>
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
              <span>展示</span>
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
              <span>点击</span>
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
