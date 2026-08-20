import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  BoldIcon,
  ChevronDownIcon,
  Code2Icon,
  EyeIcon,
  GripVerticalIcon,
  ImageIcon,
  ItalicIcon,
  PencilIcon,
  PlayIcon,
  PlusIcon,
  RefreshCwIcon,
  StrikethroughIcon,
  Trash2Icon,
  VideoIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { apiRequest, formatDateTime, unwrapList } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import {
  MessageTemplateButtonIcon,
  messageTemplateButtonLabel,
  type MessageTemplateButtonType,
} from "../components/message-template-buttons";
import { MessageTemplatePreview } from "../components/message-template-preview";
import {
  DrawerChoiceGroup,
  DrawerFormField,
  DrawerFormLayout,
  DrawerFormSection,
} from "../components/drawer-form";
import {
  ListPagination,
  ListTableCard,
  ListToolbar,
  StandardListPage,
  useClientPagination,
} from "../components/list-page";
import {
  Badge,
  Button,
  Drawer,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  EmptyState,
  IconButton,
  Input,
  SearchableSelect,
  SelectField,
  Spinner,
  Switch,
  Textarea,
  confirmAction,
  toast,
} from "../components/ui";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import { entityRowKey, snowflakeId } from "../lib/entity-identifiers";

type HeaderType = "none" | "text" | "image" | "video" | "document";
type ButtonType = MessageTemplateButtonType;
type TextRole = "body" | "header" | "footer" | "button";
type TemplateStatusFilter = "all" | "enabled" | "disabled";
type TemplateHeaderFilter = "all" | HeaderType;

type ButtonForm = {
  key: string;
  type: ButtonType;
  text: string;
  value: string;
  sectionTitle: string;
  rowsText: string;
};

type TemplateForm = {
  name: string;
  headerType: HeaderType;
  headerText: string;
  body: string;
  footer: string;
  materialId: string;
  enabled: boolean;
  buttons: ButtonForm[];
};

type TemplateRow = {
  id: string;
  readKey: string;
  name: string;
  contentJson: Record<string, unknown>;
  materialId: string;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
};

type RelatedRow = {
  id: string;
  name: string;
  type?: string;
  textRole?: TextRole;
  enabled?: boolean;
  countryCode?: string;
  contentJson?: Record<string, unknown>;
  fileName?: string;
  contentType?: string;
  hasFile?: boolean;
  previewPath?: string;
  sha256?: string;
  updatedAt?: string;
};

type HeaderOption = { value: HeaderType; label: string };
type ButtonOption = {
  value: ButtonType;
  label: string;
  limit: number;
  icon: ReactNode;
};

const HEADER_OPTIONS: HeaderOption[] = [
  { value: "none", label: "无" },
  { value: "image", label: "图片" },
  { value: "video", label: "视频" },
  { value: "document", label: "文档" },
];

const BUTTON_LIMIT = 3;
const BUTTON_OPTIONS: ButtonOption[] = [
  {
    value: "quick_reply",
    label: messageTemplateButtonLabel("quick_reply"),
    limit: 3,
    icon: <MessageTemplateButtonIcon type="quick_reply" className="size-5" />,
  },
  {
    value: "url",
    label: messageTemplateButtonLabel("url"),
    limit: 2,
    icon: <MessageTemplateButtonIcon type="url" className="size-5" />,
  },
  {
    value: "call",
    label: messageTemplateButtonLabel("call"),
    limit: 1,
    icon: <MessageTemplateButtonIcon type="call" className="size-5" />,
  },
  {
    value: "copy",
    label: messageTemplateButtonLabel("copy"),
    limit: 1,
    icon: <MessageTemplateButtonIcon type="copy" className="size-5" />,
  },
  {
    value: "single_select",
    label: messageTemplateButtonLabel("single_select"),
    limit: 1,
    icon: <MessageTemplateButtonIcon type="single_select" className="size-5" />,
  },
];

const blankForm = (): TemplateForm => ({
  name: "",
  headerType: "none",
  headerText: "",
  body: "",
  footer: "",
  materialId: "",
  enabled: true,
  buttons: [],
});

const read = (row: Record<string, unknown>, key: string) =>
  row[key] ??
  row[key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)];

const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

function normalizeTemplate(value: unknown): TemplateRow {
  const row = object(value);
  const id = snowflakeId(row, "id");
  return {
    id,
    readKey: entityRowKey(row, id, "hyperlink-template", String(row.name || "")),
    name: String(read(row, "name") || "未命名模板"),
    contentJson: object(read(row, "contentJson")),
    materialId: snowflakeId(row, "materialId", "material_id"),
    enabled: read(row, "enabled") !== false,
    createdAt: String(read(row, "createdAt") || ""),
    updatedAt: String(read(row, "updatedAt") || ""),
  };
}

function normalizeRelated(value: unknown): RelatedRow | null {
  const row = object(value);
  const id = snowflakeId(row, "id");
  if (!id) return null;
  return {
    id,
    name: String(read(row, "name") || id),
    type: String(read(row, "type") || ""),
    textRole: String(read(row, "textRole") || "body") as TextRole,
    enabled: read(row, "enabled") !== false,
    countryCode: String(read(row, "countryCode") || ""),
    contentJson: object(read(row, "contentJson")),
    fileName: String(read(row, "fileName") || ""),
    contentType: String(read(row, "contentType") || ""),
    hasFile: read(row, "hasFile") === true,
    previewPath: String(read(row, "previewPath") || ""),
    sha256: String(read(row, "sha256") || ""),
    updatedAt: String(read(row, "updatedAt") || ""),
  };
}

function buttonForm(value: unknown, index: number): ButtonForm {
  const button = object(value);
  const type = String(button.type || "quick_reply") as ButtonType;
  const sections = Array.isArray(button.sections) ? button.sections : [];
  const firstSection = object(sections[0]);
  const rows = Array.isArray(firstSection.rows) ? firstSection.rows : [];
  const valueByType =
    type === "url"
      ? button.url
      : type === "call"
        ? button.phone
        : type === "copy"
          ? button.copyText
          : button.id;
  return {
    key: `${Date.now()}-${index}-${Math.random()}`,
    type,
    text: String(button.text || ""),
    value: String(valueByType || "").replace(/^\+/, ""),
    sectionTitle: String(firstSection.title || "请选择"),
    rowsText: rows
      .map((rowValue) => {
        const row = object(rowValue);
        return [row.title, row.description].filter(Boolean).join("|");
      })
      .join("\n"),
  };
}

function formFromRow(row: TemplateRow): TemplateForm {
  const content = row.contentJson;
  const hasBody = content.body && typeof content.body === "object";
  const header = hasBody ? object(content.header) : {};
  const body = hasBody ? object(content.body) : { text: content.text || content.message };
  const footer = hasBody ? object(content.footer) : {};
  const headerType = String(header.type || "none") as HeaderType;
  return {
    name: row.name,
    headerType,
    headerText: String(header.text || ""),
    body: String(body.text || ""),
    footer: String(footer.text || ""),
    materialId: row.materialId,
    enabled: row.enabled,
    buttons: (Array.isArray(content.buttons) ? content.buttons : []).map(buttonForm),
  };
}

function rowsFromText(value: string) {
  return value
    .split("\n")
    .map((line, index) => {
      const [title, ...description] = line.split("|").map((part) => part.trim());
      return {
        id: `option_${index + 1}`,
        title: title || `选项 ${index + 1}`,
        description: description.join("|").slice(0, 120),
      };
    })
    .filter((row) => row.id && row.title);
}

function buttonPayload(button: ButtonForm, index: number) {
  const base = { type: button.type, text: button.text.trim() };
  if (button.type === "quick_reply")
    return { ...base, id: button.value.trim() || `reply_${index + 1}` };
  if (button.type === "url") return { ...base, url: button.value.trim() };
  if (button.type === "call")
    return { ...base, phone: button.value.replace(/\D/g, "") };
  if (button.type === "copy")
    return { ...base, copyText: button.value.trim() };
  return {
    ...base,
    sections: [
      {
        title: button.sectionTitle.trim() || "请选择",
        rows: rowsFromText(button.rowsText),
      },
    ],
  };
}

function contentPayload(form: TemplateForm) {
  const header: Record<string, unknown> = { type: form.headerType };
  if (form.headerType === "text") header.text = form.headerText.trim();
  return {
    version: 1,
    header,
    body: { text: form.body.trim() },
    footer: { text: form.footer.trim() },
    buttons: form.buttons.map(buttonPayload),
  };
}

function headerLabel(type: HeaderType) {
  return { none: "无页头", text: "文字", image: "图片", video: "视频", document: "文档" }[type];
}

function buttonLabel(type: ButtonType) {
  return messageTemplateButtonLabel(type);
}

function buttonIcon(type: ButtonType) {
  return BUTTON_OPTIONS.find((option) => option.value === type)?.icon;
}

function SortableButtonCard({
  button,
  index,
  onRemove,
  children,
}: {
  button: ButtonForm;
  index: number;
  onRemove: () => void;
  children: ReactNode;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: button.key });

  return (
    <article
      ref={setNodeRef}
      style={{
        transform: CSS.Translate.toString(transform),
        transition,
      }}
      className={
        isDragging
          ? "relative z-10 rounded-xl border border-primary/40 bg-card p-4 opacity-80 shadow-lg"
          : "rounded-xl border border-border bg-card p-4 shadow-sm transition-[border-color,box-shadow]"
      }
    >
      <div className="mb-4 flex min-w-0 items-center gap-2">
        <button
          type="button"
          aria-label={`拖动排序：${buttonLabel(button.type)}，当前位置 ${index + 1}`}
          className="flex size-7 touch-none cursor-grab items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 active:cursor-grabbing"
          {...attributes}
          {...listeners}
        >
          <GripVerticalIcon className="size-4" />
        </button>
        <span className="flex size-5 items-center justify-center text-muted-foreground [&_svg]:size-4">
          {buttonIcon(button.type)}
        </span>
        <span className="text-sm font-medium">{buttonLabel(button.type)}</span>
        <span className="text-xs text-muted-foreground">#{index + 1}</span>
        <IconButton
          label="删除按钮"
          className="ml-auto text-muted-foreground hover:text-destructive"
          onClick={onRemove}
        >
          <Trash2Icon />
        </IconButton>
      </div>
      <div className="grid min-w-0 gap-[var(--drawer-form-field-gap)]">
        {children}
      </div>
    </article>
  );
}

function materialOriginalText(item: RelatedRow | undefined) {
  return String(item?.contentJson?.originalText || "");
}

function materialPreviewUrl(item: RelatedRow | undefined) {
  if (!item?.previewPath) return "";
  const version = item.sha256 || item.updatedAt;
  return version
    ? `${item.previewPath}?v=${encodeURIComponent(version)}`
    : item.previewPath;
}

function MaterialOptionPreview({ material }: { material: RelatedRow }) {
  const url = materialPreviewUrl(material);
  if (material.type === "image" && url) {
    return (
      <img
        src={url}
        alt=""
        aria-hidden="true"
        loading="lazy"
        className="max-h-full max-w-full object-contain"
      />
    );
  }
  if (material.type === "video" && url) {
    return (
      <span className="relative flex size-full items-center justify-center">
        <video
          src={url}
          aria-hidden="true"
          muted
          playsInline
          preload="metadata"
          className="max-h-full max-w-full object-contain"
        />
        <span className="absolute inset-0 grid place-items-center text-white">
          <span className="grid size-7 place-items-center rounded-full bg-black/55 shadow-sm">
            <PlayIcon className="ml-0.5 size-3.5" fill="currentColor" />
          </span>
        </span>
      </span>
    );
  }
  return (
    <span className="grid size-full place-items-center text-muted-foreground">
      {material.type === "video" ? <VideoIcon className="size-5" /> : <ImageIcon className="size-5" />}
    </span>
  );
}

function textMaterialOptions(materials: RelatedRow[], role: TextRole) {
  return materials
    .filter((item) => item.type === "text" && item.textRole === role && item.enabled !== false)
    .map((item) => ({
      value: item.id,
      label: item.name,
      keywords: `${item.id} ${materialOriginalText(item)}`,
    }));
}

function TextMaterialPicker({
  materials,
  role,
  placeholder,
  onSelect,
  className,
}: {
  materials: RelatedRow[];
  role: TextRole;
  placeholder: string;
  onSelect: (text: string) => void;
  className?: string;
}) {
  const options = textMaterialOptions(materials, role);
  return (
    <SearchableSelect
      value=""
      options={options}
      className={className}
      placeholder={placeholder}
      searchPlaceholder={`搜索${placeholder.replace(/^选择/, "")}`}
      emptyText={`暂无可用的${placeholder.replace(/^选择/, "")}`}
      onValueChange={(value) => {
        const material = materials.find((item) => item.id === value);
        const text = materialOriginalText(material);
        if (text) onSelect(text);
      }}
    />
  );
}

function TemplatePreview({
  form,
  materials,
  compact = false,
}: {
  form: TemplateForm;
  materials: RelatedRow[];
  compact?: boolean;
}) {
  const material = materials.find((item) => item.id === form.materialId);
  return (
    <MessageTemplatePreview
      headerType={form.headerType}
      headerText={form.headerText}
      mediaUrl={materialPreviewUrl(material)}
      fileName={material?.fileName || material?.name || "document"}
      body={form.body}
      footer={form.footer}
      compact={compact}
      buttons={form.buttons.map((button) => ({
        id: button.key,
        type: button.type,
        text: button.text || buttonLabel(button.type),
        value: button.value,
      }))}
    />
  );
}

export function HyperlinkTemplatesPage() {
  const { can } = useAuth();
  const canManage = can("marketing.hyperlink_templates.manage");
  const [rows, setRows] = useState<TemplateRow[]>([]);
  const [materials, setMaterials] = useState<RelatedRow[]>([]);
  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState<TemplateStatusFilter>("all");
  const [headerFilter, setHeaderFilter] = useState<TemplateHeaderFilter>("all");
  const [loading, setLoading] = useState(true);
  const [previewing, setPreviewing] = useState<TemplateRow | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [editing, setEditing] = useState<TemplateRow | null>(null);
  const [form, setForm] = useState<TemplateForm>(blankForm);
  const [pending, setPending] = useState(false);
  const bodyRef = useRef<HTMLTextAreaElement | null>(null);
  const buttonSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [templatesPayload, materialsPayload] = await Promise.all([
        apiRequest("/api/hyperlink/templates?pageSize=100"),
        apiRequest("/api/materials?pageSize=100"),
      ]);
      setRows(unwrapList(templatesPayload).rows.map(normalizeTemplate));
      setMaterials(unwrapList(materialsPayload).rows.map(normalizeRelated).filter((item): item is RelatedRow => Boolean(item)));
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "超链模板加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const visible = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return rows.filter((row) => {
      const formValue = formFromRow(row);
      const matchesSearch = !search || `${row.name} ${row.id} ${row.contentJson.body ? JSON.stringify(row.contentJson.body) : ""}`.toLowerCase().includes(search);
      const matchesStatus = statusFilter === "all" || (statusFilter === "enabled" ? row.enabled : !row.enabled);
      const matchesHeader = headerFilter === "all" || formValue.headerType === headerFilter;
      return matchesSearch && matchesStatus && matchesHeader;
    });
  }, [headerFilter, keyword, rows, statusFilter]);
  const pagination = useClientPagination(visible, {
    resetKey: `${keyword}|${statusFilter}|${headerFilter}`,
  });

  function open(row?: TemplateRow) {
    setEditing(row || null);
    setForm(row ? formFromRow(row) : blankForm());
    setDrawer(true);
  }

  function updateButton(key: string, changes: Partial<ButtonForm>) {
    setForm((current) => ({ ...current, buttons: current.buttons.map((button) => button.key === key ? { ...button, ...changes } : button) }));
  }

  const buttonCounts = useMemo(
    () => form.buttons.reduce<Record<ButtonType, number>>(
      (counts, button) => ({ ...counts, [button.type]: counts[button.type] + 1 }),
      { quick_reply: 0, url: 0, call: 0, copy: 0, single_select: 0 },
    ),
    [form.buttons],
  );

  function buttonOptionDisabled(option: ButtonOption) {
    if (form.buttons.length >= BUTTON_LIMIT) return true;
    if (buttonCounts[option.value] >= option.limit) return true;
    if (option.value === "single_select") return form.buttons.length > 0;
    return buttonCounts.single_select > 0;
  }

  function addButton(type: ButtonType) {
    const option = BUTTON_OPTIONS.find((item) => item.value === type);
    if (!option || buttonOptionDisabled(option)) return;
    setForm((current) => ({
      ...current,
      buttons: [...current.buttons, {
        key: crypto.randomUUID(),
        type,
        text: "",
        value: "",
        sectionTitle: "请选择",
        rowsText: "",
      }],
    }));
  }

  function moveButton(event: DragEndEvent) {
    const activeKey = String(event.active.id);
    const targetKey = event.over ? String(event.over.id) : "";
    if (!targetKey || activeKey === targetKey) return;
    setForm((current) => {
      const from = current.buttons.findIndex((button) => button.key === activeKey);
      const to = current.buttons.findIndex((button) => button.key === targetKey);
      if (from < 0 || to < 0) return current;
      return { ...current, buttons: arrayMove(current.buttons, from, to) };
    });
  }

  function wrapBody(prefix: string, suffix = prefix) {
    const textarea = bodyRef.current;
    const start = textarea?.selectionStart ?? form.body.length;
    const end = textarea?.selectionEnd ?? start;
    const selected = form.body.slice(start, end);
    const next = `${form.body.slice(0, start)}${prefix}${selected}${suffix}${form.body.slice(end)}`;
    setForm((current) => ({ ...current, body: next }));
    window.requestAnimationFrame(() => {
      const cursorStart = start + prefix.length;
      const cursorEnd = cursorStart + selected.length;
      bodyRef.current?.focus();
      bodyRef.current?.setSelectionRange(cursorStart, cursorEnd);
    });
  }

  function insertVariable() {
    const textarea = bodyRef.current;
    const start = textarea?.selectionStart ?? form.body.length;
    const next = `${form.body.slice(0, start)}{{name}}${form.body.slice(start)}`;
    setForm((current) => ({ ...current, body: next }));
    window.requestAnimationFrame(() => {
      bodyRef.current?.focus();
      bodyRef.current?.setSelectionRange(start + 2, start + 6);
    });
  }

  function validateForm() {
    if (!form.name.trim()) return "请输入模板名称";
    if (!form.body.trim()) return "请输入正文";
    if (form.headerType === "text" && !form.headerText.trim()) return "请输入文字页头";
    if (["image", "video", "document"].includes(form.headerType) && !form.materialId) return "请选择已上传的素材";
    if (form.buttons.length > BUTTON_LIMIT) return `按钮最多${BUTTON_LIMIT}个`;
    for (const option of BUTTON_OPTIONS) {
      if (buttonCounts[option.value] > option.limit) return `${option.label}最多${option.limit}个`;
    }
    if (buttonCounts.single_select && form.buttons.length !== 1) return "单选菜单不能与其他按钮混用";
    if (form.buttons.some((button) => !button.text.trim())) return "请填写按钮文本";
    if (new Set(form.buttons.map((button) => button.text.trim().toLowerCase())).size !== form.buttons.length) return "按钮文本不能重复";
    if (form.buttons.some((button) => ["url", "call", "copy"].includes(button.type) && !button.value.trim())) return "请补全按钮动作内容";
    if (form.buttons.some((button) => button.type === "single_select" && !rowsFromText(button.rowsText).length)) return "单选菜单至少需要一个选项";
    return "";
  }

  async function save() {
    const error = validateForm();
    if (error) { toast.error(error); return; }
    setPending(true);
    try {
      await apiRequest(editing ? `/api/hyperlink/templates/${editing.id}` : "/api/hyperlink/templates", {
        method: editing ? "PATCH" : "POST",
        body: JSON.stringify({
          name: form.name.trim(),
          contentJson: contentPayload(form),
          materialId: form.materialId || null,
          enabled: form.enabled,
        }),
      });
      setDrawer(false);
      toast.success(editing ? "模板已更新" : "模板已创建");
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setPending(false);
    }
  }

  async function remove(row: TemplateRow) {
    if (!(await confirmAction({ title: `删除“${row.name}”？`, description: "删除后无法恢复；仍被任务使用的模板不能删除。", confirmText: "确认删除", destructive: true }))) return;
    try {
      await apiRequest(`/api/hyperlink/templates/${row.id}`, { method: "DELETE" });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "删除失败");
    }
  }

  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{ value: keyword, onChange: setKeyword, placeholder: "搜索模板名称、正文或 ID" }}
        filters={
          <>
            <SelectField
              value={statusFilter}
              onValueChange={(value) => setStatusFilter(value as TemplateStatusFilter)}
              ariaLabel="模板状态"
              className="w-32"
              options={[
                { value: "all", label: "全部状态" },
                { value: "enabled", label: "可用" },
                { value: "disabled", label: "已停用" },
              ]}
            />
            <SelectField
              value={headerFilter}
              onValueChange={(value) => setHeaderFilter(value as TemplateHeaderFilter)}
              ariaLabel="页头类型"
              className="w-32"
              options={[
                { value: "all", label: "全部页头" },
                { value: "none", label: "无页头" },
                { value: "text", label: "文字页头" },
                { value: "image", label: "图片页头" },
                { value: "video", label: "视频页头" },
                { value: "document", label: "文档页头" },
              ]}
            />
          </>
        }
        meta={`${visible.length} 个模板`}
        actions={<><Button variant="outline" onClick={() => void load()}><RefreshCwIcon />刷新</Button>{canManage ? <Button onClick={() => open()}><PlusIcon />创建模板</Button> : null}</>}
      />
      <ListPagination
        page={pagination.page}
        pageSize={pagination.pageSize}
        total={pagination.total}
        disabled={loading}
        onPageChange={pagination.setPage}
        onPageSizeChange={pagination.setPageSize}
      />
      <ListTableCard>
        {loading ? <div className="loading-state"><Spinner /></div> : visible.length ? (
          <div className="grid grid-cols-1 gap-4 bg-muted/[0.18] p-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {pagination.rows.map((row) => {
              const formValue = formFromRow(row);
              const material = materials.find((item) => item.id === row.materialId);
              const structure = [
                headerLabel(formValue.headerType),
                "正文",
                formValue.footer ? "页脚" : "",
                formValue.buttons.length ? `${formValue.buttons.length} 个按钮` : "",
              ].filter(Boolean).join(" · ");
              return (
                <article key={row.readKey} className="group min-w-0 overflow-hidden rounded-xl border border-border bg-card shadow-xs transition-all hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md">
                  <div className="relative flex min-h-[390px] items-center justify-center overflow-hidden bg-muted/30 p-4">
                    <div className="pointer-events-none w-full">
                      <TemplatePreview form={formValue} materials={materials} compact />
                    </div>
                    <button
                      type="button"
                      className="absolute inset-0 cursor-default"
                      aria-label={`预览${row.name}`}
                      onClick={() => setPreviewing(row)}
                    />
                  </div>
                  <div className="border-t border-border">
                    <button
                    type="button"
                    className="grid w-full cursor-default gap-2.5 p-3 text-left transition-colors hover:bg-muted/25"
                    onClick={() => canManage ? open(row) : setPreviewing(row)}
                  >
                    <div className="flex min-w-0 items-start gap-2">
                      <div className="min-w-0 flex-1">
                        <strong className="block truncate text-sm" title={row.name}>{row.name}</strong>
                        <span className="mt-0.5 block truncate text-xs text-muted-foreground" title={row.id}>{row.id}</span>
                      </div>
                      <Badge tone={row.enabled ? "success" : "neutral"}>{row.enabled ? "可用" : "已停用"}</Badge>
                    </div>
                    <p className="truncate text-xs text-muted-foreground" title={structure}>{structure}</p>
                    <div className="flex min-w-0 items-center justify-between gap-3 text-xs text-muted-foreground">
                      <span className="min-w-0 flex-1 truncate" title={material?.name || "未关联素材"}>{material?.name || "未关联素材"}</span>
                      <span className="shrink-0">{formatDateTime(row.updatedAt || row.createdAt).split(" ")[0]}</span>
                    </div>
                    </button>
                    <div className="flex items-center justify-end gap-1 border-t border-border/70 px-3 py-2">
                      <IconButton label="预览" onClick={() => setPreviewing(row)}><EyeIcon size={16} /></IconButton>
                      {canManage ? <><IconButton label="编辑" onClick={() => open(row)}><PencilIcon size={16} /></IconButton><IconButton label="删除" className="text-destructive" onClick={() => void remove(row)}><Trash2Icon size={16} /></IconButton></> : null}
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        ) : <EmptyState title="暂无超链模板" description="创建一套正文、媒体和按钮组合后即可用于群发任务。" />}
      </ListTableCard>

      {previewing ? (
        <Dialog open onOpenChange={(openValue) => !openValue && setPreviewing(null)}>
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>{previewing.name}</DialogTitle>
              <DialogDescription>{previewing.id}</DialogDescription>
            </DialogHeader>
            <DialogBody className="rounded-xl bg-muted/25 p-4">
              <TemplatePreview form={formFromRow(previewing)} materials={materials} />
            </DialogBody>
          </DialogContent>
        </Dialog>
      ) : null}

      <Drawer
        wide
        open={drawer}
        onClose={() => !pending && setDrawer(false)}
        title={editing ? "编辑超链模板" : "创建超链模板"}
        footer={
          <>
            <Button variant="outline" onClick={() => setDrawer(false)}>取消</Button>
            <Button disabled={pending || Boolean(validateForm())} onClick={() => void save()}>
              {pending ? <Spinner /> : null}保存
            </Button>
          </>
        }
      >
        <DrawerFormLayout
          aside={
            <TemplatePreview form={form} materials={materials} />
          }
        >
          <DrawerFormSection title="基础信息">
            <DrawerFormField label="模板名称" htmlFor="hyperlink-template-name" required>
              <Input
                id="hyperlink-template-name"
                value={form.name}
                maxLength={120}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                placeholder="例如：新品活动通知"
              />
            </DrawerFormField>
            <DrawerFormField
              label="模板状态"
              hint="停用后不可用于创建新的超链任务，已有关联数据不会被删除。"
            >
              <div className="flex min-h-8 flex-wrap items-center gap-x-3 gap-y-1">
                <Switch
                  checked={form.enabled}
                  onCheckedChange={(checked) => setForm({ ...form, enabled: checked })}
                />
                <span className="text-sm">{form.enabled ? "启用" : "停用"}</span>
              </div>
            </DrawerFormField>
          </DrawerFormSection>

          <DrawerFormSection title="页头">
            <DrawerFormField label="媒体类型">
              <DrawerChoiceGroup
                label="媒体类型"
                options={HEADER_OPTIONS}
                value={form.headerType === "text" ? "none" : form.headerType}
                onChange={(nextValue) => {
                  const value = nextValue as HeaderType;
                  setForm({
                    ...form,
                    headerType: value === "none" && form.headerText.trim() ? "text" : value,
                    materialId: materials.some(
                      (item) => item.id === form.materialId && item.type === value,
                    ) ? form.materialId : "",
                  });
                }}
              />
            </DrawerFormField>
            {!["image", "video", "document"].includes(form.headerType) ? (
              <DrawerFormField
                label="页头内容"
                htmlFor="hyperlink-template-header"
                meta={`${form.headerText.length}/60`}
                required={form.headerType === "text"}
              >
                <div className="grid gap-2 xl:grid-cols-[minmax(0,1fr)_200px]">
                  <Input
                    id="hyperlink-template-header"
                    value={form.headerText}
                    maxLength={60}
                    onChange={(event) => setForm({
                      ...form,
                      headerText: event.target.value,
                      headerType: event.target.value.trim() ? "text" : "none",
                    })}
                    placeholder="输入页头内容"
                  />
                  <TextMaterialPicker
                    materials={materials}
                    role="header"
                    placeholder="选择页头素材"
                    onSelect={(text) => setForm((current) => ({
                      ...current,
                      headerText: text,
                      headerType: "text",
                      materialId: "",
                    }))}
                  />
                </div>
              </DrawerFormField>
            ) : null}
            {["image", "video", "document"].includes(form.headerType) ? (
              <DrawerFormField label="选择素材" required>
                <SearchableSelect
                  value={form.materialId}
                  onValueChange={(value) => setForm({ ...form, materialId: value })}
                  options={materials
                    .filter((item) => item.type === form.headerType && item.hasFile)
                    .map((item) => ({
                      value: item.id,
                      label: item.name,
                      keywords: `${item.id} ${item.fileName || ""}`,
                      preview: ["image", "video"].includes(form.headerType)
                        ? <MaterialOptionPreview material={item} />
                        : undefined,
                    }))}
                  placeholder={`选择${headerLabel(form.headerType) as string}`}
                />
              </DrawerFormField>
            ) : null}
          </DrawerFormSection>

          <DrawerFormSection title="正文">
            <DrawerFormField
              label="正文内容"
              htmlFor="hyperlink-template-body"
              align="start"
              meta={`${form.body.length}/4096`}
              required
            >
              <div className="overflow-hidden rounded-lg border border-input bg-background focus-within:ring-3 focus-within:ring-primary/20">
                <div className="flex min-w-0 flex-wrap items-center gap-1 border-b border-input bg-muted/25 p-1.5">
                  <IconButton label="加粗" onClick={() => wrapBody("*")}><BoldIcon /></IconButton>
                  <IconButton label="斜体" onClick={() => wrapBody("_")}><ItalicIcon /></IconButton>
                  <IconButton label="删除线" onClick={() => wrapBody("~")}><StrikethroughIcon /></IconButton>
                  <IconButton label="等宽代码" onClick={() => wrapBody("```", "```")}><Code2Icon /></IconButton>
                  <Button variant="ghost" size="sm" className="ml-auto text-primary" onClick={insertVariable}>
                    <PlusIcon />变量
                  </Button>
                  <TextMaterialPicker
                    materials={materials}
                    role="body"
                    className="h-8 w-44"
                    placeholder="选择正文素材"
                    onSelect={(text) => setForm((current) => ({ ...current, body: text }))}
                  />
                </div>
                <Textarea
                  ref={bodyRef}
                  id="hyperlink-template-body"
                  rows={8}
                  maxLength={4096}
                  className="max-h-80 min-h-44 resize-y rounded-none border-0 focus-visible:ring-0"
                  value={form.body}
                  onChange={(event) => setForm({ ...form, body: event.target.value })}
                  placeholder="输入正文内容"
                />
              </div>
            </DrawerFormField>
          </DrawerFormSection>

          <DrawerFormSection title="页脚">
            <DrawerFormField
              label="页脚内容"
              htmlFor="hyperlink-template-footer"
              meta={`${form.footer.length}/60`}
            >
              <div className="grid gap-2 xl:grid-cols-[minmax(0,1fr)_200px]">
                <Input
                  id="hyperlink-template-footer"
                  maxLength={60}
                  value={form.footer}
                  onChange={(event) => setForm({ ...form, footer: event.target.value })}
                  placeholder="输入页脚内容"
                />
                <TextMaterialPicker
                  materials={materials}
                  role="footer"
                  placeholder="选择页脚素材"
                  onSelect={(text) => setForm((current) => ({ ...current, footer: text }))}
                />
              </div>
            </DrawerFormField>
          </DrawerFormSection>

          <DrawerFormSection title="按钮">
            <DrawerFormField
              label="按钮内容"
              hint="最多添加 3 个；单选菜单不能与其他按钮混用。拖动按钮卡片左上角的手柄可以调整顺序。"
            >
              <div className="flex min-h-8 items-center justify-end">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="outline"
                      disabled={form.buttons.length >= BUTTON_LIMIT || buttonCounts.single_select > 0}
                    >
                      <PlusIcon />添加按钮 ({form.buttons.length}/{BUTTON_LIMIT})
                      <ChevronDownIcon />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-72 p-2">
                    {BUTTON_OPTIONS.map((option) => (
                      <DropdownMenuItem
                        key={option.value}
                        disabled={buttonOptionDisabled(option)}
                        className="gap-3 px-3 py-2.5"
                        onClick={() => addButton(option.value)}
                      >
                        <span className="flex size-6 shrink-0 items-center justify-center text-foreground">
                          {option.icon}
                        </span>
                        <span>{option.label}</span>
                        <span className="ml-auto text-xs text-muted-foreground">
                          {buttonCounts[option.value]}/{option.limit}
                        </span>
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </DrawerFormField>
            {form.buttons.length ? (
              <DndContext
                sensors={buttonSensors}
                collisionDetection={closestCenter}
                onDragEnd={moveButton}
              >
                <SortableContext
                  items={form.buttons.map((button) => button.key)}
                  strategy={verticalListSortingStrategy}
                >
                  <div className="grid gap-3">
                    {form.buttons.map((button, index) => (
                      <SortableButtonCard
                        key={button.key}
                        button={button}
                        index={index}
                        onRemove={() => setForm((current) => ({
                          ...current,
                          buttons: current.buttons.filter((item) => item.key !== button.key),
                        }))}
                      >
                        <DrawerFormField
                          label="按钮文本"
                          htmlFor={`hyperlink-button-text-${button.key}`}
                          required
                        >
                          <div className="grid gap-2 xl:grid-cols-[minmax(0,1fr)_200px]">
                            <Input
                              id={`hyperlink-button-text-${button.key}`}
                              maxLength={25}
                              value={button.text}
                              onChange={(event) => updateButton(button.key, { text: event.target.value })}
                            />
                            <TextMaterialPicker
                              materials={materials}
                              role="button"
                              placeholder="选择按钮素材"
                              onSelect={(text) => updateButton(button.key, { text })}
                            />
                          </div>
                        </DrawerFormField>
                        {button.type === "single_select" ? (
                          <>
                            <DrawerFormField
                              label="菜单标题"
                              htmlFor={`hyperlink-button-section-${button.key}`}
                            >
                              <Input
                                id={`hyperlink-button-section-${button.key}`}
                                value={button.sectionTitle}
                                onChange={(event) => updateButton(button.key, { sectionTitle: event.target.value })}
                              />
                            </DrawerFormField>
                            <DrawerFormField
                              label="菜单选项"
                              htmlFor={`hyperlink-button-rows-${button.key}`}
                              align="start"
                              hint="每行一个选项，格式：标题|说明"
                              required
                            >
                              <Textarea
                                id={`hyperlink-button-rows-${button.key}`}
                                rows={6}
                                value={button.rowsText}
                                onChange={(event) => updateButton(button.key, { rowsText: event.target.value })}
                                placeholder={"产品 A|查看产品 A\n产品 B|查看产品 B"}
                              />
                            </DrawerFormField>
                          </>
                        ) : ["url", "call", "copy"].includes(button.type) ? (
                          <DrawerFormField
                            label={button.type === "url" ? "链接地址" : button.type === "call" ? "电话号码" : "复制内容"}
                            htmlFor={`hyperlink-button-value-${button.key}`}
                            required
                          >
                            <Input
                              id={`hyperlink-button-value-${button.key}`}
                              value={button.value}
                              onChange={(event) => updateButton(button.key, {
                                value: button.type === "call" ? event.target.value.replace(/\D/g, "") : event.target.value,
                              })}
                              placeholder={button.type === "url" ? "https://" : button.type === "call" ? "8613800000000" : ""}
                            />
                          </DrawerFormField>
                        ) : null}
                      </SortableButtonCard>
                    ))}
                  </div>
                </SortableContext>
              </DndContext>
            ) : null}
          </DrawerFormSection>
        </DrawerFormLayout>
      </Drawer>
    </StandardListPage>
  );
}
