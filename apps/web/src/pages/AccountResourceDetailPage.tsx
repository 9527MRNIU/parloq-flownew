import {
  ArrowLeftIcon,
  CheckCheckIcon,
  MessageSquareTextIcon,
  RefreshCwIcon,
  UserRoundIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { apiRequest, formatDateTime, unwrapList } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import {
  ListPagination,
  ListTableCard,
  ListToolbar,
  StandardListPage,
} from "../components/list-page";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Drawer,
  EmptyState,
  Input,
  Modal,
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
import { formatPhoneDisplay } from "../lib/utils";

type DetailTab = "overview" | "friends" | "groups" | "lifecycle";

type AccountDetail = {
  id: string;
  name: string;
  phone: string;
  status: string;
  connected: boolean;
  source: string;
  accountType: string;
  deviceOs: string;
  waPlatformRaw: string;
  metadataSyncStatus: string;
  lastError: string;
  lastConnectedAt: string;
  createdAt: string;
  groupName: string;
  protocolName: string;
  protocolType: string;
  resourceSync: Record<string, unknown>;
  quality: {
    hasAvatar: boolean | null;
    avatarUrl: string;
    friendCount: number | null;
    groupCount: number | null;
    uniqueGroupMemberCount: number | null;
    score: number | null;
    avatarPoints: number | null;
    friendPoints: number | null;
    groupMemberPoints: number | null;
    syncedAt: string;
  };
};

type FriendRow = {
  id: string;
  contactId: string;
  displayName: string;
  phone: string;
  jid: string;
  lid: string;
  isSavedContact: boolean;
  hasChatHistory: boolean;
  lastInteractionAt: string;
  syncedAt: string;
};

type GroupRow = {
  id: string;
  groupJid: string;
  subject: string;
  size: number;
  communityType: string;
  ownRole: string;
  canSend: boolean;
  announce: boolean;
  lastInteractionAt: string;
  syncedAt: string;
};

type LifecycleRow = {
  id: string;
  fromState: string;
  toState: string;
  reason: string;
  providerCode: string;
  occurredAt: string;
};

const text = (row: Record<string, unknown>, key: string) =>
  row[key] == null ? "" : String(row[key]);

const number = (row: Record<string, unknown>, key: string) => {
  const value = row[key];
  if (value == null || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

function accountDetail(input: unknown): AccountDetail {
  const row = input as Record<string, unknown>;
  const status = text(row, "status");
  const quality = (row.quality || {}) as Record<string, unknown>;
  const group = (row.group || {}) as Record<string, unknown>;
  const protocol = (row.protocol || {}) as Record<string, unknown>;
  const rawAvatar = quality.hasAvatar;
  return {
    id: text(row, "id"),
    name: text(row, "name"),
    phone: formatPhoneDisplay(text(row, "phone")),
    status,
    connected: Boolean(
      row.connected ??
        ["connected", "online", "online_idle", "sending"].includes(status),
    ),
    source: text(row, "source"),
    accountType: text(row, "accountType") || "unknown",
    deviceOs: text(row, "deviceOs") || "unknown",
    waPlatformRaw: text(row, "waPlatformRaw"),
    metadataSyncStatus: text(row, "metadataSyncStatus"),
    lastError: text(row, "lastError"),
    lastConnectedAt: text(row, "lastConnectedAt"),
    createdAt: text(row, "createdAt"),
    groupName: text(group, "name"),
    protocolName: text(protocol, "name"),
    protocolType: text(protocol, "type"),
    resourceSync:
      row.resourceSync && typeof row.resourceSync === "object"
        ? (row.resourceSync as Record<string, unknown>)
        : {},
    quality: {
      hasAvatar: rawAvatar == null ? null : Boolean(rawAvatar),
      avatarUrl: text(quality, "avatarUrl"),
      friendCount: number(quality, "friendCount"),
      groupCount: number(quality, "groupCount"),
      uniqueGroupMemberCount: number(quality, "uniqueGroupMemberCount"),
      score: number(quality, "score"),
      avatarPoints: number(quality, "avatarPoints"),
      friendPoints: number(quality, "friendPoints"),
      groupMemberPoints: number(quality, "groupMemberPoints"),
      syncedAt: text(quality, "syncedAt"),
    },
  };
}

function friendRow(input: unknown): FriendRow {
  const row = input as Record<string, unknown>;
  return {
    id: text(row, "id"),
    contactId: text(row, "contactId"),
    displayName: text(row, "displayName"),
    phone: formatPhoneDisplay(text(row, "phone")),
    jid: text(row, "jid"),
    lid: text(row, "lid"),
    isSavedContact: Boolean(row.isSavedContact),
    hasChatHistory: Boolean(row.hasChatHistory),
    lastInteractionAt: text(row, "lastInteractionAt"),
    syncedAt: text(row, "syncedAt"),
  };
}

function groupRow(input: unknown): GroupRow {
  const row = input as Record<string, unknown>;
  return {
    id: text(row, "id"),
    groupJid: text(row, "groupJid"),
    subject: text(row, "subject"),
    size: number(row, "size") || 0,
    communityType: text(row, "communityType"),
    ownRole: text(row, "ownRole"),
    canSend: Boolean(row.canSend),
    announce: Boolean(row.announce),
    lastInteractionAt: text(row, "lastInteractionAt"),
    syncedAt: text(row, "syncedAt"),
  };
}

function lifecycleRow(input: unknown): LifecycleRow {
  const row = input as Record<string, unknown>;
  return {
    id: text(row, "id"),
    fromState: text(row, "fromState"),
    toState: text(row, "toState"),
    reason: text(row, "reason"),
    providerCode: text(row, "providerCode"),
    occurredAt: text(row, "occurredAt"),
  };
}

const accountTypeLabel = (value: string) =>
  value === "business" ? "商业版" : value === "personal" ? "个人版" : "-";

const deviceOsLabel = (value: string) =>
  value === "android"
    ? "安卓"
    : value === "ios"
      ? "苹果"
      : value === "other"
        ? "其他"
        : "-";

const statusLabel = (value: unknown) => {
  const status = typeof value === "string" ? value : "pending";
  if (status === "complete" || status === "ready") return "已完成";
  if (status === "partial") return "部分完成";
  if (status === "disabled") return "未开启";
  if (status === "failed") return "失败";
  return "等待同步";
};

function resourceState(account: AccountDetail, key: "contacts" | "groups") {
  const value = account.resourceSync[key];
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function AccountResourceDetailContent({
  accountId,
  tab,
  onTabChange,
  onBack,
  onAccountChange,
}: {
  accountId: string;
  tab: DetailTab;
  onTabChange: (tab: DetailTab) => void;
  onBack?: () => void;
  onAccountChange?: () => void | Promise<void>;
}) {
  const { can } = useAuth();
  const canManage =
    can("resources.accounts.manage") ||
    can("business.personal_accounts.manage");
  const [account, setAccount] = useState<AccountDetail | null>(null);
  const [loadingAccount, setLoadingAccount] = useState(true);
  const [rows, setRows] = useState<Array<FriendRow | GroupRow | LifecycleRow>>([]);
  const [loadingRows, setLoadingRows] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [connectionPending, setConnectionPending] = useState(false);
  const [messageTestOpen, setMessageTestOpen] = useState(false);
  const [testTo, setTestTo] = useState("");
  const [testText, setTestText] = useState("Parloq 连接测试消息");
  const [testPending, setTestPending] = useState(false);
  const [testResult, setTestResult] = useState("");
  const [keyword, setKeyword] = useState("");
  const [appliedKeyword, setAppliedKeyword] = useState("");
  const [source, setSource] = useState("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [total, setTotal] = useState(0);

  const loadAccount = useCallback(async () => {
    if (!accountId) return;
    setLoadingAccount(true);
    try {
      const payload = await apiRequest(`/api/personal-accounts/${accountId}`);
      const body = ((payload as { data?: unknown }).data || payload) as Record<
        string,
        unknown
      >;
      setAccount(accountDetail(body.account || body));
    } catch (caught) {
      setAccount(null);
      toast.error(caught instanceof Error ? caught.message : "账号详情加载失败");
    } finally {
      setLoadingAccount(false);
    }
  }, [accountId]);

  const loadRows = useCallback(async () => {
    if (!accountId || tab === "overview") {
      setRows([]);
      setTotal(0);
      return;
    }
    setLoadingRows(true);
    try {
      const query = new URLSearchParams({
        page: String(page),
        pageSize: String(pageSize),
      });
      let path = `/api/personal-accounts/${accountId}/lifecycle`;
      if (tab === "friends") {
        path = `/api/personal-accounts/${accountId}/resources/contacts`;
        if (appliedKeyword) query.set("keyword", appliedKeyword);
        query.set("source", source);
      } else if (tab === "groups") {
        path = `/api/personal-accounts/${accountId}/resources/groups`;
        if (appliedKeyword) query.set("keyword", appliedKeyword);
      }
      const payload = await apiRequest(`${path}?${query.toString()}`);
      const list = unwrapList<unknown>(payload);
      setRows(
        tab === "friends"
          ? list.rows.map(friendRow)
          : tab === "groups"
            ? list.rows.map(groupRow)
            : list.rows.map(lifecycleRow),
      );
      setTotal(list.total);
    } catch (caught) {
      setRows([]);
      setTotal(0);
      toast.error(caught instanceof Error ? caught.message : "资源清单加载失败");
    } finally {
      setLoadingRows(false);
    }
  }, [accountId, appliedKeyword, page, pageSize, source, tab]);

  useEffect(() => void loadAccount(), [loadAccount]);
  useEffect(() => void loadRows(), [loadRows]);

  const switchTab = (value: DetailTab) => {
    onTabChange(value);
    setPage(1);
    setKeyword("");
    setAppliedKeyword("");
  };

  const sync = async () => {
    if (!accountId) return;
    setSyncing(true);
    try {
      await apiRequest(`/api/personal-accounts/${accountId}/sync`, {
        method: "POST",
      });
      await loadAccount();
      toast.success("资料同步任务已提交到后台");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "同步任务提交失败");
    } finally {
      setSyncing(false);
    }
  };

  const openMessageTest = (target = "") => {
    setTestTo(target);
    setTestResult("");
    setMessageTestOpen(true);
  };

  const changeConnection = async () => {
    if (!accountId || !account) return;
    const action = account.connected ? "disconnect" : "connect";
    setConnectionPending(true);
    try {
      const payload = await apiRequest(
        `/api/personal-accounts/${accountId}/${action}`,
        { method: "POST" },
      );
      const body = ((payload as { data?: unknown }).data || payload) as Record<
        string,
        unknown
      >;
      setAccount(accountDetail(body.account || body));
      await onAccountChange?.();
      toast.success(action === "connect" ? "账号已登录上线" : "账号已断开下线");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "上下线操作失败");
    } finally {
      setConnectionPending(false);
    }
  };

  const sendTest = async () => {
    if (!accountId || !testTo.trim() || !testText.trim()) return;
    setTestPending(true);
    setTestResult("");
    try {
      const payload = await apiRequest(
        `/api/personal-accounts/${accountId}/send`,
        {
          method: "POST",
          body: JSON.stringify({
            to: testTo.trim(),
            message: testText.trim(),
            idempotencyKey: crypto.randomUUID(),
          }),
        },
      );
      const data = ((payload as { data?: Record<string, unknown> }).data ||
        {}) as Record<string, unknown>;
      const delivery = (data.messageDelivery ||
        data.message_delivery ||
        data) as Record<string, unknown>;
      setTestResult(
        text(delivery, "deliveryStatus") ||
          text(delivery, "status") ||
          "server_accepted",
      );
    } catch (caught) {
      setTestResult(caught instanceof Error ? caught.message : "发送失败");
    } finally {
      setTestPending(false);
    }
  };

  if (loadingAccount) {
    return <div className="loading-state min-h-64"><Spinner />正在加载账号资源…</div>;
  }
  if (!account) {
    return (
      <div className="grid gap-4">
        <EmptyState
          title="账号不存在或无权查看"
          description="请返回账号管理重新选择账号。"
        />
        {onBack ? (
          <div className="flex justify-center">
            <Button onClick={onBack}>返回账号管理</Button>
          </div>
        ) : null}
      </div>
    );
  }

  const contactsState = resourceState(account, "contacts");
  const groupsState = resourceState(account, "groups");
  const contactRows = rows as FriendRow[];
  const groupRows = rows as GroupRow[];
  const lifecycleRows = rows as LifecycleRow[];

  return (
    <div className="grid gap-4">
      <div className="flex flex-col gap-4 rounded-xl border bg-card p-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          {onBack ? (
            <Button variant="outline" size="icon" aria-label="返回账号管理" onClick={onBack}>
              <ArrowLeftIcon size={18} />
            </Button>
          ) : null}
          <div className="flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-xl border bg-muted text-muted-foreground">
            {account.quality.avatarUrl ? (
              <img src={account.quality.avatarUrl} alt="账号头像" className="size-full object-cover" />
            ) : (
              <UserRoundIcon size={24} />
            )}
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-lg font-semibold">{account.phone || account.name || "账号详情"}</h2>
              <Badge tone={account.lastError ? "danger" : "neutral"}>{account.status || "未知状态"}</Badge>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              {accountTypeLabel(account.accountType)} · {deviceOsLabel(account.deviceOs)} · ID {account.id}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted-foreground">资料更新 {formatDateTime(account.quality.syncedAt)}</span>
          <Button variant="outline" disabled={syncing} onClick={() => void sync()}>
            {syncing ? <Spinner /> : <RefreshCwIcon size={16} />}同步资料
          </Button>
          <Button
            variant="outline"
            disabled={!account.connected || connectionPending}
            onClick={() => openMessageTest()}
          >
            <MessageSquareTextIcon size={16} />消息测试
          </Button>
          {canManage ? (
            <Button
              variant="outline"
              disabled={connectionPending}
              onClick={() => void changeConnection()}
            >
              {connectionPending ? <Spinner /> : null}
              {account.connected ? "断开下线" : "登录上线"}
            </Button>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap gap-2" role="tablist" aria-label="账号资源详情">
        {([
          ["overview", "概览"],
          ["friends", `好友清单（${account.quality.friendCount ?? "-"}）`],
          ["groups", `群组清单（${account.quality.groupCount ?? "-"}）`],
          ["lifecycle", "生命周期"],
        ] as Array<[DetailTab, string]>).map(([value, label]) => (
          <Button key={value} role="tab" aria-selected={tab === value} variant={tab === value ? "secondary" : "outline"} onClick={() => switchTab(value)}>
            {label}
          </Button>
        ))}
      </div>

      {tab === "overview" ? (
        <div className="grid gap-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Card><CardHeader><CardDescription>账户评分</CardDescription><CardTitle className="text-2xl">{account.quality.score == null ? "待同步" : `${account.quality.score} 分`}</CardTitle></CardHeader><CardContent className="text-xs text-muted-foreground">头像 {account.quality.avatarPoints ?? "-"} + 好友 {account.quality.friendPoints ?? "-"} + 群成员 {account.quality.groupMemberPoints ?? "-"}</CardContent></Card>
            <Card><CardHeader><CardDescription>好友数</CardDescription><CardTitle className="text-2xl">{account.quality.friendCount ?? "未知"}</CardTitle></CardHeader><CardContent className="text-xs text-muted-foreground">通讯录联系人与有过一对一联系的账号去重合并</CardContent></Card>
            <Card><CardHeader><CardDescription>群组数</CardDescription><CardTitle className="text-2xl">{account.quality.groupCount ?? "未知"}</CardTitle></CardHeader><CardContent className="text-xs text-muted-foreground">当前账号参与的有效群组</CardContent></Card>
            <Card><CardHeader><CardDescription>去重群成员</CardDescription><CardTitle className="text-2xl">{account.quality.uniqueGroupMemberCount ?? "未知"}</CardTitle></CardHeader><CardContent className="text-xs text-muted-foreground">跨群去重后，每 5 人计 1 分</CardContent></Card>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle>账号与设备</CardTitle><CardDescription>Baileys 可识别的信息优先，无法识别时保留接入模型参数。</CardDescription></CardHeader>
              <CardContent className="grid gap-4 sm:grid-cols-2">
                <div className="cell-main"><span>账户类型</span><strong>{accountTypeLabel(account.accountType)}</strong></div>
                <div className="cell-main"><span>系统类型</span><strong>{deviceOsLabel(account.deviceOs)}</strong><span>{account.waPlatformRaw || "无原始平台值"}</span></div>
                <div className="cell-main"><span>协议节点</span><strong>{account.protocolName || "未知"}</strong><span>{account.protocolType || "协议类型未知"}</span></div>
                <div className="cell-main"><span>账号分组</span><strong>{account.groupName || "未分组"}</strong></div>
                <div className="cell-main"><span>来源</span><strong>{account.source === "json_import" ? "会话包导入" : account.source === "landing_page" ? "落地页链接" : account.source || "待识别"}</strong></div>
                <div className="cell-main"><span>最近连接</span><strong>{formatDateTime(account.lastConnectedAt)}</strong></div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>资源同步状态</CardTitle><CardDescription>好友同步与群组同步分别落库；部分数据不会覆盖已经同步的完整清单。</CardDescription></CardHeader>
              <CardContent className="grid gap-4 sm:grid-cols-2">
                <div className="cell-main"><span>好友同步</span><strong>{statusLabel(contactsState.status)}</strong><span>{contactsState.complete === true ? "清单完整" : "清单可能不完整"}</span></div>
                <div className="cell-main"><span>群组同步</span><strong>{statusLabel(groupsState.status)}</strong><span>{groupsState.identityMappingComplete === true ? "成员身份映射完整" : "成员身份映射可能不完整"}</span></div>
                <div className="cell-main"><span>资料任务</span><strong>{account.metadataSyncStatus || "pending"}</strong></div>
                <div className="cell-main"><span>最近异常</span><strong className={account.lastError ? "text-destructive" : ""}>{account.lastError || "无异常"}</strong></div>
              </CardContent>
            </Card>
          </div>
        </div>
      ) : (
        <>
          <ListToolbar
            search={tab === "lifecycle" ? undefined : { value: keyword, onChange: setKeyword, placeholder: tab === "friends" ? "搜索好友名称、手机号、JID" : "搜索群名称或群 JID", onSubmit: () => { setAppliedKeyword(keyword.trim()); setPage(1); } }}
            filters={tab === "friends" ? <SelectField ariaLabel="好友来源" value={source} onValueChange={(value) => { setSource(value); setPage(1); }} options={[{ value: "all", label: "全部好友" }, { value: "saved", label: "通讯录联系人" }, { value: "contacted", label: "有过联系" }]} className="w-[150px]" /> : null}
            meta={`共 ${total.toLocaleString()} 条`}
            actions={<Button variant="outline" disabled={loadingRows} onClick={() => void loadRows()}><RefreshCwIcon size={16} className={loadingRows ? "spin" : ""} />刷新</Button>}
          />
          <ListPagination page={page} pageSize={pageSize} total={total} disabled={loadingRows} onPageChange={setPage} onPageSizeChange={(value) => { setPageSize(value); setPage(1); }} />
          <ListTableCard>
            {loadingRows ? <div className="loading-state"><Spinner />正在加载资源清单…</div> : tab === "friends" && contactRows.length ? (
              <Table layout="list">
                <TableHeader><TableRow><TableHead adaptive>好友</TableHead><TableHead>来源</TableHead><TableHead>身份标识</TableHead><TableHead>最近联系</TableHead><TableHead>同步时间</TableHead><TableHead>操作</TableHead></TableRow></TableHeader>
                <TableBody>{contactRows.map((row) => {
                  const target = row.phone || row.jid;
                  return <TableRow key={row.id}><TableCell primary><div className="cell-main"><strong>{row.displayName || row.phone || row.contactId}</strong><span>{row.phone || "未解析手机号"}</span></div></TableCell><TableCell><div className="flex flex-wrap gap-1">{row.isSavedContact ? <Badge tone="neutral">通讯录</Badge> : null}{row.hasChatHistory ? <Badge tone="neutral">有过联系</Badge> : null}</div></TableCell><TableCell><div className="cell-main max-w-[260px]"><span className="truncate" title={row.jid}>{row.jid || "无 JID"}</span><span className="truncate" title={row.lid}>{row.lid || "无 LID"}</span></div></TableCell><TableCell>{formatDateTime(row.lastInteractionAt)}</TableCell><TableCell>{formatDateTime(row.syncedAt)}</TableCell><TableCell><Button variant="outline" size="sm" disabled={!account.connected || !target} title={!account.connected ? "账号未上线" : !target ? "好友缺少可发送的号码或 JID" : undefined} onClick={() => openMessageTest(target)}><MessageSquareTextIcon size={14} />消息测试</Button></TableCell></TableRow>;
                })}</TableBody>
              </Table>
            ) : tab === "groups" && groupRows.length ? (
              <Table layout="list">
                <TableHeader><TableRow><TableHead adaptive>群组</TableHead><TableHead>人数</TableHead><TableHead>类型</TableHead><TableHead>我的权限</TableHead><TableHead>最近联系</TableHead><TableHead>操作</TableHead></TableRow></TableHeader>
                <TableBody>{groupRows.map((row) => <TableRow key={row.id}><TableCell primary><div className="cell-main"><strong>{row.subject || "未命名群组"}</strong><span>{row.groupJid}</span></div></TableCell><TableCell>{row.size}</TableCell><TableCell><Badge tone="neutral">{row.communityType === "community" ? "社区" : row.communityType === "community_announcement" ? "社区公告" : "普通群组"}</Badge></TableCell><TableCell><div className="cell-main"><strong>{row.ownRole === "superadmin" ? "群主" : row.ownRole === "admin" ? "管理员" : "成员"}</strong><span>{row.canSend ? "可发送" : "不可发送"}{row.announce ? " · 仅管理员发言" : ""}</span></div></TableCell><TableCell><div className="cell-main"><strong>{formatDateTime(row.lastInteractionAt)}</strong><span>同步于 {formatDateTime(row.syncedAt)}</span></div></TableCell><TableCell><Button variant="outline" size="sm" disabled={!account.connected || !row.canSend || !row.groupJid} title={!account.connected ? "账号未上线" : !row.canSend ? "当前账号无群消息发送权限" : !row.groupJid ? "群组缺少 JID" : undefined} onClick={() => openMessageTest(row.groupJid)}><MessageSquareTextIcon size={14} />消息测试</Button></TableCell></TableRow>)}</TableBody>
              </Table>
            ) : tab === "lifecycle" && lifecycleRows.length ? (
              <Table layout="list"><TableHeader><TableRow><TableHead>发生时间</TableHead><TableHead>状态变化</TableHead><TableHead adaptive>原因</TableHead><TableHead>服务码</TableHead></TableRow></TableHeader><TableBody>{lifecycleRows.map((row) => <TableRow key={row.id}><TableCell>{formatDateTime(row.occurredAt)}</TableCell><TableCell><Badge tone="neutral">{row.fromState || "初始"} → {row.toState || "未知"}</Badge></TableCell><TableCell>{row.reason || "未记录"}</TableCell><TableCell>{row.providerCode || "-"}</TableCell></TableRow>)}</TableBody></Table>
            ) : <EmptyState title={tab === "friends" ? "暂无好友资源" : tab === "groups" ? "暂无群组资源" : "暂无生命周期记录"} description={tab === "lifecycle" ? "发生账号状态变化后会在这里形成记录。" : "请确认协议节点已开启对应同步开关，并提交一次资料同步。"} />}
          </ListTableCard>
        </>
      )}

      <Modal
        open={messageTestOpen}
        onClose={() => !testPending && setMessageTestOpen(false)}
        title="消息测试"
        description={`使用 ${account.phone || account.id} 验证连接和送达状态。`}
        footer={
          <>
            <Button
              variant="outline"
              disabled={testPending}
              onClick={() => setMessageTestOpen(false)}
            >
              关闭
            </Button>
            <Button
              disabled={testPending || !testTo.trim() || !testText.trim()}
              onClick={() => void sendTest()}
            >
              {testPending ? <Spinner /> : <MessageSquareTextIcon size={16} />}
              发送
            </Button>
          </>
        }
      >
        <label className="field">
          <span>接收目标（号码或群组 JID）</span>
          <Input
            value={testTo}
            onChange={(event) => setTestTo(event.target.value)}
            placeholder="例如：8613800000000 或 120363…@g.us"
          />
        </label>
        <label className="field">
          <span>测试内容</span>
          <Textarea
            rows={4}
            value={testText}
            onChange={(event) => setTestText(event.target.value)}
          />
        </label>
        {testResult ? (
          <div className="delivery-result">
            <CheckCheckIcon size={18} />
            <div>
              <strong>
                {testResult === "delivered"
                  ? "双勾 · 已送达"
                  : testResult === "server_accepted" || testResult === "sent"
                    ? "单勾 · 服务端已接收"
                    : testResult}
              </strong>
              <small>本系统不保存回复正文、已读状态或完整会话。</small>
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}

export function AccountResourceDetailDrawer({
  accountId,
  accountLabel,
  onClose,
  onAccountChange,
}: {
  accountId: string;
  accountLabel: string;
  onClose: () => void;
  onAccountChange?: () => void | Promise<void>;
}) {
  return (
    <Drawer
      open={Boolean(accountId)}
      onClose={onClose}
      title="账号详情"
      description={
        accountId
          ? `${accountLabel || "未命名账号"} · ID ${accountId}`
          : "查看账号资料与同步资源。"
      }
      wide
    >
      {accountId ? (
        <AccountResourceDrawerBody
          key={accountId}
          accountId={accountId}
          onAccountChange={onAccountChange}
        />
      ) : null}
    </Drawer>
  );
}

function AccountResourceDrawerBody({
  accountId,
  onAccountChange,
}: {
  accountId: string;
  onAccountChange?: () => void | Promise<void>;
}) {
  const [tab, setTab] = useState<DetailTab>("overview");
  return (
    <AccountResourceDetailContent
      accountId={accountId}
      tab={tab}
      onTabChange={setTab}
      onAccountChange={onAccountChange}
    />
  );
}

export function AccountResourceDetailPage() {
  const { accountId = "" } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get("tab") as DetailTab | null;
  const tab: DetailTab = ["overview", "friends", "groups", "lifecycle"].includes(
    requestedTab || "",
  )
    ? requestedTab!
    : "overview";

  return (
    <StandardListPage>
      <AccountResourceDetailContent
        key={accountId}
        accountId={accountId}
        tab={tab}
        onTabChange={(value) => setSearchParams({ tab: value })}
        onBack={() => navigate("/resources/accounts/manage")}
      />
    </StandardListPage>
  );
}
