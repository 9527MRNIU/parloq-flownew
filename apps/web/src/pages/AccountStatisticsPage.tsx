import {
  BanIcon,
  CheckCircle2Icon,
  Globe2Icon,
  RefreshCwIcon,
  UserPlusIcon,
  UsersIcon,
  WifiIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiRequest, formatLocalDateInput } from "../api/client";
import { DatePickerField } from "../components/date-picker-field";
import { StandardListPage } from "../components/list-page";
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
function normalizeRate(value: number | null, count?: number | null, total?: number | null) {
  if (value != null) return value <= 1 ? value * 100 : value;
  if (count == null || total == null || total <= 0) return null;
  return (count / total) * 100;
}
const metric = (value: number | null) => value == null ? <span className="text-muted-foreground">-</span> : value.toLocaleString();
const percent = (value: number | null) => value == null ? "-" : `${value.toFixed(1)}%`;

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
  const invalid = numberValue(row, "invalidAccounts", "invalid_accounts", "invalid");
  const valid = numberValue(row, "validAccounts", "valid_accounts", "valid") ?? (total != null && invalid != null ? total - invalid : null);
  const online = numberValue(row, "onlineAccounts", "online_accounts", "online");
  return {
    total,
    valid,
    validRate: normalizeRate(numberValue(row, "validRate", "valid_rate"), valid, total),
    online,
    onlineRate: normalizeRate(numberValue(row, "onlineRate", "online_rate"), online, valid),
    invalid,
    invalidRate: normalizeRate(numberValue(row, "invalidRate", "invalid_rate"), invalid, total),
    countries: numberValue(row, "countryCount", "country_count", "coveredCountries", "covered_countries"),
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
  preMarketingRate: number | null;
  postMarketingInvalid: number | null;
  postMarketingRate: number | null;
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
    retained: numberValue(row, "retainedAccounts", "retained_accounts", "retained"),
    added: numberValue(row, "newAccounts", "new_accounts", "added"),
    newInvalid: numberValue(row, "newInvalidAccounts", "new_invalid_accounts", "sameDayInvalid", "same_day_invalid"),
    newInvalidRate: normalizeRate(numberValue(row, "newInvalidRate", "new_invalid_rate", "sameDayInvalidRate", "same_day_invalid_rate")),
    invalid: numberValue(row, "invalidatedAccounts", "invalidated_accounts", "invalidAccounts", "invalid_accounts", "invalid"),
    preMarketingInvalid: numberValue(row, "preMarketingInvalid", "pre_marketing_invalid"),
    preMarketingRate: normalizeRate(numberValue(row, "preMarketingInvalidRate", "pre_marketing_invalid_rate")),
    postMarketingInvalid: numberValue(row, "postMarketingInvalid", "post_marketing_invalid"),
    postMarketingRate: normalizeRate(numberValue(row, "postMarketingInvalidRate", "post_marketing_invalid_rate")),
    netGrowth: numberValue(row, "netGrowth", "net_growth"),
    overallInvalidRate: normalizeRate(numberValue(row, "overallInvalidRate", "overall_invalid_rate")),
  };
}

type CountryRow = { code: string; name: string; total: number | null; online: number | null; invalid: number | null; validRate: number | null };
function countryRow(input: unknown): CountryRow {
  const row = input as Record<string, unknown>;
  const total = numberValue(row, "totalAccounts", "total_accounts", "total");
  const invalid = numberValue(row, "invalidAccounts", "invalid_accounts", "invalid");
  return {
    code: stringValue(row, "countryCode", "country_code", "iso2").toUpperCase(),
    name: stringValue(row, "countryName", "country_name", "name"),
    total,
    online: numberValue(row, "onlineAccounts", "online_accounts", "online"),
    invalid,
    validRate: normalizeRate(numberValue(row, "validRate", "valid_rate"), total != null && invalid != null ? total - invalid : null, total),
  };
}

type QualityMetric = { count: number | null; rate: number | null; known: number | null; unknown: number | null };
type QualityRow = { id: string; account: string; source: string; avatar: boolean | null; groups: number | null; friends: number | null; mutual: number | null; score: number | null; sync: string };
function qualityMetric(input: unknown, average = false): QualityMetric {
  const row = (input || {}) as Record<string, unknown>;
  return {
    count: numberValue(row, average ? "average" : "count"),
    rate: average ? numberValue(row, "average") : normalizeRate(numberValue(row, "rate")),
    known: numberValue(row, "knownCount", "known_count"),
    unknown: numberValue(row, "unknownCount", "unknown_count"),
  };
}
function qualityRow(input: unknown): QualityRow {
  const row = input as Record<string, unknown>;
  const avatar = pick(row, "hasAvatar", "has_avatar");
  return {
    id: stringValue(row, "accountPublicId", "account_public_id", "id"),
    account: stringValue(row, "displayName", "display_name", "phone", "accountPublicId"),
    source: stringValue(row, "source"),
    avatar: avatar == null ? null : Boolean(avatar),
    groups: numberValue(row, "groupCount", "group_count"),
    friends: numberValue(row, "friendCount", "friend_count"),
    mutual: numberValue(row, "mutualCount", "mutual_count"),
    score: numberValue(row, "score", "qualityScore", "quality_score"),
    sync: stringValue(row, "syncStatus", "sync_status"),
  };
}
function listBody(payload: unknown) {
  const data = ((payload as { data?: unknown })?.data ?? payload) as Record<string, unknown>;
  return Array.isArray(data) ? data : Array.isArray(data.rows) ? data.rows : Array.isArray(data.items) ? data.items : [];
}

export function AccountStatisticsPage() {
  const today = formatLocalDateInput();
  const initialFrom = formatLocalDateInput(new Date(Date.now() - 29 * 86400000));
  const [dateFrom, setDateFrom] = useState(initialFrom);
  const [dateTo, setDateTo] = useState(today);
  const [countryCode, setCountryCode] = useState("");
  const [overview, setOverview] = useState<Overview>(overviewRow({}));
  const [daily, setDaily] = useState<DailyRow[]>([]);
  const [countries, setCountries] = useState<CountryRow[]>([]);
  const [quality, setQuality] = useState<Record<string, QualityMetric>>({});
  const [qualityRows, setQualityRows] = useState<QualityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const query = new URLSearchParams({ dateFrom, dateTo });
      if (countryCode) query.set("countryCode", countryCode);
      const [overviewPayload, dailyPayload, countriesPayload, qualityPayload] = await Promise.all([
        apiRequest("/api/account-statistics/overview"),
        apiRequest(`/api/account-statistics/daily?${query}`),
        apiRequest("/api/account-statistics/countries"),
        apiRequest("/api/personal-accounts/statistics"),
      ]);
      const overviewData = ((overviewPayload as { data?: unknown }).data ?? overviewPayload) as Record<string, unknown>;
      setOverview(overviewRow(overviewData.overview || overviewData.summary || overviewData));
      setDaily(listBody(dailyPayload).map(dailyRow));
      setCountries(listBody(countriesPayload).map(countryRow));
      const qualityData = ((qualityPayload as { data?: unknown }).data ?? qualityPayload) as Record<string, unknown>;
      const qualitySummary = (qualityData.quality || {}) as Record<string, unknown>;
      setQuality({
        noAvatar: qualityMetric(qualitySummary.noAvatar || qualitySummary.no_avatar),
        noGroup: qualityMetric(qualitySummary.noGroup || qualitySummary.no_group),
        zeroFriends: qualityMetric(qualitySummary.zeroFriends || qualitySummary.zero_friends),
        zeroMutual: qualityMetric(qualitySummary.zeroMutualContacts || qualitySummary.zero_mutual_contacts),
        score: qualityMetric(qualitySummary.score, true),
      });
      setQualityRows((Array.isArray(qualityData.rows) ? qualityData.rows : []).map(qualityRow));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "账号统计加载失败");
    } finally {
      setLoading(false);
    }
  }, [countryCode, dateFrom, dateTo]);
  useEffect(() => void load(), [load]);

  function preset(days: number) {
    setDateTo(today);
    setDateFrom(formatLocalDateInput(new Date(Date.now() - (days - 1) * 86400000)));
  }
  const overviewCards = [
    { label: "账号总数", value: overview.total, detail: "全部账号", icon: UsersIcon },
    { label: "有效数", value: overview.valid, detail: `有效率 ${percent(overview.validRate)}`, icon: CheckCircle2Icon },
    { label: "在线数", value: overview.online, detail: `在线率 ${percent(overview.onlineRate)}`, icon: WifiIcon },
    { label: "无效数", value: overview.invalid, detail: `无效率 ${percent(overview.invalidRate)}`, icon: BanIcon },
    { label: "覆盖国家", value: overview.countries, detail: "不含混合（Any）", icon: Globe2Icon },
  ];
  const qualityCards = [
    { label: "无头像 / 率", data: quality.noAvatar },
    { label: "无群组 / 率", data: quality.noGroup },
    { label: "0 好友 / 率", data: quality.zeroFriends },
    { label: "0 双向 / 率", data: quality.zeroMutual },
    { label: "平均评分", data: quality.score, score: true },
  ];
  const countryOptions = useMemo(() => countries.map((row) => ({ value: row.code, label: `${row.name || row.code}${row.code ? ` · ${row.code}` : ""}` })), [countries]);

  return (
    <StandardListPage>
      <div className="flex justify-end"><Button variant="outline" onClick={() => void load()} disabled={loading}><RefreshCwIcon size={16} className={loading ? "spin" : ""} />刷新全部</Button></div>
      {error ? <div className="rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-sm text-destructive">{error}</div> : null}
      <section>
        <div className="mb-3"><h2>账号池实时概览</h2><p className="text-sm text-muted-foreground">当前账号池的实时经营快照。</p></div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">{overviewCards.map(({ label, value, detail, icon: Icon }) => <div className="summary-card" key={label}><span className="summary-icon"><Icon size={18} /></span><div><small>{label}</small><strong>{loading && value == null ? "-" : value == null ? "-" : value.toLocaleString()}</strong><small>{value == null ? "待同步" : detail}</small></div></div>)}</div>
      </section>

      <section className="card">
        <div className="flex flex-col gap-3 border-b pb-4 lg:flex-row lg:items-end lg:justify-between">
          <div><h2>账号日统计</h2><p className="mt-1 text-sm text-muted-foreground">历史与今日实时数据，日期范围最长 90 天。</p></div>
          <div className="flex flex-wrap items-end gap-2">
            <DatePickerField value={dateFrom} onValueChange={setDateFrom} ariaLabel="开始日期" className="w-36" />
            <span className="pb-2 text-muted-foreground">至</span>
            <DatePickerField value={dateTo} onValueChange={setDateTo} ariaLabel="结束日期" className="w-36" />
            <SelectField value={countryCode} onValueChange={setCountryCode} options={countryOptions} placeholder="全部国家" clearable className="w-40" />
            {[7, 30, 90].map((days) => <Button key={days} variant="outline" onClick={() => preset(days)}>近 {days} 天</Button>)}
          </div>
        </div>
        <p className="my-3 text-sm text-muted-foreground">正在查看 {dateFrom} 至 {dateTo} 内、{countryCode || "全部国家"}的账号每天变化情况。</p>
        {loading ? <div className="loading-state min-h-64"><Spinner />正在汇总日统计…</div> : daily.length ? <div className="table-scroll"><Table><TableHeader><TableRow><TableHead>日期</TableHead><TableHead>来源</TableHead><TableHead>总数</TableHead><TableHead>可用</TableHead><TableHead>在线 / 率</TableHead><TableHead>留存</TableHead><TableHead>日新增</TableHead><TableHead>新号当日解绑 / 率</TableHead><TableHead>日解绑</TableHead><TableHead>营销前解绑 / 率</TableHead><TableHead>营销后解绑 / 率</TableHead><TableHead>日净增</TableHead><TableHead>整体解绑率</TableHead></TableRow></TableHeader>
          <TableBody>{daily.map((row) => <TableRow key={`${row.date}-${row.source}`}><TableCell><strong>{row.date}</strong></TableCell><TableCell><Badge tone={row.source === "realtime" || row.source === "实时" ? "success" : "primary"}>{row.source === "realtime" ? "实时" : row.source || "历史"}</Badge></TableCell><TableCell>{metric(row.total)}</TableCell><TableCell>{metric(row.valid)}</TableCell><TableCell>{metric(row.online)} / {percent(row.onlineRate)}</TableCell><TableCell>{metric(row.retained)}</TableCell><TableCell>{row.added == null ? "-" : `+${row.added}`}</TableCell><TableCell>{metric(row.newInvalid)} / {percent(row.newInvalidRate)}</TableCell><TableCell>{metric(row.invalid)}</TableCell><TableCell>{metric(row.preMarketingInvalid)} / {percent(row.preMarketingRate)}</TableCell><TableCell>{metric(row.postMarketingInvalid)} / {percent(row.postMarketingRate)}</TableCell><TableCell><span className={row.netGrowth != null && row.netGrowth < 0 ? "text-destructive" : "text-emerald-600"}>{row.netGrowth == null ? "-" : `${row.netGrowth >= 0 ? "+" : ""}${row.netGrowth}`}</span></TableCell><TableCell>{percent(row.overallInvalidRate)}</TableCell></TableRow>)}</TableBody></Table></div> : <EmptyState title="暂无日统计" description="所选时间和国家范围内暂无账号快照。" />}
      </section>

      <section className="card">
        <div className="mb-3"><h2>按国家统计</h2><p className="mt-1 text-sm text-muted-foreground">查看账号在各国家的分布与有效占比。</p></div>
        {loading ? <div className="loading-state min-h-48"><Spinner />正在汇总国家分布…</div> : countries.length ? <div className="table-scroll"><Table><TableHeader><TableRow><TableHead>国家</TableHead><TableHead>账号总数</TableHead><TableHead>在线数</TableHead><TableHead>无效数</TableHead><TableHead>有效占比</TableHead></TableRow></TableHeader><TableBody>{countries.map((row) => <TableRow key={row.code || row.name}><TableCell><strong>{row.name || row.code}</strong><span className="ml-2 text-muted-foreground">{row.code}</span></TableCell><TableCell>{metric(row.total)}</TableCell><TableCell><Badge tone="success">{row.online == null ? "-" : row.online.toLocaleString()}</Badge></TableCell><TableCell><Badge tone={row.invalid ? "danger" : "neutral"}>{row.invalid == null ? "-" : row.invalid.toLocaleString()}</Badge></TableCell><TableCell>{percent(row.validRate)}</TableCell></TableRow>)}</TableBody></Table></div> : <EmptyState title="暂无国家统计" description="账号同步国家信息后，这里会显示分布。" />}
      </section>

      <section>
        <div className="mb-3"><h2>账号质量</h2><p className="text-sm text-muted-foreground">质量只使用已同步数据计算；未知数据不记为 0。</p></div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">{qualityCards.map(({ label, data, score }) => <div className="summary-card" key={label}><span className="summary-icon"><UserPlusIcon size={18} /></span><div><small>{label}</small><strong>{data?.count == null ? "-" : score ? data.count.toFixed(1) : data.count.toLocaleString()}</strong><small>{data?.count == null ? "待同步" : score ? `已知 ${data.known ?? "-"} · 未知 ${data.unknown ?? "-"}` : `${percent(data.rate)} · 未知 ${data.unknown ?? "-"}`}</small></div></div>)}</div>
        <section className="mt-3 overflow-hidden rounded-lg border bg-background">{qualityRows.length ? <div className="table-scroll"><Table><TableHeader><TableRow><TableHead>账号</TableHead><TableHead>来源</TableHead><TableHead>头像</TableHead><TableHead>群组</TableHead><TableHead>好友</TableHead><TableHead>双向</TableHead><TableHead>评分</TableHead><TableHead>同步状态</TableHead></TableRow></TableHeader><TableBody>{qualityRows.map((row) => <TableRow key={row.id || row.account}><TableCell><strong>{row.account || row.id}</strong></TableCell><TableCell>{row.source === "json_import" ? "JSON 导入" : row.source === "landing_page" ? "落地页链接" : "-"}</TableCell><TableCell>{row.avatar == null ? "-" : row.avatar ? "有" : "无"}</TableCell><TableCell>{metric(row.groups)}</TableCell><TableCell>{metric(row.friends)}</TableCell><TableCell>{metric(row.mutual)}</TableCell><TableCell>{metric(row.score)}</TableCell><TableCell><Badge tone={row.sync === "synced" || row.sync === "ready" ? "success" : "warning"}>{row.sync === "synced" || row.sync === "ready" ? "已同步" : "待同步"}</Badge></TableCell></TableRow>)}</TableBody></Table></div> : <EmptyState title="暂无账号质量数据" description="账号资料同步后才会参与质量统计。" />}</section>
      </section>
    </StandardListPage>
  );
}
