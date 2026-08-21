import {
  BanIcon,
  CheckCircle2Icon,
  Globe2Icon,
  RefreshCwIcon,
  UsersIcon,
  WifiIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  XAxis,
  YAxis,
} from "recharts";
import { apiRequest, formatLocalDateInput } from "../api/client";
import { DatePickerField } from "../components/date-picker-field";
import {
  ListTableCard,
  ListToolbar,
  StandardListPage,
} from "../components/list-page";
import {
  Badge,
  Button,
  EmptyState,
  SelectField,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../components/ui";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "../components/ui/chart";

const pick = (row: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) if (row[key] != null) return row[key];
  return undefined;
};
const stringValue = (row: Record<string, unknown>, ...keys: string[]) => {
  const found = pick(row, ...keys);
  return found == null ? "" : String(found);
};
const numberValue = (row: Record<string, unknown>, ...keys: string[]) => {
  const found = pick(row, ...keys);
  if (found == null || found === "") return null;
  const parsed = Number(found);
  return Number.isFinite(parsed) ? parsed : null;
};
function normalizeRate(
  value: number | null,
  count?: number | null,
  total?: number | null,
) {
  if (value != null) return value <= 1 ? value * 100 : value;
  if (count == null || total == null || total <= 0) return null;
  return (count / total) * 100;
}
const metric = (value: number | null) =>
  value == null ? (
    <span className="text-muted-foreground">-</span>
  ) : (
    value.toLocaleString()
  );
const percent = (value: number | null) =>
  value == null ? "-" : `${value.toFixed(1)}%`;

type Overview = {
  total: number | null;
  valid: number | null;
  validRate: number | null;
  online: number | null;
  onlineRate: number | null;
  invalid: number | null;
  invalidRate: number | null;
  countries: number | null;
};
function overviewRow(input: unknown): Overview {
  const row = (input || {}) as Record<string, unknown>;
  const total = numberValue(row, "totalAccounts", "total_accounts", "total");
  const invalid = numberValue(
    row,
    "invalidAccounts",
    "invalid_accounts",
    "invalid",
  );
  const valid =
    numberValue(row, "validAccounts", "valid_accounts", "valid") ??
    (total != null && invalid != null ? total - invalid : null);
  const online = numberValue(
    row,
    "onlineAccounts",
    "online_accounts",
    "online",
  );
  return {
    total,
    valid,
    validRate: normalizeRate(
      numberValue(row, "validRate", "valid_rate"),
      valid,
      total,
    ),
    online,
    onlineRate: normalizeRate(
      numberValue(row, "onlineRate", "online_rate"),
      online,
      valid,
    ),
    invalid,
    invalidRate: normalizeRate(
      numberValue(row, "invalidRate", "invalid_rate"),
      invalid,
      total,
    ),
    countries: numberValue(
      row,
      "countryCount",
      "country_count",
      "coveredCountries",
      "covered_countries",
    ),
  };
}

type DailyRow = {
  date: string;
  source: string;
  total: number | null;
  valid: number | null;
  online: number | null;
  onlineRate: number | null;
  retained: number | null;
  added: number | null;
  newInvalid: number | null;
  newInvalidRate: number | null;
  invalid: number | null;
  preMarketingInvalid: number | null;
  postMarketingInvalid: number | null;
  netGrowth: number | null;
  overallInvalidRate: number | null;
};
function dailyRow(input: unknown): DailyRow {
  const row = input as Record<string, unknown>;
  return {
    date: stringValue(row, "date", "statDate", "stat_date"),
    source: stringValue(row, "source", "dataSource", "data_source"),
    total: numberValue(row, "totalAccounts", "total_accounts", "total"),
    valid: numberValue(row, "validAccounts", "valid_accounts", "valid"),
    online: numberValue(row, "onlineAccounts", "online_accounts", "online"),
    onlineRate: normalizeRate(numberValue(row, "onlineRate", "online_rate")),
    retained: numberValue(
      row,
      "retainedAccounts",
      "retained_accounts",
      "retained",
    ),
    added: numberValue(row, "newAccounts", "new_accounts", "added"),
    newInvalid: numberValue(
      row,
      "newInvalidAccounts",
      "new_invalid_accounts",
      "sameDayInvalid",
      "same_day_invalid",
    ),
    newInvalidRate: normalizeRate(
      numberValue(
        row,
        "newInvalidRate",
        "new_invalid_rate",
        "sameDayInvalidRate",
        "same_day_invalid_rate",
      ),
    ),
    invalid: numberValue(
      row,
      "invalidatedAccounts",
      "invalidated_accounts",
      "invalidAccounts",
      "invalid_accounts",
      "invalid",
    ),
    preMarketingInvalid: numberValue(
      row,
      "preMarketingInvalid",
      "pre_marketing_invalid",
    ),
    postMarketingInvalid: numberValue(
      row,
      "postMarketingInvalid",
      "post_marketing_invalid",
    ),
    netGrowth: numberValue(row, "netGrowth", "net_growth"),
    overallInvalidRate: normalizeRate(
      numberValue(row, "overallInvalidRate", "overall_invalid_rate"),
    ),
  };
}

type CountryRow = { code: string; name: string; total: number | null };
function countryRow(input: unknown): CountryRow {
  const row = input as Record<string, unknown>;
  return {
    code: stringValue(row, "countryCode", "country_code", "iso2").toUpperCase(),
    name: stringValue(row, "countryName", "country_name", "name"),
    total: numberValue(row, "totalAccounts", "total_accounts", "total"),
  };
}
function listBody(payload: unknown) {
  const data = ((payload as { data?: unknown })?.data ?? payload) as Record<
    string,
    unknown
  >;
  return Array.isArray(data)
    ? data
    : Array.isArray(data.rows)
      ? data.rows
      : Array.isArray(data.items)
        ? data.items
        : [];
}

const countryColors = [
  "#6d87cd",
  "#10b981",
  "#f59e0b",
  "#8b5cf6",
  "#0ea5e9",
  "#f97316",
  "#14b8a6",
  "#a855f7",
  "#94a3b8",
];

export function AccountStatisticsPage() {
  const today = formatLocalDateInput();
  const initialFrom = formatLocalDateInput(
    new Date(Date.now() - 29 * 86400000),
  );
  const [dateFrom, setDateFrom] = useState(initialFrom);
  const [dateTo, setDateTo] = useState(today);
  const [countryCode, setCountryCode] = useState("");
  const [overview, setOverview] = useState<Overview>(overviewRow({}));
  const [daily, setDaily] = useState<DailyRow[]>([]);
  const [countries, setCountries] = useState<CountryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const query = new URLSearchParams({ dateFrom, dateTo });
      if (countryCode) query.set("countryCode", countryCode);
      const [overviewPayload, dailyPayload, countriesPayload] =
        await Promise.all([
          apiRequest("/api/account-statistics/overview"),
          apiRequest(`/api/account-statistics/daily?${query}`),
          apiRequest("/api/account-statistics/countries"),
        ]);
      const overviewData = ((overviewPayload as { data?: unknown }).data ??
        overviewPayload) as Record<string, unknown>;
      setOverview(
        overviewRow(
          overviewData.overview || overviewData.summary || overviewData,
        ),
      );
      setDaily(listBody(dailyPayload).map(dailyRow));
      setCountries(listBody(countriesPayload).map(countryRow));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "账号统计加载失败");
    } finally {
      setLoading(false);
    }
  }, [countryCode, dateFrom, dateTo]);
  useEffect(() => void load(), [load]);

  function preset(days: number) {
    setDateTo(today);
    setDateFrom(
      formatLocalDateInput(new Date(Date.now() - (days - 1) * 86400000)),
    );
  }

  const overviewCards = [
    { label: "账号总数", value: overview.total, detail: "全部在池账号", icon: UsersIcon },
    { label: "有效账号", value: overview.valid, detail: `有效率 ${percent(overview.validRate)}`, icon: CheckCircle2Icon },
    { label: "在线账号", value: overview.online, detail: `在线率 ${percent(overview.onlineRate)}`, icon: WifiIcon },
    { label: "无效账号", value: overview.invalid, detail: `无效率 ${percent(overview.invalidRate)}`, icon: BanIcon },
    { label: "覆盖国家", value: overview.countries, detail: "不含混合（Any）", icon: Globe2Icon },
  ];
  const countryOptions = useMemo(
    () =>
      countries.map((row) => ({
        value: row.code,
        label:
          row.name && row.name !== row.code
            ? `${row.name} · ${row.code}`
            : row.code || row.name,
      })),
    [countries],
  );
  const countrySlices = useMemo(() => {
    const sorted = countries
      .filter((row) => (row.total ?? 0) > 0)
      .sort((left, right) => (right.total ?? 0) - (left.total ?? 0));
    const visible = sorted.slice(0, 8).map((row, index) => ({
      key: row.code || row.name || `country-${index}`,
      name: row.name || row.code || "未知国家",
      code: row.code,
      total: row.total ?? 0,
      color: countryColors[index],
    }));
    const otherTotal = sorted
      .slice(8)
      .reduce((sum, row) => sum + (row.total ?? 0), 0);
    if (otherTotal > 0) {
      visible.push({
        key: "other",
        name: "其他",
        code: "",
        total: otherTotal,
        color: countryColors[8],
      });
    }
    return visible;
  }, [countries]);
  const countryTotal = countrySlices.reduce((sum, row) => sum + row.total, 0);
  const chartConfig = {
    total: { label: "账号总数", color: "#6d87cd" },
    online: { label: "在线账号", color: "#10b981" },
    added: { label: "新增账号", color: "#8b5cf6" },
    netGrowth: { label: "净变化", color: "#f59e0b" },
  };
  const trendLegend = [
    { label: "账号总数", color: "#6d87cd" },
    { label: "在线账号", color: "#10b981" },
    { label: "新增账号", color: "#8b5cf6" },
    { label: "净变化", color: "#f59e0b" },
  ];

  return (
    <StandardListPage>
      <ListToolbar
        actions={
          <Button variant="outline" onClick={() => void load()} disabled={loading}>
            <RefreshCwIcon size={16} className={loading ? "spin" : ""} />
            刷新
          </Button>
        }
      />
      {error ? (
        <div className="rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {overviewCards.map(({ label, value, detail, icon: Icon }) => (
          <article
            className="rounded-xl border bg-card p-4 shadow-sm shadow-black/[0.02]"
            key={label}
          >
            <div className="flex items-start justify-between gap-3">
              <span className="text-sm text-muted-foreground">{label}</span>
              <span className="grid size-9 place-items-center rounded-lg bg-primary/10 text-primary">
                <Icon size={18} />
              </span>
            </div>
            <strong className="mt-4 block text-3xl font-semibold tabular-nums tracking-tight">
              {loading || value == null ? "-" : value.toLocaleString()}
            </strong>
            <span className="mt-1 block text-xs text-muted-foreground">
              {value == null ? "待同步" : detail}
            </span>
          </article>
        ))}
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(320px,0.8fr)]">
        <article className="rounded-xl border bg-card p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <header>
              <h2 className="font-semibold">账号池变化</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                同一时间轴观察账号总量、在线、新增和净变化。
              </p>
            </header>
            <div className="flex flex-wrap items-center gap-2">
              <DatePickerField value={dateFrom} onValueChange={setDateFrom} ariaLabel="开始日期" className="w-36" />
              <span className="text-sm text-muted-foreground">至</span>
              <DatePickerField value={dateTo} onValueChange={setDateTo} ariaLabel="结束日期" className="w-36" />
              <SelectField value={countryCode} onValueChange={setCountryCode} options={countryOptions} placeholder="全部国家" clearable className="w-40" />
              {[7, 30, 90].map((days) => (
                <Button key={days} variant="outline" onClick={() => preset(days)}>
                  近 {days} 天
                </Button>
              ))}
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 text-xs text-muted-foreground">
            {trendLegend.map((item) => (
              <span className="flex items-center gap-1.5" key={item.label}>
                <span className="size-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                {item.label}
              </span>
            ))}
            <span className="ml-auto">{dateFrom} 至 {dateTo}</span>
          </div>
          {loading ? (
            <div className="loading-state h-[300px]"><Spinner />正在汇总趋势…</div>
          ) : daily.length ? (
            <ChartContainer config={chartConfig} className="mt-2 h-[300px] w-full">
              <LineChart accessibilityLayer data={daily} margin={{ top: 12, right: 12, bottom: 0, left: -18 }}>
                <CartesianGrid vertical={false} strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={(value) => String(value).slice(5)} tickLine={false} axisLine={false} />
                <YAxis allowDecimals={false} tickLine={false} axisLine={false} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Line type="monotone" dataKey="total" stroke="var(--color-total)" strokeWidth={2.4} dot={false} connectNulls />
                <Line type="monotone" dataKey="online" stroke="var(--color-online)" strokeWidth={2.1} dot={false} connectNulls />
                <Line type="monotone" dataKey="added" stroke="var(--color-added)" strokeWidth={1.8} dot={false} connectNulls />
                <Line type="monotone" dataKey="netGrowth" stroke="var(--color-netGrowth)" strokeWidth={1.8} dot={false} connectNulls />
              </LineChart>
            </ChartContainer>
          ) : (
            <EmptyState title="暂无趋势数据" description="所选时间和国家范围内暂无账号快照。" />
          )}
        </article>

        <article className="rounded-xl border bg-card p-4">
          <header>
            <h2 className="font-semibold">国家分布</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              按账号总数统计，前 8 个国家之外合并为“其他”。
            </p>
          </header>
          {loading ? (
            <div className="loading-state h-[300px]"><Spinner />正在汇总国家分布…</div>
          ) : countrySlices.length ? (
            <>
              <div className="relative mx-auto mt-2 w-full max-w-[280px]">
                <ChartContainer config={{ total: { label: "账号数" } }} className="mx-auto aspect-square h-[250px] w-full">
                  <PieChart accessibilityLayer>
                    <Pie data={countrySlices} dataKey="total" nameKey="name" innerRadius={64} outerRadius={96} paddingAngle={2} strokeWidth={2}>
                      {countrySlices.map((row) => <Cell key={row.key} fill={row.color} />)}
                    </Pie>
                  </PieChart>
                </ChartContainer>
                <div className="pointer-events-none absolute inset-0 grid place-content-center text-center">
                  <strong className="text-2xl tabular-nums">{countryTotal.toLocaleString()}</strong>
                  <span className="text-xs text-muted-foreground">账号</span>
                </div>
              </div>
              <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
                {countrySlices.map((row) => (
                  <div className="flex items-center gap-2 text-sm" key={row.key}>
                    <span className="size-2.5 shrink-0 rounded-full" style={{ backgroundColor: row.color }} />
                    <span className="min-w-0 flex-1 truncate" title={row.name}>
                      {row.name}
                      {row.code && row.code !== row.name ? <span className="ml-1 text-muted-foreground">{row.code}</span> : null}
                    </span>
                    <strong className="tabular-nums">{row.total.toLocaleString()}</strong>
                    <span className="w-12 text-right text-xs tabular-nums text-muted-foreground">
                      {countryTotal > 0 ? `${((row.total / countryTotal) * 100).toFixed(1)}%` : "-"}
                    </span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <EmptyState title="暂无国家统计" description="同步国家信息后会在这里显示分布。" />
          )}
        </article>
      </section>

      <ListTableCard>
        <div className="border-b px-4 py-3">
          <h2 className="text-base font-semibold">每日明细</h2>
          <p className="mt-1 text-sm text-muted-foreground">每日账号池变化和解绑阶段，范围最长 90 天。</p>
        </div>
        {loading ? (
          <div className="loading-state min-h-64"><Spinner />正在汇总日统计…</div>
        ) : daily.length ? (
          <Table layout="list">
            <TableHeader><TableRow><TableHead>日期</TableHead><TableHead adaptive>账号池</TableHead><TableHead>在线</TableHead><TableHead>新增账号</TableHead><TableHead>解绑阶段</TableHead><TableHead>净变化</TableHead></TableRow></TableHeader>
            <TableBody>{daily.map((row) => (
              <TableRow key={`${row.date}-${row.source}`}>
                <TableCell><div className="cell-main min-w-[130px]"><strong>{row.date}</strong><span><Badge tone={row.source === "realtime" || row.source === "实时" ? "success" : "neutral"}>{row.source === "realtime" ? "实时" : row.source || "历史"}</Badge></span></div></TableCell>
                <TableCell><div className="cell-main min-w-[145px]"><strong>总数 {metric(row.total)}</strong><span>有效 {metric(row.valid)} · 留存 {metric(row.retained)}</span></div></TableCell>
                <TableCell><div className="cell-main min-w-[110px]"><strong>{metric(row.online)}</strong><span>在线率 {percent(row.onlineRate)}</span></div></TableCell>
                <TableCell><div className="cell-main min-w-[150px]"><strong>{row.added == null ? "-" : `+${row.added}`}</strong><span>当日解绑 {metric(row.newInvalid)} · {percent(row.newInvalidRate)}</span></div></TableCell>
                <TableCell><div className="cell-main min-w-[185px]"><strong>合计 {metric(row.invalid)}</strong><span>营销前 {metric(row.preMarketingInvalid)} · 营销后 {metric(row.postMarketingInvalid)}</span></div></TableCell>
                <TableCell><div className="cell-main min-w-[110px]"><strong className={row.netGrowth != null && row.netGrowth < 0 ? "text-destructive" : "text-emerald-600"}>{row.netGrowth == null ? "-" : `${row.netGrowth >= 0 ? "+" : ""}${row.netGrowth}`}</strong><span>解绑率 {percent(row.overallInvalidRate)}</span></div></TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        ) : (
          <EmptyState title="暂无日统计" description="所选时间和国家范围内暂无账号快照。" />
        )}
      </ListTableCard>
    </StandardListPage>
  );
}
