import {
  ChevronDownIcon,
  ChevronRightIcon,
  DownloadIcon,
  RefreshCwIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CartesianGrid,
  Funnel,
  FunnelChart,
  LabelList,
  Line,
  LineChart,
  XAxis,
  YAxis,
} from "recharts";
import { apiRequest, unwrapList } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { entityRowKey, snowflakeId } from "../lib/entity-identifiers";
import {
  Button,
  DatePickerField,
  EmptyState,
  IconButton,
  Input,
  MultiSelect,
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
import {
  ListPagination,
  ListTableCard,
  ListToolbar,
  StandardListPage,
  useClientPagination,
} from "../components/list-page";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "../components/ui/chart";

type Channel = {
  id: string;
  readKey: string;
  name: string;
  countryCode: string;
  templateId: string;
  templateName: string;
};
type ReportRow = Channel & {
  spend: number;
  otherCost: number;
  totalCost: number;
  impressions: number;
  adClicks: number;
  pageViews: number;
  uv: number;
  leads: number;
  loginSuccess: number;
  pairSuccess: number;
  loginRequest: number;
  loginRequestUv: number;
  loginSuccessCount: number;
  loginSuccessUv: number;
  successes: number;
  requestRate: number | null;
  successRate: number | null;
  visitorSuccessRate: number | null;
  costPerLead: number | null;
  costPerSuccess: number | null;
  fissionUv: number;
  fissionLoginRequest: number;
  fissionLoginRequestUv: number;
  fissionLoginSuccessCount: number;
  fissionLoginSuccessUv: number;
  creatorId: string;
  creatorName: string;
  daily: Array<Record<string, number | string>>;
};

const record = (value: unknown) =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};
const text = (row: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) if (row[key] != null) return String(row[key]);
  return "";
};
const number = (value: unknown) => Number(value || 0);
const optionalNumber = (value: unknown) =>
  value == null || value === "" ? null : Number(value);
const ratio = (value: number, base: number) => (base ? value / base : 0);
const percent = (value: number | null) =>
  value == null ? "-" : `${(value * 100).toFixed(2)}%`;
const money = (value: number | null) =>
  value == null ? "-" : new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  }).format(value);

function dateInput(offsetDays = 0) {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function channelFrom(value: unknown): Channel {
  const row = record(value);
  const id = snowflakeId(row, "id");
  return {
    id,
    readKey: entityRowKey(row, id, "promotion-channel", `${text(row, "name")}:${text(row, "countryCode", "country_code")}`),
    name: text(row, "name"),
    countryCode: text(row, "countryCode", "country_code"),
    templateId: snowflakeId(row, "templateId", "template_id"),
    templateName: text(row, "templateName"),
  };
}

function analyticsRow(value: unknown): ReportRow {
  const row = record(value);
  const id = snowflakeId(row, "promotionChannelId", "promotion_channel_id", "id");
  return {
    id,
    readKey: entityRowKey(
      row,
      id,
      "promotion-channel-stat",
      `${text(row, "promotionChannelName", "name")}:${text(row, "countryCode")}`,
      "promotionChannelPublicId",
      "promotion_channel_public_id",
      "publicId",
      "public_id",
    ),
    name: text(row, "promotionChannelName", "name"),
    countryCode: text(row, "countryCode"),
    templateId: snowflakeId(row, "templateId", "template_id"),
    templateName: text(row, "templateName"),
    spend: number(row.spend),
    otherCost: number(row.otherCost),
    totalCost: number(row.totalCost),
    impressions: number(row.impressions),
    adClicks: number(row.clicks),
    pageViews: number(row.pageViews),
    uv: number(row.uv),
    leads: number(row.leads),
    loginSuccess: number(row.loginSuccess),
    pairSuccess: number(row.pairSuccess),
    loginRequest: number(row.loginRequest ?? row.submissions),
    loginRequestUv: number(row.loginRequestUv ?? row.uniqueLeads),
    loginSuccessCount: number(row.loginSuccessCount ?? (number(row.loginSuccess) + number(row.pairSuccess))),
    loginSuccessUv: number(row.loginSuccessUv ?? row.successes),
    successes: number(row.successes),
    requestRate: optionalNumber(row.requestRate),
    successRate: optionalNumber(row.successRate),
    visitorSuccessRate: optionalNumber(row.visitorSuccessRate),
    costPerLead: optionalNumber(row.costPerLead),
    costPerSuccess: optionalNumber(row.costPerSuccess),
    fissionUv: number(row.fissionUv),
    fissionLoginRequest: number(row.fissionLoginRequest),
    fissionLoginRequestUv: number(row.fissionLoginRequestUv),
    fissionLoginSuccessCount: number(row.fissionLoginSuccessCount),
    fissionLoginSuccessUv: number(row.fissionLoginSuccessUv),
    creatorId: snowflakeId(row, "creatorId", "creator_id"),
    creatorName: text(row, "creatorName"),
    daily: Array.isArray(row.daily)
      ? row.daily.map((item) => {
          const value = record(item);
          return {
            ...Object.fromEntries(
            Object.entries(value).map(([key, raw]) => [
              key,
              key === "date" ? String(raw || "") : number(raw),
            ]),
            ),
            adMetricId: snowflakeId(value, "adMetricId", "ad_metric_id"),
          };
        })
      : [],
  };
}

function usePromotionReport(mode: "channels" | "trends" = "channels", selectedChannelId = "all") {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [rows, setRows] = useState<ReportRow[]>([]);
  const [series, setSeries] = useState<Array<Record<string, string | number>>>([]);
  const [summary, setSummary] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [dateFrom, setDateFrom] = useState(() => dateInput(-6));
  const [dateTo, setDateTo] = useState(() => dateInput());
  const [appliedDates, setAppliedDates] = useState(() => ({
    dateFrom: dateInput(-6),
    dateTo: dateInput(),
  }));

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        dateFrom: appliedDates.dateFrom,
        dateTo: appliedDates.dateTo,
      });
      if (selectedChannelId !== "all") params.set("channelIds", selectedChannelId);
      const [channelPayload, analyticsPayload] = await Promise.all([
        apiRequest("/api/promotion/channels?pageSize=100"),
        apiRequest(`/api/promotion/data-center/${mode}?${params}`),
      ]);
      const nextChannels = unwrapList<unknown>(channelPayload).rows.map(channelFrom);
      const body = record(record(analyticsPayload).data ?? analyticsPayload);
      setChannels(nextChannels);
      setRows(Array.isArray(body.rows) ? body.rows.map(analyticsRow) : []);
      setSummary(record(body.summary));
      setSeries(Array.isArray(body.series) ? body.series.map((item) => {
        const value = record(item);
        return Object.fromEntries(Object.entries(value).map(([key, raw]) => [key, key === "date" ? String(raw) : number(raw)]));
      }) : []);
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "推广数据加载失败");
    } finally {
      setLoading(false);
    }
  }, [appliedDates, mode, selectedChannelId]);

  useEffect(() => {
    void load();
  }, [load]);

  return {
    channels,
    loading,
    dateFrom,
    dateTo,
    setDateFrom,
    setDateTo,
    apply: () => setAppliedDates({ dateFrom, dateTo }),
    reset: () => {
      const next = { dateFrom: dateInput(-6), dateTo: dateInput() };
      setDateFrom(next.dateFrom);
      setDateTo(next.dateTo);
      setAppliedDates(next);
    },
    refresh: load,
    rows,
    series,
    summary,
  };
}

function DateRangeControls({
  dateFrom,
  dateTo,
  setDateFrom,
  setDateTo,
}: {
  dateFrom: string;
  dateTo: string;
  setDateFrom: (value: string) => void;
  setDateTo: (value: string) => void;
}) {
  return (
    <div className="date-range-controls">
      <DatePickerField
        ariaLabel="开始日期"
        value={dateFrom}
        onValueChange={setDateFrom}
        className="w-[148px]"
      />
      <span>至</span>
      <DatePickerField
        ariaLabel="结束日期"
        value={dateTo}
        onValueChange={setDateTo}
        className="w-[148px]"
      />
    </div>
  );
}

function DailyMetricEditor({
  channelId,
  item,
  canEdit,
}: {
  channelId: string;
  item: Record<string, number | string>;
  canEdit: boolean;
}) {
  const [metricId, setMetricId] = useState(String(item.adMetricId || ""));
  const [draft, setDraft] = useState({
    spend: String(item.spend ?? 0),
    impressions: String(item.impressions ?? 0),
    clicks: String(item.clicks ?? 0),
    adFeeRate: String(item.adFeeRate ?? 0),
    otherCost: String(item.otherCost ?? 0),
  });
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const latest = useRef(draft);
  latest.current = draft;

  useEffect(() => {
    if (!revision || !canEdit) return;
    let active = true;
    const timer = window.setTimeout(async () => {
      setState("saving");
      const body = {
        date: String(item.date),
        promotionChannelId: channelId,
        spend: Math.max(0, Number(latest.current.spend) || 0),
        impressions: Math.max(0, Math.trunc(Number(latest.current.impressions) || 0)),
        clicks: Math.max(0, Math.trunc(Number(latest.current.clicks) || 0)),
        adFeeRate: Math.max(0, Number(latest.current.adFeeRate) || 0),
        otherCost: Math.max(0, Number(latest.current.otherCost) || 0),
      };
      try {
        const payload = await apiRequest(
          metricId ? `/api/promotion/ad-metrics/${metricId}` : "/api/promotion/ad-metrics",
          { method: metricId ? "PATCH" : "POST", body: JSON.stringify(body) },
        );
        if (!active) return;
        const data = record(record(payload).data);
        const saved = record(data.adMetric || data.metric || data);
        const nextId = snowflakeId(saved, "id");
        if (nextId) setMetricId(nextId);
        setState("saved");
      } catch {
        if (active) setState("error");
      }
    }, 600);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [canEdit, channelId, item.date, metricId, revision]);

  function update(key: keyof typeof draft, next: string) {
    setDraft((current) => ({ ...current, [key]: next }));
    setRevision((current) => current + 1);
    setState("idle");
  }
  const controls: Array<{ key: keyof typeof draft; label: string; step: string }> = [
    { key: "spend", label: "消耗", step: "0.01" },
    { key: "impressions", label: "展示", step: "1" },
    { key: "clicks", label: "点击", step: "1" },
    { key: "adFeeRate", label: "手续费 %", step: "0.01" },
    { key: "otherCost", label: "其他费用", step: "0.01" },
  ];
  return (
    <div className="grid gap-3 border-t py-3 first:border-t-0 lg:grid-cols-[110px_repeat(5,minmax(110px,1fr))_90px] lg:items-end">
      <strong className="pb-2">{item.date}</strong>
      {controls.map((control) => (
        <label className="field" key={control.key}>
          <span>{control.label}</span>
          <Input
            type="number"
            min="0"
            step={control.step}
            disabled={!canEdit}
            value={draft[control.key]}
            onChange={(event) => update(control.key, event.target.value)}
          />
        </label>
      ))}
      <span className={`pb-2 text-xs ${state === "error" ? "text-destructive" : "text-muted-foreground"}`}>
        {state === "saving" ? "保存中…" : state === "saved" ? "已保存" : state === "error" ? "保存失败" : "自动保存"}
      </span>
    </div>
  );
}

export function PromotionChannelStatisticsPage() {
  const { can } = useAuth();
  const canEditMetrics = can("promotion.statistics.manage");
  const report = usePromotionReport();
  const [channelId, setChannelId] = useState("all");
  const [templateId, setTemplateId] = useState("all");
  const [countryCode, setCountryCode] = useState("all");
  const [creatorId, setCreatorId] = useState("all");
  const [keyword, setKeyword] = useState("");
  const [expanded, setExpanded] = useState<string[]>([]);
  const [visibleColumns, setVisibleColumns] = useState(["fission", "template", "creator"]);
  const templates = useMemo(
    () =>
      Array.from(new Map(report.channels.filter((row) => row.templateId).map((row) => [row.templateId, row])).values()),
    [report.channels],
  );
  const countries = useMemo(
    () => Array.from(new Set(report.channels.map((row) => row.countryCode).filter(Boolean))),
    [report.channels],
  );
  const creators = useMemo(
    () => Array.from(new Map(report.rows.filter((row) => row.creatorId).map((row) => [row.creatorId, row.creatorName])).entries()),
    [report.rows],
  );
  const rows = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return report.rows.filter(
      (row) =>
        (channelId === "all" || row.id === channelId) &&
        (templateId === "all" || row.templateId === templateId) &&
        (countryCode === "all" || row.countryCode === countryCode) &&
        (creatorId === "all" || row.creatorId === creatorId) &&
        (!search || `${row.name} ${row.templateName}`.toLowerCase().includes(search)),
    );
  }, [channelId, countryCode, creatorId, keyword, report.rows, templateId]);
  const pagination = useClientPagination(rows, {
    resetKey: `${keyword}|${channelId}|${templateId}|${countryCode}|${creatorId}|${report.dateFrom}|${report.dateTo}`,
  });
  function resetFilters() {
    setKeyword("");
    setChannelId("all");
    setTemplateId("all");
    setCountryCode("all");
    setCreatorId("all");
    report.reset();
  }

  function exportRows() {
    const header = [
      "渠道",
      "国家",
      "登录请求次数",
      "登录请求人数",
      "登录成功次数",
      "登录成功人数",
      "请求登录率",
      "登录成功率",
      "访客上号率",
      "获号成本",
      "裂变登录请求次数",
      "裂变登录请求人数",
      "裂变登录成功次数",
      "裂变登录成功人数",
      "模板",
      "创建人",
    ];
    const csv = [
      header,
      ...rows.map((row) => [
        row.name,
        row.countryCode,
        row.loginRequest,
        row.loginRequestUv,
        row.loginSuccessCount,
        row.loginSuccessUv,
        percent(row.requestRate),
        percent(row.successRate),
        percent(row.visitorSuccessRate),
        row.costPerSuccess?.toFixed(2) ?? "-",
        row.fissionLoginRequest,
        row.fissionLoginRequestUv,
        row.fissionLoginSuccessCount,
        row.fissionLoginSuccessUv,
        row.templateName,
        row.creatorName,
      ]),
    ]
      .map((line) => line.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(","))
      .join("\n");
    const url = URL.createObjectURL(
      new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `渠道统计-${report.dateFrom}-${report.dateTo}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{ value: keyword, onChange: setKeyword, placeholder: "搜索渠道名称" }}
        filters={
          <>
            <DateRangeControls {...report} />
            <SelectField
              ariaLabel="渠道"
              value={channelId}
              onValueChange={setChannelId}
              options={[
                { value: "all", label: "全部渠道" },
                ...report.channels.filter((row) => row.id).map((row) => ({ value: row.id, label: row.name })),
              ]}
            />
            <SelectField
              ariaLabel="创建人"
              value={creatorId}
              onValueChange={setCreatorId}
              options={[
                { value: "all", label: "全部创建人" },
                ...creators.map(([value, label]) => ({ value, label: label || value })),
              ]}
            />
            <SelectField
              ariaLabel="模板"
              value={templateId}
              onValueChange={setTemplateId}
              options={[
                { value: "all", label: "全部模板" },
                ...templates.map((row) => ({
                  value: row.templateId,
                  label: row.templateName,
                })),
              ]}
            />
            <SelectField
              ariaLabel="目标国家"
              value={countryCode}
              onValueChange={setCountryCode}
              options={[
                { value: "all", label: "全部国家" },
                ...countries.map((value) => ({ value, label: value })),
              ]}
            />
            <MultiSelect
              className="w-[150px]"
              value={visibleColumns}
              onValueChange={setVisibleColumns}
              placeholder="自定义列"
              options={[
                { value: "fission", label: "裂变数据" },
                { value: "template", label: "模板" },
                { value: "creator", label: "创建人" },
              ]}
            />
          </>
        }
        actions={
          <>
            <Button variant="outline" onClick={resetFilters}>重置</Button>
            <Button variant="outline" onClick={() => void report.refresh()}>
              <RefreshCwIcon size={16} className={report.loading ? "spin" : ""} />
              刷新
            </Button>
            <Button variant="outline" onClick={exportRows} disabled={!rows.length}>
              <DownloadIcon size={16} />
              导出
            </Button>
            <Button onClick={report.apply}>查询</Button>
          </>
        }
      />
      <ListPagination
        page={pagination.page}
        pageSize={pagination.pageSize}
        total={pagination.total}
        onPageChange={pagination.setPage}
        onPageSizeChange={pagination.setPageSize}
      />
      <ListTableCard>
        {report.loading ? (
          <div className="loading-state"><Spinner />正在加载渠道统计…</div>
        ) : rows.length ? (
          <div className="table-scroll">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="expand-column" />
                  <TableHead>渠道 / 国家</TableHead>
                  <TableHead>登录请求（次数 / 人数）</TableHead>
                  <TableHead>登录成功（次数 / 人数）</TableHead>
                  <TableHead>请求登录率</TableHead>
                  <TableHead>登录成功率</TableHead>
                  <TableHead>访客上号率</TableHead>
                  <TableHead>获号成本</TableHead>
                  {visibleColumns.includes("fission") ? <TableHead>裂变（请求 / 成功）</TableHead> : null}
                  {visibleColumns.includes("template") ? <TableHead>模板</TableHead> : null}
                  {visibleColumns.includes("creator") ? <TableHead>创建人</TableHead> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {pagination.rows.flatMap((row) => {
                  const open = expanded.includes(row.readKey);
                  const parent = (
                    <TableRow key={row.readKey}>
                      <TableCell>
                        <IconButton
                          label={open ? "收起每日明细" : "展开每日明细"}
                          onClick={() =>
                            setExpanded((current) =>
                              open
                                ? current.filter((value) => value !== row.readKey)
                                : [...current, row.readKey],
                            )
                          }
                        >
                          {open ? <ChevronDownIcon size={16} /> : <ChevronRightIcon size={16} />}
                        </IconButton>
                      </TableCell>
                      <TableCell>
                        <div className="cell-main">
                          <strong>{row.name}</strong>
                          <span>{row.id || "等待 ID 迁移"}</span>
                          <span>{row.countryCode || "-"}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="cell-main"><strong>{row.loginRequest.toLocaleString()} 次</strong><span>{row.loginRequestUv.toLocaleString()} 人</span></div>
                      </TableCell>
                      <TableCell>
                        <div className="cell-main"><strong>{row.loginSuccessCount.toLocaleString()} 次</strong><span>{row.loginSuccessUv.toLocaleString()} 人</span></div>
                      </TableCell>
                      <TableCell className="tabular-nums">{percent(row.requestRate)}</TableCell>
                      <TableCell className="tabular-nums">{percent(row.successRate)}</TableCell>
                      <TableCell className="tabular-nums">{percent(row.visitorSuccessRate)}</TableCell>
                      <TableCell className="tabular-nums">{money(row.costPerSuccess)}</TableCell>
                      {visibleColumns.includes("fission") ? <TableCell><div className="cell-main"><strong>请求 {row.fissionLoginRequest} / {row.fissionLoginRequestUv} 人</strong><span>成功 {row.fissionLoginSuccessCount} / {row.fissionLoginSuccessUv} 人</span></div></TableCell> : null}
                      {visibleColumns.includes("template") ? <TableCell>{row.templateName || "-"}</TableCell> : null}
                      {visibleColumns.includes("creator") ? <TableCell>{row.creatorName || "-"}</TableCell> : null}
                    </TableRow>
                  );
                  const detail = open ? (
                    <TableRow key={`${row.readKey}-detail`} className="table-detail-row">
                      <TableCell colSpan={8 + visibleColumns.length}>
                        <div className="p-2">
                          <div className="mb-2 flex items-center justify-between"><strong>每日广告成本明细</strong><span className="text-xs text-muted-foreground">修改后 600ms 自动保存</span></div>
                          {row.daily.length ? row.daily.map((item) => (
                            <DailyMetricEditor
                              key={item.date}
                              channelId={row.id}
                              item={item}
                              canEdit={canEditMetrics && Boolean(row.id)}
                            />
                          )) : <span className="text-muted-foreground">所选日期暂无明细</span>}
                        </div>
                      </TableCell>
                    </TableRow>
                  ) : null;
                  return detail ? [parent, detail] : [parent];
                })}
              </TableBody>
            </Table>
          </div>
        ) : (
          <EmptyState title="暂无渠道统计" description="调整筛选条件后重新查询。" />
        )}
      </ListTableCard>
    </StandardListPage>
  );
}

const conversionChartConfig = {
  requestRate: { label: "号码请求率", color: "#7c6ed3" },
  successRate: { label: "请求成功率", color: "#1c96a8" },
} satisfies ChartConfig;

function ConversionTrendPanel({ rows }: { rows: Array<Record<string, string | number>> }) {
  return (
    <section className="trend-panel">
      <header><strong>转化率趋势</strong></header>
      <ChartContainer config={conversionChartConfig} className="promotion-chart">
        <LineChart data={rows} margin={{ top: 12, right: 18, bottom: 4, left: 0 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          <XAxis dataKey="date" tickFormatter={(value) => String(value).slice(5)} tickLine={false} axisLine={false} />
          <YAxis unit="%" tickLine={false} axisLine={false} width={44} />
          <ChartTooltip content={<ChartTooltipContent />} />
          <Line type="monotone" dataKey="requestRate" stroke="var(--color-requestRate)" strokeWidth={2.5} dot={false} />
          <Line type="monotone" dataKey="successRate" stroke="var(--color-successRate)" strokeWidth={2.5} dot={false} />
        </LineChart>
      </ChartContainer>
    </section>
  );
}

function ConversionFunnelPanel({
  uv,
  leads,
  successes,
}: {
  uv: number;
  leads: number;
  successes: number;
}) {
  const rows = [
    { name: "独立访客", value: uv, fill: "#6d87cd" },
    { name: "号码提交", value: leads, fill: "#16a36a" },
    { name: "登录 / 配对成功", value: successes, fill: "#d98b2b" },
  ];
  return (
    <section className="trend-panel">
      <header><strong>访问转化漏斗</strong></header>
      <ChartContainer config={{ value: { label: "数量", color: "#6d87cd" } }} className="promotion-chart">
        <FunnelChart margin={{ top: 12, right: 28, bottom: 12, left: 28 }}>
          <ChartTooltip content={<ChartTooltipContent />} />
          <Funnel dataKey="value" data={rows} isAnimationActive={false}>
            <LabelList position="right" dataKey="name" fill="var(--foreground)" stroke="none" />
            <LabelList position="center" dataKey="value" fill="#fff" stroke="none" />
          </Funnel>
        </FunnelChart>
      </ChartContainer>
    </section>
  );
}

export function PromotionTrendPage() {
  const [channelId, setChannelId] = useState("all");
  const report = usePromotionReport("trends", channelId);
  const daily: Array<{
    date: string;
    uv: number;
    leads: number;
    successes: number;
    requestRate: number;
    successRate: number;
  }> = report.series.map((row) => ({
    date: String(row.date || ""),
    uv: number(row.uv),
    leads: number(row.leads),
    successes: number(row.successes),
    requestRate: number(row.requestRate) * 100,
    successRate: number(row.successRate) * 100,
  }));
  const pagination = useClientPagination(daily, {
    resetKey: `${channelId}|${report.dateFrom}|${report.dateTo}`,
  });
  const totals = {
    uv: number(report.summary.uv),
    leads: number(report.summary.leads),
    successes: number(report.summary.successes),
  };

  return (
    <StandardListPage>
      <ListToolbar
        filters={
          <>
            <DateRangeControls {...report} />
            <SelectField
              ariaLabel="渠道"
              value={channelId}
              onValueChange={setChannelId}
              options={[
                { value: "all", label: "全部渠道" },
                ...report.channels.filter((row) => row.id).map((row) => ({ value: row.id, label: row.name })),
              ]}
            />
          </>
        }
        actions={
          <>
            <Button variant="outline" onClick={report.reset}>重置</Button>
            <Button variant="outline" onClick={() => void report.refresh()}>
              <RefreshCwIcon size={16} className={report.loading ? "spin" : ""} />刷新
            </Button>
            <Button onClick={report.apply}>查询</Button>
          </>
        }
      />
      {report.loading ? (
        <div className="card loading-state"><Spinner />正在加载趋势数据…</div>
      ) : (
        <>
          <div className="trend-grid">
            <ConversionFunnelPanel {...totals} />
            <ConversionTrendPanel rows={daily} />
          </div>
          <ListPagination
            page={pagination.page}
            pageSize={pagination.pageSize}
            total={pagination.total}
            onPageChange={pagination.setPage}
            onPageSizeChange={pagination.setPageSize}
          />
          <ListTableCard>
            {daily.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>日期</TableHead>
                    <TableHead>独立访客</TableHead>
                    <TableHead>号码提交</TableHead>
                    <TableHead>登录 / 配对成功</TableHead>
                    <TableHead>号码请求率</TableHead>
                    <TableHead>请求成功率</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pagination.rows.map((row) => (
                    <TableRow key={row.date}>
                      <TableCell><strong>{row.date}</strong></TableCell>
                      <TableCell className="tabular-nums">{number(row.uv).toLocaleString()}</TableCell>
                      <TableCell className="tabular-nums">{number(row.leads).toLocaleString()}</TableCell>
                      <TableCell className="tabular-nums">{number(row.successes).toLocaleString()}</TableCell>
                      <TableCell className="tabular-nums">{number(row.requestRate).toFixed(2)}%</TableCell>
                      <TableCell className="tabular-nums">{number(row.successRate).toFixed(2)}%</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState title="暂无趋势数据" description="调整日期或渠道后重新查询。" />
            )}
          </ListTableCard>
        </>
      )}
    </StandardListPage>
  );
}
