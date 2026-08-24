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
  ListPagination,
  ListTableCard,
  ListToolbar,
  StandardListPage,
} from "../components/list-page";
import {
  Badge,
  Button,
  DatePickerField,
  Drawer,
  EmptyState,
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

function DefinitionRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-all">{value || "-"}</dd>
    </>
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
  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-lg border bg-card p-3">
          <span className="text-xs text-muted-foreground">事件</span>
          <strong className="mt-1 block text-lg">{item.eventLabel}</strong>
          <span className="text-xs text-muted-foreground">{item.eventType}</span>
        </div>
        <div className="rounded-lg border bg-card p-3">
          <span className="text-xs text-muted-foreground">记录来源</span>
          <div className="mt-2"><SourceBadge source={item.source} /></div>
        </div>
        <div className="rounded-lg border bg-card p-3">
          <span className="text-xs text-muted-foreground">发生时间</span>
          <strong className="mt-1 block text-base">{formatDateTime(item.occurredAt)}</strong>
        </div>
        <div className="rounded-lg border bg-card p-3">
          <span className="text-xs text-muted-foreground">流量来源</span>
          <strong className="mt-1 block text-lg">
            {item.trafficSource === "fission" ? "裂变" : "直接"}
          </strong>
        </div>
      </div>

      {pairingFailure ? (
        <div className="rounded-lg border p-4">
          <div className="mb-3 flex items-center gap-2">
            <Badge tone="danger">配对失败</Badge>
            <strong>{String(metadata.reasonLabel || "其他失败")}</strong>
          </div>
          <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-2 text-sm">
            <DefinitionRow
              label="发生阶段"
              value={pairingFailureStageLabel(metadata.stage)}
            />
            <DefinitionRow
              label="校验字段"
              value={validationFieldsLabel(metadata.validationFields)}
            />
            <DefinitionRow
              label="失败代码"
              value={String(metadata.reasonCode || "unknown")}
            />
            <DefinitionRow
              label="详细代码"
              value={String(metadata.detailCode || "-")}
            />
            {metadata.attemptId ? (
              <DefinitionRow
                label="接入任务 ID"
                value={String(metadata.attemptId)}
              />
            ) : null}
            {metadata.providerCode ? (
              <DefinitionRow
                label="网关代码"
                value={String(metadata.providerCode)}
              />
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
            <DefinitionRow label="落地页" value={item.landing.hostname || "内部访问地址"} />
            <DefinitionRow label="渠道" value={item.channel.name} />
            <DefinitionRow
              label="模板"
              value={`${item.template.name || "模板已删除"} · v${item.template.version || "-"}`}
            />
            <DefinitionRow
              label="集成"
              value={
                item.integration
                  ? `${item.integration.name} · v${item.integration.version || "-"}`
                  : "未关联"
              }
            />
          </dl>
        </div>
        <div className="rounded-lg border p-4">
          <div className="mb-3 flex items-center gap-2">
            <MonitorSmartphoneIcon className="size-4 text-muted-foreground" />
            <strong>设备信息</strong>
          </div>
          <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-2 text-sm">
            <DefinitionRow
              label="浏览器"
              value={versionedName(item.device.browser, item.device.browserVersion)}
            />
            <DefinitionRow
              label="系统"
              value={versionedName(item.device.system, item.device.systemVersion)}
            />
            <DefinitionRow label="视口" value={viewportLabel(item.device.viewport)} />
            <DefinitionRow label="指纹质量" value={item.fingerprintQuality || "未采集"} />
          </dl>
        </div>
        <div className="rounded-lg border p-4 lg:col-span-2">
          <div className="mb-3 flex items-center gap-2">
            <Globe2Icon className="size-4 text-muted-foreground" />
            <strong>网络信息</strong>
          </div>
          <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-2 text-sm">
            <DefinitionRow label="访问 IP" value={item.sourceIp || "未采集"} />
            <DefinitionRow
              label="访问国家"
              value={
                item.visitorCountryCode ? (
                  <CountryDisplay
                    code={item.visitorCountryCode}
                    className="justify-start"
                  />
                ) : "未采集"
              }
            />
            <DefinitionRow
              label="采集来源"
              value={networkSourceLabel(item.networkSource)}
            />
          </dl>
        </div>
      </div>

      <div className="rounded-lg border p-4">
        <strong>记录信息</strong>
        <dl className="mt-3 grid grid-cols-[110px_1fr] gap-x-3 gap-y-2 text-sm">
          <DefinitionRow label="记录 ID" value={item.id} />
          <DefinitionRow label="访客 ID" value={item.visitorId || "未提供"} />
          <DefinitionRow label="幂等标识" value={item.idempotencyKey || "-"} />
          <DefinitionRow label="线索 ID" value={item.leadId || "未关联"} />
          <DefinitionRow label="内部公开标识" value={item.publicId || "-"} />
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

      <section>
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <strong>记录数据</strong>
            <p className="mt-1 text-xs text-muted-foreground">
              当前只展示这一条监控记录携带的数据，不再拼接访问时间线。
            </p>
          </div>
          <Badge tone="neutral">{(item.metadataBytes || 0).toLocaleString()} 字节</Badge>
        </div>
        {Object.keys(metadata).length ? (
          <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted p-4 text-xs">
            {JSON.stringify(metadata, null, 2)}
          </pre>
        ) : (
          <EmptyState title="暂无附加数据" description="这条记录没有携带额外数据。" />
        )}
      </section>
    </div>
  );
}

export default function PromotionMonitoringPage() {
  const [searchParams] = useSearchParams();
  const integrationId = searchParams.get("integrationId") || "";
  const [rows, setRows] = useState<MonitoringRecord[]>([]);
  const [channels, setChannels] = useState<Option[]>([]);
  const [templates, setTemplates] = useState<Option[]>([]);
  const [eventTypes, setEventTypes] = useState<EventTypeOption[]>([]);
  const [visitorCountries, setVisitorCountries] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState<MonitoringRecord | null>(null);
  const [keyword, setKeyword] = useState("");
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("all");
  const [eventType, setEventType] = useState("all");
  const [trafficSource, setTrafficSource] = useState("all");
  const [visitorCountryCode, setVisitorCountryCode] = useState("all");
  const [channelId, setChannelId] = useState("all");
  const [templateId, setTemplateId] = useState("all");
  const [dateFrom, setDateFrom] = useState(() => dateInput(-6));
  const [dateTo, setDateTo] = useState(() => dateInput());
  const [appliedDates, setAppliedDates] = useState(() => ({
    dateFrom: dateInput(-6),
    dateTo: dateInput(),
  }));
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);

  const loadOptions = useCallback(async () => {
    try {
      const payload = await apiRequest("/api/promotion/monitoring/options");
      const data = record(record(payload).data ?? payload);
      setChannels(Array.isArray(data.channels) ? (data.channels as Option[]) : []);
      setTemplates(Array.isArray(data.templates) ? (data.templates as Option[]) : []);
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
      });
      if (query) params.set("keyword", query);
      if (channelId !== "all") params.set("channelId", channelId);
      if (templateId !== "all") params.set("templateId", templateId);
      if (integrationId) params.set("integrationId", integrationId);
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
    channelId,
    eventType,
    integrationId,
    page,
    pageSize,
    query,
    source,
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
    setAppliedDates({ dateFrom, dateTo });
  }

  function resetFilters() {
    const next = { dateFrom: dateInput(-6), dateTo: dateInput() };
    setKeyword("");
    setQuery("");
    setSource("all");
    setEventType("all");
    setTrafficSource("all");
    setVisitorCountryCode("all");
    setChannelId("all");
    setTemplateId("all");
    setDateFrom(next.dateFrom);
    setDateTo(next.dateTo);
    setAppliedDates(next);
    setPage(1);
  }

  async function copyLandingUrl(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      toast.success("访问地址已复制");
    } catch {
      toast.error("复制失败，请手动复制");
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
                <TableHead className="text-center">记录 / 访客</TableHead>
                <TableHead className="text-center">访问国家</TableHead>
                <TableHead className="text-center">访问 IP</TableHead>
                <TableHead className="text-center">事件</TableHead>
                <TableHead className="text-center">记录来源</TableHead>
                <TableHead className="text-center" adaptive>落地页</TableHead>
                <TableHead className="text-center">渠道</TableHead>
                <TableHead className="text-center">模板</TableHead>
                <TableHead className="text-center">集成</TableHead>
                <TableHead className="text-center">设备</TableHead>
                <TableHead className="text-center">流量来源</TableHead>
                <TableHead className="text-center">记录时间</TableHead>
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
                      <span>{row.eventType}</span>
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
                        {versionedName(row.device.system, row.device.systemVersion)} ·{" "}
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
          <RecordDetail item={detail} onCopyLanding={(value) => void copyLandingUrl(value)} />
        )}
      </Drawer>
    </StandardListPage>
  );
}
