import {
  AlertTriangleIcon,
  BanIcon,
  CheckCheckIcon,
  RefreshCwIcon,
  SendIcon,
  ShieldAlertIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiRequest, formatLocalDateInput } from "../api/client";
import {
  ListPagination,
  ListToolbar,
  StandardListPage,
  useClientPagination,
} from "../components/list-page";
import {
  Badge,
  Button,
  DatePickerField,
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

type PairInsight = {
  sourceCountry: string;
  targetCountry: string;
  sent: number;
  delivered: number;
  failed: number;
  abnormalAccounts: number;
  bannedAccounts: number;
  banRate: number;
};

type InsightSummary = {
  sent: number;
  delivered: number;
  abnormalAccounts: number;
  bannedAccounts: number;
  banRate: number;
};

const value = (row: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) if (row[key] != null) return row[key];
  return undefined;
};
const number = (row: Record<string, unknown>, ...keys: string[]) =>
  Number(value(row, ...keys) || 0);
const text = (row: Record<string, unknown>, ...keys: string[]) =>
  String(value(row, ...keys) || "");
const percent = (ratio: number) =>
  `${((ratio > 1 ? ratio / 100 : ratio) * 100).toFixed(2)}%`;
const deliveryRate = (row: PairInsight) =>
  row.sent ? `${((row.delivered / row.sent) * 100).toFixed(2)}%` : "-";

function normalizeRow(input: unknown): PairInsight {
  const row = (input || {}) as Record<string, unknown>;
  const sent = number(row, "sent", "sentCount", "sent_count");
  const bannedAccounts = number(
    row,
    "bannedAccounts",
    "banned_accounts",
    "blockedAccountCount",
    "blocked_account_count",
    "blockedAccounts",
    "blocked_accounts",
  );
  const accountTotal = number(row, "accountCount", "account_count", "accounts");
  return {
    sourceCountry:
      text(
        row,
        "sourceCountry",
        "source_country",
        "accountCountry",
        "account_country",
      ) || "未知",
    targetCountry:
      text(
        row,
        "targetCountry",
        "target_country",
        "recipientCountry",
        "recipient_country",
      ) || "未知",
    sent,
    delivered: number(row, "delivered", "deliveredCount", "delivered_count"),
    failed: number(row, "failed", "failedCount", "failed_count"),
    abnormalAccounts: number(
      row,
      "abnormalAccounts",
      "abnormal_accounts",
      "riskAccounts",
      "risk_accounts",
    ),
    bannedAccounts,
    banRate:
      number(
        row,
        "banRate",
        "ban_rate",
        "blockRate",
        "block_rate",
        "blockedRate",
        "blocked_rate",
      ) || (accountTotal ? bannedAccounts / accountTotal : 0),
  };
}

export function HyperlinkMarketInsightsPage() {
  const now = new Date();
  const monthStart = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
  const [dateFrom, setDateFrom] = useState(monthStart);
  const [dateTo, setDateTo] = useState(formatLocalDateInput(now));
  const [sourceCountry, setSourceCountry] = useState("");
  const [targetCountry, setTargetCountry] = useState("");
  const [rows, setRows] = useState<PairInsight[]>([]);
  const [summary, setSummary] = useState<InsightSummary>({
    sent: 0,
    delivered: 0,
    abnormalAccounts: 0,
    bannedAccounts: 0,
    banRate: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ dateFrom, dateTo });
    if (sourceCountry) params.set("sourceCountry", sourceCountry);
    if (targetCountry) params.set("targetCountry", targetCountry);
    try {
      const payload = await apiRequest(
        `/api/hyperlink/market-insights?${params}`,
      );
      const data = ((payload as { data?: unknown }).data || payload) as Record<
        string,
        unknown
      >;
      const rawRows = Array.isArray(data.rows)
        ? data.rows
        : Array.isArray(data.matrix)
          ? data.matrix
          : [];
      const normalized = rawRows.map(normalizeRow);
      setRows(normalized);
      const totals = (data.totals || data.summary || {}) as Record<
        string,
        unknown
      >;
      const sent =
        number(totals, "sent", "sentCount", "sent_count") ||
        normalized.reduce((sum, row) => sum + row.sent, 0);
      const bannedAccounts =
        number(
          totals,
          "bannedAccounts",
          "banned_accounts",
          "blockedAccounts",
        ) || normalized.reduce((sum, row) => sum + row.bannedAccounts, 0);
      const accountTotal = number(totals, "accountCount", "account_count");
      setSummary({
        sent,
        delivered:
          number(totals, "delivered", "deliveredCount", "delivered_count") ||
          normalized.reduce((sum, row) => sum + row.delivered, 0),
        abnormalAccounts:
          number(totals, "abnormalAccounts", "abnormal_accounts") ||
          normalized.reduce((sum, row) => sum + row.abnormalAccounts, 0),
        bannedAccounts,
        banRate:
          number(totals, "banRate", "ban_rate", "blockedRate") ||
          (accountTotal ? bannedAccounts / accountTotal : 0),
      });
    } catch (caught) {
      setRows([]);
      setError(caught instanceof Error ? caught.message : "加载市场透视失败");
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, sourceCountry, targetCountry]);

  useEffect(() => {
    void load();
  }, [load]);
  const sourceCountries = useMemo(
    () => Array.from(new Set(rows.map((row) => row.sourceCountry))).sort(),
    [rows],
  );
  const targetCountries = useMemo(
    () => Array.from(new Set(rows.map((row) => row.targetCountry))).sort(),
    [rows],
  );
  const matrixSources = useMemo(
    () => Array.from(new Set(rows.map((row) => row.sourceCountry))).sort(),
    [rows],
  );
  const matrixTargets = useMemo(
    () => Array.from(new Set(rows.map((row) => row.targetCountry))).sort(),
    [rows],
  );
  const ranking = useMemo(
    () =>
      [...rows]
        .sort(
          (a, b) =>
            b.banRate - a.banRate || b.bannedAccounts - a.bannedAccounts,
        )
        .slice(0, 8),
    [rows],
  );
  const pagination = useClientPagination(rows, {
    resetKey: `${dateFrom}|${dateTo}|${sourceCountry}|${targetCountry}`,
  });

  return (
    <StandardListPage>
      <ListToolbar
        filters={
          <>
            <DatePickerField
              ariaLabel="开始日期"
              value={dateFrom}
              onValueChange={setDateFrom}
              className="w-[148px]"
            />
            <span className="text-sm text-muted-foreground">至</span>
            <DatePickerField
              ariaLabel="结束日期"
              value={dateTo}
              onValueChange={setDateTo}
              className="w-[148px]"
            />
            <SelectField
              ariaLabel="账号来源国家"
              value={sourceCountry || "__all_source__"}
              onValueChange={(value) =>
                setSourceCountry(value === "__all_source__" ? "" : value)
              }
              options={[
                { value: "__all_source__", label: "全部账号来源国家" },
                ...sourceCountries.map((country) => ({
                  value: country,
                  label: country,
                })),
              ]}
            />
            <SelectField
              ariaLabel="发送目标国家"
              value={targetCountry || "__all_target__"}
              onValueChange={(value) =>
                setTargetCountry(value === "__all_target__" ? "" : value)
              }
              options={[
                { value: "__all_target__", label: "全部发送目标国家" },
                ...targetCountries.map((country) => ({
                  value: country,
                  label: country,
                })),
              ]}
            />
          </>
        }
        actions={
          <Button variant="outline" onClick={() => void load()}>
            <RefreshCwIcon size={16} />
            刷新
          </Button>
        }
      />
      <section className="summary-grid">
        <div className="summary-card">
          <span className="summary-icon">
            <SendIcon size={18} />
          </span>
          <div>
            <small>发送（单勾）</small>
            <strong>{summary.sent.toLocaleString()}</strong>
          </div>
        </div>
        <div className="summary-card">
          <span className="summary-icon">
            <CheckCheckIcon size={18} />
          </span>
          <div>
            <small>双勾送达</small>
            <strong>{summary.delivered.toLocaleString()}</strong>
          </div>
        </div>
        <div className="summary-card">
          <span className="summary-icon">
            <ShieldAlertIcon size={18} />
          </span>
          <div>
            <small>异常账号</small>
            <strong>{summary.abnormalAccounts.toLocaleString()}</strong>
          </div>
        </div>
        <div className="summary-card">
          <span className="summary-icon">
            <BanIcon size={18} />
          </span>
          <div>
            <small>封号率</small>
            <strong>
              {percent(summary.banRate)} · {summary.bannedAccounts}
            </strong>
          </div>
        </div>
      </section>
      {loading ? (
        <section className="card loading-state">
          <Spinner />
          正在聚合国家风险数据…
        </section>
      ) : error ? (
        <section className="card error-state">
          <strong>加载失败</strong>
          <span>{error}</span>
          <Button variant="outline" onClick={() => void load()}>
            重试
          </Button>
        </section>
      ) : rows.length ? (
        <>
          <section className="insight-grid">
            <article className="card market-matrix-card">
              <header>
                <div>
                  <strong>国家交叉矩阵</strong>
                  <span>单元格显示封号率与发送量</span>
                </div>
                <Badge tone="primary">来源国家 × 目标国家</Badge>
              </header>
              <div className="table-scroll">
                <Table className="risk-matrix">
                  <TableHeader>
                    <TableRow>
                      <TableHead>来源 \ 目标</TableHead>
                      {matrixTargets.map((country) => (
                        <TableHead key={country}>{country}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {matrixSources.map((source) => (
                      <TableRow key={source}>
                        <TableHead>{source}</TableHead>
                        {matrixTargets.map((target) => {
                          const cell = rows.find(
                            (row) =>
                              row.sourceCountry === source &&
                              row.targetCountry === target,
                          );
                          return (
                            <TableCell key={target}>
                              {cell ? (
                                <div
                                  className={
                                    cell.banRate >= 0.05
                                      ? "matrix-risk-high"
                                      : cell.banRate >= 0.02
                                        ? "matrix-risk-mid"
                                        : "matrix-risk-low"
                                  }
                                >
                                  <strong>{percent(cell.banRate)}</strong>
                                  <small>{cell.sent.toLocaleString()} 次</small>
                                </div>
                              ) : (
                                <span className="text-muted-foreground">-</span>
                              )}
                            </TableCell>
                          );
                        })}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </article>
            <article className="card risk-ranking">
              <header>
                <div>
                  <strong>风险排行</strong>
                  <span>按封号率从高到低</span>
                </div>
                <AlertTriangleIcon size={18} />
              </header>
              {ranking.map((row, index) => (
                <div key={`${row.sourceCountry}-${row.targetCountry}`}>
                  <span className="risk-rank">{index + 1}</span>
                  <div>
                    <strong>
                      {row.sourceCountry} → {row.targetCountry}
                    </strong>
                    <small>
                      {row.bannedAccounts} 个封号 · {row.abnormalAccounts}{" "}
                      个异常
                    </small>
                  </div>
                  <Badge
                    tone={
                      row.banRate >= 0.05
                        ? "danger"
                        : row.banRate >= 0.02
                          ? "warning"
                          : "success"
                    }
                  >
                    {percent(row.banRate)}
                  </Badge>
                </div>
              ))}
            </article>
          </section>
          <ListPagination
            page={pagination.page}
            pageSize={pagination.pageSize}
            total={pagination.total}
            onPageChange={pagination.setPage}
            onPageSizeChange={pagination.setPageSize}
            ariaLabel="国家风险明细分页"
          />
          <section className="card table-card">
            <div className="table-scroll">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>账号来源国家</TableHead>
                    <TableHead>发送目标国家</TableHead>
                    <TableHead>发送（单勾）</TableHead>
                    <TableHead>双勾送达</TableHead>
                    <TableHead>送达率</TableHead>
                    <TableHead>失败</TableHead>
                    <TableHead>异常账号</TableHead>
                    <TableHead>封号账号</TableHead>
                    <TableHead>封号率</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pagination.rows.map((row) => (
                    <TableRow key={`${row.sourceCountry}-${row.targetCountry}`}>
                      <TableCell>
                        <Badge>{row.sourceCountry}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge>{row.targetCountry}</Badge>
                      </TableCell>
                      <TableCell>{row.sent.toLocaleString()}</TableCell>
                      <TableCell>{row.delivered.toLocaleString()}</TableCell>
                      <TableCell>{deliveryRate(row)}</TableCell>
                      <TableCell>{row.failed.toLocaleString()}</TableCell>
                      <TableCell>
                        {row.abnormalAccounts.toLocaleString()}
                      </TableCell>
                      <TableCell>
                        {row.bannedAccounts.toLocaleString()}
                      </TableCell>
                      <TableCell>
                        <Badge
                          tone={
                            row.banRate >= 0.05
                              ? "danger"
                              : row.banRate >= 0.02
                                ? "warning"
                                : "success"
                          }
                        >
                          {percent(row.banRate)}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </section>
        </>
      ) : (
        <section className="card">
          <EmptyState
            title="暂无国家交叉数据"
            description="超链任务产生投递结果后，这里会按账号来源国家与目标国家自动汇总。"
          />
        </section>
      )}
    </StandardListPage>
  );
}
