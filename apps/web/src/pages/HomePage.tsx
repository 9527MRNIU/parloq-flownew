import {
  ActivityIcon,
  ArrowRightIcon,
  CheckCircle2Icon,
  Clock3Icon,
  ListChecksIcon,
  RefreshCwIcon,
  SendIcon,
  SmartphoneIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  XAxis,
  YAxis,
} from "recharts";
import { apiRequest, formatLocalDateInput } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "../components/ui/chart";
import { Badge, Button, EmptyState, Spinner } from "../components/ui";
import type { BadgeTone } from "../components/ui/badge";
import { entityRowKey, snowflakeId } from "../lib/entity-identifiers";

type AccountOverview = {
  total: number;
  valid: number;
  online: number;
};

type AccountDaily = {
  date: string;
  valid: number;
  online: number;
  added: number;
};

type TaskRow = {
  id: string;
  readKey: string;
  name: string;
  status: string;
  total: number;
  queued: number;
  sent: number;
  delivered: number;
  failed: number;
  createdAt: string;
};

const value = (input: unknown) => {
  const parsed = Number(input ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
};

const rowValue = (row: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) if (row[key] != null) return row[key];
  return undefined;
};

const body = (payload: unknown) =>
  ((payload as { data?: unknown })?.data ?? payload) as Record<string, unknown>;

const taskStatus: Record<
  string,
  { label: string; tone: BadgeTone; color: string }
> = {
  running: { label: "运行中", tone: "success", color: "#047857" },
  paused: { label: "已暂停", tone: "warning", color: "#b45309" },
  completed: { label: "已完成", tone: "success", color: "#047857" },
  cancelled: { label: "已取消", tone: "neutral", color: "#94a3b8" },
  draft: { label: "草稿", tone: "neutral", color: "#64748b" },
};

function normalizeTask(input: unknown): TaskRow {
  const row = input as Record<string, unknown>;
  const id = snowflakeId(row, "id");
  return {
    id,
    readKey: entityRowKey(row, id, "hyperlink-task", `${String(row.name || "")}:${String(rowValue(row, "createdAt", "created_at") || "")}`),
    name: String(row.name || "未命名任务"),
    status: String(row.status || "draft"),
    total: value(rowValue(row, "totalCount", "total_count")),
    queued: value(rowValue(row, "queuedCount", "queued_count")),
    sent: value(rowValue(row, "sentCount", "sent_count")),
    delivered: value(rowValue(row, "deliveredCount", "delivered_count")),
    failed: value(rowValue(row, "failedCount", "failed_count")),
    createdAt: String(rowValue(row, "createdAt", "created_at") || ""),
  };
}

const accountChartConfig = {
  valid: { label: "有效账号", color: "#6d87cd" },
  online: { label: "在线账号", color: "#047857" },
  added: { label: "新增账号", color: "#b45309" },
} satisfies ChartConfig;

function formatDateTime(input: string) {
  if (!input) return "-";
  const parsed = new Date(input);
  if (Number.isNaN(parsed.getTime())) return input;
  return parsed.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function rate(count: number, total: number) {
  return total ? `${((count / total) * 100).toFixed(1)}%` : "-";
}

export function HomePage() {
  const { user } = useAuth();
  const [overview, setOverview] = useState<AccountOverview>({
    total: 0,
    valid: 0,
    online: 0,
  });
  const [daily, setDaily] = useState<AccountDaily[]>([]);
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    const dateTo = formatLocalDateInput();
    const dateFrom = formatLocalDateInput(new Date(Date.now() - 13 * 86400000));
    try {
      const [overviewPayload, dailyPayload, tasksPayload] = await Promise.all([
        apiRequest("/api/account-statistics/overview"),
        apiRequest(
          `/api/account-statistics/daily?${new URLSearchParams({ dateFrom, dateTo })}`,
        ),
        apiRequest("/api/hyperlink/tasks"),
      ]);
      const overviewData = body(overviewPayload);
      const dailyData = body(dailyPayload);
      const tasksData = body(tasksPayload);
      setOverview({
        total: value(
          rowValue(overviewData, "totalAccounts", "total_accounts", "total"),
        ),
        valid: value(
          rowValue(overviewData, "validAccounts", "valid_accounts", "valid"),
        ),
        online: value(
          rowValue(overviewData, "onlineAccounts", "online_accounts", "online"),
        ),
      });
      const dailyRows = Array.isArray(dailyData.rows) ? dailyData.rows : [];
      setDaily(
        dailyRows.map((input) => {
          const row = input as Record<string, unknown>;
          return {
            date: String(rowValue(row, "date", "statDate", "stat_date") || ""),
            valid: value(rowValue(row, "validAccounts", "valid_accounts", "valid")),
            online: value(rowValue(row, "onlineAccounts", "online_accounts", "online")),
            added: value(rowValue(row, "newAccounts", "new_accounts", "added")),
          };
        }),
      );
      const taskRows = Array.isArray(tasksData.rows) ? tasksData.rows : [];
      setTasks(taskRows.map(normalizeTask));
      setRefreshedAt(new Date());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "首页数据加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const taskSummary = useMemo(() => {
    const counts = new Map<string, number>();
    tasks.forEach((task) => counts.set(task.status, (counts.get(task.status) || 0) + 1));
    return Array.from(counts.entries())
      .map(([status, count]) => ({
        status,
        name: taskStatus[status]?.label || status,
        value: count,
        color: taskStatus[status]?.color || "#94a3b8",
      }))
      .sort((left, right) => right.value - left.value);
  }, [tasks]);

  const queued = tasks.reduce((sum, task) => sum + task.queued, 0);
  const running = tasks.filter((task) => task.status === "running").length;
  const paused = tasks.filter((task) => task.status === "paused").length;
  const recentTasks = tasks.slice(0, 5);
  const cards = [
    {
      label: "绑定号码",
      value: overview.total,
      detail: `${overview.online.toLocaleString()} 个当前在线`,
      icon: SmartphoneIcon,
      tone: "text-primary bg-primary/10",
    },
    {
      label: "有效账号",
      value: overview.valid,
      detail: `有效率 ${rate(overview.valid, overview.total)}`,
      icon: CheckCircle2Icon,
      tone: "text-[var(--success)] bg-[var(--status-success-bg)]",
    },
    {
      label: "群发待发送",
      value: queued,
      detail: `${running.toLocaleString()} 个任务正在运行`,
      icon: SendIcon,
      tone: "text-[var(--warning)] bg-[var(--status-warning-bg)]",
    },
    {
      label: "群发任务",
      value: tasks.length,
      detail: `${running.toLocaleString()} 运行中 · ${paused.toLocaleString()} 已暂停`,
      icon: ListChecksIcon,
      tone: "text-[var(--info)] bg-[var(--status-info-bg)]",
    },
  ];

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            你好，{user?.username || "用户"}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            查看账号资源与群发任务的当前运行情况。
          </p>
        </div>
        <div className="flex items-center gap-3">
          {refreshedAt ? (
            <span className="text-xs text-muted-foreground">
              更新于 {refreshedAt.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
            </span>
          ) : null}
          <Button variant="outline" onClick={() => void load()} disabled={loading}>
            <RefreshCwIcon className={loading ? "spin" : ""} />
            刷新
          </Button>
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-[var(--status-danger-border)] bg-[var(--status-danger-bg)] px-4 py-3 text-sm text-[var(--danger)]">
          {error}
        </div>
      ) : null}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map(({ label, value: cardValue, detail, icon: Icon, tone }) => (
          <article key={label} className="rounded-xl border bg-card p-4 shadow-sm shadow-black/[0.02]">
            <div className="flex items-start justify-between gap-3">
              <span className="text-sm text-muted-foreground">{label}</span>
              <span className={`grid size-9 place-items-center rounded-lg ${tone}`}>
                <Icon className="size-[18px]" />
              </span>
            </div>
            <strong className="mt-4 block text-3xl font-semibold tabular-nums tracking-tight">
              {loading ? "-" : cardValue.toLocaleString()}
            </strong>
            <span className="mt-1 block text-xs text-muted-foreground">{detail}</span>
          </article>
        ))}
      </section>

      <section className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.75fr)_minmax(320px,1fr)]">
        <article className="min-w-0 rounded-xl border bg-card p-4">
          <header className="mb-2 flex items-start justify-between gap-3">
            <div>
              <h2 className="font-semibold">账号趋势</h2>
              <p className="mt-1 text-xs text-muted-foreground">最近 14 天有效、在线与新增账号变化</p>
            </div>
            <ActivityIcon className="size-4 text-muted-foreground" />
          </header>
          {loading ? (
            <div className="flex h-[280px] items-center justify-center gap-2 text-sm text-muted-foreground"><Spinner />正在加载趋势…</div>
          ) : (
            <ChartContainer config={accountChartConfig} className="h-[280px] w-full">
              <AreaChart data={daily} margin={{ top: 12, right: 12, bottom: 0, left: -18 }}>
                <CartesianGrid vertical={false} strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={(input) => String(input).slice(5)} tickLine={false} axisLine={false} />
                <YAxis allowDecimals={false} tickLine={false} axisLine={false} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Area type="monotone" dataKey="valid" stroke="var(--color-valid)" fill="var(--color-valid)" fillOpacity={0.1} strokeWidth={2.3} />
                <Area type="monotone" dataKey="online" stroke="var(--color-online)" fill="var(--color-online)" fillOpacity={0.08} strokeWidth={2.1} />
                <Area type="monotone" dataKey="added" stroke="var(--color-added)" fill="var(--color-added)" fillOpacity={0.05} strokeWidth={1.8} />
              </AreaChart>
            </ChartContainer>
          )}
        </article>

        <article className="min-w-0 rounded-xl border bg-card p-4">
          <header>
            <h2 className="font-semibold">任务状态</h2>
            <p className="mt-1 text-xs text-muted-foreground">当前全部群发任务构成</p>
          </header>
          {loading ? (
            <div className="flex h-[280px] items-center justify-center gap-2 text-sm text-muted-foreground"><Spinner />正在加载任务…</div>
          ) : taskSummary.length ? (
            <div className="grid min-h-[280px] grid-cols-[minmax(160px,1fr)_minmax(120px,0.8fr)] items-center gap-2">
              <ChartContainer config={{ value: { label: "任务", color: "#6d87cd" } }} className="h-[240px] w-full">
                <PieChart>
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <Pie data={taskSummary} dataKey="value" nameKey="name" innerRadius={58} outerRadius={88} paddingAngle={3} stroke="none">
                    {taskSummary.map((item) => <Cell key={item.status} fill={item.color} />)}
                  </Pie>
                </PieChart>
              </ChartContainer>
              <div className="grid gap-3">
                {taskSummary.map((item) => (
                  <div key={item.status} className="flex items-center justify-between gap-3 text-sm">
                    <span className="flex items-center gap-2 text-muted-foreground"><i className="size-2 rounded-full" style={{ background: item.color }} />{item.name}</span>
                    <strong className="tabular-nums">{item.value}</strong>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <EmptyState title="暂无群发任务" description="创建任务后会在这里展示运行状态。" />
          )}
        </article>
      </section>

      <section className="min-w-0 rounded-xl border bg-card">
        <header className="flex items-center justify-between gap-3 border-b px-4 py-3">
          <div>
            <h2 className="font-semibold">最近任务</h2>
            <p className="mt-1 text-xs text-muted-foreground">优先关注仍有待发送或失败号码的任务</p>
          </div>
          <Button variant="ghost" asChild>
            <Link to="/hyperlink/tasks">查看全部<ArrowRightIcon /></Link>
          </Button>
        </header>
        {loading ? (
          <div className="flex min-h-48 items-center justify-center gap-2 text-sm text-muted-foreground"><Spinner />正在加载任务…</div>
        ) : recentTasks.length ? (
          <div className="divide-y">
            {recentTasks.map((task) => {
              const status = taskStatus[task.status] || { label: task.status, tone: "neutral" as const, color: "#94a3b8" };
              const finished = task.sent + task.delivered + task.failed;
              const progress = task.total ? Math.min(100, (finished / task.total) * 100) : 0;
              return (
                <div key={task.readKey} className="grid gap-3 px-4 py-3 lg:grid-cols-[minmax(220px,1.3fr)_minmax(260px,1fr)_auto] lg:items-center">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2"><strong className="truncate text-sm">{task.name}</strong><Badge tone={status.tone}>{status.label}</Badge></div>
                    <span className="mt-1 block truncate text-xs text-muted-foreground">{task.id || "等待 ID 迁移"} · {formatDateTime(task.createdAt)}</span>
                  </div>
                  <div className="min-w-0">
                    <div className="mb-1.5 flex justify-between gap-3 text-xs text-muted-foreground"><span>处理进度</span><span className="tabular-nums">{finished.toLocaleString()} / {task.total.toLocaleString()}</span></div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary transition-all" style={{ width: `${progress}%` }} /></div>
                  </div>
                  <div className="flex min-w-[250px] justify-between gap-4 text-xs text-muted-foreground lg:justify-end">
                    <span>待发 <b className="text-foreground">{task.queued.toLocaleString()}</b></span>
                    <span>双勾 <b className="text-[var(--success)]">{task.delivered.toLocaleString()}</b></span>
                    <span>失败 <b className="text-[var(--danger)]">{task.failed.toLocaleString()}</b></span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="min-h-48"><EmptyState title="暂无群发任务" description="创建任务后可在首页跟踪处理进度。" /></div>
        )}
      </section>

      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Clock3Icon className="size-3.5" />
        首页数据来自账号统计与超链任务实时接口。
      </div>
    </div>
  );
}
