import {
  DownloadIcon,
  PackageIcon,
  PlusIcon,
  RefreshCwIcon,
  UploadCloudIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiRequest, formatDateTime, unwrapList } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EntityPrimaryCell } from "../components/entity-primary-cell";
import { DrawerFieldLabel } from "../components/drawer-form";
import { RepositorySourceTabs } from "../components/repository-source-tabs";
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
  confirmAction,
  toast,
} from "../components/ui";
import { entityRowKey, snowflakeId } from "../lib/entity-identifiers";
import {
  formatRepositorySize,
  localRepositorySourceRow,
  remotePromotionArtifactRow,
  type LocalRepositorySource,
  type RemotePromotionArtifact,
  type RepositoryView,
} from "../lib/promotion-repository";

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
  feedbackEnabled: boolean;
  feedbackEvents: string[];
  eventCount: number;
  lastEventAt?: string;
  repositorySource: LocalRepositorySource | null;
  createdAt?: string;
  updatedAt?: string;
};

type IntegrationEvent = {
  id: string;
  eventType: string;
  channelId: string;
  channelSlug: string;
  integrationVersion: string;
  visitorId: string;
  fingerprintQuality: string;
  trafficSource: string;
  occurredAt?: string;
  metadata: Record<string, unknown>;
};

type IntegrationEventSummary = {
  eventType: string;
  count: number;
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
    feedbackEnabled: row.feedbackEnabled === true || row.feedback_enabled === true,
    feedbackEvents: stringList(row.feedbackEvents ?? row.feedback_events),
    eventCount: Number(row.eventCount ?? row.event_count ?? 0),
    lastEventAt: field(row, "lastEventAt", "last_event_at"),
    repositorySource: localRepositorySourceRow(
      row.repositorySource ?? row.repository_source,
    ),
    createdAt: field(row, "createdAt", "created_at"),
    updatedAt: field(row, "updatedAt", "updated_at"),
  };
}

function eventRow(input: unknown): IntegrationEvent {
  const row = object(input);
  return {
    id: snowflakeId(row, "id"),
    eventType: field(row, "eventType", "event_type"),
    channelId: snowflakeId(row, "channelId", "channel_id"),
    channelSlug: field(row, "channelSlug", "channel_slug"),
    integrationVersion: field(row, "integrationVersion", "integration_version"),
    visitorId: field(row, "visitorId", "visitor_id"),
    fingerprintQuality: field(row, "fingerprintQuality", "fingerprint_quality"),
    trafficSource: field(row, "trafficSource", "traffic_source") || "direct",
    occurredAt: field(row, "occurredAt", "occurred_at"),
    metadata: object(row.metadata),
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
  const [view, setView] = useState<RepositoryView>("local");
  const [repositoryRows, setRepositoryRows] = useState<RemotePromotionArtifact[]>([]);
  const [repositoryLoading, setRepositoryLoading] = useState(false);
  const [repositoryRefreshing, setRepositoryRefreshing] = useState(false);
  const repositoryRefreshActive = useRef(false);
  const [repositoryError, setRepositoryError] = useState("");
  const [repositoryPending, setRepositoryPending] = useState("");
  const [repositoryImporting, setRepositoryImporting] =
    useState<RemotePromotionArtifact | null>(null);
  const [repositoryDomainId, setRepositoryDomainId] = useState("");
  const [repositoryEnabled, setRepositoryEnabled] = useState(true);
  const [domains, setDomains] = useState<DomainOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [drawer, setDrawer] = useState(false);
  const [editing, setEditing] = useState<PromotionIntegration | null>(null);
  const [pending, setPending] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [packageInspecting, setPackageInspecting] = useState(false);
  const packageInspectionRequest = useRef(0);
  const [form, setForm] = useState<IntegrationForm>(emptyForm);
  const [eventIntegration, setEventIntegration] =
    useState<PromotionIntegration | null>(null);
  const [eventRows, setEventRows] = useState<IntegrationEvent[]>([]);
  const [eventSummary, setEventSummary] = useState<IntegrationEventSummary[]>([]);
  const [eventTotal, setEventTotal] = useState(0);
  const [eventPage, setEventPage] = useState(1);
  const [eventPageSize, setEventPageSize] = useState(20);
  const [eventsLoading, setEventsLoading] = useState(false);

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

  const loadRepository = useCallback(async ({
    refresh = false,
    preserve = false,
  }: {
    refresh?: boolean;
    preserve?: boolean;
  } = {}) => {
    if (refresh && repositoryRefreshActive.current) {
      return { ok: false, cacheHit: true };
    }
    if (refresh) repositoryRefreshActive.current = true;
    if (preserve) setRepositoryRefreshing(true);
    else {
      setRepositoryLoading(true);
      setRepositoryError("");
    }
    try {
      const payload = await apiRequest(
        `/api/promotion/integrations/repository${refresh ? "/refresh" : ""}`,
        {
          method: refresh ? "POST" : "GET",
        },
      );
      const data = object(object(payload).data ?? payload);
      const nextRows = unwrapList<unknown>(payload).rows.map(remotePromotionArtifactRow);
      setRepositoryRows(nextRows);
      setRepositoryError("");
      return { ok: true, cacheHit: data.cacheHit === true };
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "远程仓库读取失败";
      if (preserve) toast.error(`仓库刷新失败，当前显示上次缓存：${message}`);
      else {
        setRepositoryRows([]);
        setRepositoryError(message);
      }
      return { ok: false, cacheHit: false };
    } finally {
      if (refresh) repositoryRefreshActive.current = false;
      if (preserve) setRepositoryRefreshing(false);
      else setRepositoryLoading(false);
    }
  }, []);

  function changeView(next: RepositoryView) {
    setView(next);
    if (next !== "repository") return;
    void (async () => {
      const cached = await loadRepository({ preserve: repositoryRows.length > 0 });
      if (!cached.ok || !cached.cacheHit) return;
      const refreshed = await loadRepository({ refresh: true, preserve: true });
      if (refreshed.ok) await load();
    })();
  }

  const loadEvents = useCallback(
    async (row: PromotionIntegration, page: number, pageSize: number) => {
      setEventsLoading(true);
      try {
        const payload = await apiRequest(
          `/api/promotion/integrations/${row.id}/events?page=${page}&perPage=${pageSize}`,
        );
        const data = object(object(payload).data);
        setEventRows(
          (Array.isArray(data.rows) ? data.rows : []).map(eventRow),
        );
        setEventSummary(
          (Array.isArray(data.summary) ? data.summary : []).map((input) => {
            const summary = object(input);
            return {
              eventType: field(summary, "eventType", "event_type"),
              count: Number(summary.count || 0),
            };
          }),
        );
        setEventTotal(Number(data.total || 0));
      } catch (caught) {
        setEventRows([]);
        setEventSummary([]);
        setEventTotal(0);
        toast.error(caught instanceof Error ? caught.message : "回传记录读取失败");
      } finally {
        setEventsLoading(false);
      }
    },
    [],
  );

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
  const repositoryVisible = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    if (!search) return repositoryRows;
    return repositoryRows.filter((row) =>
      `${row.sequence} ${row.name} ${row.description} ${row.slug} ${row.integrationKey} ${row.version}`
        .toLowerCase()
        .includes(search),
    );
  }, [keyword, repositoryRows]);
  const repositoryPagination = useClientPagination(repositoryVisible, {
    resetKey: keyword,
  });

  async function importRepositoryIntegration(
    row: Pick<RemotePromotionArtifact, "sequence">,
    domainId?: string,
  ) {
    if (!canManage || repositoryPending) return;
    setRepositoryPending(row.sequence);
    try {
      const payload = await apiRequest(
        `/api/promotion/integrations/repository/${row.sequence}/import`,
        {
          method: "POST",
          body: JSON.stringify({
            ...(domainId ? { domainId } : {}),
            enabled: repositoryEnabled,
          }),
        },
      );
      const data = object(object(payload).data ?? payload);
      const action = field(data, "action");
      setRepositoryImporting(null);
      toast.success(action === "updated" ? "远程集成已更新" : "远程集成已添加到本地");
      await Promise.all([load(), loadRepository()]);
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "远程集成导入失败");
    } finally {
      setRepositoryPending("");
    }
  }

  function beginRepositoryImport(row: RemotePromotionArtifact) {
    if (row.localStatus === "update") {
      void importRepositoryIntegration(row);
      return;
    }
    setRepositoryDomainId(domains[0]?.id || "");
    setRepositoryEnabled(true);
    setRepositoryImporting(row);
  }

  async function chooseIntegrationPackage(next: File | null) {
    const requestId = ++packageInspectionRequest.current;
    setFile(next);
    if (!next || editing) {
      setPackageInspecting(false);
      return;
    }
    setPackageInspecting(true);
    try {
      const body = new FormData();
      body.set("file", next);
      const payload = await apiRequest(
        "/api/promotion/integrations/package-metadata",
        { method: "POST", body },
      );
      if (requestId !== packageInspectionRequest.current) return;
      const data = object(object(payload).data ?? payload);
      const metadata = object(data.metadata ?? data);
      setForm((current) => ({
        ...current,
        integrationKey: field(metadata, "integrationKey", "integration_key"),
        name: field(metadata, "name"),
        description: field(metadata, "description"),
      }));
    } catch (caught) {
      if (requestId !== packageInspectionRequest.current) return;
      setForm((current) => ({
        ...current,
        integrationKey: "",
        name: "",
        description: "",
      }));
      toast.error(
        caught instanceof Error ? caught.message : "集成 ZIP 元数据读取失败",
      );
    } finally {
      if (requestId === packageInspectionRequest.current) {
        setPackageInspecting(false);
      }
    }
  }

  function openCreate() {
    packageInspectionRequest.current += 1;
    setPackageInspecting(false);
    setEditing(null);
    setFile(null);
    setForm({ ...emptyForm, domainId: domains[0]?.id || "" });
    setDrawer(true);
  }

  function openEditor(row: PromotionIntegration) {
    packageInspectionRequest.current += 1;
    setPackageInspecting(false);
    setEditing(row);
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

  function openEvents(row: PromotionIntegration) {
    setEventIntegration(row);
    setEventPage(1);
    void loadEvents(row, 1, eventPageSize);
  }

  async function save() {
    if (!canManage) return;
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
      const body = new FormData();
      if (file) body.set("file", file);
      body.set("integrationKey", form.integrationKey.trim());
      body.set("name", form.name.trim());
      body.set("domainId", form.domainId);
      body.set("enabled", String(form.enabled));
      body.set("description", form.description.trim());
      await apiRequest(
        editing
          ? `/api/promotion/integrations/${editing.id}/edit`
          : "/api/promotion/integrations",
        {
          method: "POST",
          body,
        },
      );
      setDrawer(false);
      toast.success(
        editing
          ? file
            ? "集成及资源包已更新"
            : "集成已保存"
          : "集成已导入",
      );
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

  async function remove(row: PromotionIntegration) {
    if (!canManage || !row.id) return;
    if (!(await confirmAction({
      title: `删除集成“${row.name}”？`,
      description: "删除后资源包、模板绑定和本地回传记录会一并删除，且无法恢复。",
      confirmText: "确认删除",
      destructive: true,
    }))) return;
    try {
      await apiRequest(`/api/promotion/integrations/${row.id}`, { method: "DELETE" });
      toast.success("集成已删除");
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "集成删除失败");
    }
  }

  const createDisabled =
    pending ||
    packageInspecting ||
    !form.integrationKey.trim() ||
    !form.name.trim() ||
    !form.domainId ||
    (!editing && !file);

  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder:
            view === "local"
              ? "搜索集成、标识、入口或源域名"
              : "搜索远程集成名称、编号或标识",
        }}
        filters={
          <RepositorySourceTabs
            value={view}
            localLabel="本地集成"
            onChange={changeView}
          />
        }
        meta={`${view === "local" ? visible.length : repositoryVisible.length} 个集成`}
        actions={
          <>
            <Button
              variant={view === "repository" ? "default" : "outline"}
              disabled={view === "repository" && (repositoryLoading || repositoryRefreshing)}
              onClick={() => {
                if (view === "local") void load();
                else void (async () => {
                  const refreshed = await loadRepository({ refresh: true, preserve: true });
                  if (refreshed.ok) await load();
                })();
              }}
            >
              {repositoryRefreshing ? <Spinner /> : <RefreshCwIcon size={16} />}
              {view === "local" ? "刷新" : "刷新仓库"}
            </Button>
            {canManage && view === "local" ? (
              <Button onClick={openCreate}>
                <PlusIcon size={17} />
                导入集成
              </Button>
            ) : null}
          </>
        }
      />
      <ListPagination
        page={view === "local" ? pagination.page : repositoryPagination.page}
        pageSize={view === "local" ? pagination.pageSize : repositoryPagination.pageSize}
        total={view === "local" ? pagination.total : repositoryPagination.total}
        disabled={view === "local" ? loading : repositoryLoading}
        onPageChange={view === "local" ? pagination.setPage : repositoryPagination.setPage}
        onPageSizeChange={view === "local" ? pagination.setPageSize : repositoryPagination.setPageSize}
      />
      <ListTableCard>
        {view === "repository" ? (
          repositoryLoading ? (
            <div className="loading-state">
              <Spinner />
            </div>
          ) : repositoryError ? (
            <EmptyState
              title="远程仓库暂不可用"
              description={repositoryError}
            />
          ) : repositoryVisible.length ? (
            <Table layout="list">
              <TableHeader>
                <TableRow>
                  <TableHead>远程集成</TableHead>
                  <TableHead adaptive>备注</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>版本</TableHead>
                  <TableHead>源码目录</TableHead>
                  <TableHead>资源</TableHead>
                  <TableHead>本地状态</TableHead>
                  <TableHead>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {repositoryPagination.rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>
                      <EntityPrimaryCell
                        title={`${row.sequence} · ${row.name}`}
                        showId={false}
                        description={row.integrationKey}
                        status={{
                          label: "远程仓库",
                          description: "此集成来自已配置的 GitHub 私人仓库。",
                          tone: "neutral",
                          details: [
                            { label: "版本", value: row.version },
                            { label: "文件", value: row.fileCount },
                            { label: "分支", value: row.ref },
                          ],
                        }}
                      />
                    </TableCell>
                    <TableCell className="whitespace-normal text-muted-foreground">
                      <span className="line-clamp-2 break-words" title={row.description || undefined}>
                        {row.description || "暂无备注"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Badge tone="neutral">
                        {row.type === "iframe" ? "iframe" : "JavaScript"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge tone="neutral">{row.version}</Badge>
                    </TableCell>
                    <TableCell>
                      <div className="cell-main max-w-72">
                        <strong>{row.repository}</strong>
                        <span className="truncate" title={row.source}>{row.source}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="cell-main">
                        <strong>{row.fileCount} 个文件</strong>
                        <span>{formatRepositorySize(row.totalSize)}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge
                        tone={
                          row.localStatus === "current"
                            ? "success"
                            : row.localStatus === "conflict"
                              ? "danger"
                              : row.localStatus === "update"
                                ? "warning"
                                : "neutral"
                        }
                      >
                        {row.localStatus === "current"
                          ? "已添加"
                          : row.localStatus === "conflict"
                            ? "版本冲突"
                            : row.localStatus === "update"
                              ? `可更新 · ${row.localVersion}`
                              : "未添加"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-2">
                        <Button variant="outline" size="sm" asChild>
                          <a href={row.sourceUrl} target="_blank" rel="noreferrer">
                            源码
                          </a>
                        </Button>
                        {canManage ? (
                          <Button
                            size="sm"
                            variant={row.localStatus === "current" ? "outline" : "default"}
                            disabled={
                              row.localStatus === "current" ||
                              row.localStatus === "conflict" ||
                              Boolean(repositoryPending)
                            }
                            onClick={() => beginRepositoryImport(row)}
                          >
                            {repositoryPending === row.sequence ? <Spinner /> : null}
                            {row.localStatus === "update" ? "更新" : row.localStatus === "current" ? "已添加" : "添加到本地"}
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
              title="远程仓库没有集成"
              description="当前目录清单中没有可用的远程集成。"
            />
          )
        ) : loading ? (
          <div className="loading-state">
            <Spinner />
          </div>
        ) : visible.length ? (
          <Table layout="list">
            <TableHeader>
              <TableRow>
                <TableHead>集成</TableHead>
                <TableHead>集成标识</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>源域名</TableHead>
                <TableHead>资源包</TableHead>
                <TableHead>模板</TableHead>
                <TableHead>回传</TableHead>
                <TableHead adaptive>备注</TableHead>
                <TableHead>创建时间</TableHead>
                <TableHead>更新时间</TableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pagination.rows.map((row) => (
                <TableRow key={row.readKey}>
                  <TableCell>
                    <EntityPrimaryCell
                      title={row.name}
                      id={row.id}
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
                  <TableCell className="permission-key">
                    <span title={row.integrationKey}>
                      {row.integrationKey}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Badge tone="neutral">
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
                  <TableCell>
                    <div className="cell-main">
                      <strong>
                        {row.feedbackEnabled ? `${row.eventCount} 条` : "未启用"}
                      </strong>
                      <span>
                        {row.feedbackEnabled
                          ? row.lastEventAt
                            ? formatDateTime(row.lastEventAt)
                            : "暂无回传"
                          : "—"}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="whitespace-normal text-muted-foreground">
                    <span className="line-clamp-2 break-words" title={row.description || undefined}>
                      {row.description || "暂无备注"}
                    </span>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(row.createdAt)}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(row.updatedAt)}
                  </TableCell>
                  <TableCell>
                    <div className="flex min-w-max items-center justify-end gap-2">
                      {row.feedbackEnabled ? (
                        <Button variant="outline" size="sm" onClick={() => openEvents(row)}>
                          回传记录
                        </Button>
                      ) : null}
                      {canManage ? (
                        <>
                          {row.repositorySource?.localStatus === "update" ? (
                            <Button
                              size="sm"
                              disabled={Boolean(repositoryPending)}
                              onClick={() => void importRepositoryIntegration(row.repositorySource!)}
                            >
                              {repositoryPending === row.repositorySource.sequence ? <Spinner /> : null}
                              更新
                            </Button>
                          ) : row.repositorySource?.localStatus === "conflict" ? (
                            <Button size="sm" variant="outline" disabled>
                              版本冲突
                            </Button>
                          ) : null}
                          <Button variant="outline" size="sm" onClick={() => openEditor(row)}>
                            编辑
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => void toggle(row)}
                          >
                            {row.enabled ? "停用" : "启用"}
                          </Button>
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => void remove(row)}
                          >
                            删除
                          </Button>
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
        open={Boolean(repositoryImporting)}
        onClose={() => !repositoryPending && setRepositoryImporting(null)}
        title={repositoryImporting ? `添加远程集成 · ${repositoryImporting.name}` : "添加远程集成"}
        description="选择资源托管域名后，系统会直接读取仓库源码并保存为本地集成。"
        footer={
          <>
            <Button
              variant="outline"
              disabled={Boolean(repositoryPending)}
              onClick={() => setRepositoryImporting(null)}
            >
              取消
            </Button>
            <Button
              disabled={!repositoryImporting || !repositoryDomainId || Boolean(repositoryPending)}
              onClick={() => {
                if (repositoryImporting) {
                  void importRepositoryIntegration(repositoryImporting, repositoryDomainId);
                }
              }}
            >
              {repositoryPending ? <Spinner /> : <DownloadIcon />}
              添加到本地
            </Button>
          </>
        }
      >
        {repositoryImporting ? (
          <div className="drawer-form">
            <div className="rounded-lg border bg-muted/30 p-3">
              <div className="flex items-center gap-2">
                <Badge tone="neutral">{repositoryImporting.sequence}</Badge>
                <strong>{repositoryImporting.name}</strong>
                <Badge tone="neutral">{repositoryImporting.version}</Badge>
              </div>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {repositoryImporting.description || repositoryImporting.integrationKey}
              </p>
            </div>
            <label className="field">
              <DrawerFieldLabel required>源域名</DrawerFieldLabel>
              <SearchableSelect
                value={repositoryDomainId}
                onValueChange={setRepositoryDomainId}
                options={domains.map((domain) => ({
                  value: domain.id,
                  label: domain.hostname,
                  description: domain.id,
                }))}
                placeholder="选择已验证域名"
                searchPlaceholder="搜索域名"
                emptyText="没有可用域名，请先完成域名接入"
                ariaLabel="远程集成源域名"
              />
              <small>后续从仓库更新时会保留这个源域名。</small>
            </label>
            <label className="switch-row">
              <span>
                <strong>添加后立即启用</strong>
                <small>关闭后可以先检查资源，再手动启用。</small>
              </span>
              <Switch
                checked={repositoryEnabled}
                onCheckedChange={setRepositoryEnabled}
                aria-label="添加后立即启用远程集成"
              />
            </label>
          </div>
        ) : null}
      </Drawer>

      <Drawer
        open={drawer}
        onClose={() => !pending && setDrawer(false)}
        title={editing ? `编辑集成 · ${editing.name}` : "导入集成"}
        description={
          editing
            ? "统一修改管理信息和状态；如需更新资源，可同时选择新的 ZIP。"
            : "上传 ZIP 后自动识别 iframe 或一个或多个 JavaScript 入口。"
        }
        footer={
          <>
            <Button variant="outline" disabled={pending} onClick={() => setDrawer(false)}>
              取消
            </Button>
            <Button disabled={createDisabled} onClick={() => void save()}>
              {pending ? <Spinner /> : editing ? <PackageIcon size={16} /> : <UploadCloudIcon size={16} />}
              {editing ? "保存集成" : "开始导入"}
            </Button>
          </>
        }
      >
        <div className="drawer-form">
          <label className="upload-zone">
            <Input
              type="file"
              accept=".zip,application/zip"
              onChange={(event) =>
                void chooseIntegrationPackage(event.target.files?.[0] || null)
              }
            />
            <UploadCloudIcon size={27} />
            <strong>
              <DrawerFieldLabel required={!editing}>
                {file?.name || (editing ? "可选：选择新的集成 ZIP" : "选择集成 ZIP 文件")}
              </DrawerFieldLabel>
            </strong>
            <span>
              {packageInspecting
                ? "正在读取包内名称、标识和说明…"
                : editing
                  ? "不选择则只保存管理信息；选择后同时原子替换资源包"
                  : "目录不限；包内元数据会自动填写且可修改，最大 20 MB"}
            </span>
          </label>
          <>
              <label className="field">
                <DrawerFieldLabel required>集成名称</DrawerFieldLabel>
                <Input
                  value={form.name}
                  maxLength={120}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, name: event.target.value }))
                  }
                  placeholder="例如：统一访客关联"
                />
              </label>
              <label className="field">
                <DrawerFieldLabel required>集成标识</DrawerFieldLabel>
                <Input
                  value={form.integrationKey}
                  maxLength={80}
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
                <DrawerFieldLabel required>源域名</DrawerFieldLabel>
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
                <DrawerFieldLabel>备注</DrawerFieldLabel>
                <Input
                  value={form.description}
                  maxLength={2000}
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
          {!editing ? (
            <div className="rounded-lg border bg-muted/30 p-3 text-sm text-muted-foreground">
              ZIP 有唯一 HTML 入口时自动识别为 iframe；没有 HTML 时，所有 JS/MJS
              按文件名稳定排序加载。存在多个 HTML 或需要自定义脚本顺序时，可选用
              integration.json 指定 entry 或 entries。
            </div>
          ) : null}
        </div>
      </Drawer>

      <Drawer
        open={Boolean(eventIntegration)}
        onClose={() => setEventIntegration(null)}
        title={`回传记录${eventIntegration ? ` · ${eventIntegration.name}` : ""}`}
        description={`共 ${eventTotal.toLocaleString()} 条事件`}
        wide
      >
        <div className="flex flex-col gap-4">
          {eventSummary.length ? (
            <div className="flex flex-wrap gap-2">
              {eventSummary.map((summary) => (
                <Badge key={summary.eventType} tone="neutral">
                  {summary.eventType} · {summary.count}
                </Badge>
              ))}
            </div>
          ) : null}
          <ListPagination
            page={eventPage}
            pageSize={eventPageSize}
            total={eventTotal}
            disabled={eventsLoading}
            ariaLabel="回传记录分页"
            onPageChange={(page) => {
              if (!eventIntegration) return;
              setEventPage(page);
              void loadEvents(eventIntegration, page, eventPageSize);
            }}
            onPageSizeChange={(pageSize) => {
              if (!eventIntegration) return;
              setEventPage(1);
              setEventPageSize(pageSize);
              void loadEvents(eventIntegration, 1, pageSize);
            }}
          />
          <ListTableCard>
            {eventsLoading ? (
              <div className="loading-state">
                <Spinner />
              </div>
            ) : eventRows.length ? (
              <Table layout="list">
                <TableHeader>
                  <TableRow>
                    <TableHead>事件</TableHead>
                    <TableHead>渠道</TableHead>
                    <TableHead>访客</TableHead>
                    <TableHead>来源</TableHead>
                    <TableHead>时间</TableHead>
                    <TableHead adaptive>数据</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {eventRows.map((event) => (
                    <TableRow key={event.id}>
                      <TableCell>
                        <div className="cell-main">
                          <strong>{event.eventType}</strong>
                          <span>v{event.integrationVersion}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="cell-main">
                          <strong>{event.channelSlug}</strong>
                          <span>{event.channelId}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="cell-main max-w-56">
                          <strong className="truncate" title={event.visitorId}>
                            {event.visitorId}
                          </strong>
                          <span>{event.fingerprintQuality || "无指纹"}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        {event.trafficSource === "fission" ? "裂变" : "直接"}
                      </TableCell>
                      <TableCell>{formatDateTime(event.occurredAt)}</TableCell>
                      <TableCell>
                        {Object.keys(event.metadata).length ? (
                          <details className="max-w-72">
                            <summary className="cursor-pointer text-sm text-primary">
                              查看
                            </summary>
                            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-muted p-2 text-xs">
                              {JSON.stringify(event.metadata, null, 2)}
                            </pre>
                          </details>
                        ) : (
                          "—"
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState
                title="暂无回传记录"
                description="当前集成还没有收到数据。"
              />
            )}
          </ListTableCard>
        </div>
      </Drawer>
    </StandardListPage>
  );
}
