import {
  ArchiveIcon,
  BoxesIcon,
  FileStackIcon,
  GaugeIcon,
  ImageIcon,
  LoaderCircleIcon,
  PauseIcon,
  PencilIcon,
  PlayIcon,
  PlusIcon,
  RefreshCwIcon,
  Trash2Icon,
  WorkflowIcon,
  XCircleIcon,
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
  ListTableCard,
  ListToolbar,
  StandardListPage,
} from "../components/list-page";
import {
  Badge,
  Button,
  Drawer,
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
  Textarea,
  confirmAction,
  toast,
} from "../components/ui";

type AnyRow = Record<string, unknown> & { id: string };
type OptionSource =
  | "materials"
  | "promotionChannels"
  | "templates"
  | "strategies"
  | "packages"
  | "accounts";
type FieldConfig = {
  key: string;
  label: string;
  type?: "text" | "number" | "textarea" | "select";
  required?: boolean;
  placeholder?: string;
  options?: Array<{ value: string; label: string }>;
  optionSource?: OptionSource;
  multiple?: boolean;
};
type Column = {
  key: string;
  label: string;
  render?: (row: AnyRow) => ReactNode;
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
};
const read = (row: Record<string, unknown>, key: string) =>
  row[key] ??
  row[key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)] ??
  "";
const displayValue = (row: Record<string, unknown>, key: string) => {
  const value = read(row, key);
  return value === "" || value == null ? "-" : String(value);
};
function normalize(input: unknown): AnyRow {
  const source = input as Record<string, unknown>;
  return {
    ...source,
    id: String(source.publicId || source.public_id || source.id || ""),
  };
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
  if (["paused", "draft", "pending"].includes(status))
    return (
      <Badge tone="warning">{status === "paused" ? "已暂停" : "准备中"}</Badge>
    );
  return <Badge tone="neutral">{status}</Badge>;
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
const optionEndpoints: Record<OptionSource, string> = {
  materials: "/api/hyperlink/materials",
  promotionChannels: "/api/promotion/channels",
  templates: "/api/hyperlink/templates",
  strategies: "/api/hyperlink/strategies",
  packages: "/api/hyperlink/data-packages",
  accounts: "/api/personal-accounts?pageSize=100",
};
function optionLabel(source: OptionSource, row: Record<string, unknown>) {
  const name = String(
    read(row, "name") ||
      read(row, "displayName") ||
      read(row, "phone") ||
      read(row, "id"),
  );
  if (source === "accounts")
    return `${name}${read(row, "phone") && read(row, "phone") !== name ? ` · ${String(read(row, "phone"))}` : ""}${read(row, "status") ? ` · ${String(read(row, "status"))}` : ""}`;
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
  const [drawer, setDrawer] = useState(false);
  const [editing, setEditing] = useState<AnyRow | null>(null);
  const [form, setForm] = useState<Record<string, string>>(config.defaults);
  const [dynamicOptions, setDynamicOptions] = useState<
    Record<string, Array<{ value: string; label: string }>>
  >({});
  const [pending, setPending] = useState(false);
  const [operation, setOperation] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await apiRequest(`${config.endpoint}?pageSize=100`);
      setRows(unwrapList<unknown>(payload).rows.map(normalize));
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [config.endpoint]);
  useEffect(() => {
    void load();
  }, [load]);
  const visible = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return search
      ? rows.filter((row) =>
          Object.values(row).some((value) =>
            String(value || "")
              .toLowerCase()
              .includes(search),
          ),
        )
      : rows;
  }, [keyword, rows]);
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
              .rows.filter(
                (row) => source !== "accounts" || row.enabled !== false,
              )
              .map((row) => ({
                value: String(row.publicId || row.id || ""),
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
                  : String(read(row, item.key) ?? ""),
            ]),
          )
        : config.defaults,
    );
    setDrawer(true);
  }
  async function save() {
    if (config.fields.some((item) => item.required && !form[item.key]?.trim()))
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
    if (
      !(await confirmAction({
        title: `归档“${String(read(row, "name"))}”？`,
        description: "归档后该资源将不再用于新任务。",
        confirmText: "确认归档",
      }))
    )
      return;
    try {
      await apiRequest(`${config.endpoint}/${row.id}`, { method: "DELETE" });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "归档失败");
    }
  }
  async function taskAction(row: AnyRow, action: string) {
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
  function rowActions(row: AnyRow) {
    if (!canManage) return null;
    const taskStatus = String(read(row, "status"));
    const canEdit =
      !config.taskActions || ["draft", "paused"].includes(taskStatus);
    const canStart =
      config.taskActions && ["draft", "paused"].includes(taskStatus);
    const canPause = config.taskActions && taskStatus === "running";
    const canCancel =
      config.taskActions && ["draft", "paused", "running"].includes(taskStatus);
    return (
      <div className="flex items-center justify-end gap-1">
        {canStart ? (
          <IconButton
            label="开始"
            disabled={Boolean(operation)}
            onClick={() => void taskAction(row, "start")}
          >
            <PlayIcon size={16} />
          </IconButton>
        ) : null}
        {canPause ? (
          <IconButton
            label="暂停"
            disabled={Boolean(operation)}
            onClick={() => void taskAction(row, "pause")}
          >
            <PauseIcon size={16} />
          </IconButton>
        ) : null}
        {canCancel ? (
          <IconButton
            label="取消"
            disabled={Boolean(operation)}
            onClick={() => void taskAction(row, "cancel")}
          >
            {operation.startsWith(row.id) ? (
              <LoaderCircleIcon className="spin" size={16} />
            ) : (
              <XCircleIcon size={16} />
            )}
          </IconButton>
        ) : null}
        {canEdit ? (
          <IconButton label="编辑" onClick={() => open(row)}>
            <PencilIcon size={16} />
          </IconButton>
        ) : null}
        <IconButton
          className="text-destructive"
          label="归档"
          onClick={() => void remove(row)}
        >
          <Trash2Icon size={16} />
        </IconButton>
      </div>
    );
  }
  return (
    <StandardListPage>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: `搜索${config.title}`,
        }}
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
      <ListTableCard>
        {loading ? (
          <div className="loading-state">
            <Spinner />
          </div>
        ) : visible.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                {config.columns.map((column) => (
                  <TableHead key={column.key}>{column.label}</TableHead>
                ))}
                <TableHead>更新时间</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((row) => (
                <TableRow key={row.id}>
                  {config.columns.map((column) => (
                    <TableCell key={column.key}>
                      {column.render
                        ? column.render(row)
                        : displayValue(row, column.key)}
                    </TableCell>
                  ))}
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(
                      String(read(row, "updatedAt") || read(row, "createdAt")),
                    )}
                  </TableCell>
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
        description="保存后立即同步到超链营销资源库。"
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
              <span>{item.label}</span>
              {item.type === "textarea" ? (
                <Textarea
                  rows={item.key === "recipients" ? 9 : 5}
                  value={form[item.key] || ""}
                  onChange={(e) =>
                    setForm({ ...form, [item.key]: e.target.value })
                  }
                  placeholder={item.placeholder}
                />
              ) : item.type === "select" ? (
                item.multiple ? (
                  <MultiSelect
                    className="w-full"
                    value={(form[item.key] || "").split(",").filter(Boolean)}
                    onValueChange={(values) =>
                      setForm({ ...form, [item.key]: values.join(",") })
                    }
                    placeholder={item.required ? "请选择" : "不绑定"}
                    options={item.options || dynamicOptions[item.key] || []}
                  />
                ) : (
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
                )
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
              {item.multiple ? (
                <small className="field-help">
                  可直接勾选多个账号，无需组合键。
                </small>
              ) : null}
            </label>
          ))}
        </div>
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
    empty: "选择模板、策略、数据包和发送账号创建任务。",
    icon: <WorkflowIcon />,
    taskActions: true,
    defaults: {
      name: "",
      templateId: "",
      strategyId: "",
      dataPackageId: "",
      accountIds: "",
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
        key: "accountIds",
        label: "发送账号",
        type: "select",
        optionSource: "accounts",
        multiple: true,
        required: true,
      },
      {
        key: "channel",
        label: "任务类型",
        type: "select",
        options: [{ value: "hyperlink", label: "超链营销" }],
      },
    ],
    columns: [
      { key: "name", label: "任务" },
      {
        key: "status",
        label: "状态",
        render: (row) => statusBadge(read(row, "status")),
      },
      { key: "totalCount", label: "目标数" },
      {
        key: "sentCount",
        label: "单勾",
        render: (row) =>
          Number(read(row, "sentCount") || 0) +
          Number(read(row, "deliveredCount") || 0),
      },
      { key: "deliveredCount", label: "双勾" },
      { key: "failedCount", label: "失败" },
    ],
    toPayload: (form) => ({
      name: form.name,
      templateId: form.templateId,
      strategyId: form.strategyId,
      dataPackageId: form.dataPackageId,
      accountIds: form.accountIds
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
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
                return { phone, ...(countryCode ? { countryCode } : {}) };
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
        label: "关联素材（可选）",
        type: "select",
        optionSource: "materials",
      },
      {
        key: "promotionChannelId",
        label: "关联推广渠道（可选）",
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
    description: "配置每账号 QPS、并发、批次与失败重试规则。",
    endpoint: "/api/hyperlink/strategies",
    permissionKey: "marketing.hyperlink_strategies.manage",
    createLabel: "创建策略",
    empty: "创建发送节奏和风险控制策略。",
    icon: <GaugeIcon />,
    defaults: {
      name: "",
      maxQps: "10",
      concurrency: "10",
      batchSize: "100",
      retryLimit: "2",
    },
    fields: [
      commonName,
      {
        key: "maxQps",
        label: "单账号峰值 QPS",
        type: "number",
        required: true,
      },
      {
        key: "concurrency",
        label: "账号内并发",
        type: "number",
        required: true,
      },
      { key: "batchSize", label: "领取批次", type: "number", required: true },
      {
        key: "retryLimit",
        label: "失败重试次数",
        type: "number",
        required: true,
      },
    ],
    columns: [
      { key: "name", label: "策略" },
      { key: "maxQps", label: "QPS" },
      { key: "concurrency", label: "并发" },
      { key: "batchSize", label: "批次" },
      { key: "retryLimit", label: "重试" },
    ],
    toPayload: (form) => ({
      name: form.name,
      maxQps: Number(form.maxQps),
      concurrency: Number(form.concurrency),
      batchSize: Number(form.batchSize),
      retryLimit: Number(form.retryLimit),
    }),
  },
  materials: {
    title: "素材库",
    description: "统一管理超链营销使用的图片、视频、链接和文字素材。",
    endpoint: "/api/hyperlink/materials",
    permissionKey: "marketing.materials.manage",
    createLabel: "添加素材",
    empty: "添加素材后可以绑定到超链模板。",
    icon: <ImageIcon />,
    defaults: { name: "", type: "image", content: "" },
    fields: [
      commonName,
      {
        key: "type",
        label: "素材类型",
        type: "select",
        options: [
          { value: "image", label: "图片" },
          { value: "video", label: "视频" },
          { value: "document", label: "文档" },
          { value: "link", label: "链接" },
          { value: "text", label: "文字" },
        ],
      },
      {
        key: "content",
        label: "素材地址或内容",
        type: "textarea",
        required: true,
      },
    ],
    columns: [
      { key: "name", label: "素材" },
      {
        key: "type",
        label: "类型",
        render: (row) => <Badge>{String(read(row, "type"))}</Badge>,
      },
      {
        key: "contentJson",
        label: "内容",
        render: (row) => (
          <div className="truncate-cell">
            {jsonText(read(row, "contentJson"))}
          </div>
        ),
      },
    ],
    toPayload: (form) => ({
      name: form.name,
      type: form.type,
      contentJson: { content: form.content },
    }),
  },
};

export const HyperlinkTasksPage = () => (
  <HyperlinkResourcePage config={configs.tasks} />
);
export const HyperlinkDataPackagesPage = () => (
  <HyperlinkResourcePage config={configs.packages} />
);
export const HyperlinkTemplatesPage = () => (
  <HyperlinkResourcePage config={configs.templates} />
);
export const HyperlinkStrategiesPage = () => (
  <HyperlinkResourcePage config={configs.strategies} />
);
export const HyperlinkMaterialsPage = () => (
  <HyperlinkResourcePage config={configs.materials} />
);
