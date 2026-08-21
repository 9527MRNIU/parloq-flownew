import {
  LoaderCircleIcon,
  PlusIcon,
  RefreshCwIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiRequest, formatDateTime, unwrapList } from "../api/client";
import { entityRowKey, snowflakeId } from "../lib/entity-identifiers";
import {
  Badge,
  Button,
  confirmAction,
  Drawer,
  EmptyState,
  Input,
  MultiSelect,
  Spinner,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Textarea,
  toast,
} from "../components/ui";
import {
  ListPagination,
  ListTableCard,
  ListToolbar,
  StandardListPage,
  useClientPagination,
} from "../components/list-page";
import { EntityPrimaryCell } from "../components/entity-primary-cell";
import { DrawerFieldLabel } from "../components/drawer-form";

type GroupRow = {
  id: string;
  readKey: string;
  name: string;
  description: string;
  builtin: boolean;
  userCount: number;
  enabled: boolean;
  menuIds: string[];
  permissionKeys: string[];
  createdAt?: string;
  updatedAt?: string;
};
function normalize(input: unknown): GroupRow {
  const row = input as Record<string, unknown>;
  const id = snowflakeId(row, "id");
  return {
    id,
    readKey: entityRowKey(row, id, "role", `${String(row.name || "")}:${String(row.createdAt || row.created_at || "")}`),
    name: String(row.name || ""),
    description: String(row.description || ""),
    builtin: Boolean(row.builtin ?? row.isBuiltin ?? row.is_builtin),
    userCount: Number(row.userCount ?? row.user_count ?? 0),
    enabled: Boolean(row.enabled ?? true),
    menuIds: Array.isArray(row.menuIds ?? row.menu_ids)
      ? ((row.menuIds ?? row.menu_ids) as unknown[])
          .map((value) => snowflakeId({ id: value }, "id"))
          .filter(Boolean)
      : [],
    permissionKeys: Array.isArray(row.permissionKeys ?? row.permission_keys)
      ? ((row.permissionKeys ?? row.permission_keys) as unknown[]).map(String)
      : [],
    createdAt: String(row.createdAt || row.created_at || ""),
    updatedAt: String(row.updatedAt || row.updated_at || ""),
  };
}

const actionPermissionOptions = [
  { value: "business.personal_accounts.manage", label: "管理账号（兼容权限）" },
  { value: "resources.accounts.manage", label: "管理账号中心" },
  { value: "resources.accounts.import", label: "导入账号 JSON" },
  { value: "resources.accounts.export", label: "导出账号 JSON" },
  { value: "promotion.templates.manage", label: "管理推广模板" },
  { value: "promotion.channels.manage", label: "管理推广渠道" },
  { value: "promotion.domain.manage", label: "管理域名" },
  { value: "promotion.domain.purchase", label: "购买域名" },
  { value: "promotion.statistics.manage", label: "录入推广数据" },
  { value: "marketing.hyperlink_tasks.manage", label: "管理超链任务" },
  { value: "marketing.data_packages.manage", label: "管理数据包" },
  { value: "marketing.hyperlink_templates.manage", label: "管理超链模板" },
  { value: "marketing.hyperlink_strategies.manage", label: "管理超链策略" },
  { value: "resources.materials.manage", label: "管理素材库" },
  { value: "marketing.direct_short_links.manage", label: "管理直接短链" },
  { value: "resources.ip.manage", label: "管理 IP 资源" },
];

export function UserGroupsPage() {
  const [rows, setRows] = useState<GroupRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [keyword, setKeyword] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<GroupRow | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [menuIds, setMenuIds] = useState<string[]>([]);
  const [permissionKeys, setPermissionKeys] = useState<string[]>([]);
  const [menus, setMenus] = useState<Array<{ value: string; label: string }>>([]);
  const [pending, setPending] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [payload, menuPayload] = await Promise.all([
        apiRequest("/api/system/roles"),
        apiRequest("/api/system/menus"),
      ]);
      setRows(unwrapList<unknown>(payload).rows.map(normalize));
      setMenus(
        unwrapList<Record<string, unknown>>(menuPayload).rows
          .map((row) => ({
            value: snowflakeId(row, "id"),
            label: String(row.name || row.routePath || "未命名菜单"),
          }))
          .filter((row) => row.value),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载角色失败");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const visibleRows = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return search
      ? rows.filter((row) =>
          `${row.name} ${row.description}`.toLowerCase().includes(search),
        )
      : rows;
  }, [keyword, rows]);
  const pagination = useClientPagination(visibleRows, { resetKey: keyword });
  function create() {
    setEditing(null);
    setName("");
    setDescription("");
    setEnabled(true);
    setMenuIds([]);
    setPermissionKeys([]);
    setOpen(true);
  }
  function edit(row: GroupRow) {
    if (!row.id) return;
    setEditing(row);
    setName(row.name);
    setDescription(row.description);
    setEnabled(row.enabled);
    setMenuIds(row.menuIds);
    setPermissionKeys(row.permissionKeys);
    setOpen(true);
  }
  async function save() {
    if (!name.trim() || (editing && !editing.id)) return;
    setPending(true);
    try {
      await apiRequest(
        editing ? `/api/system/roles/${editing.id}` : "/api/system/roles",
        {
          method: editing ? "PATCH" : "POST",
          body: JSON.stringify(
            editing?.builtin
              ? { description: description.trim(), menuIds, permissionKeys }
              : {
                  name: name.trim(),
                  description: description.trim(),
                  enabled,
                  menuIds,
                  permissionKeys,
                },
          ),
        },
      );
      setOpen(false);
      await load();
      toast.success(editing ? "角色已更新" : "角色已创建");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setPending(false);
    }
  }
  async function remove(row: GroupRow) {
    if (!row.id) return;
    if (
      !(await confirmAction({
        title: `删除角色“${row.name}”？`,
        description: "删除后无法恢复。",
        confirmText: "确认删除",
      }))
    )
      return;
    try {
      await apiRequest(`/api/system/roles/${row.id}`, { method: "DELETE" });
      await load();
      toast.success("角色已删除");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "删除失败");
    }
  }

  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: "搜索角色名称或备注",
        }}
        meta={`${visibleRows.length} 个角色`}
        actions={
          <>
            <Button
              variant="outline"
              onClick={() => void load()}
              disabled={loading}
            >
              <RefreshCwIcon size={16} className={loading ? "spin" : ""} />
              刷新
            </Button>
            <Button onClick={create}>
              <PlusIcon size={17} />
              新增角色
            </Button>
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
            正在加载角色…
          </div>
        ) : error ? (
          <div className="error-state">
            <strong>加载失败</strong>
            <span>{error}</span>
            <Button variant="outline" onClick={() => void load()}>
              重试
            </Button>
          </div>
        ) : visibleRows.length ? (
          <div className="table-scroll">
            <Table layout="list">
              <TableHeader>
                <TableRow>
                  <TableHead>角色</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>成员数</TableHead>
                  <TableHead adaptive>菜单 / 操作权限</TableHead>
                  <TableHead>备注</TableHead>
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
                          label: row.enabled ? "启用" : "停用",
                          description: row.enabled
                            ? "角色当前可分配给用户并应用权限。"
                            : "角色已停用，不应继续分配给用户。",
                          tone: row.enabled ? "success" : "neutral",
                          details: [
                            { label: "类型", value: row.builtin ? "系统内置" : "自定义" },
                            { label: "成员数", value: row.userCount },
                          ],
                        }}
                      />
                    </TableCell>
                    <TableCell>
                      <Badge tone="neutral">
                        {row.builtin ? "系统内置" : "自定义"}
                      </Badge>
                    </TableCell>
                    <TableCell className="tabular-nums">{row.userCount}</TableCell>
                    <TableCell className="tabular-nums">
                      {row.menuIds.length} / {row.permissionKeys.length}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {row.description || "-"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(row.createdAt)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(row.updatedAt || row.createdAt)}
                    </TableCell>
                    <TableCell>
                      <div className="flex min-w-max items-center justify-end gap-2">
                        <Button variant="outline" size="sm" disabled={!row.id} onClick={() => edit(row)}>
                          编辑
                        </Button>
                        <Button
                          variant="destructive"
                          size="sm"
                          disabled={!row.id || row.builtin}
                          onClick={() => void remove(row)}
                        >
                          删除
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <EmptyState
            title="暂无角色"
            description="创建角色后，可以批量为用户配置权限边界。"
          />
        )}
      </ListTableCard>
      <Drawer
        open={open}
        onClose={() => !pending && setOpen(false)}
        title={editing ? "编辑角色" : "新增角色"}
        description="为角色设置名称和用途，再将用户分配到对应角色。"
        footer={
          <>
            <Button
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={pending}
            >
              取消
            </Button>
            <Button
              onClick={() => void save()}
              disabled={pending || !name.trim()}
            >
              {pending ? <LoaderCircleIcon className="spin" size={17} /> : null}
              保存
            </Button>
          </>
        }
      >
        <div className="drawer-form">
          <label className="field">
            <DrawerFieldLabel required>角色名称</DrawerFieldLabel>
            <Input
              value={name}
              disabled={Boolean(editing?.builtin)}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：运营一组"
            />
          </label>
          <label className="field">
            <DrawerFieldLabel>备注</DrawerFieldLabel>
            <Textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="填写该角色的用途或其他说明"
              rows={4}
            />
          </label>
          <label className="field">
            <DrawerFieldLabel>授权菜单</DrawerFieldLabel>
            <MultiSelect
              value={menuIds}
              onValueChange={setMenuIds}
              options={menus}
              placeholder="选择角色可访问的菜单"
            />
          </label>
          <label className="field">
            <DrawerFieldLabel>操作权限</DrawerFieldLabel>
            <MultiSelect
              value={permissionKeys}
              onValueChange={setPermissionKeys}
              options={actionPermissionOptions}
              placeholder="选择新增、编辑、购买等操作权限"
              disabled={Boolean(editing?.builtin)}
            />
            {editing?.builtin ? <small>系统内置角色的操作权限由系统维护。</small> : null}
          </label>
          <label className="switch-row">
            <span>
              <strong>启用角色</strong>
              <small>停用后该角色不再用于新的用户分配。</small>
            </span>
            <Switch checked={enabled} disabled={Boolean(editing?.builtin)} onCheckedChange={setEnabled} />
          </label>
        </div>
      </Drawer>
    </StandardListPage>
  );
}
