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
import { EntityPrimaryCell } from "../components/entity-primary-cell";
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
import { accountRowKey, snowflakeId } from "../lib/account-identifiers";
import { formatPhoneDisplay } from "../lib/utils";

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
type QualityRow = { id: string; readKey: string; account: string; phone: string; source: string; avatar: boolean | null; groups: number | null; friends: number | null; mutual: number | null; score: number | null; sync: string };
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
  const id = snowflakeId(row, "id", "accountId", "account_id");
  const phone = formatPhoneDisplay(
    stringValue(row, "phone", "phoneNumber", "phone_number"),
  );
  const displayName = stringValue(row, "displayName", "display_name");
  return {
    id,
    readKey: accountRowKey(row, id),
    account: /^\+\d+$/.test(displayName)
      ? formatPhoneDisplay(displayName)
      : displayName || phone,
    phone,
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

  return (
    <StandardListPage>
      <ListToolbar
        filters={
          <>
            <DatePickerField
              value={dateFrom}
              onValueChange={setDateFrom}
              ariaLabel="开始日期"
              className="w-36"
            />
            <span className="hidden text-sm text-muted-foreground xl:inline">至</span>
            <DatePickerField
              value={dateTo}
              onValueChange={setDateTo}
              ariaLabel="结束日期"
              className="w-36"
            />
            <SelectField
              value={countryCode}
              onValueChange={setCountryCode}
              options={countryOptions}
              placeholder="全部国家"
              clearable
              className="w-40"
            />
            {[7, 30, 90].map((days) => (
              <Button key={days} variant="outline" onClick={() => preset(days)}>
                近 {days} 天
              </Button>
            ))}
          </>
        }
        meta={`${dateFrom} 至 ${dateTo}`}
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

      <section className="grid gap-3">
        <div>
          <h2 className="text-base font-semibold">账号池概览</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            账号总量、可用性与在线状态的实时快照。
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {overviewCards.map(({ label, value, detail, icon: Icon }) => (
            <div className="summary-card" key={label}>
              <span className="summary-icon"><Icon size={18} /></span>
              <div>
                <small>{label}</small>
                <strong>{value == null ? "-" : value.toLocaleString()}</strong>
                <small>{value == null ? "待同步" : detail}</small>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="grid gap-3">
        <div>
          <h2 className="text-base font-semibold">账号质量</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            只使用已同步资料计算；未知数据不会被当作 0。
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {qualityCards.map(({ label, data, score }) => (
            <div className="summary-card" key={label}>
              <span className="summary-icon"><UserPlusIcon size={18} /></span>
              <div>
                <small>{label}</small>
                <strong>
                  {data?.count == null
                    ? "-"
                    : score
                      ? data.count.toFixed(1)
                      : data.count.toLocaleString()}
                </strong>
                <small>
                  {data?.count == null
                    ? "待同步"
                    : score
                      ? `已知 ${data.known ?? "-"} · 未知 ${data.unknown ?? "-"}`
                      : `${percent(data.rate)} · 未知 ${data.unknown ?? "-"}`}
                </small>
              </div>
            </div>
          ))}
        </div>
      </section>

      <ListTableCard>
        <div className="border-b px-4 py-3">
          <h2 className="text-base font-semibold">账号日统计</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            每日账号池变化与解绑阶段，范围最长 90 天。
          </p>
        </div>
        {loading ? (
          <div className="loading-state min-h-64"><Spinner />正在汇总日统计…</div>
        ) : daily.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>日期</TableHead>
                <TableHead>账号池</TableHead>
                <TableHead>在线</TableHead>
                <TableHead>新增账号</TableHead>
                <TableHead>解绑阶段</TableHead>
                <TableHead>净变化</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {daily.map((row) => (
                <TableRow key={`${row.date}-${row.source}`}>
                  <TableCell>
                    <div className="cell-main min-w-[130px]">
                      <strong>{row.date}</strong>
                      <span>
                        <Badge tone={row.source === "realtime" || row.source === "实时" ? "success" : "primary"}>
                          {row.source === "realtime" ? "实时" : row.source || "历史"}
                        </Badge>
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="cell-main min-w-[145px]">
                      <strong>总数 {metric(row.total)}</strong>
                      <span>有效 {metric(row.valid)} · 留存 {metric(row.retained)}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="cell-main min-w-[110px]">
                      <strong>{metric(row.online)}</strong>
                      <span>在线率 {percent(row.onlineRate)}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="cell-main min-w-[150px]">
                      <strong>{row.added == null ? "-" : `+${row.added}`}</strong>
                      <span>当日解绑 {metric(row.newInvalid)} · {percent(row.newInvalidRate)}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="cell-main min-w-[185px]">
                      <strong>合计 {metric(row.invalid)}</strong>
                      <span>营销前 {metric(row.preMarketingInvalid)} · 营销后 {metric(row.postMarketingInvalid)}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="cell-main min-w-[110px]">
                      <strong className={row.netGrowth != null && row.netGrowth < 0 ? "text-destructive" : "text-emerald-600"}>
                        {row.netGrowth == null ? "-" : `${row.netGrowth >= 0 ? "+" : ""}${row.netGrowth}`}
                      </strong>
                      <span>解绑率 {percent(row.overallInvalidRate)}</span>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <EmptyState title="暂无日统计" description="所选时间和国家范围内暂无账号快照。" />
        )}
      </ListTableCard>

      <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
        <ListTableCard>
          <div className="border-b px-4 py-3">
            <h2 className="text-base font-semibold">国家分布</h2>
            <p className="mt-1 text-sm text-muted-foreground">账号覆盖与有效占比。</p>
          </div>
          {loading ? (
            <div className="loading-state"><Spinner />正在汇总国家分布…</div>
          ) : countries.length ? (
            <Table>
              <TableHeader><TableRow><TableHead>国家</TableHead><TableHead>账号</TableHead><TableHead>在线</TableHead><TableHead>有效率</TableHead></TableRow></TableHeader>
              <TableBody>
                {countries.map((row) => (
                  <TableRow key={row.code || row.name}>
                    <TableCell>
                      <strong>{row.name || row.code}</strong>
                      {row.name && row.code && row.name !== row.code ? <span className="ml-2 text-muted-foreground">{row.code}</span> : null}
                    </TableCell>
                    <TableCell>{metric(row.total)}</TableCell>
                    <TableCell><Badge tone="success">{row.online == null ? "-" : row.online.toLocaleString()}</Badge></TableCell>
                    <TableCell>{percent(row.validRate)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState title="暂无国家统计" description="同步国家信息后会在这里显示分布。" />
          )}
        </ListTableCard>

        <ListTableCard>
          <div className="border-b px-4 py-3">
            <h2 className="text-base font-semibold">账号质量明细</h2>
            <p className="mt-1 text-sm text-muted-foreground">用于定位尚未完成资料同步的账号。</p>
          </div>
          {qualityRows.length ? (
            <Table>
              <TableHeader><TableRow><TableHead>账号</TableHead><TableHead>来源</TableHead><TableHead>头像</TableHead><TableHead>群组</TableHead><TableHead>好友</TableHead><TableHead>双向</TableHead><TableHead>评分</TableHead></TableRow></TableHeader>
              <TableBody>
                {qualityRows.map((row) => (
                  <TableRow key={row.readKey}>
                    <TableCell>
                      <EntityPrimaryCell
                        title={row.phone || row.account || "账号待迁移"}
                        id={row.id}
                        status={{
                          label: row.sync === "synced" || row.sync === "ready" ? "已同步" : "待同步",
                          description: row.sync === "synced" || row.sync === "ready"
                            ? "账号资料已同步，可以参与质量指标统计。"
                            : "账号资料尚未完成同步，部分质量指标暂不可用。",
                          tone: row.sync === "synced" || row.sync === "ready" ? "success" : "warning",
                          details: [
                            { label: "头像", value: row.avatar == null ? "未知" : row.avatar ? "有" : "无" },
                            { label: "评分", value: row.score == null ? "-" : row.score },
                          ],
                        }}
                      />
                    </TableCell>
                    <TableCell>{row.source === "json_import" ? <Badge tone="neutral">JSON 导入</Badge> : row.source === "landing_page" ? <Badge tone="info">落地页链接</Badge> : "-"}</TableCell>
                    <TableCell>{row.avatar == null ? "-" : row.avatar ? "有" : "无"}</TableCell>
                    <TableCell>{metric(row.groups)}</TableCell>
                    <TableCell>{metric(row.friends)}</TableCell>
                    <TableCell>{metric(row.mutual)}</TableCell>
                    <TableCell>{metric(row.score)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState title="暂无账号质量数据" description="账号资料同步后才会参与质量统计。" />
          )}
        </ListTableCard>
      </div>
    </StandardListPage>
  );
}
