import {
  PackageIcon,
  PauseIcon,
  PencilIcon,
  PlayIcon,
  PlusIcon,
  RefreshCwIcon,
  UploadCloudIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiRequest, formatDateTime, unwrapList } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EntityPrimaryCell } from "../components/entity-primary-cell";
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
  EmptyState,
  IconButton,
  Input,
  SearchableSelect,
  Spinner,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  toast,
} from "../components/ui";
import { entityRowKey, snowflakeId } from "../lib/entity-identifiers";

type IntegrationType = "script" | "iframe";

type PromotionIntegration = {
  id: string;
  readKey: string;
  integrationKey: string;
  name: string;
  description: string;
  type: IntegrationType;
  domainId: string;
  hostname: string;
  entryPaths: string[];
  sourceUrls: string[];
  version: string;
  assetCount: number;
  totalSize: number;
  packageSha256: string;
  enabled: boolean;
  domainReady: boolean;
  templateCount: number;
  updatedAt?: string;
};

type DomainOption = {
  id: string;
  hostname: string;
};

type IntegrationForm = {
  integrationKey: string;
  name: string;
  description: string;
  domainId: string;
  enabled: boolean;
};

const emptyForm: IntegrationForm = {
  integrationKey: "",
  name: "",
  description: "",
  domainId: "",
  enabled: true,
};

const object = (input: unknown) =>
  input && typeof input === "object" ? (input as Record<string, unknown>) : {};

const field = (row: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) if (row[key] != null) return String(row[key]);
  return "";
};

const stringList = (value: unknown) =>
  Array.isArray(value) ? value.map(String).filter(Boolean) : [];

function integrationRow(input: unknown): PromotionIntegration {
  const row = object(input);
  const id = snowflakeId(row, "id");
  const type = field(row, "type", "integrationType", "integration_type");
  return {
    id,
    readKey: entityRowKey(
      row,
      id,
      "promotion-integration",
      `${field(row, "integrationKey", "integration_key")}:${field(row, "updatedAt", "updated_at")}`,
    ),
    integrationKey: field(row, "integrationKey", "integration_key"),
    name: field(row, "name"),
    description: field(row, "description"),
    type: type === "script" ? "script" : "iframe",
    domainId: snowflakeId(row, "domainId", "domain_id"),
    hostname: field(row, "hostname"),
    entryPaths: stringList(row.entryPaths ?? row.entry_paths),
    sourceUrls: stringList(row.sourceUrls ?? row.source_urls),
    version: field(row, "version") || "1",
    assetCount: Number(row.assetCount ?? row.asset_count ?? 0),
    totalSize: Number(row.totalSize ?? row.total_size ?? 0),
    packageSha256: field(row, "packageSha256", "package_sha256"),
    enabled: row.enabled !== false,
    domainReady: row.domainReady !== false && row.domain_ready !== false,
    templateCount: Number(row.templateCount ?? row.template_count ?? 0),
    updatedAt: field(row, "updatedAt", "updated_at"),
  };
}

function formatSize(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export default function PromotionIntegrationsPage() {
  const { can } = useAuth();
  const canManage = can("promotion.integrations.manage");
  const [rows, setRows] = useState<PromotionIntegration[]>([]);
  const [domains, setDomains] = useState<DomainOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [drawer, setDrawer] = useState(false);
  const [editing, setEditing] = useState<PromotionIntegration | null>(null);
  const [replacing, setReplacing] = useState<PromotionIntegration | null>(null);
  const [pending, setPending] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [form, setForm] = useState<IntegrationForm>(emptyForm);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [integrationPayload, domainPayload] = await Promise.all([
        apiRequest("/api/promotion/integrations"),
        apiRequest("/api/domains/available-for-channels"),
      ]);
      setRows(unwrapList<unknown>(integrationPayload).rows.map(integrationRow));
      setDomains(
        unwrapList<unknown>(domainPayload)
          .rows.map((input) => {
            const row = object(input);
            return {
              id: snowflakeId(row, "id"),
              hostname: field(row, "hostname"),
            };
          })
          .filter((row) => row.id && row.hostname),
      );
    } catch (caught) {
      setRows([]);
      setDomains([]);
      toast.error(caught instanceof Error ? caught.message : "集成列表读取失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const visible = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    if (!search) return rows;
    return rows.filter((row) =>
      `${row.name} ${row.integrationKey} ${row.hostname} ${row.entryPaths.join(" ")} ${row.type}`
        .toLowerCase()
        .includes(search),
    );
  }, [keyword, rows]);
  const pagination = useClientPagination(visible, { resetKey: keyword });

  function openCreate() {
    setEditing(null);
    setReplacing(null);
    setFile(null);
    setForm({ ...emptyForm, domainId: domains[0]?.id || "" });
    setDrawer(true);
  }

  function openEditor(row: PromotionIntegration) {
    setEditing(row);
    setReplacing(null);
    setFile(null);
    setForm({
      integrationKey: row.integrationKey,
      name: row.name,
      description: row.description,
      domainId: row.domainId,
      enabled: row.enabled,
    });
    setDrawer(true);
  }

  function openVersion(row: PromotionIntegration) {
    setEditing(null);
    setReplacing(row);
    setFile(null);
    setDrawer(true);
  }

  async function save() {
    if (!canManage) return;
    if (replacing) {
      if (!file) return;
      setPending(true);
      try {
        const body = new FormData();
        body.set("file", file);
        await apiRequest(`/api/promotion/integrations/${replacing.id}/versions`, {
          method: "POST",
          body,
        });
        setDrawer(false);
        toast.success("集成版本已更新");
        await load();
      } catch (caught) {
        toast.error(caught instanceof Error ? caught.message : "集成版本更新失败");
      } finally {
        setPending(false);
      }
      return;
    }
    if (
      !form.integrationKey.trim() ||
      !form.name.trim() ||
      !form.domainId ||
      (!editing && !file)
    ) {
      return;
    }
    setPending(true);
    try {
      if (editing) {
        await apiRequest(`/api/promotion/integrations/${editing.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            integrationKey: form.integrationKey.trim(),
            name: form.name.trim(),
            description: form.description.trim() || null,
            domainId: form.domainId,
            enabled: form.enabled,
          }),
        });
      } else {
        const body = new FormData();
        body.set("file", file as File);
        body.set("integrationKey", form.integrationKey.trim());
        body.set("name", form.name.trim());
        body.set("domainId", form.domainId);
        body.set("enabled", String(form.enabled));
        if (form.description.trim()) {
          body.set("description", form.description.trim());
        }
        await apiRequest("/api/promotion/integrations", {
          method: "POST",
          body,
        });
      }
      setDrawer(false);
      toast.success(editing ? "集成已更新" : "集成已导入");
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "集成保存失败");
    } finally {
      setPending(false);
    }
  }

  async function toggle(row: PromotionIntegration) {
    if (!canManage || !row.id) return;
    try {
      await apiRequest(`/api/promotion/integrations/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !row.enabled }),
      });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "集成状态更新失败");
    }
  }

  const createDisabled =
    pending ||
    (!replacing &&
      (!form.integrationKey.trim() ||
        !form.name.trim() ||
        !form.domainId ||
        (!editing && !file))) ||
    (Boolean(replacing) && !file);

  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: "搜索集成、标识、入口或源域名",
        }}
        meta={`${visible.length} 个集成`}
        actions={
          <>
            <Button variant="outline" onClick={() => void load()}>
              <RefreshCwIcon size={16} />
              刷新
            </Button>
            {canManage ? (
              <Button onClick={openCreate}>
                <PlusIcon size={17} />
                导入集成
              </Button>
            ) : null}
          </>
        }
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
        {loading ? (
          <div className="loading-state">
            <Spinner />
          </div>
        ) : visible.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>集成</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>源域名</TableHead>
                <TableHead>资源包</TableHead>
                <TableHead>模板</TableHead>
                <TableHead>更新时间</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pagination.rows.map((row) => (
                <TableRow key={row.readKey}>
                  <TableCell>
                    <EntityPrimaryCell
                      title={row.name}
                      id={row.id}
                      description={row.integrationKey}
                      status={{
                        label: row.enabled && row.domainReady ? "已启用" : "已停用",
                        description:
                          row.enabled && row.domainReady
                            ? "资源包可以被已绑定模板统一加载。"
                            : row.domainReady
                              ? "集成已停用，不会注入模板页面。"
                              : "源域名当前不可用，集成不会注入模板页面。",
                        tone: row.enabled && row.domainReady ? "success" : "neutral",
                        details: [
                          { label: "版本", value: row.version },
                          { label: "入口", value: row.entryPaths.length },
                          { label: "模板", value: row.templateCount },
                        ],
                      }}
                    />
                  </TableCell>
                  <TableCell>
                    <Badge tone={row.type === "iframe" ? "primary" : "info"}>
                      {row.type === "iframe" ? "iframe" : "JavaScript"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="cell-main">
                      <strong>{row.hostname}</strong>
                      <span>{row.domainReady ? "已验证" : "不可用"}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="cell-main max-w-80">
                      <strong>
                        {row.assetCount} 个文件 · {formatSize(row.totalSize)}
                      </strong>
                      <span className="truncate" title={row.entryPaths.join("、")}>
                        {row.entryPaths.length} 个入口 · {row.entryPaths.join("、")}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>{row.templateCount} 个</TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(row.updatedAt)}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      {canManage ? (
                        <>
                          <IconButton label="上传新版本" onClick={() => openVersion(row)}>
                            <UploadCloudIcon size={16} />
                          </IconButton>
                          <IconButton label="编辑集成" onClick={() => openEditor(row)}>
                            <PencilIcon size={16} />
                          </IconButton>
                          <IconButton
                            label={row.enabled ? "停用集成" : "启用集成"}
                            onClick={() => void toggle(row)}
                          >
                            {row.enabled ? (
                              <PauseIcon size={16} />
                            ) : (
                              <PlayIcon size={16} />
                            )}
                          </IconButton>
                        </>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <EmptyState
            title="还没有集成"
            description="上传第一个 ZIP 集成资源包，再从模板管理中启用。"
          />
        )}
      </ListTableCard>

      <Drawer
        open={drawer}
        onClose={() => !pending && setDrawer(false)}
        title={
          replacing
            ? `上传新版本 · ${replacing.name}`
            : editing
              ? `编辑集成 · ${editing.name}`
              : "导入集成"
        }
        description={
          replacing
            ? "完整校验新 ZIP 后原子替换资源包，失败不会影响当前版本。"
            : editing
              ? "修改管理信息不会改变已经托管的资源包。"
              : "上传 ZIP 后自动识别 iframe 或一个或多个 JavaScript 入口。"
        }
        footer={
          <>
            <Button variant="outline" disabled={pending} onClick={() => setDrawer(false)}>
              取消
            </Button>
            <Button disabled={createDisabled} onClick={() => void save()}>
              {pending ? <Spinner /> : replacing || !editing ? <UploadCloudIcon size={16} /> : <PackageIcon size={16} />}
              {replacing ? "导入新版本" : editing ? "保存集成" : "开始导入"}
            </Button>
          </>
        }
      >
        <div className="drawer-form">
          {!editing ? (
            <label className="upload-zone">
              <Input
                type="file"
                accept=".zip,application/zip"
                onChange={(event) => setFile(event.target.files?.[0] || null)}
              />
              <UploadCloudIcon size={27} />
              <strong>{file?.name || "选择集成 ZIP 文件"}</strong>
              <span>目录不限；支持多 JS、MJS 或完整 iframe 包，最大 20 MB</span>
            </label>
          ) : null}
          {!replacing ? (
            <>
              <label className="field">
                <span>集成名称</span>
                <Input
                  value={form.name}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, name: event.target.value }))
                  }
                  placeholder="例如：统一访客关联"
                />
              </label>
              <label className="field">
                <span>集成标识</span>
                <Input
                  value={form.integrationKey}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      integrationKey: event.target.value,
                    }))
                  }
                  placeholder="例如：visitor-link-v1"
                />
                <small>用于模板绑定，租户内保持唯一。</small>
              </label>
              <label className="field">
                <span>源域名</span>
                <SearchableSelect
                  value={form.domainId}
                  onValueChange={(value) =>
                    setForm((current) => ({ ...current, domainId: value }))
                  }
                  options={domains.map((domain) => ({
                    value: domain.id,
                    label: domain.hostname,
                    description: domain.id,
                  }))}
                  placeholder="选择已验证域名"
                  searchPlaceholder="搜索域名"
                  emptyText="没有可用域名，请先完成域名接入"
                  ariaLabel="源域名"
                />
                <small>系统会在这个域名下自动生成资源地址，不需要填写路径。</small>
              </label>
              <label className="field">
                <span>内部说明（可选）</span>
                <Input
                  value={form.description}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      description: event.target.value,
                    }))
                  }
                  placeholder="说明用途和适用模板"
                />
              </label>
              <label className="switch-row">
                <span>
                  <strong>启用集成</strong>
                  <small>停用后，所有绑定模板都会立即停止加载该集成。</small>
                </span>
                <Switch
                  checked={form.enabled}
                  onCheckedChange={(checked) =>
                    setForm((current) => ({ ...current, enabled: checked }))
                  }
                  aria-label="启用集成"
                />
              </label>
            </>
          ) : null}
          {!editing ? (
            <div className="rounded-lg border bg-muted/30 p-3 text-sm text-muted-foreground">
              ZIP 有唯一 HTML 入口时自动识别为 iframe；没有 HTML 时，所有 JS/MJS
              按文件名稳定排序加载。存在多个 HTML 或需要自定义脚本顺序时，可选用
              integration.json 指定 entry 或 entries。
            </div>
          ) : null}
        </div>
      </Drawer>
    </StandardListPage>
  );
}
