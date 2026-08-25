import {
  ExternalLinkIcon,
  LoaderCircleIcon,
  PlusIcon,
  RefreshCwIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import { apiRequest, formatDateTime, unwrapList } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import {
  DrawerFormField,
  DrawerFormLayout,
  DrawerFormSection,
} from "../components/drawer-form";
import { EntityPrimaryCell } from "../components/entity-primary-cell";
import {
  ListPagination,
  ListSortableHead,
  ListTableCard,
  ListToolbar,
  StandardListPage,
  type ListSortOrder,
} from "../components/list-page";
import {
  Badge,
  Button,
  confirmAction,
  Drawer,
  EmptyState,
  Input,
  SelectField,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Textarea,
  toast,
} from "../components/ui";
import { entityRowKey, snowflakeId } from "../lib/entity-identifiers";

type ProtocolDefinition = {
  id: string;
  readKey: string;
  name: string;
  adapterKey: string;
  repositoryUrl: string;
  packageName: string;
  version: string;
  upstreamRef: string;
  buildStatus:
    | "pending"
    | "building"
    | "ready"
    | "failed"
    | "requires_adaptation"
    | "disabled";
  contractVersion: number;
  enabled: boolean;
  builtin: boolean;
  remark: string;
  nodeCount: number;
  runtimeInstalled: boolean;
  runtimeActive: boolean;
  runtimeEngine: string;
  currentWebRevision: string;
  versionCategory: VersionCategory;
  remoteLatestVersion: string;
  upstreamCheckedAt: string;
  upstreamError: string;
  buildErrorCode: string;
  buildErrorMessage: string;
  latestBuild: {
    status: string;
    attemptNumber: number;
    errorMessage: string;
  } | null;
  createdAt: string;
};

type VersionCategory = "stable" | "preview";

type ProtocolDefinitionSortBy =
  | "id"
  | "packageName"
  | "version"
  | "remoteLatestVersion"
  | "buildStatus"
  | "nodeCount"
  | "contractVersion"
  | "createdAt";

type AvailableVersion = {
  version: string;
  category: VersionCategory;
  tags: string[];
};

const value = (row: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) if (row[key] != null) return row[key];
  return undefined;
};
const text = (row: Record<string, unknown>, ...keys: string[]) => {
  const found = value(row, ...keys);
  return found == null ? "" : String(found);
};
const number = (row: Record<string, unknown>, ...keys: string[]) => {
  const parsed = Number(value(row, ...keys));
  return Number.isFinite(parsed) ? parsed : 0;
};

function protocolDefinition(input: unknown): ProtocolDefinition {
  const row = input as Record<string, unknown>;
  const id = snowflakeId(row, "id");
  return {
    id,
    readKey: entityRowKey(
      row,
      id,
      "protocol-definition",
      `${text(row, "name")}:${text(row, "version")}`,
    ),
    name: text(row, "name"),
    adapterKey: text(row, "adapterKey", "adapter_key"),
    repositoryUrl: text(row, "repositoryUrl", "repository_url"),
    packageName: text(row, "packageName", "package_name"),
    version: text(row, "version"),
    upstreamRef: text(row, "upstreamRef", "upstream_ref"),
    buildStatus: (text(row, "buildStatus", "build_status") ||
      "pending") as ProtocolDefinition["buildStatus"],
    contractVersion: number(row, "contractVersion", "contract_version"),
    enabled: Boolean(value(row, "enabled")),
    builtin: Boolean(value(row, "builtin", "isBuiltin", "is_builtin")),
    remark: text(row, "remark"),
    nodeCount: number(row, "nodeCount", "node_count"),
    runtimeInstalled: Boolean(
      value(row, "runtimeInstalled", "runtime_installed"),
    ),
    runtimeActive: Boolean(value(row, "runtimeActive", "runtime_active")),
    runtimeEngine: text(row, "runtimeEngine", "runtime_engine"),
    currentWebRevision: text(
      row,
      "currentWebRevision",
      "current_web_revision",
    ),
    versionCategory:
      text(row, "versionCategory", "version_category") === "preview"
        ? "preview"
        : "stable",
    remoteLatestVersion: text(
      row,
      "remoteLatestVersion",
      "remote_latest_version",
    ),
    upstreamCheckedAt: text(
      row,
      "upstreamCheckedAt",
      "upstream_checked_at",
    ),
    upstreamError: text(row, "upstreamError", "upstream_error"),
    buildErrorCode: text(row, "buildErrorCode", "build_error_code"),
    buildErrorMessage: text(row, "buildErrorMessage", "build_error_message"),
    latestBuild: (() => {
      const raw = value(row, "latestBuild", "latest_build");
      if (!raw || typeof raw !== "object") return null;
      const build = raw as Record<string, unknown>;
      return {
        status: text(build, "status"),
        attemptNumber: number(build, "attemptNumber", "attempt_number"),
        errorMessage: text(build, "errorMessage", "error_message"),
      };
    })(),
    createdAt: text(row, "createdAt", "created_at"),
  };
}

function buildBadge(status: ProtocolDefinition["buildStatus"]) {
  if (status === "ready") return { label: "构建完成", tone: "success" as const };
  if (status === "building") return { label: "构建中", tone: "warning" as const };
  if (status === "failed") return { label: "构建失败", tone: "danger" as const };
  if (status === "requires_adaptation")
    return { label: "需要适配", tone: "warning" as const };
  if (status === "disabled") return { label: "已停用", tone: "neutral" as const };
  return { label: "排队中", tone: "neutral" as const };
}

export function ProtocolDefinitionsPage({
  toolbarTabs,
}: {
  toolbarTabs?: ReactNode;
} = {}) {
  const { can } = useAuth();
  const navigate = useNavigate();
  const canManage = can("resources.protocol.manage");
  const [rows, setRows] = useState<ProtocolDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [keyword, setKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [sortBy, setSortBy] = useState<ProtocolDefinitionSortBy>("id");
  const [sortOrder, setSortOrder] = useState<ListSortOrder>("desc");
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [availableVersions, setAvailableVersions] = useState<AvailableVersion[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [versionsError, setVersionsError] = useState("");
  const [versionCategory, setVersionCategory] =
    useState<VersionCategory>("stable");
  const versionRequest = useRef(0);
  const [form, setForm] = useState({
    name: "Baileys Web协议",
    adapterKey: "baileys",
    repositoryUrl: "https://github.com/WhiskeySockets/Baileys",
    packageName: "@whiskeysockets/baileys",
    version: "",
    upstreamRef: "",
    remark: "",
  });

  const load = useCallback(async (silent = false) => {
    if (!silent) {
      setLoading(true);
      setError("");
    }
    try {
      const query = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
      if (debouncedKeyword) query.set("keyword", debouncedKeyword);
      query.set("sortBy", sortBy);
      query.set("sortOrder", sortOrder);
      const payload = await apiRequest(`/api/protocol-definitions?${query}`);
      const list = unwrapList<unknown>(payload);
      setRows(list.rows.map(protocolDefinition));
      setTotal(list.total);
    } catch (caught) {
      if (!silent) {
        setRows([]);
        setTotal(0);
        setError(caught instanceof Error ? caught.message : "协议加载失败");
      }
    } finally {
      if (!silent) setLoading(false);
    }
  }, [debouncedKeyword, page, pageSize, sortBy, sortOrder]);

  useEffect(() => void load(), [load]);

  const hasActiveBuild = rows.some(
    (row) => row.buildStatus === "pending" || row.buildStatus === "building",
  );
  useEffect(() => {
    if (!hasActiveBuild) return;
    const timer = window.setInterval(() => void load(true), 2000);
    return () => window.clearInterval(timer);
  }, [hasActiveBuild, load]);

  const loadAvailableVersions = useCallback(async (packageName: string) => {
    const request = ++versionRequest.current;
    setVersionsLoading(true);
    setVersionsError("");
    try {
      const payload = await apiRequest(
        `/api/protocol-definitions/available-versions?packageName=${encodeURIComponent(packageName)}`,
      );
      if (request !== versionRequest.current) return;
      const nextVersions = unwrapList<unknown>(payload).rows
        .map((item): AvailableVersion => {
          const row = item as Record<string, unknown>;
          const tags = value(row, "tags");
          return {
            version: text(row, "version"),
            category:
              text(row, "category") === "preview" ? "preview" : "stable",
            tags: Array.isArray(tags) ? tags.map(String) : [],
          };
        })
        .filter((item) => item.version);
      setAvailableVersions(nextVersions);
      setForm((current) =>
        current.packageName.trim() === packageName &&
        current.version &&
        !nextVersions.some((item) => item.version === current.version)
          ? { ...current, version: "" }
          : current,
      );
    } catch (caught) {
      if (request !== versionRequest.current) return;
      setAvailableVersions([]);
      setVersionsError(
        caught instanceof Error ? caught.message : "远程版本读取失败",
      );
    } finally {
      if (request === versionRequest.current) setVersionsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!creating) return;
    const packageName = form.packageName.trim();
    if (!packageName) {
      setAvailableVersions([]);
      setVersionsError("");
      return;
    }
    const timer = window.setTimeout(
      () => void loadAvailableVersions(packageName),
      350,
    );
    return () => window.clearTimeout(timer);
  }, [creating, form.packageName, loadAvailableVersions]);

  const filteredVersions = useMemo(
    () =>
      availableVersions.filter((item) => item.category === versionCategory),
    [availableVersions, versionCategory],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedKeyword(keyword.trim());
      setPage(1);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [keyword]);

  function changeSort(nextSortBy: ProtocolDefinitionSortBy, nextSortOrder: ListSortOrder) {
    setSortBy(nextSortBy);
    setSortOrder(nextSortOrder);
    setPage(1);
  }

  function openCreate() {
    setForm({
      name: "Baileys Web协议",
      adapterKey: "baileys",
      repositoryUrl: "https://github.com/WhiskeySockets/Baileys",
      packageName: "@whiskeysockets/baileys",
      version: "",
      upstreamRef: "",
      remark: "",
    });
    setAvailableVersions([]);
    setVersionsError("");
    setVersionCategory("stable");
    setCreating(true);
  }

  function openUpdate(row: ProtocolDefinition) {
    if (!row.remoteLatestVersion || row.remoteLatestVersion === row.version) return;
    setForm({
      name: row.name,
      adapterKey: row.adapterKey,
      repositoryUrl: row.repositoryUrl,
      packageName: row.packageName,
      version: row.remoteLatestVersion,
      upstreamRef: "",
      remark: row.remark,
    });
    setAvailableVersions([]);
    setVersionsError("");
    setVersionCategory(row.versionCategory);
    setCreating(true);
  }

  async function save() {
    if (!form.name.trim() || !form.version.trim()) return;
    setSaving(true);
    try {
      await apiRequest("/api/protocol-definitions", {
        method: "POST",
        body: JSON.stringify({
          name: form.name.trim(),
          adapterKey: form.adapterKey,
          repositoryUrl: form.repositoryUrl.trim(),
          packageName: form.packageName.trim(),
          version: form.version.trim(),
          upstreamRef: form.upstreamRef.trim() || null,
          remark: form.remark.trim() || null,
        }),
      });
      setCreating(false);
      toast.success("协议已创建，正在自动构建");
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "协议创建失败");
    } finally {
      setSaving(false);
    }
  }

  async function remove(row: ProtocolDefinition) {
    if (
      !(await confirmAction({
        title: `删除协议“${row.name} · ${row.version}”？`,
        description: "只允许删除未被节点使用的非内置协议。",
        confirmText: "确认删除",
        destructive: true,
      }))
    )
      return;
    try {
      await apiRequest(`/api/protocol-definitions/${row.id}`, {
        method: "DELETE",
      });
      toast.success("协议已删除");
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "协议删除失败");
    }
  }

  async function retryBuild(row: ProtocolDefinition) {
    try {
      await apiRequest(`/api/protocol-definitions/${row.id}/builds`, {
        method: "POST",
      });
      toast.success("协议已重新加入构建队列");
      await load(true);
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "重新构建失败");
    }
  }

  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: "搜索协议、仓库、版本或 ID",
        }}
        filters={toolbarTabs}
        meta={`${total} 个协议`}
        actions={
          <>
            <Button disabled={!canManage} onClick={openCreate}>
              <PlusIcon size={16} />新建协议
            </Button>
            <Button variant="outline" disabled={loading} onClick={() => void load()}>
              <RefreshCwIcon size={16} className={loading ? "spin" : ""} />
              检查更新
            </Button>
          </>
        }
      />
      <ListPagination
        page={page}
        pageSize={pageSize}
        total={total}
        disabled={loading}
        onPageChange={setPage}
        onPageSizeChange={(value) => { setPageSize(value); setPage(1); }}
      />
      <ListTableCard>
        {loading ? (
          <div className="loading-state"><Spinner />正在加载协议…</div>
        ) : error ? (
          <div className="error-state">
            <strong>协议加载失败</strong><span>{error}</span>
            <Button variant="outline" onClick={() => void load()}>重试</Button>
          </div>
        ) : rows.length ? (
          <Table layout="list">
            <TableHeader>
              <TableRow>
                <ListSortableHead sortKey="id" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort}>协议</ListSortableHead>
                <ListSortableHead sortKey="packageName" activeSortKey={sortBy} sortOrder={sortOrder} onSort={changeSort}>实现仓库</ListSortableHead>
                <ListSortableHead sortKey="version" activeSortKey={sortBy} sortOrder={sortOrder} onSort={changeSort}>当前版本</ListSortableHead>
                <ListSortableHead sortKey="remoteLatestVersion" activeSortKey={sortBy} sortOrder={sortOrder} onSort={changeSort}>远程版本</ListSortableHead>
                <ListSortableHead sortKey="buildStatus" activeSortKey={sortBy} sortOrder={sortOrder} onSort={changeSort}>构建状态</ListSortableHead>
                <ListSortableHead sortKey="nodeCount" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort}>节点数</ListSortableHead>
                <ListSortableHead sortKey="contractVersion" activeSortKey={sortBy} sortOrder={sortOrder} onSort={changeSort}>契约版本</ListSortableHead>
                <TableHead adaptive>备注</TableHead>
                <ListSortableHead sortKey="createdAt" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort}>创建时间</ListSortableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.readKey}>
                  <TableCell primary>
                    <EntityPrimaryCell
                      title={row.name}
                      id={row.id}
                      status={{
                        label: row.enabled ? "已启用" : "已停用",
                        description: row.enabled
                          ? "该协议可以在构建完成后用于创建节点。"
                          : "该协议已停止创建新节点。",
                        tone: row.enabled ? "success" : "neutral",
                      }}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="grid min-w-max gap-1">
                      <a
                        className="inline-flex items-center gap-1 hover:underline"
                        href={row.repositoryUrl}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {row.packageName}<ExternalLinkIcon size={13} />
                      </a>
                      <span className="text-xs text-muted-foreground">
                        适配器 {row.adapterKey}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="mx-auto grid min-w-max justify-items-center gap-1 text-center">
                      <span className="font-mono">{row.version}</span>
                      {row.runtimeActive ? (
                        <Badge tone="success">当前运行</Badge>
                      ) : row.runtimeInstalled ? (
                        <Badge tone="neutral">运行包就绪</Badge>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="grid min-w-max gap-1.5" title={row.upstreamError || undefined}>
                      <div className="flex items-center gap-2">
                        <Badge tone={row.versionCategory === "stable" ? "success" : "warning"}>
                          {row.versionCategory === "stable" ? "稳定" : "预览"}
                        </Badge>
                        <span className="font-mono">{row.remoteLatestVersion || "-"}</span>
                      </div>
                      <span className="text-xs text-muted-foreground">
                        {row.upstreamCheckedAt
                          ? formatDateTime(row.upstreamCheckedAt)
                          : "尚未检查"}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div
                      className="grid min-w-max gap-1"
                      title={row.buildErrorMessage || undefined}
                    >
                      <Badge tone={buildBadge(row.buildStatus).tone}>
                        {buildBadge(row.buildStatus).label}
                      </Badge>
                      {row.latestBuild?.attemptNumber ? (
                        <span className="text-xs text-muted-foreground">
                          第 {row.latestBuild.attemptNumber} 次
                        </span>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>{row.nodeCount.toLocaleString()}</TableCell>
                  <TableCell>v{row.contractVersion}</TableCell>
                  <TableCell className="max-w-0">
                    <span className="block w-full truncate text-muted-foreground" title={row.remark}>
                      {row.remark || "-"}
                    </span>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(row.createdAt)}
                  </TableCell>
                  <TableCell>
                    <div className="flex min-w-max justify-end gap-2">
                      {row.buildStatus === "ready" && row.enabled ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            navigate(
                              `/resources/operations/protocol-center?tab=nodes&create=1&protocolDefinitionId=${row.id}`,
                            )
                          }
                        >
                          新建节点
                        </Button>
                      ) : null}
                      {canManage &&
                      row.remoteLatestVersion &&
                      row.remoteLatestVersion !== row.version ? (
                        <Button variant="outline" size="sm" onClick={() => openUpdate(row)}>
                          更新协议
                        </Button>
                      ) : null}
                      {canManage &&
                      !row.builtin &&
                      (row.buildStatus === "failed" ||
                        row.buildStatus === "requires_adaptation") ? (
                        <Button variant="outline" size="sm" onClick={() => void retryBuild(row)}>
                          重新构建
                        </Button>
                      ) : null}
                      {canManage && !row.builtin ? (
                        <Button variant="destructive" size="sm" onClick={() => void remove(row)}>
                          删除
                        </Button>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <EmptyState
            title={keyword.trim() ? "没有符合条件的协议" : "暂无协议"}
            description="从实现仓库和具体版本创建协议，构建完成后即可用于新建节点。"
          />
        )}
      </ListTableCard>

      <Drawer
        open={creating}
        onClose={() => !saving && setCreating(false)}
        title="新建协议"
        description="选择远程版本后，系统会自动拉取、校验并构建独立运行包。构建完成后才能创建节点。"
        footer={
          <>
            <Button variant="outline" disabled={saving} onClick={() => setCreating(false)}>
              取消
            </Button>
            <Button
              disabled={saving || !form.name.trim() || !form.version.trim()}
              onClick={() => void save()}
            >
              {saving ? <LoaderCircleIcon className="spin" size={16} /> : null}
              创建协议
            </Button>
          </>
        }
      >
        <DrawerFormLayout>
          <DrawerFormSection title="协议标识" hideHeader>
            <DrawerFormField label="协议名称" required>
              <Input
                maxLength={64}
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              />
            </DrawerFormField>
            <DrawerFormField label="适配器" required hint="第一版使用系统已有的 BaileysEngine 适配器。">
              <SelectField
                className="w-full"
                value={form.adapterKey}
                disabled
                onValueChange={(adapterKey) => setForm((current) => ({ ...current, adapterKey }))}
                options={[{ value: "baileys", label: "Baileys" }]}
              />
            </DrawerFormField>
          </DrawerFormSection>
          <DrawerFormSection title="上游实现">
            <DrawerFormField label="实现仓库" required>
              <Input
                value={form.repositoryUrl}
                readOnly
              />
            </DrawerFormField>
            <DrawerFormField label="NPM 软件包" required>
              <Input
                value={form.packageName}
                readOnly
              />
            </DrawerFormField>
            <DrawerFormField
              label="版本类型"
              required
              hint="只用于筛选远程版本，不会保存为单独的协议字段。"
            >
              <SelectField
                className="w-full"
                value={versionCategory}
                onValueChange={(nextValue) => {
                  const nextCategory = nextValue as VersionCategory;
                  setVersionCategory(nextCategory);
                  setForm((current) =>
                    availableVersions.some(
                      (item) =>
                        item.category === nextCategory &&
                        item.version === current.version,
                    )
                      ? current
                      : { ...current, version: "" },
                  );
                }}
                options={[
                  { value: "stable", label: "稳定版" },
                  { value: "preview", label: "预览版" },
                ]}
              />
            </DrawerFormField>
            <DrawerFormField
              label="版本"
              required
              hint={
                versionsError ||
                (filteredVersions.length
                  ? `已读取 ${filteredVersions.length} 个${
                      versionCategory === "stable" ? "稳定版" : "预览版"
                    }。`
                  : "根据 NPM 软件包自动读取可用版本。")
              }
            >
              <SelectField
                className="w-full"
                value={form.version}
                disabled={versionsLoading || !filteredVersions.length}
                placeholder={
                  versionsLoading
                    ? "正在读取远程版本…"
                    : versionsError
                      ? "远程版本读取失败"
                      : filteredVersions.length
                        ? "请选择远程版本"
                        : `暂无${versionCategory === "stable" ? "稳定版" : "预览版"}`
                }
                onValueChange={(version) =>
                  setForm((current) => ({ ...current, version }))
                }
                options={filteredVersions.map((item) => ({
                  value: item.version,
                  label: `${item.version}${
                    item.tags.length ? ` · ${item.tags.join(" / ")}` : ""
                  }`,
                }))}
              />
            </DrawerFormField>
          </DrawerFormSection>
          <DrawerFormSection title="备注">
            <DrawerFormField label="备注内容" align="start" meta={`${form.remark.length}/512`}>
              <Textarea
                rows={5}
                maxLength={512}
                value={form.remark}
                onChange={(event) => setForm((current) => ({ ...current, remark: event.target.value }))}
              />
            </DrawerFormField>
          </DrawerFormSection>
        </DrawerFormLayout>
      </Drawer>
    </StandardListPage>
  );
}
