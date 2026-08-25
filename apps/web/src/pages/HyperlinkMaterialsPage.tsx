import {
  AudioLinesIcon,
  ContactIcon,
  DownloadIcon,
  EyeIcon,
  FileTextIcon,
  FilmIcon,
  ImageIcon,
  PencilIcon,
  PlayIcon,
  PlusIcon,
  RefreshCwIcon,
  StickerIcon,
  Trash2Icon,
  TypeIcon,
  UploadCloudIcon,
  VideoIcon,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiDownload, apiRequest, formatDateTime, unwrapList } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EntityStatusIndicator } from "../components/entity-primary-cell";
import { DrawerFieldLabel } from "../components/drawer-form";
import {
  ListPagination,
  ListTableCard,
  ListToolbar,
  StandardListPage,
} from "../components/list-page";
import {
  Badge,
  Button,
  Checkbox,
  Drawer,
  EmptyState,
  IconButton,
  Input,
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
import { cn, formatPhoneDisplay } from "../lib/utils";

type MaterialType =
  | "image"
  | "text"
  | "video"
  | "audio"
  | "contact"
  | "document"
  | "gif"
  | "sticker";

type StatusFilter = "all" | "enabled" | "disabled" | "missing";
type TextRole = "body" | "header" | "footer" | "button";
type TextRoleFilter = "all" | TextRole;

type MaterialDefinition = {
  value: MaterialType;
  label: string;
  icon: LucideIcon;
  binary?: boolean;
  accept?: string;
  limit: string;
};

type MaterialRow = {
  id: string;
  readKey: string;
  name: string;
  type: MaterialType;
  textRole: TextRole | null;
  contentJson: Record<string, unknown>;
  fileName: string;
  contentType: string;
  size: number;
  sha256: string;
  hasFile: boolean;
  previewPath: string;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
};

type MaterialForm = {
  name: string;
  type: MaterialType;
  textRole: TextRole;
  originalText: string;
  translatedText: string;
  contactName: string;
  contactPhone: string;
  file: File | null;
  enabled: boolean;
};

type BatchNamingMode = "filename" | "prefix" | "sequence";
type BatchUploadStatus = "ready" | "uploading" | "success" | "failed";

type BatchUploadItem = {
  key: string;
  file: File;
  fileBaseName: string;
  name: string;
  status: BatchUploadStatus;
  error: string;
};

const MATERIAL_TYPES: MaterialDefinition[] = [
  { value: "image", label: "图片", icon: ImageIcon, binary: true, accept: "image/jpeg,image/png,image/webp,image/avif", limit: "最大 8 MB" },
  { value: "text", label: "文本", icon: TypeIcon, limit: "" },
  { value: "video", label: "视频", icon: VideoIcon, binary: true, accept: "video/mp4,video/quicktime,video/webm", limit: "最大 64 MB" },
  { value: "audio", label: "语音", icon: AudioLinesIcon, binary: true, accept: "audio/mpeg,audio/mp4,audio/ogg,audio/wav,audio/flac", limit: "最大 16 MB" },
  { value: "contact", label: "名片", icon: ContactIcon, limit: "" },
  { value: "document", label: "文件", icon: FileTextIcon, binary: true, accept: ".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.zip", limit: "最大 64 MB" },
  { value: "gif", label: "GIF", icon: FilmIcon, binary: true, accept: "image/gif", limit: "最大 16 MB" },
  { value: "sticker", label: "贴纸", icon: StickerIcon, binary: true, accept: "image/webp", limit: "WebP，最大 1 MB" },
];

const TEXT_ROLE_OPTIONS: Array<{ value: TextRole; label: string; maxLength: number; multiline: boolean }> = [
  { value: "body", label: "正文", maxLength: 4096, multiline: true },
  { value: "header", label: "页头", maxLength: 60, multiline: false },
  { value: "footer", label: "页脚", maxLength: 60, multiline: false },
  { value: "button", label: "按钮", maxLength: 25, multiline: false },
];

const TEXT_ROLE_FILTERS: Array<{ value: TextRoleFilter; label: string }> = [
  { value: "all", label: "全部" },
  ...TEXT_ROLE_OPTIONS.map(({ value, label }) => ({ value, label })),
];

const GRID_TYPES = new Set<MaterialType>(["image", "text", "video", "contact", "gif", "sticker"]);
const TYPE_VALUES = new Set(MATERIAL_TYPES.map((item) => item.value));
const CHECKERBOARD = {
  backgroundColor: "var(--muted)",
  backgroundImage:
    "linear-gradient(45deg, color-mix(in srgb, var(--foreground) 6%, transparent) 25%, transparent 25%), linear-gradient(-45deg, color-mix(in srgb, var(--foreground) 6%, transparent) 25%, transparent 25%), linear-gradient(45deg, transparent 75%, color-mix(in srgb, var(--foreground) 6%, transparent) 75%), linear-gradient(-45deg, transparent 75%, color-mix(in srgb, var(--foreground) 6%, transparent) 75%)",
  backgroundPosition: "0 0, 0 8px, 8px -8px, -8px 0",
  backgroundSize: "16px 16px",
};

const blankForm = (type: MaterialType = "image", textRole: TextRole = "body"): MaterialForm => ({
  name: "",
  type,
  textRole,
  originalText: "",
  translatedText: "",
  contactName: "",
  contactPhone: "",
  file: null,
  enabled: true,
});

function trimMaterialName(value: string) {
  return Array.from(value.trim()).slice(0, 120).join("");
}

function fileBaseName(fileName: string) {
  const trimmed = fileName.trim();
  const dot = trimmed.lastIndexOf(".");
  const value = dot > 0 ? trimmed.slice(0, dot) : trimmed;
  return trimMaterialName(value) || "未命名素材";
}

function acceptsMaterialFile(file: File, accept = "") {
  if (!accept) return true;
  const fileName = file.name.toLocaleLowerCase();
  const mime = file.type.toLocaleLowerCase();
  return accept.split(",").some((rawRule) => {
    const rule = rawRule.trim().toLocaleLowerCase();
    if (!rule) return false;
    if (rule.startsWith(".")) return fileName.endsWith(rule);
    if (rule.endsWith("/*")) return mime.startsWith(rule.slice(0, -1));
    return mime === rule;
  });
}

function uniqueMaterialName(value: string, usedNames: Set<string>) {
  const base = trimMaterialName(value) || "未命名素材";
  let candidate = base;
  let suffix = 2;
  while (usedNames.has(candidate.toLocaleLowerCase())) {
    const ending = `_${suffix}`;
    candidate = `${Array.from(base).slice(0, 120 - ending.length).join("")}${ending}`;
    suffix += 1;
  }
  usedNames.add(candidate.toLocaleLowerCase());
  return candidate;
}

function applyBatchNaming(items: BatchUploadItem[], mode: BatchNamingMode, value: string) {
  const used = new Set<string>();
  const digits = Math.max(3, String(items.length).length);
  return items.map((item, index) => {
    if (item.status === "success") {
      used.add(item.name.trim().toLocaleLowerCase());
      return item;
    }
    const proposed = mode === "prefix"
      ? `${value}${item.fileBaseName}`
      : mode === "sequence"
        ? `${value.trim() || "素材"}_${String(index + 1).padStart(digits, "0")}`
        : item.fileBaseName;
    return { ...item, name: uniqueMaterialName(proposed, used), error: item.status === "failed" ? "" : item.error, status: item.status === "failed" ? "ready" : item.status };
  });
}

function uploadStatusMeta(status: BatchUploadStatus) {
  if (status === "uploading") return { label: "上传中", tone: "warning" as const };
  if (status === "success") return { label: "成功", tone: "success" as const };
  if (status === "failed") return { label: "失败", tone: "danger" as const };
  return { label: "待上传", tone: "neutral" as const };
}

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function read(row: Record<string, unknown>, key: string) {
  return row[key] ?? row[key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)];
}

function normalize(value: unknown): MaterialRow | null {
  const row = object(value);
  const id = snowflakeId(row, "id");
  const rawType = String(read(row, "type") || "");
  if (!TYPE_VALUES.has(rawType as MaterialType)) return null;
  return {
    id,
    readKey: entityRowKey(row, id, "material", String(read(row, "name") || "")),
    name: String(read(row, "name") || "未命名素材"),
    type: rawType as MaterialType,
    textRole: rawType === "text" ? (String(read(row, "textRole") || "body") as TextRole) : null,
    contentJson: object(read(row, "contentJson")),
    fileName: String(read(row, "fileName") || ""),
    contentType: String(read(row, "contentType") || ""),
    size: Number(read(row, "size") || 0),
    sha256: String(read(row, "sha256") || ""),
    hasFile: read(row, "hasFile") === true,
    previewPath: String(read(row, "previewPath") || ""),
    enabled: read(row, "enabled") !== false,
    createdAt: String(read(row, "createdAt") || ""),
    updatedAt: String(read(row, "updatedAt") || ""),
  };
}

function definition(type: MaterialType) {
  return MATERIAL_TYPES.find((item) => item.value === type) || MATERIAL_TYPES[0];
}

function textRoleDefinition(role: TextRole | null | undefined) {
  return TEXT_ROLE_OPTIONS.find((item) => item.value === role) || TEXT_ROLE_OPTIONS[0];
}

function formatSize(value: number) {
  if (!value) return "-";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function materialContent(row: MaterialRow) {
  if (definition(row.type).binary) {
    return [row.fileName, formatSize(row.size)].filter(Boolean).join(" · ");
  }
  if (row.type === "contact") {
    const name = String(row.contentJson.displayName || row.contentJson.name || "");
    const phone = formatPhoneDisplay(row.contentJson.phone);
    return [name, phone].filter(Boolean).join(" · ");
  }
  return [materialOriginalText(row), materialTranslatedText(row)].filter(Boolean).join(" ");
}

function characterCount(value: string) {
  return Array.from(value).length;
}

function materialCardSummary(row: MaterialRow) {
  if (row.type === "text") {
    return `原文 ${characterCount(materialOriginalText(row))} 字 · 译文 ${characterCount(materialTranslatedText(row))} 字`;
  }
  return definition(row.type).binary ? formatSize(row.size) : materialContent(row);
}

function materialOriginalText(row: MaterialRow) {
  return String(
    row.contentJson.originalText
    || row.contentJson.text
    || row.contentJson.content
    || "",
  );
}

function materialTranslatedText(row: MaterialRow) {
  return String(
    row.contentJson.translatedText
    || row.contentJson.translation
    || "",
  );
}

function previewUrl(row: MaterialRow) {
  if (!row.previewPath) return "";
  return `${row.previewPath}?v=${encodeURIComponent(row.sha256 || row.updatedAt)}`;
}

function ready(row: MaterialRow) {
  return !definition(row.type).binary || row.hasFile;
}

function statusMeta(row: MaterialRow) {
  const isReady = ready(row);
  return {
    label: isReady ? (row.enabled ? "可用" : "已停用") : "待上传",
    description: isReady
      ? row.enabled
        ? "该素材可以用于新的消息。"
        : "该素材当前不会用于新的消息。"
      : "请重新上传素材文件后再使用。",
    tone: (isReady && row.enabled ? "success" : isReady ? "neutral" : "warning") as "success" | "neutral" | "warning",
    details: [
      { label: "素材类型", value: definition(row.type).label },
      ...(row.type === "text" ? [{ label: "文本用途", value: textRoleDefinition(row.textRole).label }] : []),
      { label: "文件大小", value: definition(row.type).binary ? formatSize(row.size) : "-" },
      { label: "更新时间", value: formatDateTime(row.updatedAt || row.createdAt) },
    ],
  };
}

function StructuredPreview({ row, compact = false }: { row: MaterialRow; compact?: boolean }) {
  const item = definition(row.type);
  const Icon = item.icon;
  const url = previewUrl(row);

  if (["image", "gif", "sticker"].includes(row.type) && url) {
    return (
      <div
        className={cn("relative size-full overflow-hidden", row.type !== "sticker" && "bg-muted/55")}
        style={row.type === "sticker" ? CHECKERBOARD : undefined}
      >
        <img
          className={cn("absolute inset-0 h-full w-full object-contain", row.type === "sticker" ? "p-5" : "p-1")}
          src={url}
          alt={row.name}
          loading="lazy"
        />
      </div>
    );
  }

  if (row.type === "video" && url) {
    return (
      <div className="relative size-full overflow-hidden bg-black">
        <video className="absolute inset-0 h-full w-full object-contain" src={url} muted playsInline preload="metadata" />
        <span className="absolute inset-0 grid place-items-center bg-black/10">
          <span className="grid size-11 place-items-center rounded-full bg-black/55 text-white shadow-sm"><PlayIcon className="ml-0.5" size={20} fill="currentColor" /></span>
        </span>
      </div>
    );
  }

  if (row.type === "text") {
    const originalText = materialOriginalText(row);
    const translatedText = materialTranslatedText(row);
    return (
      <div className={cn(
        "size-full bg-gradient-to-br from-background to-muted/45 text-left",
        compact ? "overflow-hidden p-3" : "overflow-y-auto overscroll-contain p-5",
      )}>
        <section>
          <span className={cn("mb-2 block font-medium text-muted-foreground", compact ? "text-[11px]" : "text-xs")}>原文</span>
          <p className={cn("whitespace-pre-wrap break-words text-foreground/85", compact ? "line-clamp-3 text-xs leading-5" : "text-sm leading-6")}>
            {originalText || "暂无原文"}
          </p>
        </section>
        <section className={cn("border-t border-border/70", compact ? "mt-3 pt-3" : "mt-5 pt-5")}>
          <span className={cn("mb-2 block font-medium text-muted-foreground", compact ? "text-[11px]" : "text-xs")}>译文</span>
          <p className={cn("whitespace-pre-wrap break-words text-foreground/85", compact ? "line-clamp-3 text-xs leading-5" : "text-sm leading-6")}>
            {translatedText || "暂无译文"}
          </p>
        </section>
      </div>
    );
  }

  if (row.type === "contact") {
    const name = String(row.contentJson.displayName || row.contentJson.name || row.name);
    const phone = formatPhoneDisplay(row.contentJson.phone);
    const initial = name.trim().slice(0, 1).toUpperCase() || "联";
    return (
      <div className={cn("flex size-full flex-col items-center justify-center bg-gradient-to-b from-primary/[0.08] to-background text-center", compact ? "gap-2 p-3" : "gap-3 p-6")}>
        <span className={cn("grid place-items-center rounded-full bg-primary/12 font-semibold text-primary ring-1 ring-primary/15", compact ? "size-12 text-lg" : "size-20 text-2xl")}>{initial}</span>
        <div className="min-w-0">
          <strong className="block truncate text-sm">{name}</strong>
          <span className="mt-1 block truncate text-xs text-muted-foreground">{phone || "未填写号码"}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="grid size-full place-items-center bg-muted/60 text-muted-foreground">
      <Icon size={compact ? 22 : 38} strokeWidth={1.7} />
    </div>
  );
}

function PreviewDialog({ row, onClose, onDownload }: { row: MaterialRow | null; onClose: () => void; onDownload: (row: MaterialRow) => void }) {
  if (!row) return null;
  const url = previewUrl(row);
  const item = definition(row.type);
  const Icon = item.icon;
  const originalText = materialOriginalText(row);
  const translatedText = materialTranslatedText(row);
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="gap-3 sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>{row.name}</DialogTitle>
          <DialogDescription>{row.id} · {item.label}{row.size ? ` · ${formatSize(row.size)}` : ""}</DialogDescription>
        </DialogHeader>
        <DialogBody className="overflow-hidden rounded-xl border border-border bg-muted/30 p-0">
          {["image", "gif", "sticker"].includes(row.type) && url ? (
            <div className="grid min-h-72 place-items-center" style={row.type === "sticker" ? CHECKERBOARD : undefined}>
              <img className="max-h-[68vh] max-w-full object-contain" src={url} alt={row.name} />
            </div>
          ) : row.type === "video" && url ? (
            <video className="max-h-[68vh] w-full bg-black" src={url} controls playsInline autoFocus />
          ) : row.type === "audio" && url ? (
            <div className="flex min-h-52 flex-col items-center justify-center gap-5 p-8">
              <span className="grid size-20 place-items-center rounded-full bg-primary/10 text-primary"><AudioLinesIcon size={36} /></span>
              <audio className="w-full max-w-xl" src={url} controls autoFocus />
            </div>
          ) : row.type === "contact" ? (
            <div className="mx-auto h-80 w-full max-w-md"><StructuredPreview row={row} /></div>
          ) : row.type === "text" ? (
            <div className="grid h-[60vh] min-h-80 max-h-[68vh] grid-cols-2 divide-x divide-border">
              <section className="min-h-0 min-w-0 overflow-y-auto p-6">
                <strong className="mb-4 block text-sm">原文</strong>
                <p className="whitespace-pre-wrap break-words text-sm leading-7 text-foreground/85">{originalText || "暂无原文"}</p>
              </section>
              <section className="min-h-0 min-w-0 overflow-y-auto p-6">
                <strong className="mb-4 block text-sm">译文</strong>
                <p className="whitespace-pre-wrap break-words text-sm leading-7 text-foreground/85">{translatedText || "暂无译文"}</p>
              </section>
            </div>
          ) : (
            <div className="flex min-h-64 flex-col items-center justify-center gap-4 p-8 text-center">
              <span className="grid size-20 place-items-center rounded-2xl bg-primary/8 text-primary"><Icon size={38} /></span>
              <div><strong className="block">{row.fileName || row.name}</strong><span className="mt-1 block text-sm text-muted-foreground">{row.contentType || "文件"} · {formatSize(row.size)}</span></div>
            </div>
          )}
        </DialogBody>
        {item.binary && row.hasFile ? (
          <div className="flex justify-end"><Button variant="outline" onClick={() => onDownload(row)}><DownloadIcon size={16} />下载素材</Button></div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function structuredPayload(form: MaterialForm) {
  const contentJson = form.type === "contact"
    ? { displayName: form.contactName.trim(), phone: formatPhoneDisplay(form.contactPhone) }
    : { originalText: form.originalText.trim(), translatedText: form.translatedText.trim() };
  return {
    name: form.name.trim(),
    type: form.type,
    textRole: form.type === "text" ? form.textRole : undefined,
    contentJson,
    enabled: form.enabled,
  };
}

export function MaterialsPage() {
  const { can } = useAuth();
  const canManage = can("resources.materials.manage");
  const [rows, setRows] = useState<MaterialRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState<Record<MaterialType, number>>(
    () => Object.fromEntries(MATERIAL_TYPES.map((item) => [item.value, 0])) as Record<MaterialType, number>,
  );
  const [textRoleCounts, setTextRoleCounts] = useState<Partial<Record<TextRole, number>>>({});
  const [activeType, setActiveType] = useState<MaterialType>("image");
  const [activeTextRole, setActiveTextRole] = useState<TextRoleFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<MaterialRow | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [editing, setEditing] = useState<MaterialRow | null>(null);
  const [form, setForm] = useState<MaterialForm>(() => blankForm());
  const [pending, setPending] = useState(false);
  const [batchItems, setBatchItems] = useState<BatchUploadItem[]>([]);
  const [batchNamingMode, setBatchNamingMode] = useState<BatchNamingMode>("filename");
  const [batchNamingValue, setBatchNamingValue] = useState("");
  const [draggingFiles, setDraggingFiles] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const query = new URLSearchParams({
        page: String(page),
        pageSize: String(pageSize),
        type: activeType,
      });
      if (debouncedKeyword) query.set("keyword", debouncedKeyword);
      if (activeType === "text" && activeTextRole !== "all") query.set("textRole", activeTextRole);
      if (statusFilter !== "all") query.set("status", statusFilter);
      const response = await apiRequest(`/api/materials?${query}`);
      const list = unwrapList<unknown>(response);
      const normalized = list.rows.map(normalize).filter((item): item is MaterialRow => Boolean(item));
      setRows(normalized);
      setTotal(list.total);
      const data = (response as { data?: { typeCounts?: Partial<Record<MaterialType, number>>; textRoleCounts?: Partial<Record<TextRole, number>> } }).data;
      setCounts((current) => ({ ...current, ...(data?.typeCounts || {}) }));
      setTextRoleCounts(data?.textRoleCounts || {});
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "素材加载失败");
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [activeTextRole, activeType, debouncedKeyword, page, pageSize, statusFilter]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedKeyword(keyword.trim());
      setPage(1);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [keyword]);
  useEffect(() => {
    setSelected(new Set());
    setPage(1);
  }, [activeTextRole, activeType, statusFilter]);

  const selectedRows = useMemo(() => rows.filter((row) => selected.has(row.id)), [rows, selected]);
  const allVisibleSelected = Boolean(rows.length) && rows.every((row) => selected.has(row.id));
  const existingMaterialNames = useMemo(() => new Set(rows.map((row) => row.name.trim().toLocaleLowerCase())), [rows]);
  const batchReadyCount = batchItems.filter((item) => item.status === "ready").length;
  const batchFailedCount = batchItems.filter((item) => item.status === "failed").length;
  const batchSuccessCount = batchItems.filter((item) => item.status === "success").length;

  function toggleSelected(id: string, checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(id); else next.delete(id);
      return next;
    });
  }

  function toggleAllVisible(checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      rows.forEach((row) => checked ? next.add(row.id) : next.delete(row.id));
      return next;
    });
  }

  function resetBatchUpload() {
    setBatchItems([]);
    setBatchNamingMode("filename");
    setBatchNamingValue("");
    setDraggingFiles(false);
  }

  function addBatchFiles(files: FileList | File[]) {
    const selectedFiles = Array.from(files).filter((file) => file.size > 0);
    const additions = selectedFiles.filter((file) => acceptsMaterialFile(file, definition(form.type).accept));
    const rejectedCount = selectedFiles.length - additions.length;
    if (rejectedCount) toast.error(`${rejectedCount} 个文件格式不符合${definition(form.type).label}要求`);
    if (!additions.length) return;
    setBatchItems((current) => {
      const usedNames = new Set(current.map((item) => item.name.trim().toLocaleLowerCase()));
      const nextItems = additions.map<BatchUploadItem>((file) => {
        const base = fileBaseName(file.name);
        return {
          key: crypto.randomUUID(),
          file,
          fileBaseName: base,
          name: uniqueMaterialName(base, usedNames),
          status: "ready",
          error: "",
        };
      });
      const combined = [...current, ...nextItems];
      return batchNamingMode === "filename"
        ? combined
        : applyBatchNaming(combined, batchNamingMode, batchNamingValue);
    });
  }

  function changeBatchNamingMode(mode: BatchNamingMode) {
    setBatchNamingMode(mode);
    setBatchItems((current) => applyBatchNaming(current, mode, batchNamingValue));
  }

  function changeBatchNamingValue(value: string) {
    setBatchNamingValue(value);
    setBatchItems((current) => applyBatchNaming(current, batchNamingMode, value));
  }

  function changeBatchItemName(key: string, value: string) {
    setBatchItems((current) => current.map((item) => item.key === key && item.status !== "success"
      ? { ...item, name: value, status: item.status === "failed" ? "ready" : item.status, error: "" }
      : item));
  }

  function normalizeBatchItemName(key: string) {
    setBatchItems((current) => {
      const usedNames = new Set(current.filter((item) => item.key !== key).map((item) => item.name.trim().toLocaleLowerCase()));
      return current.map((item) => item.key === key && item.status !== "success"
        ? { ...item, name: uniqueMaterialName(item.name, usedNames) }
        : item);
    });
  }

  function removeBatchItem(key: string) {
    setBatchItems((current) => current.filter((item) => item.key !== key || item.status === "success"));
  }

  function closeDrawer() {
    if (pending) return;
    setDrawer(false);
    resetBatchUpload();
  }

  function open(row?: MaterialRow) {
    resetBatchUpload();
    setEditing(row || null);
    if (!row) setForm(blankForm(activeType, activeType === "text" && activeTextRole !== "all" ? activeTextRole : "body"));
    else {
      setForm({
        name: row.name,
        type: row.type,
        textRole: row.textRole || "body",
        originalText: materialOriginalText(row),
        translatedText: materialTranslatedText(row),
        contactName: String(row.contentJson.displayName || row.contentJson.name || ""),
        contactPhone: formatPhoneDisplay(row.contentJson.phone),
        file: null,
        enabled: row.enabled,
      });
    }
    setDrawer(true);
  }

  function contentReady() {
    if (!editing && definition(form.type).binary) {
      const uploadable = batchItems.filter((item) => item.status === "ready" || item.status === "failed");
      return Boolean(uploadable.length) && uploadable.every((item) => trimMaterialName(item.name));
    }
    if (!form.name.trim()) return false;
    if (form.type === "contact") return Boolean(form.contactName.trim() && form.contactPhone.trim());
    if (form.type === "text") {
      const role = textRoleDefinition(form.textRole);
      const original = form.originalText.trim();
      const translated = form.translatedText.trim();
      return Boolean(original)
        && [original, translated].every((value) => (!value || (
          characterCount(value) <= role.maxLength
          && (role.multiline || (!value.includes("\n") && !value.includes("\r")))
        )));
    }
    return Boolean(form.file || (editing?.hasFile && editing.type === form.type));
  }

  async function uploadBatch() {
    const usedNames = new Set(batchItems.filter((item) => item.status === "success").map((item) => item.name.trim().toLocaleLowerCase()));
    const queue = batchItems
      .filter((item) => item.status === "ready" || item.status === "failed")
      .map((item) => ({ ...item, name: uniqueMaterialName(item.name, usedNames) }));
    if (!queue.length || queue.some((item) => !item.name)) return;

    const normalizedNames = new Map(queue.map((item) => [item.key, item.name]));
    setBatchItems((current) => current.map((item) => normalizedNames.has(item.key) ? { ...item, name: normalizedNames.get(item.key) as string } : item));

    setPending(true);
    const failures: string[] = [];
    let cursor = 0;
    const updateItem = (key: string, patch: Partial<BatchUploadItem>) => {
      setBatchItems((current) => current.map((item) => item.key === key ? { ...item, ...patch } : item));
    };
    const worker = async () => {
      while (cursor < queue.length) {
        const item = queue[cursor];
        cursor += 1;
        updateItem(item.key, { name: item.name, status: "uploading", error: "" });
        try {
          const body = new FormData();
          body.append("name", item.name);
          body.append("type", form.type);
          body.append("enabled", String(form.enabled));
          body.append("file", item.file);
          await apiRequest("/api/materials/upload", { method: "POST", body });
          updateItem(item.key, { status: "success", error: "" });
        } catch (caught) {
          const message = caught instanceof Error ? caught.message : "上传失败";
          failures.push(item.key);
          updateItem(item.key, { status: "failed", error: message });
        }
      }
    };

    await Promise.all(Array.from({ length: Math.min(3, queue.length) }, () => worker()));
    setActiveType(form.type);
    await load();
    if (failures.length) toast.error(`${queue.length - failures.length} 个上传成功，${failures.length} 个失败`);
    else toast.success(`已上传 ${queue.length} 个素材`);
    setPending(false);
  }

  async function save() {
    if (!contentReady()) return;
    const itemDefinition = definition(form.type);
    if (!editing && itemDefinition.binary) {
      await uploadBatch();
      return;
    }
    setPending(true);
    try {
      if (editing) {
        const body: Record<string, unknown> = { name: form.name.trim(), enabled: form.enabled };
        if (!itemDefinition.binary) Object.assign(body, structuredPayload(form));
        await apiRequest(`/api/materials/${editing.id}`, { method: "PATCH", body: JSON.stringify(body) });
        if (itemDefinition.binary && form.file) {
          const upload = new FormData();
          upload.append("file", form.file);
          await apiRequest(`/api/materials/${editing.id}/content`, { method: "PUT", body: upload });
        }
      } else {
        await apiRequest("/api/materials", { method: "POST", body: JSON.stringify(structuredPayload(form)) });
      }
      closeDrawer();
      setActiveType(form.type);
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setPending(false);
    }
  }

  async function download(row: MaterialRow) {
    try {
      const result = await apiDownload(`${row.previewPath}?download=true`);
      const anchor = document.createElement("a");
      const url = URL.createObjectURL(result.blob);
      anchor.href = url;
      anchor.download = decodeURIComponent(result.filename || row.fileName || row.name);
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "下载失败");
    }
  }

  async function remove(row: MaterialRow) {
    if (!(await confirmAction({ title: `删除“${row.name}”？`, description: "删除后无法恢复；仍被模板使用的素材不能删除。", confirmText: "确认删除", destructive: true }))) return;
    try {
      await apiRequest(`/api/materials/${row.id}`, { method: "DELETE" });
      setSelected((current) => { const next = new Set(current); next.delete(row.id); return next; });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "删除失败");
    }
  }

  async function batchChange(action: "enable" | "disable" | "delete") {
    if (!selectedRows.length) return;
    if (action === "delete" && !(await confirmAction({
      title: `删除 ${selectedRows.length} 个素材？`,
      description: "删除后无法恢复；仍被模板使用的素材会删除失败。",
      confirmText: "确认删除",
      destructive: true,
    }))) return;
    setPending(true);
    const settled = await Promise.allSettled(selectedRows.map((row) => action === "delete"
      ? apiRequest(`/api/materials/${row.id}`, { method: "DELETE" })
      : apiRequest(`/api/materials/${row.id}`, { method: "PATCH", body: JSON.stringify({ enabled: action === "enable" }) })));
    const failed = settled.filter((item) => item.status === "rejected").length;
    if (failed) toast.error(`${selectedRows.length - failed} 个处理成功，${failed} 个失败`);
    else toast.success(`已处理 ${selectedRows.length} 个素材`);
    setSelected(new Set());
    await load();
    setPending(false);
  }

  async function batchChangeTextRole(role: TextRole) {
    const textRows = selectedRows.filter((row) => row.type === "text");
    if (!textRows.length) return;
    setPending(true);
    const settled = await Promise.allSettled(textRows.map((row) => apiRequest(
      `/api/materials/${row.id}`,
      { method: "PATCH", body: JSON.stringify({ textRole: role }) },
    )));
    const failed = settled.filter((item) => item.status === "rejected").length;
    if (failed) toast.error(`${textRows.length - failed} 个已修改，${failed} 个不符合${textRoleDefinition(role).label}规则`);
    else toast.success(`已改为${textRoleDefinition(role).label}素材`);
    setSelected(new Set());
    await load();
    setPending(false);
  }

  const currentDefinition = definition(form.type);
  const gridMode = GRID_TYPES.has(activeType);
  const isNewBinary = !editing && Boolean(currentDefinition.binary);
  const batchUploadableCount = batchReadyCount + batchFailedCount;
  const drawerFooter = isNewBinary ? (
    <>
      <Button variant="outline" disabled={pending} onClick={closeDrawer}>{batchSuccessCount || batchFailedCount ? "关闭" : "取消"}</Button>
      {batchUploadableCount ? (
        <Button disabled={pending || !contentReady()} onClick={() => void uploadBatch()}>
          {pending ? <Spinner /> : null}
          {batchReadyCount ? `开始上传（${batchUploadableCount}）` : `重试失败（${batchFailedCount}）`}
        </Button>
      ) : null}
    </>
  ) : (
    <>
      <Button variant="outline" onClick={closeDrawer}>取消</Button>
      <Button disabled={pending || !contentReady()} onClick={() => void save()}>{pending ? <Spinner /> : null}保存素材</Button>
    </>
  );

  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{ value: keyword, onChange: setKeyword, placeholder: `搜索${definition(activeType).label}素材` }}
        filters={<SelectField value={statusFilter} onValueChange={(value) => setStatusFilter(value as StatusFilter)} className="w-32" ariaLabel="素材状态" options={[{ value: "all", label: "全部状态" }, { value: "enabled", label: "可用" }, { value: "disabled", label: "已停用" }, { value: "missing", label: "待上传" }]} />}
        meta={`${total} 条素材`}
        actions={
          <>
            {selected.size ? (
              <>
                <Badge tone="neutral">已选择 {selected.size}</Badge>
                {activeType === "text" ? (
                  <SelectField
                    value=""
                    onValueChange={(value) => value && void batchChangeTextRole(value as TextRole)}
                    className="w-32"
                    ariaLabel="批量修改文本用途"
                    placeholder="修改用途"
                    options={TEXT_ROLE_OPTIONS.map(({ value, label }) => ({ value, label }))}
                  />
                ) : null}
                <Button variant="outline" disabled={pending} onClick={() => void batchChange("enable")}>启用</Button>
                <Button variant="outline" disabled={pending} onClick={() => void batchChange("disable")}>停用</Button>
                <Button variant="outline" className="text-destructive" disabled={pending} onClick={() => void batchChange("delete")}><Trash2Icon size={15} />删除</Button>
              </>
            ) : null}
            <Button variant="outline" onClick={() => void load()}><RefreshCwIcon size={16} />刷新</Button>
            {canManage ? <Button onClick={() => open()}><PlusIcon size={17} />上传{definition(activeType).label}</Button> : null}
          </>
        }
      />

      <ListPagination
        page={page}
        pageSize={pageSize}
        total={total}
        onPageChange={setPage}
        onPageSizeChange={(value) => { setPageSize(value); setPage(1); }}
      />

      <ListTableCard>
        <div className="flex shrink-0 items-center border-b border-border bg-background pr-3">
          <div className="overflow-x-auto">
            <div className="flex min-w-max px-2">
              {MATERIAL_TYPES.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  className={cn(
                    "relative flex h-12 min-w-24 items-center justify-center gap-2 px-4 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground",
                    activeType === item.value && "text-primary after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:rounded-full after:bg-primary",
                  )}
                  onClick={() => setActiveType(item.value)}
                >
                  {item.label}
                  {counts[item.value] ? <span className="text-xs text-muted-foreground">{counts[item.value]}</span> : null}
                </button>
              ))}
            </div>
          </div>
          {rows.length ? (
            <label className="ml-auto flex shrink-0 cursor-pointer items-center gap-2 pl-4 text-xs text-muted-foreground">
              <Checkbox checked={allVisibleSelected} onCheckedChange={(checked) => toggleAllVisible(checked === true)} />全选
            </label>
          ) : null}
        </div>

        {activeType === "text" ? (
          <div className="flex shrink-0 items-center gap-1 border-b border-border bg-background px-4 py-2">
            {TEXT_ROLE_FILTERS.map((item) => {
              const count = item.value === "all"
                ? counts.text
                : textRoleCounts[item.value] || 0;
              return (
                <button
                  key={item.value}
                  type="button"
                  className={cn(
                    "rounded-lg px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                    activeTextRole === item.value && "bg-primary/8 font-medium text-primary",
                  )}
                  onClick={() => setActiveTextRole(item.value)}
                >
                  {item.label}{count ? <span className="ml-1.5 text-xs opacity-70">{count}</span> : null}
                </button>
              );
            })}
          </div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-y-auto bg-muted/[0.18]">
          {loading ? <div className="loading-state h-full"><Spinner /></div> : !rows.length ? (
            <EmptyState title={`暂无${definition(activeType).label}素材`} description={`上传${definition(activeType).label}素材后即可在消息中复用。`} />
          ) : gridMode ? (
            <div className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
              {rows.map((row) => {
                const item = definition(row.type);
                const isSelected = selected.has(row.id);
                const state = statusMeta(row);
                return (
                  <article key={row.readKey} className={cn("group relative min-w-0 overflow-hidden rounded-xl border border-border bg-card shadow-xs transition-all hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md", isSelected && "border-primary ring-2 ring-primary/15")}>
                    {row.type === "text" ? (
                      <div
                        className="aspect-square w-full overflow-hidden"
                        role="button"
                        tabIndex={0}
                        aria-label={`预览${row.name}`}
                        onClick={() => setPreview(row)}
                        onKeyDown={(event) => {
                          if (event.key !== "Enter" && event.key !== " ") return;
                          event.preventDefault();
                          setPreview(row);
                        }}
                      >
                        <StructuredPreview row={row} />
                      </div>
                    ) : (
                      <button type="button" className="block aspect-square w-full overflow-hidden text-left" onClick={() => setPreview(row)} aria-label={`预览${row.name}`}>
                        <StructuredPreview row={row} />
                      </button>
                    )}
                    <div
                      className="grid min-w-0 cursor-pointer gap-2.5 overflow-hidden p-3 transition-colors hover:bg-muted/30"
                      role="checkbox"
                      aria-checked={isSelected}
                      aria-label={`选择${row.name}`}
                      tabIndex={0}
                      onClick={() => toggleSelected(row.id, !isSelected)}
                      onKeyDown={(event) => {
                        if (event.currentTarget !== event.target || (event.key !== "Enter" && event.key !== " ")) return;
                        event.preventDefault();
                        toggleSelected(row.id, !isSelected);
                      }}
                    >
                      <div className="flex min-w-0 items-start gap-2">
                        <div className="min-w-0 flex-1"><strong className="block truncate text-sm" title={row.name}>{row.name}</strong><span className="mt-0.5 block truncate text-xs text-muted-foreground" title={row.id}>{row.id}</span></div>
                        {row.type === "text" ? <Badge tone="neutral">{textRoleDefinition(row.textRole).label}</Badge> : null}
                        <Badge tone={state.tone}>{state.label}</Badge>
                      </div>
                      <div className={cn("min-w-0 text-xs text-muted-foreground", row.type === "text" ? "grid gap-0.5" : "flex items-center justify-between gap-2")}>
                        <span className={cn("min-w-0", row.type !== "text" && "flex-1 truncate")}>{materialCardSummary(row)}</span>
                        <span className={cn("shrink-0", row.type === "text" && "justify-self-end")}>{formatDateTime(row.updatedAt || row.createdAt).split(" ")[0]}</span>
                      </div>
                      <div className="flex items-center justify-between border-t border-border/70 pt-2">
                        <label className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground" onClick={(event) => event.stopPropagation()}>
                          <Checkbox checked={isSelected} onCheckedChange={(checked) => toggleSelected(row.id, checked === true)} />选择
                        </label>
                        <div className="flex min-w-max items-center gap-2">
                          <Button variant="outline" size="sm" onClick={(event) => { event.stopPropagation(); setPreview(row); }}>预览</Button>
                          {canManage ? <Button variant="outline" size="sm" onClick={(event) => { event.stopPropagation(); open(row); }}>编辑</Button> : null}
                        </div>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="divide-y divide-border bg-background">
              {rows.map((row) => {
                const item = definition(row.type);
                const Icon = item.icon;
                const url = previewUrl(row);
                return (
                  <div key={row.readKey} className={cn("group flex min-w-0 items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/35", selected.has(row.id) && "bg-primary/[0.04]")}>
                    <Checkbox checked={selected.has(row.id)} onCheckedChange={(checked) => toggleSelected(row.id, checked === true)} />
                    <EntityStatusIndicator status={statusMeta(row)} />
                    <div className="grid size-11 shrink-0 place-items-center rounded-lg border border-border bg-muted/60 text-muted-foreground"><Icon size={20} /></div>
                    <button type="button" className="min-w-0 flex-1 text-left" onClick={() => setPreview(row)}>
                      <strong className="block truncate text-sm">{row.name}</strong>
                      <span className="mt-1 block truncate text-xs text-muted-foreground">{row.id}</span>
                    </button>
                    {row.type === "audio" && url ? <audio className="hidden w-64 max-w-[24vw] md:block" controls preload="none" src={url} /> : null}
                    <div className="hidden min-w-0 max-w-sm flex-1 lg:block"><p className="truncate text-sm text-muted-foreground" title={materialContent(row)}>{materialContent(row) || "-"}</p></div>
                    <div className="hidden w-28 shrink-0 text-right text-xs text-muted-foreground xl:block">{formatDateTime(row.updatedAt || row.createdAt)}</div>
                    <div className="flex min-w-max shrink-0 items-center justify-end gap-2">
                      <Button variant="outline" size="sm" onClick={() => setPreview(row)}>预览</Button>
                      {item.binary && row.hasFile ? <Button variant="outline" size="sm" onClick={() => void download(row)}>下载</Button> : null}
                      {canManage ? <><Button variant="outline" size="sm" onClick={() => open(row)}>编辑</Button><Button variant="destructive" size="sm" onClick={() => void remove(row)}>删除</Button></> : null}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </ListTableCard>

      <PreviewDialog row={preview} onClose={() => setPreview(null)} onDownload={(row) => void download(row)} />

      <Drawer
        open={drawer}
        onClose={closeDrawer}
        title={editing ? "编辑素材" : isNewBinary ? `批量上传${definition(form.type).label}` : `上传${definition(form.type).label}`}
        description={isNewBinary ? "选择文件并确认名称后开始上传。" : "保存后即可在各类营销任务中使用。"}
        footer={drawerFooter}
      >
        <div className="drawer-form">
          <div className="field">
            <DrawerFieldLabel required>素材类型</DrawerFieldLabel>
            <div className="grid grid-cols-3 gap-2">
              {MATERIAL_TYPES.map((item) => {
                const Icon = item.icon;
                return (
                  <button key={item.value} type="button" disabled={Boolean(editing) || pending} className={cn("flex h-8 items-center justify-center gap-2 rounded-lg border border-border bg-background text-sm font-medium transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60", form.type === item.value && "border-primary bg-primary/5 text-primary")} onClick={() => { resetBatchUpload(); setForm({ ...blankForm(item.value, item.value === "text" && activeTextRole !== "all" ? activeTextRole : "body"), name: form.name, enabled: form.enabled }); }}>
                    <Icon size={16} />{item.label}
                  </button>
                );
              })}
            </div>
          </div>

          {!isNewBinary ? <label className="field"><DrawerFieldLabel required>素材名称</DrawerFieldLabel><Input maxLength={120} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder={`输入${currentDefinition.label}素材名称`} /></label> : null}

          {form.type === "text" ? (
            <>
              <div className="field">
                <DrawerFieldLabel required>文本用途</DrawerFieldLabel>
                <div className="grid grid-cols-4 gap-2">
                  {TEXT_ROLE_OPTIONS.map((role) => (
                    <button
                      key={role.value}
                      type="button"
                      className={cn(
                        "h-8 rounded-lg border border-border bg-background text-sm font-medium transition-colors hover:bg-muted",
                        form.textRole === role.value && "border-primary bg-primary/5 text-primary",
                      )}
                      onClick={() => setForm({
                        ...form,
                        textRole: role.value,
                        originalText: role.multiline ? form.originalText : form.originalText.replace(/[\r\n]+/g, " ").slice(0, role.maxLength),
                        translatedText: role.multiline ? form.translatedText : form.translatedText.replace(/[\r\n]+/g, " ").slice(0, role.maxLength),
                      })}
                    >
                      {role.label}
                    </button>
                  ))}
                </div>
              </div>
              {(() => {
                const role = textRoleDefinition(form.textRole);
                const updateText = (field: "originalText" | "translatedText", value: string) => setForm({
                  ...form,
                  [field]: role.multiline ? value : value.replace(/[\r\n]+/g, " "),
                });
                return (
                  <>
                    <label className="field">
                      <DrawerFieldLabel required>原文</DrawerFieldLabel>
                      <Textarea rows={role.multiline ? 7 : 3} maxLength={role.maxLength} value={form.originalText} onChange={(event) => updateText("originalText", event.target.value)} placeholder={`输入${role.label}原文`} />
                      <span className="text-right text-xs text-muted-foreground">{characterCount(form.originalText)}/{role.maxLength}</span>
                    </label>
                    <label className="field">
                      <DrawerFieldLabel>译文</DrawerFieldLabel>
                      <Textarea rows={role.multiline ? 7 : 3} maxLength={role.maxLength} value={form.translatedText} onChange={(event) => updateText("translatedText", event.target.value)} placeholder={`输入${role.label}译文`} />
                      <span className="text-right text-xs text-muted-foreground">{characterCount(form.translatedText)}/{role.maxLength}</span>
                    </label>
                  </>
                );
              })()}
            </>
          ) : form.type === "contact" ? (
            <>
              <label className="field"><DrawerFieldLabel required>联系人名称</DrawerFieldLabel><Input value={form.contactName} onChange={(event) => setForm({ ...form, contactName: event.target.value })} placeholder="输入联系人名称" /></label>
              <label className="field"><DrawerFieldLabel required>电话号码</DrawerFieldLabel><Input value={form.contactPhone} onChange={(event) => setForm({ ...form, contactPhone: formatPhoneDisplay(event.target.value) })} placeholder="8613800000000" /></label>
            </>
          ) : isNewBinary ? (
            <>
              <div className="field">
                <DrawerFieldLabel required>批量命名</DrawerFieldLabel>
                <div className="grid grid-cols-3 gap-2">
                  {([
                    { value: "filename", label: "保留原文件名" },
                    { value: "prefix", label: "添加统一前缀" },
                    { value: "sequence", label: "顺序编号" },
                  ] as Array<{ value: BatchNamingMode; label: string }>).map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      disabled={pending}
                      className={cn(
                        "h-8 rounded-lg border border-border bg-background px-3 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-60",
                        batchNamingMode === option.value && "border-primary bg-primary/5 text-primary",
                      )}
                      onClick={() => changeBatchNamingMode(option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                {batchNamingMode !== "filename" ? (
                  <Input
                    value={batchNamingValue}
                    maxLength={100}
                    disabled={pending}
                    onChange={(event) => changeBatchNamingValue(event.target.value)}
                    placeholder={batchNamingMode === "prefix" ? "例如：巴西活动_" : "例如：巴西活动"}
                  />
                ) : null}
              </div>

              <label
                className="field"
                onDragEnter={(event) => { event.preventDefault(); if (!pending) setDraggingFiles(true); }}
                onDragOver={(event) => { event.preventDefault(); if (!pending) setDraggingFiles(true); }}
                onDragLeave={() => setDraggingFiles(false)}
                onDrop={(event) => {
                  event.preventDefault();
                  setDraggingFiles(false);
                  if (!pending) addBatchFiles(event.dataTransfer.files);
                }}
              >
                <DrawerFieldLabel required>选择文件</DrawerFieldLabel>
                <input
                  className="sr-only"
                  type="file"
                  multiple
                  disabled={pending}
                  accept={currentDefinition.accept}
                  onChange={(event) => {
                    if (event.target.files) addBatchFiles(event.target.files);
                    event.target.value = "";
                  }}
                />
                <span className={cn(
                  "flex min-h-32 cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-primary/40 bg-primary/[0.03] px-5 text-center transition-colors hover:bg-primary/[0.06]",
                  draggingFiles && "border-primary bg-primary/[0.08] ring-2 ring-primary/10",
                  pending && "cursor-not-allowed opacity-60",
                )}>
                  <UploadCloudIcon className="text-primary" size={30} />
                  <strong className="text-sm">点击选择或拖入多个文件</strong>
                  <span className="text-xs text-muted-foreground">{currentDefinition.limit}，单次可选择多个</span>
                </span>
              </label>

              {batchItems.length ? (
                <div className="overflow-hidden rounded-xl border border-border">
                  <div className="flex items-center justify-between border-b border-border bg-muted/35 px-4 py-3">
                    <strong className="text-sm">上传队列（{batchItems.length}）</strong>
                    <span className="text-xs text-muted-foreground">成功 {batchSuccessCount} · 失败 {batchFailedCount}</span>
                  </div>
                  <div className="max-h-96 divide-y divide-border overflow-y-auto">
                    {batchItems.map((item) => {
                      const status = uploadStatusMeta(item.status);
                      const duplicate = item.status !== "success" && existingMaterialNames.has(item.name.trim().toLocaleLowerCase());
                      return (
                        <div key={item.key} className="grid min-w-0 grid-cols-[minmax(0,1fr)_5rem] gap-3 px-4 py-3 sm:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)_5rem_4.5rem_2rem] sm:items-start">
                          <div className="min-w-0">
                            <strong className="block truncate text-sm" title={item.file.name}>{item.file.name}</strong>
                            <span className="mt-1 block text-xs text-muted-foreground sm:hidden">{formatSize(item.file.size)}</span>
                          </div>
                          <div className="col-span-2 min-w-0 sm:col-span-1">
                            <Input
                              value={item.name}
                              maxLength={120}
                              disabled={pending || item.status === "success"}
                              aria-label={`${item.file.name}的素材名称`}
                              onChange={(event) => changeBatchItemName(item.key, event.target.value)}
                              onBlur={() => normalizeBatchItemName(item.key)}
                            />
                            {duplicate ? <span className="mt-1 block"><Badge tone="warning">名称重复，不会覆盖旧素材</Badge></span> : null}
                            {item.error ? <span className="mt-1 block break-words text-xs text-destructive">{item.error}</span> : null}
                          </div>
                          <span className="hidden pt-2 text-xs text-muted-foreground sm:block">{formatSize(item.file.size)}</span>
                          <div className="pt-2"><Badge tone={status.tone}>{item.status === "uploading" ? <Spinner /> : null}{status.label}</Badge></div>
                          <div className="pt-1">
                            {item.status !== "success" ? <IconButton disabled={pending} label="移除" className="text-muted-foreground" onClick={() => removeBatchItem(item.key)}><Trash2Icon size={15} /></IconButton> : null}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : null}
            </>
          ) : (
            <label className="field">
              <DrawerFieldLabel required={!editing?.hasFile}>
                {editing?.hasFile ? "替换文件" : "上传文件"}
              </DrawerFieldLabel>
              <input className="sr-only" type="file" accept={currentDefinition.accept} onChange={(event) => { const file = event.target.files?.[0] || null; setForm((current) => ({ ...current, file, name: current.name || file?.name.replace(/\.[^.]+$/, "") || "" })); }} />
              <span className="flex min-h-36 cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-primary/40 bg-primary/[0.03] px-5 text-center transition-colors hover:bg-primary/[0.06]">
                <UploadCloudIcon className="text-primary" size={30} />
                <strong className="text-sm">{form.file?.name || (editing?.fileName ? `当前：${editing.fileName}` : "点击选择文件")}</strong>
                <span className="text-xs text-muted-foreground">{form.file ? formatSize(form.file.size) : currentDefinition.limit}</span>
              </span>
            </label>
          )}

          <div className="flex items-center justify-between rounded-lg border border-border p-4">
            <div><strong className="block text-sm">启用素材</strong><span className="text-xs text-muted-foreground">停用后不再用于新的消息。</span></div>
            <Switch checked={form.enabled} onCheckedChange={(enabled) => setForm({ ...form, enabled })} />
          </div>
        </div>
      </Drawer>
    </StandardListPage>
  );
}
