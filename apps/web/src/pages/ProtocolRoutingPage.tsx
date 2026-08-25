import { PlusIcon, RefreshCwIcon } from "lucide-react";
import {
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { apiRequest, formatDateTime, unwrapList } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EntityPrimaryCell } from "../components/entity-primary-cell";
import {
  ListPagination,
  ListSortableHead,
  ListTableCard,
  ListToolbar,
  StandardListPage,
  type ListSortOrder,
} from "../components/list-page";
import { DrawerFieldLabel } from "../components/drawer-form";
import { snowflakeId } from "../lib/entity-identifiers";
import {
  Badge,
  Button,
  Checkbox,
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

type ProtocolNodeOption = {
  id: string;
  name: string;
};

type ProtocolPool = {
  id: string;
  name: string;
  remark: string;
  createdAt: string;
  updatedAt: string;
  members: Array<{
    protocolNodeId: string;
    protocolNodeName: string;
    enabled: boolean;
    available: boolean;
  }>;
};

type ProtocolPoolSortBy = "id" | "createdAt" | "updatedAt";

function value(row: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) if (row[key] != null) return row[key];
  return undefined;
}

function text(row: Record<string, unknown>, ...keys: string[]) {
  const found = value(row, ...keys);
  return found == null ? "" : String(found);
}

function boolean(
  row: Record<string, unknown>,
  fallback: boolean,
  ...keys: string[]
) {
  const found = value(row, ...keys);
  if (found == null) return fallback;
  if (typeof found === "string")
    return ["true", "1", "enabled", "on"].includes(found.toLowerCase());
  return Boolean(found);
}

function protocolNodeOption(input: unknown): ProtocolNodeOption {
  const row = input as Record<string, unknown>;
  return {
    id: snowflakeId(row, "id"),
    name: text(row, "name", "title"),
  };
}

function protocolPool(input: unknown): ProtocolPool {
  const row = input as Record<string, unknown>;
  const rawMembers = Array.isArray(row.members) ? row.members : [];
  return {
    id: snowflakeId(row, "id"),
    name: text(row, "name"),
    remark: text(row, "remark"),
    createdAt: text(row, "createdAt", "created_at"),
    updatedAt: text(row, "updatedAt", "updated_at"),
    members: rawMembers.map((inputMember) => {
      const member = inputMember as Record<string, unknown>;
      return {
        protocolNodeId: snowflakeId(
          member,
          "protocolNodeId",
          "protocol_node_id",
        ),
        protocolNodeName: text(
          member,
          "protocolNodeName",
          "protocol_node_name",
        ),
        enabled: boolean(member, true, "enabled"),
        available: boolean(member, false, "available"),
      };
    }),
  };
}

export function ProtocolRoutingPage({
  toolbarTabs,
}: {
  toolbarTabs?: ReactNode;
} = {}) {
  const { can } = useAuth();
  const canManage =
    can("resources.protocol.manage") || can("resources.ip.manage");
  const [nodes, setNodes] = useState<ProtocolNodeOption[]>([]);
  const [pools, setPools] = useState<ProtocolPool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [keyword, setKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [protocolNodeId, setProtocolNodeId] = useState("all");
  const [status, setStatus] = useState("all");
  const [sortBy, setSortBy] = useState<ProtocolPoolSortBy>("id");
  const [sortOrder, setSortOrder] = useState<ListSortOrder>("desc");
  const [editing, setEditing] = useState<ProtocolPool | "new" | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    name: "",
    remark: "",
    memberIds: [] as string[],
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const query = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
      if (debouncedKeyword) query.set("keyword", debouncedKeyword);
      if (protocolNodeId !== "all") query.set("protocolNodeId", protocolNodeId);
      if (status !== "all") query.set("status", status);
      query.set("sortBy", sortBy);
      query.set("sortOrder", sortOrder);
      const [nodePayload, poolPayload] = await Promise.all([
        apiRequest("/api/protocol-nodes/options"),
        apiRequest(`/api/protocol-pools?${query}`),
      ]);
      setNodes(
        unwrapList<unknown>(nodePayload).rows.map(protocolNodeOption),
      );
      const poolList = unwrapList<unknown>(poolPayload);
      setPools(poolList.rows.map(protocolPool));
      setTotal(poolList.total);
    } catch (caught) {
      setNodes([]);
      setPools([]);
      setTotal(0);
      setError(caught instanceof Error ? caught.message : "路由策略加载失败");
    } finally {
      setLoading(false);
    }
  }, [debouncedKeyword, page, pageSize, protocolNodeId, sortBy, sortOrder, status]);

  useEffect(() => void load(), [load]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedKeyword(keyword.trim());
      setPage(1);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [keyword]);

  function changeSort(nextSortBy: ProtocolPoolSortBy, nextSortOrder: ListSortOrder) {
    setSortBy(nextSortBy);
    setSortOrder(nextSortOrder);
    setPage(1);
  }

  function openPool(pool?: ProtocolPool) {
    setEditing(pool || "new");
    setForm({
      name: pool?.name || "",
      remark: pool?.remark || "",
      memberIds:
        pool?.members
          .filter((member) => member.enabled)
          .map((member) => member.protocolNodeId) || [],
    });
  }

  async function savePool() {
    if (!editing || !form.name.trim() || !form.memberIds.length) return;
    const creating = editing === "new";
    setSaving(true);
    try {
      await apiRequest(
        creating ? "/api/protocol-pools" : `/api/protocol-pools/${editing.id}`,
        {
          method: creating ? "POST" : "PATCH",
          body: JSON.stringify({
            name: form.name.trim(),
            remark: form.remark.trim() || null,
            members: form.memberIds.map((protocolNodeId, index) => ({
              protocolNodeId,
              priority: (index + 1) * 100,
              enabled: true,
            })),
          }),
        },
      );
      setEditing(null);
      toast.success(creating ? "协议池已创建" : "协议池已保存");
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "协议池保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function removePool(pool: ProtocolPool) {
    if (
      !(await confirmAction({
        title: `删除协议池“${pool.name}”？`,
        description: "删除后无法恢复；仍被推广渠道使用的协议池不能删除。",
        confirmText: "确认删除",
        destructive: true,
      }))
    )
      return;
    try {
      await apiRequest(`/api/protocol-pools/${pool.id}`, { method: "DELETE" });
      toast.success("协议池已删除");
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "协议池删除失败");
    }
  }

  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: "搜索策略名称、ID、备注或协议节点",
        }}
        filters={
          <>
            {toolbarTabs}
            <SelectField
              value={protocolNodeId}
              onValueChange={(value) => { setProtocolNodeId(value); setPage(1); }}
              options={[
                { value: "all", label: "全部协议节点" },
                ...nodes.map((node) => ({ value: node.id, label: `${node.name} · ${node.id}` })),
              ]}
            />
            <SelectField
              value={status}
              onValueChange={(value) => { setStatus(value); setPage(1); }}
              options={[
                { value: "all", label: "全部可用状态" },
                { value: "available", label: "可用" },
                { value: "unavailable", label: "不可用" },
              ]}
            />
          </>
        }
        meta={`${total} 个路由策略`}
        actions={
          <>
            <Button
              disabled={!canManage || !nodes.length}
              onClick={() => openPool()}
            >
              <PlusIcon size={16} />新建策略
            </Button>
            <Button variant="outline" onClick={() => void load()} disabled={loading}>
              <RefreshCwIcon size={16} className={loading ? "spin" : ""} />
              刷新
            </Button>
          </>
        }
      />
      <ListPagination
        ariaLabel="路由策略分页"
        page={page}
        pageSize={pageSize}
        total={total}
        disabled={loading}
        onPageChange={setPage}
        onPageSizeChange={(value) => { setPageSize(value); setPage(1); }}
      />
      <ListTableCard>
        {loading ? (
          <div className="loading-state">
            <Spinner />正在加载路由策略…
          </div>
        ) : error ? (
          <div className="error-state">
            <strong>路由策略加载失败</strong>
            <span>{error}</span>
            <Button variant="outline" onClick={() => void load()}>
              重试
            </Button>
          </div>
        ) : pools.length ? (
          <Table layout="list">
            <TableHeader>
              <TableRow>
                <ListSortableHead sortKey="id" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort}>路由策略</ListSortableHead>
                <TableHead adaptive>回退顺序</TableHead>
                <TableHead>备注</TableHead>
                <ListSortableHead sortKey="createdAt" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort}>创建时间</ListSortableHead>
                <ListSortableHead sortKey="updatedAt" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort}>更新时间</ListSortableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pools.map((pool) => {
                const available = pool.members.some(
                  (member) => member.available,
                );
                return (
                  <TableRow key={pool.id}>
                    <TableCell primary>
                      <EntityPrimaryCell
                        title={pool.name}
                        id={pool.id}
                        status={{
                          label: available ? "可回退" : "无可用成员",
                          description: available
                            ? "池中至少有一个成员可接入。"
                            : "当前所有成员不可接入，渠道请求会明确失败。",
                          tone: available ? "success" : "warning",
                        }}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {pool.members.map((member, index) => (
                          <Badge
                            key={member.protocolNodeId}
                            tone={member.available ? "success" : "neutral"}
                          >
                            {index + 1}. {member.protocolNodeName}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell>
                      <span
                        className="block max-w-64 truncate text-muted-foreground"
                        title={pool.remark}
                      >
                        {pool.remark || "-"}
                      </span>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(pool.createdAt)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(pool.updatedAt)}
                    </TableCell>
                    <TableCell>
                      <div className="flex min-w-max justify-end gap-2">
                        {canManage ? (
                          <>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => openPool(pool)}
                            >
                              编辑
                            </Button>
                            <Button
                              variant="destructive"
                              size="sm"
                              onClick={() => void removePool(pool)}
                            >
                              删除
                            </Button>
                          </>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        ) : (
          <EmptyState
            title={keyword.trim() || protocolNodeId !== "all" || status !== "all" ? "没有符合条件的路由策略" : "暂无路由策略"}
            description={
              keyword.trim() || protocolNodeId !== "all" || status !== "all"
                ? "请调整搜索条件后重试。"
                : "默认拒绝不可用节点；需要回退时再创建路由策略并绑定渠道。"
            }
          />
        )}
      </ListTableCard>
      <Drawer
        open={Boolean(editing)}
        onClose={() => !saving && setEditing(null)}
        title={editing === "new" ? "新建路由策略" : "编辑路由策略"}
        description="勾选顺序就是回退顺序。接入时选择第一个当前可用且未超容量的协议节点。"
        footer={
          <>
            <Button
              variant="outline"
              disabled={saving}
              onClick={() => setEditing(null)}
            >
              取消
            </Button>
            <Button
              disabled={
                saving || !form.name.trim() || !form.memberIds.length
              }
              onClick={() => void savePool()}
            >
              {saving ? <Spinner /> : null}保存
            </Button>
          </>
        }
      >
        <div className="drawer-form">
          <label className="field">
            <DrawerFieldLabel required>策略名称</DrawerFieldLabel>
            <Input
              maxLength={64}
              value={form.name}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  name: event.target.value,
                }))
              }
            />
          </label>
          <div className="field">
            <DrawerFieldLabel required>协议节点与回退顺序</DrawerFieldLabel>
            <div className="space-y-2 rounded-lg border p-3">
              {nodes.map((node) => {
                const selectedIndex = form.memberIds.indexOf(node.id);
                return (
                  <label
                    className="flex items-center justify-between gap-3"
                    key={node.id}
                  >
                    <span className="flex items-center gap-2">
                      <Checkbox
                        aria-label={`选择协议节点 ${node.name}`}
                        checked={selectedIndex >= 0}
                        onCheckedChange={(checked) =>
                          setForm((current) => ({
                            ...current,
                            memberIds: checked
                              ? [...current.memberIds, node.id]
                              : current.memberIds.filter(
                                  (id) => id !== node.id,
                                ),
                          }))
                        }
                      />
                      <span>{node.name}</span>
                    </span>
                    <small className="text-muted-foreground">
                      {selectedIndex >= 0
                        ? `优先级 ${selectedIndex + 1}`
                        : "未启用"}
                    </small>
                  </label>
                );
              })}
            </div>
            <small>若要调整优先级，可取消后按目标顺序重新勾选。</small>
          </div>
          <label className="field">
            <DrawerFieldLabel>备注</DrawerFieldLabel>
            <Textarea
              rows={4}
              maxLength={512}
              value={form.remark}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  remark: event.target.value,
                }))
              }
            />
          </label>
        </div>
      </Drawer>
    </StandardListPage>
  );
}
