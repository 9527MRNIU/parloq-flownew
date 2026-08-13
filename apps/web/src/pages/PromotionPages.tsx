import {
  ArchiveIcon,
  EyeIcon,
  LoaderCircleIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  RocketIcon,
  Settings2Icon,
  Trash2Icon,
  UploadCloudIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import {
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
import { useAuth } from "../auth/AuthContext";

const field = (row: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) if (row[key] != null) return String(row[key]);
  return "";
};
const object = (input: unknown) =>
  input && typeof input === "object" ? (input as Record<string, unknown>) : {};
type PromotionTemplate = {
  id: string;
  name: string;
  version: string;
  status: string;
  previewUrl: string;
  assetCount: number;
  channelCount: number;
  defaultLocale: string;
  supportedLocales: string[];
  updatedAt?: string;
};
type PromotionChannel = {
  id: string;
  name: string;
  platform: string;
  countryCode: string;
  templateId: string;
  templateName: string;
  domainId: string;
  hostname: string;
  slug: string;
  pixelId: string;
  pixelName: string;
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
type PixelOption = Option & {
  name: string;
  datasetId: string;
  enabled: boolean;
  tokenMasked: string;
};
type AdMetric = {
  id: string;
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
  protectionMode: "basic",
  devtoolsAction: "log",
  lockViewportZoom: false,
  deviceSignals: "standard",
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
  const id = field(row, "publicId", "public_id", "id");
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
  return {
    id,
    name: field(row, "name"),
    version: `${rawVersion} · ${defaultLocale} / ${locales.length} 语言`,
    status:
      field(row, "status") || (row.enabled === false ? "disabled" : "ready"),
    previewUrl:
      field(row, "previewUrl", "preview_url") ||
      `/api/promotion/templates/${id}/preview`,
    assetCount: Number(row.assetCount ?? row.asset_count ?? 0),
    channelCount: Number(row.channelCount ?? row.channel_count ?? 0),
    defaultLocale,
    supportedLocales: locales,
    updatedAt: field(row, "updatedAt", "updated_at"),
  };
}
function channelRow(input: unknown): PromotionChannel {
  const row = object(input);
  const stats = object(row.stats);
  const status = field(row, "status") || "draft";
  return {
    id: field(row, "publicId", "public_id", "id"),
    name: field(row, "name"),
    platform: field(row, "type", "platform") || "facebook",
    countryCode: field(row, "countryCode", "country_code"),
    templateId: field(
      row,
      "templatePublicId",
      "template_public_id",
      "templateId",
      "template_id",
    ),
    templateName: field(row, "templateName", "template_name"),
    domainId: field(
      row,
      "domainPublicId",
      "domain_public_id",
      "domainId",
      "domain_id",
    ),
    hostname: field(row, "hostname", "domain"),
    slug: field(row, "slug"),
    pixelId: field(
      row,
      "pixelPublicId",
      "pixel_public_id",
      "pixelId",
      "pixel_id",
    ),
    pixelName: field(row, "pixelName", "pixel_name", "datasetId", "dataset_id"),
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
    "pixelId",
    "pixel_id",
  );
  return {
    id: field(row, "publicId", "public_id", "id"),
    name,
    datasetId,
    label: `${name} · ${datasetId}`,
    enabled: Boolean(row.enabled ?? true),
    tokenMasked: field(row, "capiTokenMasked", "capi_token_masked"),
  };
}
function metricRow(input: unknown): AdMetric {
  const row = object(input);
  return {
    id: field(row, "publicId", "public_id", "id"),
    date: field(row, "date", "metricDate", "metric_date"),
    spend: Number(row.spend || 0),
    impressions: Number(row.impressions || 0),
    clicks: Number(row.clicks || 0),
    updatedAt: field(row, "updatedAt", "updated_at"),
  };
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
  const [pending, setPending] = useState(false);
  const [policyDrawer, setPolicyDrawer] = useState(false);
  const [policy, setPolicy] = useState<TemplatePolicy>(defaultTemplatePolicy);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [policySaving, setPolicySaving] = useState(false);
  const [policyError, setPolicyError] = useState("");
  const [policyLoaded, setPolicyLoaded] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [templatePayload, channelPayload] = await Promise.all([
        apiRequest("/api/promotion/templates?pageSize=100"),
        apiRequest("/api/promotion/channels?pageSize=100"),
      ]);
      const channels = unwrapList<unknown>(channelPayload).rows.map(channelRow);
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
    if (!file || !name.trim()) return;
    setPending(true);
    try {
      const body = new FormData();
      body.set("file", file);
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
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "导入失败");
    } finally {
      setPending(false);
    }
  }
  function openImport(row?: PromotionTemplate) {
    setReplacing(row || null);
    setFile(null);
    setName(row?.name || "");
    setDescription("");
    setDrawer(true);
  }
  async function toggle(row: PromotionTemplate) {
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
    <StandardListPage>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: "搜索模板名称、版本或状态",
        }}
        meta={`${visible.length} 个模板`}
        actions={
          <>
            <Button variant="outline" onClick={openPolicy}>
              <Settings2Icon size={16} />
              模板策略
            </Button>
            <Button variant="outline" onClick={() => void load()}>
              <RefreshCwIcon size={16} />
              刷新
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
                <TableHead>使用渠道</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>更新时间</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>
                    <div className="cell-main">
                      <strong>{row.name}</strong>
                      <span>{row.id}</span>
                    </div>
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
                  <TableCell>{row.channelCount} 个渠道</TableCell>
                  <TableCell>
                    <Badge
                      tone={
                        row.status === "ready" || row.status === "active"
                          ? "success"
                          : row.status === "disabled"
                            ? "neutral"
                            : "warning"
                      }
                    >
                      {row.status === "ready" || row.status === "active"
                        ? "可用"
                        : row.status === "disabled"
                          ? "已停用"
                          : "处理中"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(row.updatedAt)}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      <IconButton
                        label="模拟预览：不创建账号、不占用 IP"
                        onClick={() => window.open(row.previewUrl, "_blank")}
                      >
                        <EyeIcon size={16} />
                      </IconButton>
                      {canManage ? (
                        <>
                          <IconButton
                            label="替换版本"
                            onClick={() => openImport(row)}
                          >
                            <UploadCloudIcon size={16} />
                          </IconButton>
                          <IconButton
                            label={row.status === "disabled" ? "启用" : "停用"}
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
  const [templates, setTemplates] = useState<Option[]>([]);
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
    domainId: "",
    slug: "",
    pixelId: "",
    localeMode: "auto",
    locale: "",
    goLiveAt: "",
    enabled: true,
  });
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [c, t, d, p] = await Promise.all([
        apiRequest("/api/promotion/channels?pageSize=100"),
        apiRequest("/api/promotion/templates?pageSize=100"),
        apiRequest("/api/domains/available-for-channels"),
        apiRequest("/api/meta-pixels?pageSize=100"),
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
            id: field(row, "publicId", "id"),
            label: `${field(row, "name")} · ${field(row, "version") || "v1"}`,
            locales,
          };
        }),
      );
      setDomains(
        unwrapList<unknown>(d).rows.map((input) => {
          const row = object(input);
          return {
            id: field(row, "publicId", "id"),
            label: field(row, "hostname"),
          };
        }),
      );
      setPixels(unwrapList<unknown>(p).rows.map(pixelRow));
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
          `${row.name} ${row.countryCode} ${row.hostname} ${row.slug}`
            .toLowerCase()
            .includes(search),
        )
      : rows;
  }, [keyword, rows]);
  function open(row?: PromotionChannel) {
    setEditing(row || null);
    setForm(
      row
        ? {
            name: row.name,
            countryCode: row.countryCode,
            templateId: row.templateId,
            domainId: row.domainId,
            slug: row.slug,
            pixelId: row.pixelId,
            localeMode: row.localeMode,
            locale: row.locale,
            goLiveAt: row.goLiveAt?.slice(0, 16) || "",
            enabled: row.enabled,
          }
        : {
            name: "",
            countryCode: "US",
            templateId: templates[0]?.id || "",
            domainId: "",
            slug: "",
            pixelId: "",
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
      !form.domainId ||
      !form.slug.trim()
    )
      return;
    setPending(true);
    try {
      const body = {
        type: "facebook",
        name: form.name.trim(),
        countryCode: form.countryCode.toUpperCase(),
        templatePublicId: form.templateId,
        domainPublicId: form.domainId || undefined,
        slug: form.slug.trim(),
        pixelPublicId: form.pixelId || undefined,
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
  async function toggle(row: PromotionChannel) {
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
    const [statsPayload, leadsPayload, metricsPayload] = await Promise.all([
      apiRequest(`/api/promotion/channels/${insightChannelId}/stats`).catch(
        () => null,
      ),
      apiRequest(
        `/api/promotion/channels/${insightChannelId}/leads?pageSize=100`,
      ).catch(() => null),
      apiRequest(
        `/api/promotion/ad-metrics?promotionChannelId=${encodeURIComponent(insightChannelId)}&pageSize=100`,
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
    setInsightLoading(false);
  }
  function openMetric(row?: AdMetric) {
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
    if (!insightChannelId || !metricForm.date) return;
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
    <StandardListPage>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: "搜索渠道、国家、域名或 Slug",
        }}
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
                <TableHead>访问地址</TableHead>
                <TableHead>Pixel</TableHead>
                <TableHead>语言</TableHead>
                <TableHead>上线时间</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>
                    <strong>{row.name}</strong>
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
                      <strong>{row.hostname || "-"}</strong>
                      <span>/{row.slug}</span>
                    </div>
                  </TableCell>
                  <TableCell>{row.pixelName || "未绑定"}</TableCell>
                  <TableCell>
                    {row.localeMode === "fixed" ? row.locale || "固定" : "自动"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(row.goLiveAt)}
                  </TableCell>
                  <TableCell>
                    <Badge tone={row.enabled ? "success" : "neutral"}>
                      {row.enabled ? "启用" : "停用"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      <IconButton
                        label="打开真实渠道页：提交号码会创建账号并占用 IP"
                        onClick={() =>
                          window.open(
                            `/api/public/promotion/channels/${encodeURIComponent(row.slug)}/render`,
                            "_blank",
                          )
                        }
                      >
                        <EyeIcon size={16} />
                      </IconButton>
                      {canManage ? (
                        <>
                          <IconButton label="编辑" onClick={() => open(row)}>
                            <PencilIcon size={16} />
                          </IconButton>
                          <IconButton
                            label={row.enabled ? "停用" : "启用"}
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
      <div className="channel-data-bar">
        <SelectField
          className="w-[280px]"
          value={insightChannelId}
          onValueChange={setInsightChannelId}
          placeholder="选择渠道查看数据和号码"
          options={rows.map((row) => ({ value: row.id, label: row.name }))}
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
                !form.templateId ||
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
            <label className="field">
              <span>投放国家</span>
              <Input
                value={form.countryCode}
                maxLength={2}
                onChange={(e) =>
                  setForm({ ...form, countryCode: e.target.value })
                }
                placeholder="US"
              />
            </label>
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
              <span>域名</span>
              <SelectField
                className="w-full"
                value={form.domainId}
                clearable
                placeholder="不绑定独立域名"
                onValueChange={(value) => setForm({ ...form, domainId: value })}
                options={domains.map((row) => ({
                  value: row.id,
                  label: row.label,
                }))}
              />
            </label>
            <label className="field">
              <span>访问短码（Slug）</span>
              <Input
                value={form.slug}
                onChange={(e) =>
                  setForm({
                    ...form,
                    slug: e.target.value.replace(/[^a-zA-Z0-9-_]/g, ""),
                  })
                }
              />
            </label>
          </div>
          <label className="field">
            <span>Meta Pixel（可选）</span>
            <SelectField
              className="w-full"
              value={form.pixelId}
              clearable
              onValueChange={(value) => setForm({ ...form, pixelId: value })}
              placeholder="不绑定"
              options={pixels
                .filter((row) => row.enabled)
                .map((row) => ({ value: row.id, label: row.label }))}
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
        </div>
      </Drawer>
      <Drawer
        open={pixelDrawer}
        onClose={() => !pixelPending && setPixelDrawer(false)}
        title="Meta Pixel 管理"
        description="保存 Dataset ID；CAPI Token 只加密存储，之后仅显示掩码。"
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
                <div key={row.id}>
                  <div>
                    <strong>{row.name}</strong>
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
                    onClick={() => void togglePixel(row)}
                  >
                    {row.enabled ? "停用" : "启用"}
                  </Button>
                  <IconButton
                    label="归档 Pixel"
                    className="text-destructive"
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
                  <div key={metric.id}>
                    <strong>{metric.date}</strong>
                    <span>${metric.spend.toFixed(2)}</span>
                    <span>{metric.impressions.toLocaleString()} 展示</span>
                    <span>{metric.clicks.toLocaleString()} 点击</span>
                    {canManageMetrics ? (
                      <>
                        <IconButton
                          label="编辑日投放数据"
                          onClick={() => openMetric(metric)}
                        >
                          <PencilIcon size={14} />
                        </IconButton>
                        <IconButton
                          label="删除日投放数据"
                          className="text-destructive"
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
                      {String(lead.phone || lead.phoneNumber || "-")}
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
