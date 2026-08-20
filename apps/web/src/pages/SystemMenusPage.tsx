import {
  LoaderCircleIcon,
  RefreshCwIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiRequest, unwrapList } from "../api/client";
import {
  entityRowKey,
  legacyReadKey,
  snowflakeId,
} from "../lib/entity-identifiers";
import {
  Badge,
  Button,
  Drawer,
  Input,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
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

type MenuRow = {
  id: string;
  readKey: string;
  parentId: string;
  parentReadKey: string;
  name: string;
  type: "目录" | "页面";
  path: string;
  permission: string;
  sortOrder: number;
  enabled: boolean;
  visible: boolean;
  builtin: boolean;
};

type MenuPreset = Omit<MenuRow, "id" | "readKey" | "parentId" | "parentReadKey"> & {
  presetKey: string;
  parentPresetKey: string;
};

const menuPresets: MenuPreset[] = [
  { presetKey: "promotion-management", parentPresetKey: "", name: "推广管理", type: "目录", path: "", permission: "", sortOrder: 10, enabled: true, visible: true, builtin: true },
  { presetKey: "promotion-templates", parentPresetKey: "promotion-management", name: "模板管理", type: "页面", path: "/promotion/templates", permission: "promotion.templates.read", sortOrder: 10, enabled: true, visible: true, builtin: true },
  { presetKey: "promotion-integrations", parentPresetKey: "promotion-management", name: "集成管理", type: "页面", path: "/promotion/integrations", permission: "promotion.integrations.read", sortOrder: 20, enabled: true, visible: true, builtin: true },
  { presetKey: "promotion-channels", parentPresetKey: "promotion-management", name: "渠道管理", type: "页面", path: "/promotion/channels", permission: "promotion.channels.read", sortOrder: 30, enabled: true, visible: true, builtin: true },
  { presetKey: "promotion-domains", parentPresetKey: "promotion-management", name: "域名管理", type: "页面", path: "/promotion/domains", permission: "promotion.domain.read", sortOrder: 40, enabled: true, visible: true, builtin: true },
  { presetKey: "promotion-data", parentPresetKey: "", name: "数据中心", type: "目录", path: "", permission: "", sortOrder: 20, enabled: true, visible: true, builtin: true },
  { presetKey: "promotion-statistics", parentPresetKey: "promotion-data", name: "渠道统计", type: "页面", path: "/promotion/statistics", permission: "promotion.statistics.read", sortOrder: 10, enabled: true, visible: true, builtin: true },
  { presetKey: "promotion-trends", parentPresetKey: "promotion-data", name: "趋势图", type: "页面", path: "/promotion/trends", permission: "promotion.trends.read", sortOrder: 20, enabled: true, visible: true, builtin: true },
  { presetKey: "system-management", parentPresetKey: "", name: "系统管理", type: "目录", path: "", permission: "", sortOrder: 90, enabled: true, visible: true, builtin: true },
  { presetKey: "system-users", parentPresetKey: "system-management", name: "用户管理", type: "页面", path: "/system/users", permission: "system.users.manage", sortOrder: 10, enabled: true, visible: true, builtin: true },
  { presetKey: "system-roles", parentPresetKey: "system-management", name: "角色管理", type: "页面", path: "/system/roles", permission: "system.roles.manage", sortOrder: 20, enabled: true, visible: true, builtin: true },
  { presetKey: "system-developer-docs", parentPresetKey: "system-management", name: "开发文档", type: "页面", path: "/system/developer-docs", permission: "system.developer_docs.read", sortOrder: 30, enabled: true, visible: true, builtin: true },
  { presetKey: "system-configuration", parentPresetKey: "system-management", name: "系统配置", type: "页面", path: "/system/configuration", permission: "system.configuration.manage", sortOrder: 40, enabled: true, visible: true, builtin: true },
  { presetKey: "system-menus", parentPresetKey: "system-management", name: "菜单管理", type: "页面", path: "/system/menus", permission: "system.menus.manage", sortOrder: 50, enabled: true, visible: true, builtin: true },
];

const defaultRows: MenuRow[] = menuPresets.map(({ presetKey, parentPresetKey, ...row }) => ({
  ...row,
  id: "",
  readKey: `menu:preset:${presetKey}`,
  parentId: "",
  parentReadKey: parentPresetKey ? `menu:preset:${parentPresetKey}` : "",
}));

type MenuEditForm = Pick<MenuRow, "name" | "sortOrder" | "enabled" | "visible">;

const emptyForm: MenuEditForm = {
  name: "",
  sortOrder: 10,
  enabled: true,
  visible: true,
};

export function SystemMenusPage() {
  const [rows, setRows] = useState<MenuRow[]>(defaultRows);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<MenuRow | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [pending, setPending] = useState(false);
  const visible = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return search
      ? rows.filter((row) =>
          `${row.name} ${rows.find((item) => item.readKey === row.parentReadKey)?.name || ""} ${row.path} ${row.permission}`
            .toLowerCase()
            .includes(search),
        )
      : rows;
  }, [keyword, rows]);
  const pagination = useClientPagination(visible, { resetKey: keyword });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await apiRequest("/api/system/menus");
      const next = unwrapList<Record<string, unknown>>(payload).rows.map<MenuRow>((row) => {
        const id = snowflakeId(row, "id");
        const parentId = snowflakeId(row, "parentId", "parent_id");
        return {
        id,
        readKey: entityRowKey(row, id, "menu", `${String(row.routePath || "")}:${String(row.name || "")}`),
        parentId,
        parentReadKey:
          (parentId && `menu:${parentId}`) ||
          legacyReadKey(
            row,
            "menu",
            "parentPublicId",
            "parent_public_id",
          ),
        name: String(row.name || ""),
        type: String(row.type) === "directory" ? "目录" : "页面",
        path: String(row.routePath || ""),
        permission: String(row.permissionKey || ""),
        sortOrder: Number(row.sortOrder || 0),
        enabled: Boolean(row.enabled ?? true),
        visible: Boolean(row.visible ?? true),
        builtin: Boolean(row.isBuiltin),
      };});
      setRows(next.length ? next : defaultRows);
    } catch {
      setRows(defaultRows);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function startEdit(row: MenuRow) {
    setEditing(row);
    setForm({
      name: row.name,
      sortOrder: row.sortOrder,
      enabled: row.enabled,
      visible: row.visible,
    });
    setOpen(true);
  }

  async function save() {
    if (!editing?.id || !form.name.trim()) return;
    setPending(true);
    try {
      const payload = {
        name: form.name.trim(),
        sortOrder: form.sortOrder,
        enabled: form.enabled,
        visible: form.visible,
      };
      await apiRequest(`/api/system/menus/${editing.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      setOpen(false);
      await load();
      toast.success("菜单已更新");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "菜单保存失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: "搜索菜单名称、路径或权限标识",
        }}
        meta={`${visible.length} 个菜单项`}
        actions={
          <Button variant="outline" onClick={() => void load()} disabled={loading}>
            <RefreshCwIcon size={16} />
            刷新
          </Button>
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
        {loading ? <div className="loading-state"><LoaderCircleIcon className="spin" size={18} />正在加载菜单…</div> : (
        <div className="table-scroll">
          <Table layout="list">
            <TableHeader>
              <TableRow>
                <TableHead>菜单名称</TableHead>
                <TableHead>上级菜单</TableHead>
                <TableHead>类型</TableHead>
                <TableHead adaptive>路由路径</TableHead>
                <TableHead>权限标识</TableHead>
                <TableHead>显示</TableHead>
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
                        label: !row.enabled ? "已停用" : row.visible ? "正常" : "已隐藏",
                        description: !row.enabled
                          ? "菜单入口已停用，相关页面不应再作为可访问入口。"
                          : row.visible
                            ? "菜单已启用并在导航中显示。"
                            : "菜单保留路由配置，但不会显示在导航中。",
                        tone: !row.enabled ? "warning" : row.visible ? "success" : "neutral",
                        details: [
                          { label: "类型", value: row.type },
                          { label: "内置", value: row.builtin ? "是" : "否" },
                        ],
                      }}
                    />
                  </TableCell>
                  <TableCell>{rows.find((item) => item.readKey === row.parentReadKey)?.name || "根目录"}</TableCell>
                  <TableCell><Badge tone="neutral">{row.type}</Badge></TableCell>
                  <TableCell className="text-muted-foreground">{row.path || "-"}</TableCell>
                  <TableCell className="permission-key">{row.permission}</TableCell>
                  <TableCell>{row.visible ? "显示" : "隐藏"}</TableCell>
                  <TableCell>
                    <div className="flex min-w-max items-center justify-end gap-2">
                      <Button variant="outline" size="sm" disabled={!row.id} onClick={() => startEdit(row)}>
                        编辑
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        )}
      </ListTableCard>
      <Drawer
        open={open}
        onClose={() => !pending && setOpen(false)}
        title="编辑菜单"
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={pending}>取消</Button>
            <Button onClick={() => void save()} disabled={pending || !form.name.trim()}>
              {pending ? <LoaderCircleIcon className="spin" size={16} /> : null}
              保存
            </Button>
          </>
        }
      >
        <div className="drawer-form">
          <label className="field">
            <DrawerFieldLabel required>菜单名称</DrawerFieldLabel>
            <Input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
          </label>
          <label className="field">
            <DrawerFieldLabel required>排序</DrawerFieldLabel>
            <Input type="number" min="0" value={String(form.sortOrder)} onChange={(event) => setForm({ ...form, sortOrder: Number(event.target.value) })} />
          </label>
          <label className="switch-row">
            <span><strong>启用菜单</strong><small>停用后不再作为可访问入口。</small></span>
            <Switch checked={form.enabled} onCheckedChange={(enabled) => setForm({ ...form, enabled })} />
          </label>
          <label className="switch-row">
            <span><strong>在导航中显示</strong><small>隐藏后仍保留路由配置。</small></span>
            <Switch checked={form.visible} onCheckedChange={(visible) => setForm({ ...form, visible })} />
          </label>
        </div>
      </Drawer>
    </StandardListPage>
  );
}
