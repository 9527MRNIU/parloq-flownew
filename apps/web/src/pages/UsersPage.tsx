import {
  BanIcon,
  LoaderCircleIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  UserRoundIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { apiRequest, formatDateTime, unwrapList } from "../api/client";
import {
  Badge,
  Button,
  confirmAction,
  Drawer,
  EmptyState,
  IconButton,
  Input,
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
import {
  ListPagination,
  ListTableCard,
  ListToolbar,
  StandardListPage,
} from "../components/list-page";

type UserRow = {
  id: string | number;
  username: string;
  groupId?: string | number;
  groupName?: string;
  enabled: boolean;
  isAdmin: boolean;
  lastLoginAt?: string;
  createdAt?: string;
};
type GroupRow = { id: string | number; name: string; systemKey?: string };

function userRow(input: unknown): UserRow {
  const row = input as Record<string, unknown>;
  const status = String(row.status || "");
  const role = String(row.role || "").toLowerCase();
  return {
    id: (row.id || row.publicId || row.public_id) as string | number,
    username: String(row.username || ""),
    groupId: (row.groupId || row.group_id) as string | number | undefined,
    groupName: String(row.groupName || row.group_name || ""),
    enabled: Boolean(
      row.enabled ?? row.isActive ?? row.is_active ?? status !== "disabled",
    ),
    isAdmin: Boolean(row.isAdmin ?? row.is_admin ?? role === "admin"),
    lastLoginAt: String(row.lastLoginAt || row.last_login_at || ""),
    createdAt: String(row.createdAt || row.created_at || ""),
  };
}

function groupRow(input: unknown): GroupRow {
  const row = input as Record<string, unknown>;
  return {
    id: (row.id || row.publicId || row.public_id) as string | number,
    name: String(row.name || ""),
    systemKey: String(row.systemKey || row.system_key || ""),
  };
}

export function UsersPage() {
  const [rows, setRows] = useState<UserRow[]>([]);
  const [groups, setGroups] = useState<GroupRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [keyword, setKeyword] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<UserRow | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [groupId, setGroupId] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [pending, setPending] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        page: String(page),
        pageSize: String(pageSize),
      });
      if (query) params.set("keyword", query);
      const [usersPayload, groupsPayload] = await Promise.all([
        apiRequest(`/api/users?${params}`),
        apiRequest("/api/system/roles"),
      ]);
      const users = unwrapList<unknown>(usersPayload);
      setRows(users.rows.map(userRow));
      setTotal(users.total);
      setGroups(unwrapList<unknown>(groupsPayload).rows.map(groupRow));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载用户失败");
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, query]);
  useEffect(() => {
    void load();
  }, [load]);
  function create() {
    const defaultGroup =
      groups.find((group) => group.systemKey === "operator") ??
      groups.find((group) => group.systemKey !== "admin");
    setEditing(null);
    setUsername("");
    setPassword("");
    setGroupId(String(defaultGroup?.id || ""));
    setEnabled(true);
    setOpen(true);
  }
  function edit(row: UserRow) {
    setEditing(row);
    setUsername(row.username);
    setPassword("");
    setGroupId(String(row.groupId || ""));
    setEnabled(row.enabled);
    setOpen(true);
  }

  async function save() {
    if (!username.trim() || !groupId || (!editing && !password)) return;
    setPending(true);
    try {
      const body = {
        username: username.trim(),
        password: password || undefined,
        groupId: groupId || undefined,
        enabled,
      };
      await apiRequest(editing ? `/api/users/${editing.id}` : "/api/users", {
        method: editing ? "PATCH" : "POST",
        body: JSON.stringify(body),
      });
      setOpen(false);
      await load();
      toast.success(editing ? "用户已更新" : "用户已创建");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setPending(false);
    }
  }

  async function remove(row: UserRow) {
    if (
      !(await confirmAction({
        title: `停用用户“${row.username}”？`,
        description: "该用户将无法登录，但业务资源和审计记录会保留。",
        confirmText: "确认停用",
      }))
    )
      return;
    try {
      await apiRequest(`/api/users/${row.id}`, { method: "DELETE" });
      await load();
      toast.success("用户已停用");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "停用失败");
    }
  }

  return (
    <StandardListPage>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: "搜索用户名或角色",
          onSubmit: () => {
            setPage(1);
            setQuery(keyword.trim());
          },
        }}
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
              新增用户
            </Button>
          </>
        }
      />
      <ListPagination
        page={page}
        pageSize={pageSize}
        total={total}
        pageSizeOptions={[20, 50]}
        disabled={loading}
        onPageChange={setPage}
        onPageSizeChange={(value) => {
          setPage(1);
          setPageSize(value);
        }}
      />
      <ListTableCard>
        {loading ? (
          <div className="loading-state">
            <Spinner />
            正在加载用户…
          </div>
        ) : error ? (
          <div className="error-state">
            <strong>加载失败</strong>
            <span>{error}</span>
            <Button variant="outline" onClick={() => void load()}>
              重试
            </Button>
          </div>
        ) : rows.length ? (
          <div className="table-scroll">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>用户</TableHead>
                  <TableHead>角色</TableHead>
                  <TableHead>账号类型</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>最近登录</TableHead>
                  <TableHead>创建时间</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>
                      <div className="user-cell">
                        <span className="small-avatar">
                          <UserRoundIcon size={15} />
                        </span>
                        <strong>{row.username}</strong>
                      </div>
                    </TableCell>
                    <TableCell>{row.groupName || "-"}</TableCell>
                    <TableCell>
                      <Badge tone={row.isAdmin ? "primary" : "neutral"}>
                        {row.isAdmin ? "管理员" : "普通用户"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge tone={row.enabled ? "success" : "warning"}>
                        {row.enabled ? "正常" : "已停用"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(row.lastLoginAt)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(row.createdAt)}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        <IconButton
                          label="编辑（可恢复登录）"
                          onClick={() => edit(row)}
                        >
                          <PencilIcon size={16} />
                        </IconButton>
                        <IconButton
                          label={
                            row.enabled
                              ? "停用用户"
                              : "用户已停用，可在编辑中恢复"
                          }
                          variant="ghost"
                          className="danger"
                          disabled={row.username === "admin" || !row.enabled}
                          onClick={() => void remove(row)}
                        >
                          <BanIcon size={16} />
                        </IconButton>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <EmptyState
            title="暂无用户"
            description={
              query
                ? "没有匹配的用户，请调整搜索条件。"
                : "新增用户后，可以为其分配角色和后台访问权限。"
            }
          />
        )}
      </ListTableCard>
      <Drawer
        open={open}
        onClose={() => !pending && setOpen(false)}
        title={editing ? "编辑用户" : "新增用户"}
        description="用户可以使用用户名和密码登录后台。"
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
              disabled={
                pending ||
                !username.trim() ||
                !groupId ||
                (!editing && !password)
              }
            >
              {pending ? <LoaderCircleIcon className="spin" size={17} /> : null}
              保存
            </Button>
          </>
        }
      >
        <div className="drawer-form">
          <label className="field">
            <span>用户名</span>
            <Input
              value={username}
              disabled={Boolean(editing)}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="请输入用户名"
            />
          </label>
          <label className="field">
            <span>{editing ? "重置密码（留空则不修改）" : "登录密码"}</span>
            <Input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={editing ? "不修改请留空" : "请输入登录密码"}
            />
          </label>
          <label className="field">
            <span>角色</span>
            <SelectField
              value={groupId}
              onValueChange={setGroupId}
              placeholder="请选择角色"
              options={groups.map((group) => ({
                value: String(group.id),
                label: group.name,
              }))}
            />
          </label>
          <label className="switch-row">
            <span>
              <strong>允许登录</strong>
              <small>停用后该用户将无法登录系统。</small>
            </span>
            <Switch checked={enabled} onCheckedChange={setEnabled} />
          </label>
        </div>
      </Drawer>
    </StandardListPage>
  );
}
