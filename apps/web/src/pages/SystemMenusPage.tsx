import {
  FolderTreeIcon,
  LoaderCircleIcon,
  PencilIcon,
  RefreshCwIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiRequest, unwrapList } from "../api/client";
import {
  Badge,
  Button,
  Drawer,
  IconButton,
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
  ListTableCard,
  ListToolbar,
  StandardListPage,
} from "../components/list-page";

type MenuRow = {
  id: string;
  parentId: string;
  name: string;
  type: "目录" | "页面";
  path: string;
  permission: string;
  sortOrder: number;
  enabled: boolean;
  visible: boolean;
  builtin: boolean;
};

const defaultRows: MenuRow[] = [
  { id: "promotion-management", parentId: "", name: "推广管理", type: "目录", path: "", permission: "", sortOrder: 10, enabled: true, visible: true, builtin: true },
  { id: "promotion-templates", parentId: "promotion-management", name: "模板管理", type: "页面", path: "/promotion/templates", permission: "promotion.templates.read", sortOrder: 10, enabled: true, visible: true, builtin: true },
  { id: "promotion-channels", parentId: "promotion-management", name: "渠道管理", type: "页面", path: "/promotion/channels", permission: "promotion.channels.read", sortOrder: 20, enabled: true, visible: true, builtin: true },
  { id: "promotion-domains", parentId: "promotion-management", name: "域名管理", type: "页面", path: "/promotion/domains", permission: "promotion.domain.read", sortOrder: 30, enabled: true, visible: true, builtin: true },
  { id: "promotion-data", parentId: "", name: "数据中心", type: "目录", path: "", permission: "", sortOrder: 20, enabled: true, visible: true, builtin: true },
  { id: "promotion-statistics", parentId: "promotion-data", name: "渠道统计", type: "页面", path: "/promotion/statistics", permission: "promotion.statistics.read", sortOrder: 10, enabled: true, visible: true, builtin: true },
  { id: "promotion-trends", parentId: "promotion-data", name: "趋势图", type: "页面", path: "/promotion/trends", permission: "promotion.trends.read", sortOrder: 20, enabled: true, visible: true, builtin: true },
  { id: "system-management", parentId: "", name: "系统管理", type: "目录", path: "", permission: "", sortOrder: 90, enabled: true, visible: true, builtin: true },
  { id: "system-users", parentId: "system-management", name: "用户管理", type: "页面", path: "/system/users", permission: "system.users.manage", sortOrder: 10, enabled: true, visible: true, builtin: true },
  { id: "system-roles", parentId: "system-management", name: "角色管理", type: "页面", path: "/system/roles", permission: "system.roles.manage", sortOrder: 20, enabled: true, visible: true, builtin: true },
  { id: "system-menus", parentId: "system-management", name: "菜单管理", type: "页面", path: "/system/menus", permission: "system.menus.manage", sortOrder: 30, enabled: true, visible: true, builtin: true },
];

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
          `${row.name} ${rows.find((item) => item.id === row.parentId)?.name || ""} ${row.path} ${row.permission}`
            .toLowerCase()
            .includes(search),
        )
      : rows;
  }, [keyword, rows]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await apiRequest("/api/system/menus");
      const next = unwrapList<Record<string, unknown>>(payload).rows.map<MenuRow>((row) => ({
        id: String(row.publicId || row.id),
        parentId: String(row.parentId || ""),
        name: String(row.name || ""),
        type: String(row.type) === "directory" ? "目录" : "页面",
        path: String(row.routePath || ""),
        permission: String(row.permissionKey || ""),
        sortOrder: Number(row.sortOrder || 0),
        enabled: Boolean(row.enabled ?? true),
        visible: Boolean(row.visible ?? true),
        builtin: Boolean(row.isBuiltin),
      }));
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
    if (!editing || !form.name.trim()) return;
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
    <StandardListPage>
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
      <ListTableCard>
        {loading ? <div className="loading-state"><LoaderCircleIcon className="spin" size={18} />正在加载菜单…</div> : (
        <div className="table-scroll">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>菜单名称</TableHead>
                <TableHead>上级菜单</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>路由路径</TableHead>
                <TableHead>权限标识</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>显示</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>
                    <div className="menu-name-cell">
                      <FolderTreeIcon size={16} />
                      <strong>{row.name}</strong>
                    </div>
                  </TableCell>
                  <TableCell>{rows.find((item) => item.id === row.parentId)?.name || "根目录"}</TableCell>
                  <TableCell><Badge tone={row.type === "目录" ? "primary" : "neutral"}>{row.type}</Badge></TableCell>
                  <TableCell className="text-muted-foreground">{row.path || "-"}</TableCell>
                  <TableCell className="permission-key">{row.permission}</TableCell>
                  <TableCell><Badge tone={row.enabled ? "success" : "neutral"}>{row.enabled ? "启用" : "停用"}</Badge></TableCell>
                  <TableCell>{row.visible ? "显示" : "隐藏"}</TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      <IconButton label="编辑菜单" onClick={() => startEdit(row)}>
                        <PencilIcon size={16} />
                      </IconButton>
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
            <span>菜单名称</span>
            <Input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
          </label>
          <label className="field">
            <span>排序</span>
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
