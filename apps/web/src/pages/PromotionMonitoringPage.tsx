import {
  CopyIcon,
  ExternalLinkIcon,
  Globe2Icon,
  MonitorSmartphoneIcon,
  RefreshCwIcon,
  RouteIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiRequest, formatDateTime, unwrapList } from "../api/client";
import {
  CountryDisplay,
  countryDisplayName,
} from "../components/country-display";
import { MonitoringLandingCell } from "../components/monitoring-landing-cell";
import {
  RecordDataSection,
  RecordDetailField,
  RecordDetailSummaryCard,
  RecordDetailSummaryGrid,
} from "../components/record-detail";
import {
  ListPagination,
  ListSortableHead,
  ListTableCard,
  ListToolbar,
  StandardListPage,
  type ListSortOrder,
} from "../components/list-page";
import {
  Badge,
  Button,
  DatePickerField,
  Drawer,
  EmptyState,
  Input,
  SelectField,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  toast,
} from "../components/ui";

type RecordSource = "client" | "server" | "integration";

type MonitoringRecord = {
  id: string;
  publicId?: string;
  source: RecordSource;
  sourceLabel: string;
  eventType: string;
  eventLabel: string;
  failureLabel?: string | null;
  idempotencyKey?: string;
  trafficSource: string;
  occurredAt?: string;
  visitorId?: string | null;
  fingerprintVersion?: string | null;
  fingerprintQuality?: string | null;
  countryCode?: string | null;
  sourceIp?: string | null;
  visitorCountryCode?: string | null;
  networkSource?: string | null;
  device: {
    browser: string;
    type: "mobile" | "tablet" | "desktop";
    browserVersion?: string | null;
    system: string;
    systemVersion?: string | null;
    viewport?: number[] | null;
    userAgent?: string | null;
  };
  channel: {
    id: string;
    name: string;
    slug: string;
    countryCode: string;
  };
  template: {
    id?: string | null;
    name?: string | null;
    version?: string | null;
  };
  integration?: {
    id: string;
    name: string;
    version?: string | null;
  } | null;
  landing: { hostname?: string | null; url: string };
  leadId?: string | null;
  metadata?: Record<string, unknown>;
  metadataBytes?: number;
};

type Option = { id: string; name: string; version?: string };
type EventTypeOption = { value: string; label: string };
type MonitoringSortBy =
  | "id"
  | "visitorCountryCode"
  | "eventType"
  | "source"
  | "channelName"
  | "templateName"
  | "integrationName"
  | "deviceType"
  | "trafficSource"
  | "occurredAt";

const sourcePresentation: Record<
  RecordSource,
  { label: string; tone: "neutral" | "warning" | "success" }
> = {
  client: { label: "客户端行为", tone: "neutral" },
  server: { label: "服务端业务", tone: "success" },
  integration: { label: "集成回传", tone: "warning" },
};

const record = (value: unknown) =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

function dateInput(offsetDays = 0) {
  const value = new Date();
  value.setDate(value.getDate() + offsetDays);
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function viewportLabel(viewport?: number[] | null) {
  return viewport?.length === 2 ? `${viewport[0]} × ${viewport[1]}` : "尺寸未知";
}

function versionedName(name: string, version?: string | null) {
  return version ? `${name} ${version}` : name;
}

function networkSourceLabel(value?: string | null) {
  return {
    cloudflare: "Cloudflare",
    proxy: "反向代理",
    peer: "直接连接",
  }[value || ""] || "未采集";
}

function deviceTypeLabel(value?: string | null) {
  return { mobile: "手机", tablet: "平板", desktop: "桌面设备" }[value || ""] || "未知设备";
}

function pairingFailureStageLabel(value: unknown) {
  return {
    request_validation: "请求校验",
    preflight_rate_limit: "请求限速",
    number_check: "号码检查",
    protocol_routing: "协议路由",
    channel_configuration: "渠道配置",
    attempt_rate_limit: "任务限速",
    connection_route: "连接线路",
    attempt_creation: "任务创建",
    pairing_start: "启动配对",
    pairing_status: "配对状态",
    pairing_cancel: "取消配对",
    gateway_state: "网关状态",
    prepare_pairing: "准备配对通道",
    resolve_wa_version: "获取 WhatsApp 版本",
    wait_pair_success: "等待手机确认",
    connection: "协议连接",
  }[String(value || "")] || String(value || "未记录");
}

function validationFieldsLabel(value: unknown) {
  if (!Array.isArray(value) || !value.length) return "-";
  const labels: Record<string, string> = {
    body: "请求体",
    phone: "号码",
    deviceFingerprint: "设备指纹",
    metadata: "附加信息",
  };
  return value.map((field) => labels[String(field)] || String(field)).join("、");
}

function SourceBadge({ source }: { source: RecordSource }) {
  const value = sourcePresentation[source];
  return <Badge tone={value.tone}>{value.label}</Badge>;
}

function DateRangeFilters({
  from,
  to,
  onFromChange,
  onToChange,
}: {
  from: string;
  to: string;
  onFromChange: (value: string) => void;
  onToChange: (value: string) => void;
}) {
  return (
    <div className="date-range-controls">
      <DatePickerField
        ariaLabel="开始日期"
        value={from}
        onValueChange={onFromChange}
        className="w-[148px]"
      />
      <span>至</span>
      <DatePickerField
        ariaLabel="结束日期"
        value={to}
        onValueChange={onToChange}
        className="w-[148px]"
      />
    </div>
  );
}

function RecordDetail({
  item,
  onCopyLanding,
}: {
  item: MonitoringRecord;
  onCopyLanding: (value: string) => void;
}) {
  const metadata = item.metadata || {};
  const pairingFailure = item.eventType === "pairing_failed";
  const failureDetail = record(metadata.failureDetail);
  const failureTitle = String(
    failureDetail.title || metadata.reasonLabel || "其他失败",
  );
  return (
    <div className="flex flex-col gap-5">
      <RecordDetailSummaryGrid>
        <RecordDetailSummaryCard label="事件">
          <strong className="mt-1 block text-lg">{item.eventLabel}</strong>
          <span className="text-xs text-muted-foreground">{item.eventType}</span>
        </RecordDetailSummaryCard>
        <RecordDetailSummaryCard label="记录来源">
          <div className="mt-2"><SourceBadge source={item.source} /></div>
        </RecordDetailSummaryCard>
        <RecordDetailSummaryCard label="发生时间">
          <strong className="mt-1 block text-base">{formatDateTime(item.occurredAt)}</strong>
        </RecordDetailSummaryCard>
        <RecordDetailSummaryCard label="流量来源">
          <strong className="mt-1 block text-lg">
            {item.trafficSource === "fission" ? "裂变" : "直接"}
          </strong>
        </RecordDetailSummaryCard>
      </RecordDetailSummaryGrid>

      {pairingFailure ? (
        <div className="rounded-lg border p-4">
          <div className="mb-3 flex items-center gap-2">
            <Badge tone="danger">配对失败</Badge>
            <strong>{failureTitle}</strong>
          </div>
          {failureDetail.message ? (
            <p className="mb-2 text-sm text-muted-foreground">
              {String(failureDetail.message)}
            </p>
          ) : null}
          {failureDetail.suggestion ? (
            <p className="mb-3 text-sm">
              <span className="font-medium">处理建议：</span>
              {String(failureDetail.suggestion)}
            </p>
          ) : null}
          <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-2 text-sm">
            <RecordDetailField label="发生阶段">
              {pairingFailureStageLabel(metadata.stage)}
            </RecordDetailField>
            <RecordDetailField label="校验字段">
              {validationFieldsLabel(metadata.validationFields)}
            </RecordDetailField>
            <RecordDetailField label="失败代码">
              {String(metadata.reasonCode || "unknown")}
            </RecordDetailField>
            <RecordDetailField label="详细代码">
              {String(metadata.detailCode || "-")}
            </RecordDetailField>
            {metadata.attemptId ? (
              <RecordDetailField label="接入任务 ID">
                {String(metadata.attemptId)}
              </RecordDetailField>
            ) : null}
            {metadata.providerCode ? (
              <RecordDetailField label="网关代码">
                {String(metadata.providerCode)}
              </RecordDetailField>
            ) : null}
            {failureDetail.code ? (
              <RecordDetailField label="诊断代码">
                {String(failureDetail.code)}
              </RecordDetailField>
            ) : null}
            {failureDetail.technicalMessage ? (
              <RecordDetailField label="技术错误">
                {String(failureDetail.technicalMessage)}
              </RecordDetailField>
            ) : null}
          </dl>
        </div>
      ) : null}

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-lg border p-4">
          <div className="mb-3 flex items-center gap-2">
            <RouteIcon className="size-4 text-muted-foreground" />
            <strong>推广信息</strong>
          </div>
          <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-2 text-sm">
            <RecordDetailField label="落地页">{item.landing.hostname || "内部访问地址"}</RecordDetailField>
            <RecordDetailField label="渠道">{item.channel.name}</RecordDetailField>
            <RecordDetailField label="模板">
              {`${item.template.name || "模板已删除"} · v${item.template.version || "-"}`}
            </RecordDetailField>
            <RecordDetailField label="集成">
              {item.integration
                ? `${item.integration.name} · v${item.integration.version || "-"}`
                : "未关联"}
            </RecordDetailField>
          </dl>
        </div>
        <div className="rounded-lg border p-4">
          <div className="mb-3 flex items-center gap-2">
            <MonitorSmartphoneIcon className="size-4 text-muted-foreground" />
            <strong>设备信息</strong>
          </div>
          <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-2 text-sm">
            <RecordDetailField label="浏览器">
              {versionedName(item.device.browser, item.device.browserVersion)}
            </RecordDetailField>
            <RecordDetailField label="系统">
              {versionedName(item.device.system, item.device.systemVersion)}
            </RecordDetailField>
            <RecordDetailField label="视口">{viewportLabel(item.device.viewport)}</RecordDetailField>
            <RecordDetailField label="指纹质量">{item.fingerprintQuality || "未采集"}</RecordDetailField>
          </dl>
        </div>
        <div className="rounded-lg border p-4 lg:col-span-2">
          <div className="mb-3 flex items-center gap-2">
            <Globe2Icon className="size-4 text-muted-foreground" />
            <strong>网络信息</strong>
          </div>
          <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-2 text-sm">
            <RecordDetailField label="访问 IP">{item.sourceIp || "未采集"}</RecordDetailField>
            <RecordDetailField label="访问国家">
              {item.visitorCountryCode ? (
                <CountryDisplay
                  code={item.visitorCountryCode}
                  className="justify-start"
                />
              ) : "未采集"}
            </RecordDetailField>
            <RecordDetailField label="采集来源">
              {networkSourceLabel(item.networkSource)}
            </RecordDetailField>
          </dl>
        </div>
      </div>

      <div className="rounded-lg border p-4">
        <strong>记录信息</strong>
        <dl className="mt-3 grid grid-cols-[110px_1fr] gap-x-3 gap-y-2 text-sm">
          <RecordDetailField label="记录 ID">{item.id}</RecordDetailField>
          <RecordDetailField label="访客 ID">{item.visitorId || "未提供"}</RecordDetailField>
          <RecordDetailField label="幂等标识">{item.idempotencyKey || "-"}</RecordDetailField>
          <RecordDetailField label="线索 ID">{item.leadId || "未关联"}</RecordDetailField>
          <RecordDetailField label="内部公开标识">{item.publicId || "-"}</RecordDetailField>
        </dl>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          onClick={() => window.open(item.landing.url, "_blank", "noopener,noreferrer")}
        >
          <ExternalLinkIcon size={16} />打开落地页
        </Button>
        <Button variant="outline" onClick={() => onCopyLanding(item.landing.url)}>
          <CopyIcon size={16} />复制落地页
        </Button>
      </div>

      <RecordDataSection
        data={metadata}
        description="当前只展示这一条监控记录携带的数据，不再拼接访问时间线。"
        bytes={item.metadataBytes || 0}
      />
    </div>
  );
}

export default function PromotionMonitoringPage() {
  const [searchParams] = useSearchParams();
  const initialIntegrationId = searchParams.get("integrationId") || "all";
  const [rows, setRows] = useState<MonitoringRecord[]>([]);
  const [channels, setChannels] = useState<Option[]>([]);
  const [templates, setTemplates] = useState<Option[]>([]);
  const [integrations, setIntegrations] = useState<Option[]>([]);
  const [eventTypes, setEventTypes] = useState<EventTypeOption[]>([]);
  const [visitorCountries, setVisitorCountries] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState<MonitoringRecord | null>(null);
  const [keyword, setKeyword] = useState("");
  const [query, setQuery] = useState("");
  const [sourceIp, setSourceIp] = useState("");
  const [appliedSourceIp, setAppliedSourceIp] = useState("");
  const [source, setSource] = useState("all");
  const [eventType, setEventType] = useState("all");
  const [trafficSource, setTrafficSource] = useState("all");
  const [visitorCountryCode, setVisitorCountryCode] = useState("all");
  const [channelId, setChannelId] = useState("all");
  const [templateId, setTemplateId] = useState("all");
  const [integrationId, setIntegrationId] = useState(initialIntegrationId);
  const [deviceType, setDeviceType] = useState("all");
  const [dateFrom, setDateFrom] = useState(() => dateInput(-6));
  const [dateTo, setDateTo] = useState(() => dateInput());
  const [appliedDates, setAppliedDates] = useState(() => ({
    dateFrom: dateInput(-6),
    dateTo: dateInput(),
  }));
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [sortBy, setSortBy] = useState<MonitoringSortBy>("id");
  const [sortOrder, setSortOrder] = useState<ListSortOrder>("desc");

  const loadOptions = useCallback(async () => {
    try {
      const payload = await apiRequest("/api/promotion/monitoring/options");
      const data = record(record(payload).data ?? payload);
      setChannels(Array.isArray(data.channels) ? (data.channels as Option[]) : []);
      setTemplates(Array.isArray(data.templates) ? (data.templates as Option[]) : []);
      setIntegrations(Array.isArray(data.integrations) ? (data.integrations as Option[]) : []);
      setEventTypes(
        Array.isArray(data.eventTypes) ? (data.eventTypes as EventTypeOption[]) : [],
      );
      setVisitorCountries(
        Array.isArray(data.visitorCountries)
          ? (data.visitorCountries as string[])
          : [],
      );
    } catch {
      setChannels([]);
      setTemplates([]);
      setIntegrations([]);
      setEventTypes([]);
      setVisitorCountries([]);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        pageSize: String(pageSize),
        dateFrom: appliedDates.dateFrom,
        dateTo: appliedDates.dateTo,
        source,
        eventType,
        trafficSource,
        visitorCountryCode,
        deviceType,
        sortBy,
        sortOrder,
      });
      if (query) params.set("keyword", query);
      if (appliedSourceIp) params.set("sourceIp", appliedSourceIp);
      if (channelId !== "all") params.set("channelId", channelId);
      if (templateId !== "all") params.set("templateId", templateId);
      if (integrationId !== "all") params.set("integrationId", integrationId);
      const payload = await apiRequest(`/api/promotion/monitoring/records?${params}`);
      const list = unwrapList<MonitoringRecord>(payload);
      setRows(list.rows);
      setTotal(list.total);
    } catch (caught) {
      setRows([]);
      setTotal(0);
      toast.error(caught instanceof Error ? caught.message : "访问监控加载失败");
    } finally {
      setLoading(false);
    }
  }, [
    appliedDates,
    appliedSourceIp,
    channelId,
    eventType,
    deviceType,
    integrationId,
    page,
    pageSize,
    query,
    source,
    sortBy,
    sortOrder,
    templateId,
    trafficSource,
    visitorCountryCode,
  ]);

  useEffect(() => {
    void loadOptions();
  }, [loadOptions]);

  useEffect(() => {
    void load();
  }, [load]);

  const visibleSummary = useMemo(
    () => ({
      client: rows.filter((row) => row.source === "client").length,
      server: rows.filter((row) => row.source === "server").length,
      integration: rows.filter((row) => row.source === "integration").length,
    }),
    [rows],
  );

  async function openDetail(row: MonitoringRecord) {
    setDetail(row);
    setDetailLoading(true);
    try {
      const payload = await apiRequest(
        `/api/promotion/monitoring/records/${row.source}/${encodeURIComponent(row.id)}`,
      );
      const value = record(record(payload).data).record;
      setDetail(value as MonitoringRecord);
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "监控详情加载失败");
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }

  function applyFilters() {
    setPage(1);
    setQuery(keyword.trim());
    setAppliedSourceIp(sourceIp.trim());
    setAppliedDates({ dateFrom, dateTo });
  }

  function resetFilters() {
    const next = { dateFrom: dateInput(-6), dateTo: dateInput() };
    setKeyword("");
    setQuery("");
    setSourceIp("");
    setAppliedSourceIp("");
    setSource("all");
    setEventType("all");
    setTrafficSource("all");
    setVisitorCountryCode("all");
    setChannelId("all");
    setTemplateId("all");
    setIntegrationId("all");
    setDeviceType("all");
    setSortBy("id");
    setSortOrder("desc");
    setDateFrom(next.dateFrom);
    setDateTo(next.dateTo);
    setAppliedDates(next);
    setPage(1);
  }

  async function copyLandingUrl(value: string, notifications = toast) {
    try {
      await navigator.clipboard.writeText(value);
      notifications.success("访问地址已复制");
    } catch {
      notifications.error("复制失败，请手动复制");
    }
  }

  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          onSubmit: applyFilters,
          placeholder: "搜索记录 ID、访客 ID、访问 IP、渠道、域名或事件",
        }}
        filters={
          <>
            <DateRangeFilters
              from={dateFrom}
              to={dateTo}
              onFromChange={setDateFrom}
              onToChange={setDateTo}
            />
            <Input
              className="w-[160px]"
              aria-label="访问 IP"
              value={sourceIp}
              onChange={(event) => setSourceIp(event.target.value)}
              placeholder="访问 IP"
            />
            <SelectField
              ariaLabel="记录来源"
              value={source}
              onValueChange={(value) => {
                setPage(1);
                setSource(value);
              }}
              options={[
                { value: "all", label: "全部记录" },
                { value: "client", label: "客户端行为" },
                { value: "server", label: "服务端业务" },
                { value: "integration", label: "集成回传" },
              ]}
            />
            <SelectField
              ariaLabel="事件类型"
              value={eventType}
              onValueChange={(value) => {
                setPage(1);
                setEventType(value);
              }}
              options={[
                { value: "all", label: "全部事件" },
                ...eventTypes,
              ]}
            />
            <SelectField
              ariaLabel="流量来源"
              value={trafficSource}
              onValueChange={(value) => {
                setPage(1);
                setTrafficSource(value);
              }}
              options={[
                { value: "all", label: "全部流量" },
                { value: "direct", label: "直接" },
                { value: "fission", label: "裂变" },
              ]}
            />
            <SelectField
              ariaLabel="访问国家"
              value={visitorCountryCode}
              onValueChange={(value) => {
                setPage(1);
                setVisitorCountryCode(value);
              }}
              options={[
                { value: "all", label: "全部国家" },
                ...visitorCountries.map((code) => ({
                  value: code,
                  label: `${countryDisplayName(code)} · ${code}`,
                })),
              ]}
            />
            <SelectField
              ariaLabel="推广渠道"
              value={channelId}
              onValueChange={(value) => {
                setPage(1);
                setChannelId(value);
              }}
              options={[
                { value: "all", label: "全部渠道" },
                ...channels.map((row) => ({ value: row.id, label: row.name })),
              ]}
            />
            <SelectField
              ariaLabel="推广模板"
              value={templateId}
              onValueChange={(value) => {
                setPage(1);
                setTemplateId(value);
              }}
              options={[
                { value: "all", label: "全部模板" },
                ...templates.map((row) => ({
                  value: row.id,
                  label: `${row.name} · v${row.version || "-"}`,
                })),
              ]}
            />
            <SelectField
              ariaLabel="推广集成"
              value={integrationId}
              onValueChange={(value) => {
                setPage(1);
                setIntegrationId(value);
              }}
              options={[
                { value: "all", label: "全部集成" },
                ...integrations.map((row) => ({ value: row.id, label: row.name })),
              ]}
            />
            <SelectField
              ariaLabel="设备类型"
              value={deviceType}
              onValueChange={(value) => {
                setPage(1);
                setDeviceType(value);
              }}
              options={[
                { value: "all", label: "全部设备" },
                { value: "mobile", label: "手机" },
                { value: "tablet", label: "平板" },
                { value: "desktop", label: "桌面设备" },
              ]}
            />
          </>
        }
        meta={`${total} 条记录 · 当前页客户端 ${visibleSummary.client} · 服务端 ${visibleSummary.server} · 集成 ${visibleSummary.integration}`}
        actions={
          <>
            <Button variant="outline" onClick={resetFilters}>重置</Button>
            <Button variant="outline" onClick={() => void load()} disabled={loading}>
              <RefreshCwIcon size={16} className={loading ? "spin" : ""} />刷新
            </Button>
            <Button onClick={applyFilters}>查询</Button>
          </>
        }
      />
      <ListPagination
        page={page}
        pageSize={pageSize}
        total={total}
        disabled={loading}
        onPageChange={setPage}
        onPageSizeChange={(value) => {
          setPage(1);
          setPageSize(value);
        }}
      />
      <ListTableCard>
        {loading ? (
          <div className="loading-state"><Spinner />正在加载监控记录…</div>
        ) : rows.length ? (
          <Table layout="list">
            <TableHeader>
              <TableRow>
                <ListSortableHead sortKey="id" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={(key, order) => { setSortBy(key); setSortOrder(order); setPage(1); }}>访问ID/访客ID</ListSortableHead>
                <ListSortableHead sortKey="visitorCountryCode" activeSortKey={sortBy} sortOrder={sortOrder} onSort={(key, order) => { setSortBy(key); setSortOrder(order); setPage(1); }}>访问国家</ListSortableHead>
                <TableHead className="text-center">访问 IP</TableHead>
                <ListSortableHead sortKey="eventType" activeSortKey={sortBy} sortOrder={sortOrder} onSort={(key, order) => { setSortBy(key); setSortOrder(order); setPage(1); }}>事件</ListSortableHead>
                <ListSortableHead sortKey="source" activeSortKey={sortBy} sortOrder={sortOrder} onSort={(key, order) => { setSortBy(key); setSortOrder(order); setPage(1); }}>记录来源</ListSortableHead>
                <TableHead className="text-center" adaptive>落地页</TableHead>
                <ListSortableHead sortKey="channelName" activeSortKey={sortBy} sortOrder={sortOrder} onSort={(key, order) => { setSortBy(key); setSortOrder(order); setPage(1); }}>渠道</ListSortableHead>
                <ListSortableHead sortKey="templateName" activeSortKey={sortBy} sortOrder={sortOrder} onSort={(key, order) => { setSortBy(key); setSortOrder(order); setPage(1); }}>模板</ListSortableHead>
                <ListSortableHead sortKey="integrationName" activeSortKey={sortBy} sortOrder={sortOrder} onSort={(key, order) => { setSortBy(key); setSortOrder(order); setPage(1); }}>集成</ListSortableHead>
                <ListSortableHead sortKey="deviceType" activeSortKey={sortBy} sortOrder={sortOrder} onSort={(key, order) => { setSortBy(key); setSortOrder(order); setPage(1); }}>设备</ListSortableHead>
                <ListSortableHead sortKey="trafficSource" activeSortKey={sortBy} sortOrder={sortOrder} onSort={(key, order) => { setSortBy(key); setSortOrder(order); setPage(1); }}>流量来源</ListSortableHead>
                <ListSortableHead sortKey="occurredAt" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={(key, order) => { setSortBy(key); setSortOrder(order); setPage(1); }}>记录时间</ListSortableHead>
                <TableHead className="text-center">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={`${row.source}:${row.id}`}>
                  <TableCell className="text-center align-middle">
                    <div className="cell-main mx-auto min-w-[260px] justify-items-center text-center">
                      <strong className="whitespace-nowrap" title={row.id}>{row.id}</strong>
                      <span className="whitespace-nowrap" title={row.visitorId || ""}>
                        {row.visitorId || "未提供访客 ID"}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    {row.visitorCountryCode ? (
                      <CountryDisplay code={row.visitorCountryCode} />
                    ) : "-"}
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    <strong className="whitespace-nowrap" title={row.sourceIp || ""}>
                      {row.sourceIp || "-"}
                    </strong>
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    <div className="cell-main mx-auto min-w-[140px] justify-items-center text-center">
                      <strong>{row.eventLabel}</strong>
                      <span>{row.failureLabel || row.eventType}</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    <SourceBadge source={row.source} />
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    <MonitoringLandingCell
                      hostname={row.landing.hostname}
                      url={row.landing.url}
                      slug={row.channel.slug}
                      onCopy={(value) => void copyLandingUrl(value)}
                    />
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    <strong className="whitespace-nowrap">{row.channel.name}</strong>
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    <div className="cell-main mx-auto min-w-[145px] justify-items-center text-center">
                      <strong>{row.template.name || "模板已删除"}</strong>
                      <span>v{row.template.version || "-"}</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    {row.integration ? (
                      <div className="cell-main mx-auto min-w-[145px] justify-items-center text-center">
                        <strong>{row.integration.name}</strong>
                        <span>v{row.integration.version || "-"}</span>
                      </div>
                    ) : "-"}
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    <div className="cell-main mx-auto min-w-[180px] justify-items-center text-center">
                      <strong>{versionedName(row.device.browser, row.device.browserVersion)}</strong>
                      <span>
                        {deviceTypeLabel(row.device.type)} · {versionedName(row.device.system, row.device.systemVersion)} ·{" "}
                        {viewportLabel(row.device.viewport)}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    {row.trafficSource === "fission" ? "裂变" : "直接"}
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    <strong className="whitespace-nowrap">{formatDateTime(row.occurredAt)}</strong>
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    <div className="flex min-w-max items-center justify-center">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => void openDetail(row)}
                      >
                        查看详情
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <EmptyState
            title="暂无监控记录"
            description="落地页行为、服务端业务动作或集成回传产生后，会逐条显示在这里。"
          />
        )}
      </ListTableCard>

      <Drawer
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        title={`监控详情${detail ? ` · ${detail.id}` : ""}`}
        description={
          detail ? `${detail.eventLabel} · ${detail.sourceLabel} · ${formatDateTime(detail.occurredAt)}` : ""
        }
        wide
        footer={<Button onClick={() => setDetail(null)}>关闭</Button>}
      >
        {detailLoading || !detail?.metadata ? (
          <div className="loading-state"><Spinner />正在加载监控详情…</div>
        ) : (
          <RecordDetail
            item={detail}
            onCopyLanding={(value) => void copyLandingUrl(value, toast)}
          />
        )}
      </Drawer>
    </StandardListPage>
  );
}
