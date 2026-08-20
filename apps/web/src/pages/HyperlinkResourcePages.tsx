import {
  BoxesIcon,
  FileStackIcon,
  GaugeIcon,
  LoaderCircleIcon,
  PlusIcon,
  RefreshCwIcon,
  WorkflowIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { apiRequest, formatDateTime, unwrapList } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import {
  ListPagination,
  ListTableCard,
  ListToolbar,
  StandardListPage,
  useClientPagination,
} from "../components/list-page";
import {
  EntityPrimaryCell,
  type EntityStatusMeta,
} from "../components/entity-primary-cell";
import {
  MessageTemplatePreview,
  type MessagePreviewButton,
  type MessagePreviewButtonType,
  type MessagePreviewHeaderType,
} from "../components/message-template-preview";
import { DrawerFieldLabel } from "../components/drawer-form";
import {
  Badge,
  Button,
  Drawer,
  EmptyState,
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
  Textarea,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
  confirmAction,
  toast,
} from "../components/ui";
import { entityRowKey, snowflakeId } from "../lib/entity-identifiers";
import { formatPhoneDisplay } from "../lib/utils";

type AnyRow = Record<string, unknown> & { id: string; readKey: string };
type TaskRecipientRow = Record<string, unknown> & { id: string };
type OptionSource =
  | "materials"
  | "promotionChannels"
  | "templates"
  | "strategies"
  | "packages"
  | "accountGroups";
type FieldConfig = {
  key: string;
  label: string;
  type?: "text" | "number" | "textarea" | "select" | "switch";
  required?: boolean;
  placeholder?: string;
  options?: Array<{ value: string; label: string }>;
  optionSource?: OptionSource;
  help?: string;
};
type Column = {
  key: string;
  label: string;
  render?: (row: AnyRow) => ReactNode;
  className?: string;
};
type ModuleConfig = {
  title: string;
  description: string;
  endpoint: string;
  permissionKey: string;
  createLabel: string;
  empty: string;
  icon: ReactNode;
  fields: FieldConfig[];
  columns: Column[];
  defaults: Record<string, string>;
  toPayload: (form: Record<string, string>) => Record<string, unknown>;
  taskActions?: boolean;
  statusFilter?: boolean;
  showUpdatedAt?: boolean;
  drawerDescription?: string;
};
const read = (row: Record<string, unknown>, key: string) =>
  row[key] ??
  row[key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)] ??
  "";
const snakeKey = (key: string) =>
  key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
const displayValue = (row: Record<string, unknown>, key: string) => {
  const value = read(row, key);
  return value === "" || value == null ? "-" : String(value);
};
function normalize(input: unknown): AnyRow {
  const source = input as Record<string, unknown>;
  const id = snowflakeId(source, "id");
  const cleanSource = Object.fromEntries(
    Object.entries(source).filter(
      ([key]) =>
        key !== "publicId" &&
        key !== "public_id" &&
        !key.endsWith("PublicId") &&
        !key.endsWith("_public_id"),
    ),
  );
  return {
    ...cleanSource,
    id,
    readKey: entityRowKey(
      source,
      id,
      "hyperlink-resource",
      `${String(source.name || "")}:${String(source.createdAt || source.created_at || "")}`,
    ),
  };
}
function resourceStatus(row: AnyRow): EntityStatusMeta {
  const rawStatus = String(read(row, "status") || "").toLowerCase();
  const enabled = read(row, "enabled");
  if (enabled === false || rawStatus === "disabled") {
    return { label: "已停用", description: "该资源当前不会参与新的营销任务。", tone: "neutral" };
  }
  if (["failed", "error", "invalid", "rejected", "cancelled", "canceled"].includes(rawStatus)) {
    return {
      label: ["cancelled", "canceled"].includes(rawStatus) ? "已取消" : "异常",
      description: ["cancelled", "canceled"].includes(rawStatus)
        ? "该任务已经取消，不会继续执行。"
        : "该资源处理失败或配置无效，请检查详情后重试。",
      tone: "danger",
    };
  }
  if (["pending", "draft", "processing", "running", "paused", "waiting_accounts"].includes(rawStatus)) {
    return {
      label:
        rawStatus === "waiting_accounts"
          ? "等待可用账号"
          : rawStatus === "paused"
          ? "已暂停"
          : rawStatus === "running"
            ? "执行中"
            : rawStatus === "draft"
              ? "草稿"
              : "准备中",
      description:
        rawStatus === "waiting_accounts"
          ? "账号分组当前没有可用账号；账号加入分组或恢复可用后，任务会自动继续。"
          : rawStatus === "running"
          ? "任务正在执行。"
          : rawStatus === "paused"
            ? "任务已经暂停，可以继续执行或取消。"
            : rawStatus === "draft"
              ? "任务尚未开始，可以继续编辑。"
              : "该资源尚未进入稳定可用状态。",
      tone: "warning",
    };
  }
  if (["active", "ready", "completed", "enabled", "success"].includes(rawStatus)) {
    return {
      label: rawStatus === "completed" ? "已完成" : "可用",
      description: rawStatus === "completed" ? "任务已经执行完成。" : "该资源当前可以正常使用。",
      tone: "success",
    };
  }
  return { label: "已创建", description: "资源已创建，当前没有额外的运行状态。", tone: "neutral" };
}
function statusBadge(value: unknown) {
  const status = String(value || "ready");
  if (["active", "running", "ready", "completed"].includes(status))
    return (
      <Badge tone="success">
        {status === "running"
          ? "执行中"
          : status === "completed"
            ? "已完成"
            : "可用"}
      </Badge>
    );
  if (["failed", "cancelled", "error"].includes(status))
    return (
      <Badge tone="danger">{status === "cancelled" ? "已取消" : "异常"}</Badge>
    );
  if (["paused", "draft", "pending", "waiting_accounts"].includes(status))
    return (
      <Badge tone="warning">
        {status === "waiting_accounts"
          ? "等待可用账号"
          : status === "paused"
            ? "已暂停"
            : "准备中"}
      </Badge>
    );
  return <Badge tone="neutral">{status}</Badge>;
}

function taskRecipientStatus(value: unknown) {
  const status = String(value || "pending");
  const values: Record<
    string,
    {
      label: string;
      tone: "neutral" | "success" | "warning" | "danger";
    }
  > = {
    pending: { label: "等待发送", tone: "warning" },
    leased: { label: "已进入缓冲", tone: "warning" },
    submitting: { label: "提交中", tone: "warning" },
    accepted: { label: "已受理", tone: "success" },
    retry: { label: "等待重试", tone: "warning" },
    reconciling: { label: "状态核对中", tone: "warning" },
    failed: { label: "提交失败", tone: "danger" },
    skipped: { label: "已跳过", tone: "neutral" },
    cancelled: { label: "已取消", tone: "neutral" },
  };
  const current = values[status] || {
    label: status,
    tone: "neutral" as const,
  };
  return <Badge tone={current.tone}>{current.label}</Badge>;
}

function taskMessageStatus(value: unknown) {
  const status = String(value || "");
  if (!status) return <span className="text-muted-foreground">-</span>;
  const values: Record<
    string,
    {
      label: string;
      tone: "neutral" | "success" | "warning" | "danger";
    }
  > = {
    queued: { label: "已提交", tone: "warning" },
    sent: { label: "已发送", tone: "success" },
    delivered: { label: "已送达", tone: "success" },
    read: { label: "已读", tone: "success" },
    replied: { label: "已回复", tone: "success" },
    failed: { label: "发送失败", tone: "danger" },
  };
  const current = values[status] || {
    label: status,
    tone: "neutral" as const,
  };
  return <Badge tone={current.tone}>{current.label}</Badge>;
}

function parseRecipientFile(contents: string) {
  const lines = contents
    .replace(/^\uFEFF/, "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (
    lines.length &&
    /^(phone|number|mobile|手机号|手机号码|号码)(\s*[,;\t]|$)/i.test(lines[0])
  ) {
    lines.shift();
  }
  return lines
    .map((line) => {
      const [phone = "", countryCode = ""] = line
        .split(/[,;\t]/, 2)
        .map((value) => value.trim());
      const cleanPhone = formatPhoneDisplay(phone).replace(/[\s()-]/g, "");
      return [cleanPhone, countryCode.toUpperCase()].filter(Boolean).join(",");
    })
    .filter((line) => line.split(",", 1)[0]);
}
const jsonText = (value: unknown) => {
  if (value && typeof value === "object")
    return String(
      (value as Record<string, unknown>).text ||
        (value as Record<string, unknown>).content ||
        JSON.stringify(value),
    );
  return String(value || "");
};
const objectValue = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

function taskTemplatePreview(row: AnyRow) {
  const content = objectValue(read(row, "templateContent"));
  const header = objectValue(content.header);
  const body = objectValue(content.body);
  const footer = objectValue(content.footer);
  const snapshot = objectValue(read(row, "templateSnapshot"));
  const material = objectValue(snapshot.material);
  const headerType = String(header.type || "none") as MessagePreviewHeaderType;
  const buttons: MessagePreviewButton[] = (Array.isArray(content.buttons)
    ? content.buttons
    : []
  ).map((value, index) => {
    const button = objectValue(value);
    const type = String(button.type || "quick_reply") as MessagePreviewButtonType;
    return {
      id: String(button.id || `button-${index}`),
      type,
      text: String(button.text || "按钮"),
      value: String(
        button.url || button.phone || button.copyText || button.id || "",
      ),
    };
  });
  const materialId = String(material.id || "");
  return {
    headerType,
    headerText: String(header.text || ""),
    mediaUrl:
      materialId && ["image", "video"].includes(headerType)
        ? `/api/materials/${materialId}/content`
        : "",
    fileName: String(material.fileName || material.name || "document"),
    body: String(body.text || content.text || content.content || ""),
    footer: String(footer.text || ""),
    buttons,
  };
}

function TaskTemplateCell({ row }: { row: AnyRow }) {
  const name = String(read(row, "templateName") || "未命名模板");
  const preview = taskTemplatePreview(row);
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="max-w-52 truncate border-b border-dotted border-muted-foreground/60 text-left font-medium text-foreground"
        >
          {name}
        </button>
      </TooltipTrigger>
      <TooltipContent
        hideArrow
        side="left"
        align="center"
        sideOffset={10}
        collisionPadding={16}
        className="block w-[220px] max-w-[calc(100vw-24px)] rounded-none bg-transparent p-0 text-foreground shadow-none ring-0"
      >
        <MessageTemplatePreview {...preview} compact />
      </TooltipContent>
    </Tooltip>
  );
}

function TaskTimeCell({ row }: { row: AnyRow }) {
  const times = [
    ["创建", read(row, "createdAt")],
    ["开始", read(row, "startedAt")],
    ["完成", read(row, "completedAt")],
  ];
  return (
    <div className="grid min-w-48 gap-1 text-xs text-muted-foreground">
      {times.map(([label, value]) => (
        <div className="grid grid-cols-[32px_minmax(0,1fr)] gap-2" key={String(label)}>
          <span>{String(label)}</span>
          <span className="tabular-nums">{value ? formatDateTime(String(value)) : "-"}</span>
        </div>
      ))}
    </div>
  );
}

function statRate(value: number, total: number) {
  return total ? `${((value / total) * 100).toFixed(2)}%` : "-";
}

function TaskStatLine({
  label,
  value,
  total,
  tone = "neutral",
}: {
  label: string;
  value: number;
  total?: number;
  tone?: "neutral" | "success" | "warning" | "danger";
}) {
  return (
    <div className="flex min-w-40 items-center gap-2 text-xs tabular-nums">
      <Badge tone={tone} className="w-14 justify-center">
        {label}
      </Badge>
      <strong className="min-w-8 font-medium text-foreground">{value}</strong>
      {total !== undefined ? (
        <span className="text-muted-foreground">{statRate(value, total)}</span>
      ) : null}
    </div>
  );
}

function TaskSubmissionStats({ row }: { row: AnyRow }) {
  const stats = objectValue(read(row, "submissionStats"));
  const total = Number(stats.total || 0);
  return (
    <div className="grid gap-1.5">
      <TaskStatLine label="总数" value={total} />
      <TaskStatLine label="等待" value={Number(stats.waiting || 0)} total={total} tone="warning" />
      <TaskStatLine label="提交中" value={Number(stats.submitting || 0)} total={total} tone="warning" />
      <TaskStatLine label="成功" value={Number(stats.accepted || 0)} total={total} tone="success" />
      <TaskStatLine label="失败" value={Number(stats.failed || 0)} total={total} tone="danger" />
    </div>
  );
}

function TaskSendStats({ row }: { row: AnyRow }) {
  const stats = objectValue(read(row, "sendStats"));
  const accepted = Number(objectValue(read(row, "submissionStats")).accepted || 0);
  return (
    <div className="grid gap-1.5">
      <TaskStatLine label="发送" value={Number(stats.sent || 0)} total={accepted} />
      <TaskStatLine label="送达" value={Number(stats.delivered || 0)} total={accepted} tone="success" />
      <TaskStatLine label="失败" value={Number(stats.failed || 0)} total={accepted} tone="danger" />
    </div>
  );
}

function TaskAccountGroupCell({ row }: { row: AnyRow }) {
  const group = objectValue(read(row, "accountGroup"));
  const groupId =
    snowflakeId(row, "accountGroupId", "account_group_id") ||
    snowflakeId(group, "id");
  const groupName = String(
    read(row, "accountGroupName") || group.name || "",
  );
  const selectionMode = String(
      read(row, "senderMode") ||
      read(row, "accountSelectionMode") ||
      read(row, "accountAssignmentMode") ||
      read(row, "accountMode") ||
      read(row, "accountSourceMode") ||
      "",
  ).toLowerCase();
  const legacyAccountIds = read(row, "accountIds");
  const legacyFixed =
    selectionMode === "legacy_fixed" ||
    (!groupId &&
      ((Array.isArray(legacyAccountIds) && legacyAccountIds.length > 0) ||
        (typeof legacyAccountIds === "string" && legacyAccountIds.length > 0)));
  const slotStats = objectValue(read(row, "accountSlotStats"));
  const activeSlots = Number(slotStats.active || 0);
  const totalSlots = Number(slotStats.total || 0);

  if (legacyFixed) {
    return (
      <div className="cell-main min-w-[180px]">
        <strong>历史固定账号</strong>
        <Badge tone="neutral">兼容模式</Badge>
        <span>仅保留旧任务的固定账号快照</span>
      </div>
    );
  }

  return (
    <div className="cell-main min-w-[200px]">
      <strong>{groupName || "账号分组待同步"}</strong>
      <Badge tone="neutral">自动调度</Badge>
      {groupId ? <span>{groupId}</span> : null}
      <span>
        {totalSlots
          ? `已占用 ${activeSlots}/${totalSlots} 个并发账号槽位`
          : "启动后按并发配置占用可用账号"}
      </span>
    </div>
  );
}

const optionEndpoints: Record<OptionSource, string> = {
  materials: "/api/materials",
  promotionChannels: "/api/promotion/channels",
  templates: "/api/hyperlink/templates",
  strategies: "/api/hyperlink/strategies",
  packages: "/api/hyperlink/data-packages",
  accountGroups: "/api/account-groups?pageSize=100",
};
function optionLabel(source: OptionSource, row: Record<string, unknown>) {
  const name = String(
    read(row, "name") ||
      read(row, "displayName") ||
      snowflakeId(row, "id") ||
      "未命名资源",
  );
  if (source === "accountGroups") {
    const accountCount = read(row, "accountCount");
    return `${name}${accountCount !== "" ? ` · ${Number(accountCount)} 个账号` : ""}`;
  }
  if (source === "promotionChannels")
    return `${name}${read(row, "countryCode") ? ` · ${String(read(row, "countryCode"))}` : ""}`;
  return name;
}

function HyperlinkResourcePage({ config }: { config: ModuleConfig }) {
  const { can } = useAuth();
  const canManage = can(config.permissionKey);
  const [rows, setRows] = useState<AnyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [drawer, setDrawer] = useState(false);
  const [editing, setEditing] = useState<AnyRow | null>(null);
  const [form, setForm] = useState<Record<string, string>>(config.defaults);
  const [dynamicOptions, setDynamicOptions] = useState<
    Record<string, Array<{ value: string; label: string }>>
  >({});
  const [pending, setPending] = useState(false);
  const [operation, setOperation] = useState("");
  const [detailTask, setDetailTask] = useState<AnyRow | null>(null);
  const [detailRows, setDetailRows] = useState<TaskRecipientRow[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailPage, setDetailPage] = useState(1);
  const [detailTotal, setDetailTotal] = useState(0);
  const [detailPageSize, setDetailPageSize] = useState(50);
  const displayColumns = config.columns.filter(
    (column) => column.key.toLowerCase() !== "status",
  );
  const load = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      const payload = await apiRequest(`${config.endpoint}?pageSize=100`);
      setRows(unwrapList<unknown>(payload).rows.map(normalize));
    } catch {
      setRows([]);
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [config.endpoint]);
  useEffect(() => {
    void load();
  }, [load]);
  const visible = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return rows.filter((row) => {
      if (
        statusFilter !== "all" &&
        String(read(row, "status") || "") !== statusFilter
      )
        return false;
      return (
        !search ||
        Object.values(row).some((value) =>
          String(value || "")
            .toLowerCase()
            .includes(search),
        )
      );
    });
  }, [keyword, rows, statusFilter]);
  const listPagination = useClientPagination(visible, {
    resetKey: `${keyword}|${statusFilter}`,
  });
  useEffect(() => {
    if (
      !config.taskActions ||
      !rows.some((row) =>
        ["running", "waiting_accounts"].includes(String(read(row, "status"))),
      )
    )
      return;
    const timer = window.setInterval(() => void load(false), 5_000);
    return () => window.clearInterval(timer);
  }, [config.taskActions, load, rows]);
  useEffect(() => {
    const fields = config.fields.filter((item) => item.optionSource);
    if (!fields.length) {
      setDynamicOptions({});
      return;
    }
    void Promise.all(
      fields.map(async (item) => {
        const source = item.optionSource!;
        try {
          const payload = await apiRequest(optionEndpoints[source]);
          return [
            item.key,
            unwrapList<Record<string, unknown>>(payload)
              .rows.filter((row) => row.enabled !== false)
              .map((row) => ({
                value: snowflakeId(row, "id"),
                label: optionLabel(source, row),
              }))
              .filter((row) => row.value),
          ] as const;
        } catch {
          return [item.key, []] as const;
        }
      }),
    ).then((entries) => setDynamicOptions(Object.fromEntries(entries)));
  }, [config]);
  function open(row?: AnyRow) {
    if (row && !row.id) return;
    setEditing(row || null);
    setForm(
      row
        ? Object.fromEntries(
            config.fields.map((item) => [
              item.key,
              item.key === "content"
                ? jsonText(read(row, "contentJson"))
                : item.key === "recipients"
                  ? ""
                  : item.optionSource
                    ? snowflakeId(row, item.key, snakeKey(item.key))
                  : String(read(row, item.key) ?? ""),
            ]),
          )
        : config.defaults,
    );
    setDrawer(true);
  }
  async function save() {
    if (
      (editing && !editing.id) ||
      config.fields.some((item) => item.required && !form[item.key]?.trim())
    )
      return;
    setPending(true);
    try {
      await apiRequest(
        editing ? `${config.endpoint}/${editing.id}` : config.endpoint,
        {
          method: editing ? "PATCH" : "POST",
          body: JSON.stringify(config.toPayload(form)),
        },
      );
      setDrawer(false);
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setPending(false);
    }
  }
  async function remove(row: AnyRow) {
    if (!row.id) return;
    if (
      !(await confirmAction({
        title: `删除“${String(read(row, "name"))}”？`,
        description: "删除后无法恢复；仍被其他资源使用时系统会拒绝。",
        confirmText: "确认删除",
        destructive: true,
      }))
    )
      return;
    try {
      await apiRequest(`${config.endpoint}/${row.id}`, { method: "DELETE" });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "删除失败");
    }
  }
  async function taskAction(row: AnyRow, action: string) {
    if (!row.id) return;
    setOperation(`${row.id}:${action}`);
    try {
      await apiRequest(`${config.endpoint}/${row.id}/${action}`, {
        method: "POST",
      });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "操作失败");
    } finally {
      setOperation("");
    }
  }
  async function loadTaskDetails(
    row: AnyRow,
    page = 1,
    pageSize = detailPageSize,
  ) {
    if (!row.id) return;
    setDetailTask(row);
    setDetailPage(page);
    setDetailLoading(true);
    try {
      const payload = await apiRequest(
        `${config.endpoint}/${row.id}/recipients?page=${page}&pageSize=${pageSize}`,
      );
      const result = unwrapList<Record<string, unknown>>(payload);
      setDetailRows(
        result.rows.map((item) => ({
          ...item,
          id: snowflakeId(item, "id"),
        })),
      );
      setDetailTotal(result.total);
    } catch (caught) {
      setDetailRows([]);
      setDetailTotal(0);
      toast.error(caught instanceof Error ? caught.message : "任务明细读取失败");
    } finally {
      setDetailLoading(false);
    }
  }
  function rowActions(row: AnyRow) {
    const taskStatus = String(read(row, "status"));
    const canEdit =
      !config.taskActions || ["draft", "paused"].includes(taskStatus);
    const canStart =
      config.taskActions && ["draft", "paused"].includes(taskStatus);
    const canPause =
      config.taskActions && ["running", "waiting_accounts"].includes(taskStatus);
    const canCancel =
      config.taskActions &&
      ["draft", "paused", "running", "waiting_accounts"].includes(taskStatus);
    return (
      <div className="flex min-w-max items-center justify-end gap-2">
        {config.taskActions ? (
          <Button
            variant="outline"
            size="sm"
            disabled={!row.id}
            onClick={() => void loadTaskDetails(row)}
          >
            任务明细
          </Button>
        ) : null}
        {canManage ? (
          <>
        {canStart ? (
          <Button
            variant="outline"
            size="sm"
            disabled={!row.id || Boolean(operation)}
            onClick={() => void taskAction(row, "start")}
          >
            开始
          </Button>
        ) : null}
        {canPause ? (
          <Button
            variant="outline"
            size="sm"
            disabled={!row.id || Boolean(operation)}
            onClick={() => void taskAction(row, "pause")}
          >
            暂停
          </Button>
        ) : null}
        {canCancel ? (
          <Button
            variant="outline"
            size="sm"
            disabled={!row.id || Boolean(operation)}
            onClick={() => void taskAction(row, "cancel")}
          >
            {operation.startsWith(row.id) ? <LoaderCircleIcon className="spin" size={16} /> : null}
            取消
          </Button>
        ) : null}
        {canEdit ? (
          <Button variant="outline" size="sm" disabled={!row.id} onClick={() => open(row)}>
            编辑
          </Button>
        ) : null}
        <Button
          variant="destructive"
          size="sm"
          disabled={!row.id}
          onClick={() => void remove(row)}
        >
          删除
        </Button>
          </>
        ) : null}
      </div>
    );
  }
  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: `搜索${config.title}`,
        }}
        filters={
          config.statusFilter ? (
            <SelectField
              className="w-36"
              value={statusFilter}
              onValueChange={setStatusFilter}
              options={[
                { value: "all", label: "全部状态" },
                { value: "draft", label: "草稿" },
                { value: "running", label: "执行中" },
                { value: "waiting_accounts", label: "等待可用账号" },
                { value: "paused", label: "已暂停" },
                { value: "completed", label: "已完成" },
                { value: "failed", label: "失败" },
                { value: "cancelled", label: "已取消" },
              ]}
            />
          ) : undefined
        }
        meta={`${visible.length} 条记录`}
        actions={
          <>
            <Button variant="outline" onClick={() => void load()}>
              <RefreshCwIcon size={16} />
              刷新
            </Button>
            {canManage ? (
              <Button onClick={() => open()}>
                <PlusIcon size={17} />
                {config.createLabel}
              </Button>
            ) : null}
          </>
        }
      />
      <ListPagination
        page={listPagination.page}
        pageSize={listPagination.pageSize}
        total={listPagination.total}
        disabled={loading}
        onPageChange={listPagination.setPage}
        onPageSizeChange={listPagination.setPageSize}
      />
      <ListTableCard>
        {loading ? (
          <div className="loading-state">
            <Spinner />
          </div>
        ) : visible.length ? (
          <Table layout="list">
            <TableHeader>
              <TableRow>
                {displayColumns.map((column, columnIndex) => (
                  <TableHead
                    adaptive={columnIndex === 0}
                    className={column.className}
                    key={column.key}
                  >
                    {column.label}
                  </TableHead>
                ))}
                {config.showUpdatedAt !== false ? <TableHead>更新时间</TableHead> : null}
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {listPagination.rows.map((row) => (
                <TableRow key={row.readKey}>
                  {displayColumns.map((column, columnIndex) => (
                    <TableCell className={column.className} key={column.key}>
                      {columnIndex === 0 ? (
                        <EntityPrimaryCell
                          title={column.render ? column.render(row) : displayValue(row, column.key)}
                          id={row.id}
                          status={{
                            ...resourceStatus(row),
                            details: config.taskActions
                              ? [
                                  { label: "目标数", value: displayValue(row, "totalCount") },
                                  { label: "模板", value: displayValue(row, "templateName") },
                                  {
                                    label: "开始时间",
                                    value: read(row, "startedAt")
                                      ? formatDateTime(String(read(row, "startedAt")))
                                      : "-",
                                  },
                                ]
                              : [
                              { label: "资源类型", value: config.title },
                              { label: "更新时间", value: formatDateTime(String(read(row, "updatedAt") || read(row, "createdAt"))) },
                                ],
                          }}
                        />
                      ) : column.render ? column.render(row) : displayValue(row, column.key)}
                    </TableCell>
                  ))}
                  {config.showUpdatedAt !== false ? (
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(
                        String(read(row, "updatedAt") || read(row, "createdAt")),
                      )}
                    </TableCell>
                  ) : null}
                  <TableCell>{rowActions(row)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <EmptyState
            title={`暂无${config.title}`}
            description={config.empty}
          />
        )}
      </ListTableCard>
      <Drawer
        open={drawer}
        onClose={() => !pending && setDrawer(false)}
        title={editing ? `编辑${config.title}` : config.createLabel}
        description={config.drawerDescription || config.description}
        footer={
          <>
            <Button variant="outline" onClick={() => setDrawer(false)}>
              取消
            </Button>
            <Button
              disabled={
                pending ||
                config.fields.some(
                  (item) => item.required && !form[item.key]?.trim(),
                )
              }
              onClick={() => void save()}
            >
              {pending ? <Spinner /> : null}保存
            </Button>
          </>
        }
      >
        <div className="drawer-form">
          {config.fields.map((item) => (
            <label className="field" key={item.key}>
              <DrawerFieldLabel required={item.required}>
                {item.label}
              </DrawerFieldLabel>
              {item.type === "textarea" ? (
                <>
                  {item.key === "recipients" ? (
                    <Input
                      accept=".txt,.csv,text/plain,text/csv"
                      type="file"
                      onChange={(event) => {
                        const file = event.currentTarget.files?.[0];
                        event.currentTarget.value = "";
                        if (!file) return;
                        void file
                          .text()
                          .then((contents) => {
                            const lines = parseRecipientFile(contents);
                            setForm((current) => ({
                              ...current,
                              recipients: lines.join("\n"),
                            }));
                            toast.success(`已读取 ${lines.length} 个号码`);
                          })
                          .catch(() => toast.error("文件读取失败"));
                      }}
                    />
                  ) : null}
                  <Textarea
                    rows={item.key === "recipients" ? 9 : 5}
                    value={form[item.key] || ""}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        [item.key]:
                          item.key === "recipients"
                            ? e.target.value.replace(/\+/g, "")
                            : e.target.value,
                      })
                    }
                    placeholder={item.placeholder}
                  />
                </>
              ) : item.type === "select" ? (
                <SelectField
                  className="w-full"
                  value={form[item.key] || ""}
                  onValueChange={(value) =>
                    setForm({ ...form, [item.key]: value })
                  }
                  placeholder={item.required ? "请选择" : "不绑定"}
                  clearable={!item.required}
                  options={item.options || dynamicOptions[item.key] || []}
                />
              ) : item.type === "switch" ? (
                <div className="flex min-h-8 items-center justify-between rounded-lg border border-input px-2.5">
                  <span className="text-sm text-muted-foreground">
                    {form[item.key] === "true" ? "已启用" : "已关闭"}
                  </span>
                  <Switch
                    checked={form[item.key] === "true"}
                    onCheckedChange={(checked) =>
                      setForm({ ...form, [item.key]: String(checked) })
                    }
                  />
                </div>
              ) : (
                <Input
                  type={item.type === "number" ? "number" : "text"}
                  value={form[item.key] || ""}
                  onChange={(e) =>
                    setForm({ ...form, [item.key]: e.target.value })
                  }
                  placeholder={item.placeholder}
                />
              )}
              {item.help ? <small className="field-help">{item.help}</small> : null}
            </label>
          ))}
        </div>
      </Drawer>
      <Drawer
        open={Boolean(detailTask)}
        onClose={() => setDetailTask(null)}
        title="任务明细"
        description={
          detailTask
            ? `${String(read(detailTask, "name") || "未命名任务")} · ${detailTotal} 个目标`
            : undefined
        }
      >
        <ListPagination
          ariaLabel="任务明细分页"
          page={detailPage}
          pageSize={detailPageSize}
          total={detailTotal}
          pageSizeOptions={[20, 50, 100]}
          disabled={detailLoading || !detailTask}
          onPageChange={(value) =>
            detailTask && void loadTaskDetails(detailTask, value)
          }
          onPageSizeChange={(value) => {
            setDetailPageSize(value);
            if (detailTask) void loadTaskDetails(detailTask, 1, value);
          }}
        />
        {detailLoading ? (
          <div className="loading-state">
            <Spinner />
          </div>
        ) : detailRows.length ? (
          <div className="overflow-auto rounded-lg border">
            <Table layout="list">
              <TableHeader>
                <TableRow>
                  <TableHead>目标号码</TableHead>
                  <TableHead>执行状态</TableHead>
                  <TableHead>消息状态</TableHead>
                  <TableHead>发送账号</TableHead>
                  <TableHead>尝试次数</TableHead>
                  <TableHead>最近更新</TableHead>
                  <TableHead adaptive>异常信息</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {detailRows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>
                      <div className="cell-main">
                        <strong>
                          {formatPhoneDisplay(String(read(row, "phone")))}
                        </strong>
                        <span>{row.id}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      {taskRecipientStatus(read(row, "executionStatus"))}
                    </TableCell>
                    <TableCell>
                      {taskMessageStatus(read(row, "messageStatus"))}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {String(read(row, "accountId") || "-")}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {Number(read(row, "attemptCount") || 0)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {formatDateTime(String(read(row, "updatedAt") || ""))}
                    </TableCell>
                    <TableCell
                      className="max-w-64 truncate text-destructive"
                      title={String(read(row, "lastError") || "")}
                    >
                      {String(read(row, "lastError") || "-")}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <EmptyState
            title="暂无任务明细"
            description="任务首次启动后会冻结数据包并生成目标执行记录。"
          />
        )}
      </Drawer>
    </StandardListPage>
  );
}

const commonName = {
  key: "name",
  label: "名称",
  required: true,
  placeholder: "请输入名称",
} satisfies FieldConfig;
const configs: Record<string, ModuleConfig> = {
  tasks: {
    title: "超链任务",
    description: "创建超链群发任务，控制执行状态并查看单勾、双勾结果。",
    endpoint: "/api/hyperlink/tasks",
    permissionKey: "marketing.hyperlink_tasks.manage",
    createLabel: "创建任务",
    empty: "选择模板、策略、数据包和发送账号分组创建任务。",
    icon: <WorkflowIcon />,
    taskActions: true,
    statusFilter: true,
    showUpdatedAt: false,
    drawerDescription: "配置模板、数据包、发送账号分组与执行策略。",
    defaults: {
      name: "",
      templateId: "",
      strategyId: "",
      dataPackageId: "",
      accountGroupId: "",
      channel: "hyperlink",
    },
    fields: [
      commonName,
      {
        key: "templateId",
        label: "超链模板",
        type: "select",
        optionSource: "templates",
        required: true,
      },
      {
        key: "strategyId",
        label: "发送策略",
        type: "select",
        optionSource: "strategies",
        required: true,
      },
      {
        key: "dataPackageId",
        label: "目标数据包",
        type: "select",
        optionSource: "packages",
        required: true,
      },
      {
        key: "accountGroupId",
        label: "发送账号分组",
        type: "select",
        optionSource: "accountGroups",
        required: true,
        help: "启动后从分组占用并发账号；账号异常或出现空槽位时，自动使用组内新可用账号补位。",
      },
      {
        key: "channel",
        label: "任务类型",
        type: "select",
        options: [{ value: "hyperlink", label: "超链营销" }],
      },
    ],
    columns: [
      {
        key: "name",
        label: "任务",
        className: "min-w-[260px]",
      },
      {
        key: "templateName",
        label: "发送内容",
        className: "min-w-[220px]",
        render: (row) => <TaskTemplateCell row={row} />,
      },
      {
        key: "accountGroupName",
        label: "发送账号来源",
        className: "min-w-[220px]",
        render: (row) => <TaskAccountGroupCell row={row} />,
      },
      {
        key: "timeInfo",
        label: "时间信息",
        className: "min-w-[220px]",
        render: (row) => <TaskTimeCell row={row} />,
      },
      {
        key: "submissionStats",
        label: "下发统计",
        className: "min-w-[190px]",
        render: (row) => <TaskSubmissionStats row={row} />,
      },
      {
        key: "sendStats",
        label: "发送统计",
        className: "min-w-[190px]",
        render: (row) => <TaskSendStats row={row} />,
      },
    ],
    toPayload: (form) => ({
      name: form.name,
      templateId: form.templateId,
      strategyId: form.strategyId,
      dataPackageId: form.dataPackageId,
      accountGroupId: form.accountGroupId,
      channel: form.channel,
    }),
  },
  packages: {
    title: "数据包",
    description: "管理超链任务的目标号码、国家和变量数据。",
    endpoint: "/api/hyperlink/data-packages",
    permissionKey: "marketing.data_packages.manage",
    createLabel: "导入数据包",
    empty: "导入号码后即可用于超链群发任务。",
    icon: <FileStackIcon />,
    defaults: { name: "", recipients: "" },
    fields: [
      commonName,
      {
        key: "recipients",
        label: "号码数据（新建时填写）",
        type: "textarea",
        placeholder:
          "每行一个号码，可选国家代码：\n8613800000000,CN\n15550000000,US",
      },
    ],
    columns: [
      { key: "name", label: "数据包" },
      { key: "recipientCount", label: "号码数" },
      { key: "revision", label: "当前版本" },
      { key: "taskCount", label: "使用任务" },
      {
        key: "status",
        label: "状态",
        render: (row) => statusBadge(read(row, "status")),
      },
    ],
    toPayload: (form) => ({
      name: form.name,
      ...(form.recipients.trim()
        ? {
            recipients: form.recipients
              .split("\n")
              .map((line) => {
                const [phone, countryCode] = line
                  .split(",")
                  .map((item) => item.trim());
                return {
                  phone: formatPhoneDisplay(phone),
                  ...(countryCode ? { countryCode } : {}),
                };
              })
              .filter((row) => row.phone),
          }
        : {}),
    }),
  },
  templates: {
    title: "超链模板",
    description: "管理超链消息文案和可复用素材组合。",
    endpoint: "/api/hyperlink/templates",
    permissionKey: "marketing.hyperlink_templates.manage",
    createLabel: "创建超链模板",
    empty: "创建模板后可在多个超链任务中复用。",
    icon: <BoxesIcon />,
    defaults: { name: "", content: "", materialId: "", promotionChannelId: "" },
    fields: [
      commonName,
      {
        key: "content",
        label: "消息内容",
        type: "textarea",
        required: true,
        placeholder: "输入消息文案，可使用 {{name}} 等变量",
      },
      {
        key: "materialId",
        label: "关联素材",
        type: "select",
        optionSource: "materials",
      },
      {
        key: "promotionChannelId",
        label: "关联推广渠道",
        type: "select",
        optionSource: "promotionChannels",
      },
    ],
    columns: [
      { key: "name", label: "模板" },
      {
        key: "contentJson",
        label: "内容",
        render: (row) => (
          <div className="truncate-cell">
            {jsonText(read(row, "contentJson"))}
          </div>
        ),
      },
      { key: "materialId", label: "素材" },
      { key: "promotionChannelId", label: "推广渠道" },
    ],
    toPayload: (form) => ({
      name: form.name,
      contentJson: { text: form.content },
      materialId: form.materialId || undefined,
      promotionChannelId: form.promotionChannelId || undefined,
    }),
  },
  strategies: {
    title: "超链策略",
    description: "配置账号池调度、发送节奏和失败处理。",
    endpoint: "/api/hyperlink/strategies",
    permissionKey: "marketing.hyperlink_strategies.manage",
    createLabel: "创建策略",
    empty: "创建发送节奏和风险控制策略。",
    icon: <GaugeIcon />,
    defaults: {
      name: "",
      maxQps: "10",
      concurrency: "10",
      retryLimit: "2",
      retryBackoffSeconds: "5",
      accountFailureThreshold: "3",
      accountCooldownSeconds: "300",
      noAccountAction: "wait",
      sendJitterMs: "0",
      enabled: "true",
    },
    fields: [
      commonName,
      {
        key: "maxQps",
        label: "单账号峰值 QPS",
        type: "number",
        required: true,
        help: "每个账号按顺序发送，限制该账号每秒最多提交的消息数。",
      },
      {
        key: "concurrency",
        label: "并发账号数",
        type: "number",
        required: true,
        help: "任务同时占用的账号数量。每个槽位持续使用同一账号，异常时才更换。",
      },
      {
        key: "retryLimit",
        label: "失败重试次数",
        type: "number",
        required: true,
      },
      {
        key: "retryBackoffSeconds",
        label: "重试间隔（秒）",
        type: "number",
        required: true,
      },
      {
        key: "accountFailureThreshold",
        label: "连续失败换号阈值",
        type: "number",
        required: true,
        help: "同一账号连续提交失败达到阈值后释放该账号，并从分组补入新账号。",
      },
      {
        key: "accountCooldownSeconds",
        label: "异常账号冷却（秒）",
        type: "number",
        required: true,
        help: "被换下的账号在冷却期间不会再次参与发送。",
      },
      {
        key: "noAccountAction",
        label: "没有可用账号时",
        type: "select",
        required: true,
        options: [
          { value: "wait", label: "等待账号并自动继续" },
          { value: "pause", label: "暂停任务" },
        ],
      },
      {
        key: "sendJitterMs",
        label: "发送随机延迟（毫秒）",
        type: "number",
        required: true,
      },
      {
        key: "enabled",
        label: "启用策略",
        type: "switch",
      },
    ],
    columns: [
      { key: "name", label: "策略" },
      {
        key: "accountSlots",
        label: "账号槽位",
        render: (row) => `${displayValue(row, "concurrency")} 个并发账号`,
      },
      {
        key: "accountPace",
        label: "单账号节奏",
        render: (row) => `峰值 ${displayValue(row, "maxQps")} QPS · 随机延迟 ${displayValue(row, "sendJitterMs")} ms`,
      },
      {
        key: "retryPolicy",
        label: "失败处理",
        render: (row) => `重试 ${displayValue(row, "retryLimit")} 次 · 连续失败 ${displayValue(row, "accountFailureThreshold")} 次换号`,
      },
      {
        key: "noAccountPolicy",
        label: "账号不足",
        render: (row) =>
          String(read(row, "noAccountAction")) === "pause"
            ? "自动暂停任务"
            : "等待并自动续发",
      },
    ],
    toPayload: (form) => ({
      name: form.name,
      maxQps: Number(form.maxQps),
      concurrency: Number(form.concurrency),
      retryLimit: Number(form.retryLimit),
      retryBackoffSeconds: Number(form.retryBackoffSeconds),
      accountFailureThreshold: Number(form.accountFailureThreshold),
      accountCooldownSeconds: Number(form.accountCooldownSeconds),
      noAccountAction: form.noAccountAction,
      sendJitterMs: Number(form.sendJitterMs),
      enabled: form.enabled === "true",
    }),
  },
};

export const HyperlinkTasksPage = () => (
  <HyperlinkResourcePage config={configs.tasks} />
);
export const HyperlinkDataPackagesPage = () => (
  <HyperlinkResourcePage config={configs.packages} />
);
export { HyperlinkTemplatesPage } from "./HyperlinkTemplatesPage";
export const HyperlinkStrategiesPage = () => (
  <HyperlinkResourcePage config={configs.strategies} />
);
