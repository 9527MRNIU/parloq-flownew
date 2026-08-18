import {
  PauseIcon,
  PencilIcon,
  PlayIcon,
  PlugZapIcon,
  PlusIcon,
  RefreshCwIcon,
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
  SelectField,
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
  sourcePath: string;
  sourceUrl: string;
  version: string;
  integrity: string;
  enabled: boolean;
  domainReady: boolean;
  templateCount: number;
  updatedAt?: string;
};

type DomainOption = {
  id: string;
  hostname: string;
};

const object = (input: unknown) =>
  input && typeof input === "object" ? (input as Record<string, unknown>) : {};

const field = (row: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) if (row[key] != null) return String(row[key]);
  return "";
};

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
    sourcePath: field(row, "sourcePath", "source_path"),
    sourceUrl: field(row, "sourceUrl", "source_url"),
    version: field(row, "version") || "1",
    integrity: field(row, "integrity"),
    enabled: row.enabled !== false,
    domainReady: row.domainReady !== false && row.domain_ready !== false,
    templateCount: Number(row.templateCount ?? row.template_count ?? 0),
    updatedAt: field(row, "updatedAt", "updated_at"),
  };
}

const emptyForm = {
  integrationKey: "",
  name: "",
  description: "",
  type: "iframe" as IntegrationType,
  domainId: "",
  sourcePath: "",
  version: "1",
  integrity: "",
  enabled: true,
};

export default function PromotionIntegrationsPage() {
  const { can } = useAuth();
  const canManage = can("promotion.integrations.manage");
  const [rows, setRows] = useState<PromotionIntegration[]>([]);
  const [domains, setDomains] = useState<DomainOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [drawer, setDrawer] = useState(false);
  const [editing, setEditing] = useState<PromotionIntegration | null>(null);
  const [pending, setPending] = useState(false);
  const [form, setForm] = useState(emptyForm);

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
      `${row.name} ${row.integrationKey} ${row.hostname} ${row.sourcePath} ${row.type}`
        .toLowerCase()
        .includes(search),
    );
  }, [keyword, rows]);
  const pagination = useClientPagination(visible, { resetKey: keyword });

  function openEditor(row?: PromotionIntegration) {
    setEditing(row || null);
    setForm(
      row
        ? {
            integrationKey: row.integrationKey,
            name: row.name,
            description: row.description,
            type: row.type,
            domainId: row.domainId,
            sourcePath: row.sourcePath,
            version: row.version,
            integrity: row.integrity,
            enabled: row.enabled,
          }
        : { ...emptyForm, domainId: domains[0]?.id || "" },
    );
    setDrawer(true);
  }

  async function save() {
    if (
      !canManage ||
      !form.integrationKey.trim() ||
      !form.name.trim() ||
      !form.domainId ||
      !form.sourcePath.trim()
    ) {
      return;
    }
    setPending(true);
    try {
      await apiRequest(
        editing
          ? `/api/promotion/integrations/${editing.id}`
          : "/api/promotion/integrations",
        {
          method: editing ? "PATCH" : "POST",
          body: JSON.stringify({
            integrationKey: form.integrationKey.trim(),
            name: form.name.trim(),
            description: form.description.trim() || null,
            type: form.type,
            domainId: form.domainId,
            sourcePath: form.sourcePath.trim(),
            version: form.version.trim() || "1",
            integrity:
              form.type === "script" ? form.integrity.trim() || null : null,
            enabled: form.enabled,
          }),
        },
      );
      setDrawer(false);
      toast.success(editing ? "集成已更新" : "集成已创建");
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

  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: "搜索集成、标识或源域名",
        }}
        meta={`${visible.length} 个集成`}
        actions={
          <>
            <Button variant="outline" onClick={() => void load()}>
              <RefreshCwIcon size={16} />
              刷新
            </Button>
            {canManage ? (
              <Button onClick={() => openEditor()}>
                <PlusIcon size={17} />
                新增集成
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
                <TableHead>资源路径</TableHead>
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
                            ? "集成可以被已绑定模板统一加载。"
                            : row.domainReady
                              ? "集成已停用，不会注入模板页面。"
                              : "源域名当前不可用，集成不会注入模板页面。",
                        tone: row.enabled && row.domainReady ? "success" : "neutral",
                        details: [
                          { label: "版本", value: row.version },
                          { label: "类型", value: row.type },
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
                    <span className="block max-w-72 truncate" title={row.sourceUrl}>
                      {row.sourcePath}
                    </span>
                  </TableCell>
                  <TableCell>{row.templateCount} 个</TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(row.updatedAt)}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      {canManage ? (
                        <>
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
            description="创建第一个平台托管集成，再从模板管理中启用。"
          />
        )}
      </ListTableCard>

      <Drawer
        open={drawer}
        onClose={() => !pending && setDrawer(false)}
        title={editing ? `编辑集成 · ${editing.name}` : "新增集成"}
        description="绑定已验证源域名，并定义平台统一分发的资源路径。"
        footer={
          <>
            <Button
              variant="outline"
              disabled={pending}
              onClick={() => setDrawer(false)}
            >
              取消
            </Button>
            <Button
              disabled={
                pending ||
                !form.integrationKey.trim() ||
                !form.name.trim() ||
                !form.domainId ||
                !form.sourcePath.trim()
              }
              onClick={() => void save()}
            >
              {pending ? <Spinner /> : <PlugZapIcon size={16} />}
              保存集成
            </Button>
          </>
        }
      >
        <div className="drawer-form">
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
            <small>用于模板绑定和版本识别，租户内保持唯一。</small>
          </label>
          <label className="field">
            <span>集成类型</span>
            <SelectField
              value={form.type}
              onValueChange={(value) =>
                setForm((current) => ({
                  ...current,
                  type: value as IntegrationType,
                  integrity: value === "iframe" ? "" : current.integrity,
                }))
              }
              options={[
                { value: "iframe", label: "隐藏 iframe" },
                { value: "script", label: "外部 JavaScript" },
              ]}
            />
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
          </label>
          <label className="field">
            <span>资源路径</span>
            <Input
              value={form.sourcePath}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  sourcePath: event.target.value,
                }))
              }
              placeholder={
                form.type === "iframe" ? "/runtime/frame" : "/runtime/shared.js"
              }
            />
            <small>必须以 / 开头，最终地址由源域名和资源路径组合。</small>
          </label>
          <label className="field">
            <span>版本</span>
            <Input
              value={form.version}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  version: event.target.value,
                }))
              }
              placeholder="1.0.0"
            />
          </label>
          {form.type === "script" ? (
            <label className="field">
              <span>SRI 完整性校验（可选）</span>
              <Input
                value={form.integrity}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    integrity: event.target.value,
                  }))
                }
                placeholder="sha256-..."
              />
            </label>
          ) : null}
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
        </div>
      </Drawer>
    </StandardListPage>
  );
}
