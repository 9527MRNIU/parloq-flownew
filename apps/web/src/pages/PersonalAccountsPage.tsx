import {
  AlertTriangleIcon,
  CheckCheckIcon,
  EyeIcon,
  FolderInputIcon,
  LoaderCircleIcon,
  MessageSquareTextIcon,
  RefreshCwIcon,
  SlidersHorizontalIcon,
  SmartphoneIcon,
  Trash2Icon,
  UploadCloudIcon,
  UserRoundIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { SiAndroid, SiApple } from "react-icons/si";
import { useSearchParams } from "react-router-dom";
import { apiRequest, formatDateTime, unwrapList } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import {
  AccountStatusIndicator,
} from "../components/account-status-indicator";
import { CountryDisplay } from "../components/country-display";
import { DrawerFieldLabel } from "../components/drawer-form";
import { AccountResourceDetailDrawer } from "./AccountResourceDetailPage";
import {
  ListPagination,
  ListTableCard,
  ListToolbar,
  StandardListPage,
} from "../components/list-page";
import {
  Badge,
  Button,
  Checkbox,
  confirmAction,
  Drawer,
  EmptyState,
  Input,
  Modal,
  Popover,
  PopoverContent,
  PopoverTrigger,
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
import {
  accountRowKey,
  groupRowKey,
  snowflakeId,
} from "../lib/account-identifiers";
import { formatPhoneDisplay } from "../lib/utils";

type Account = {
  id: string;
  readKey: string;
  ownerId: string;
  phone: string;
  name: string;
  countryCode: string;
  visitorCountryCode: string;
  status: string;
  connected: boolean;
  proxyId: string;
  source: string;
  sourceRefType: string;
  importFormat: string;
  validationStatus: string;
  metadataSyncStatus: string;
  lastError: string;
  groupId: string;
  groupName: string;
  protocolId: string;
  protocolName: string;
  protocolType: string;
  accepted: number | null;
  delivered: number | null;
  hasAvatar: boolean | null;
  avatarUrl: string;
  avatarFetchedAt: string;
  groupCount: number | null;
  friendCount: number | null;
  uniqueGroupMemberCount: number | null;
  qualityScore: number | null;
  accountType: string;
  deviceOs: string;
  waPlatformRaw: string;
  qualitySyncedAt: string;
  enabled: boolean;
  marketingEligible: boolean;
  lastConnectedAt?: string;
  createdAt?: string;
  updatedAt?: string;
};

function AccountAvatar({
  account,
  large = false,
}: {
  account: Account;
  large?: boolean;
}) {
  const label = account.phone || account.name || "账号";
  return (
    <div
      className={`${large ? "size-16" : "size-10"} flex shrink-0 items-center justify-center overflow-hidden rounded-lg border bg-muted text-muted-foreground`}
      title={account.avatarUrl ? `${label}的 WhatsApp 头像` : `${label}暂无已拉取头像`}
    >
      {account.avatarUrl ? (
        <img
          src={account.avatarUrl}
          alt={`${label}的 WhatsApp 头像`}
          className="size-full object-cover"
          loading={large ? "eager" : "lazy"}
          decoding="async"
        />
      ) : (
        <UserRoundIcon size={large ? 28 : 18} aria-hidden="true" />
      )}
    </div>
  );
}

type ProxyRow = {
  id: string;
  endpoint: string;
  countryCode: string;
  enabled: boolean;
};
type AccountGroup = { id: string; readKey: string; name: string; ownerId: string };
type ImportProtocol = {
  id: string;
  name: string;
  type: string;
  available: boolean;
  unavailableReason: string;
  supportedFormats: string[];
};
type FilterProtocol = { id: string; name: string; type: string };
const val = (row: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) if (row[key] != null) return String(row[key]);
  return "";
};
const optionalNumber = (row: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) {
    const value = row[key];
    if (value !== undefined && value !== null && value !== "") {
      const number = Number(value);
      return Number.isFinite(number) ? number : null;
    }
  }
  return null;
};
function accountRow(input: unknown): Account {
  const row = input as Record<string, unknown>;
  const status =
    val(row, "connectionStatus", "connection_status", "status") || "offline";
  const proxy = (row.proxyBinding || row.proxy_binding || {}) as Record<
    string,
    unknown
  >;
  const group = (row.group || {}) as Record<string, unknown>;
  const protocol = (row.protocol || {}) as Record<string, unknown>;
  const quality = (row.quality || {}) as Record<string, unknown>;
  const rawAvatar = quality.hasAvatar ?? quality.has_avatar;
  const id = snowflakeId(
    row,
    "id",
    "accountId",
    "account_id",
    "snowflakeId",
    "snowflake_id",
  );
  const rawName = val(row, "displayName", "display_name", "name");
  return {
    id,
    readKey: accountRowKey(row, id),
    ownerId: val(row, "ownerId", "owner_id", "createdBy", "created_by"),
    phone: formatPhoneDisplay(
      val(row, "phoneNumber", "phone_number", "phone"),
    ),
    name: /^\+\d+$/.test(rawName)
      ? formatPhoneDisplay(rawName)
      : rawName,
    countryCode: val(row, "countryCode", "country_code"),
    visitorCountryCode: val(
      row,
      "visitorCountryCode",
      "visitor_country_code",
    ),
    status,
    connected: Boolean(
      row.connected ??
        ["connected", "online", "online_idle", "sending"].includes(status),
    ),
    proxyId:
      snowflakeId(row, "proxyId", "proxy_id") ||
      snowflakeId(proxy, "id", "proxyId", "proxy_id"),
    source: val(row, "source", "credentialSource", "credential_source"),
    sourceRefType: val(row, "sourceRefType", "source_ref_type"),
    importFormat: val(row, "importFormat", "import_format"),
    validationStatus: val(
      row,
      "validationStatus",
      "validation_status",
    ),
    metadataSyncStatus: val(
      row,
      "metadataSyncStatus",
      "metadata_sync_status",
      "syncStatus",
      "sync_status",
    ),
    lastError: val(row, "lastError", "last_error"),
    groupId:
      snowflakeId(group, "id", "groupId", "group_id") ||
      snowflakeId(row, "groupId", "group_id"),
    groupName: val(group, "name") || val(row, "groupName", "group_name"),
    protocolId:
      snowflakeId(protocol, "id", "protocolId", "protocol_id") ||
      snowflakeId(row, "protocolId", "protocol_id"),
    protocolName:
      val(protocol, "name") || val(row, "protocolName", "protocol_name"),
    protocolType:
      val(protocol, "type", "protocolType", "protocol_type") ||
      val(row, "protocolType", "protocol_type"),
    accepted: optionalNumber(
      row,
      "acceptedCount",
      "accepted_count",
      "singleTickCount",
      "sentCount",
      "sent_count",
    ),
    delivered: optionalNumber(
      row,
      "deliveredCount",
      "delivered_count",
      "doubleTickCount",
    ),
    hasAvatar: rawAvatar == null ? null : Boolean(rawAvatar),
    avatarUrl: val(quality, "avatarUrl", "avatar_url"),
    avatarFetchedAt: val(quality, "avatarFetchedAt", "avatar_fetched_at"),
    groupCount: optionalNumber(quality, "groupCount", "group_count"),
    friendCount: optionalNumber(quality, "friendCount", "friend_count"),
    uniqueGroupMemberCount: optionalNumber(
      quality,
      "uniqueGroupMemberCount",
      "unique_group_member_count",
    ),
    qualityScore: optionalNumber(quality, "score"),
    accountType: val(row, "accountType", "account_type") || "unknown",
    deviceOs: val(row, "deviceOs", "device_os") || "unknown",
    waPlatformRaw: val(row, "waPlatformRaw", "wa_platform_raw"),
    qualitySyncedAt: val(quality, "syncedAt", "synced_at"),
    enabled: Boolean(row.enabled ?? true),
    marketingEligible: Boolean(
      row.marketingEligible ?? row.marketing_eligible ?? true,
    ),
    lastConnectedAt: val(row, "lastConnectedAt", "last_connected_at"),
    createdAt: val(row, "createdAt", "created_at"),
    updatedAt: val(row, "updatedAt", "updated_at"),
  };
}

function proxyRow(input: unknown): ProxyRow {
  const row = input as Record<string, unknown>;
  const id = snowflakeId(row, "id", "proxyId", "proxy_id");
  const host = val(row, "host", "hostname");
  const port = val(row, "port");
  return {
    id,
    endpoint: host && port ? `${host}:${port}` : `代理 #${id}`,
    countryCode: val(row, "countryCode", "country_code"),
    enabled: Boolean(row.enabled ?? true),
  };
}
function importProtocol(input: unknown): ImportProtocol {
  const row = input as Record<string, unknown>;
  return {
    id: snowflakeId(row, "id", "protocolId", "protocol_id"),
    name: val(row, "name"),
    type: val(row, "type", "protocol", "protocolType", "protocol_type"),
    available: Boolean(row.available),
    unavailableReason: val(row, "unavailableReason", "unavailable_reason"),
    supportedFormats: Array.isArray(row.supportedFormats ?? row.supported_formats)
      ? ((row.supportedFormats ?? row.supported_formats) as unknown[]).map(String)
      : [],
  };
}
function sourceBadge(row: Account) {
  if (["landing_page", "landing", "pairing"].includes(row.source))
    return <Badge tone="neutral">落地页链接</Badge>;
  if (["json", "json_import", "import"].includes(row.source))
    return <Badge tone="neutral">会话包导入</Badge>;
  return <Badge tone="neutral">待识别</Badge>;
}
const accountTypeLabel = (value: string) =>
  value === "business" ? "商业版" : value === "personal" ? "个人版" : "待识别";
const deviceOsLabel = (value: string) =>
  value === "android"
    ? "Android"
    : value === "ios"
      ? "iOS"
      : value === "other"
        ? "其他"
        : "待识别";
function DeviceOsDisplay({ value }: { value: string }) {
  const label = deviceOsLabel(value);
  const Icon =
    value === "android" ? SiAndroid : value === "ios" ? SiApple : SmartphoneIcon;
  return (
    <div className="flex min-w-max items-center justify-center gap-2">
      <Icon
        className="size-4 shrink-0"
        color={value === "android" ? "#3DDC84" : undefined}
        aria-hidden="true"
      />
      <span>{label}</span>
    </div>
  );
}
export function PersonalAccountsPage() {
  const { user, can } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const canManage =
    can("resources.accounts.manage") ||
    can("business.personal_accounts.manage");
  const canImport = can("resources.accounts.import") || canManage;
  const [rows, setRows] = useState<Account[]>([]);
  const [proxies, setProxies] = useState<ProxyRow[]>([]);
  const [groups, setGroups] = useState<AccountGroup[]>([]);
  const [importProtocols, setImportProtocols] = useState<ImportProtocol[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [groupFilter, setGroupFilter] = useState(
    searchParams.get("groupId") || "all",
  );
  const [sourceFilter, setSourceFilter] = useState("all");
  const [countryFilter, setCountryFilter] = useState("");
  const [protocolFilter, setProtocolFilter] = useState("");
  const [metadataFilter, setMetadataFilter] = useState("");
  const [qualityFilter, setQualityFilter] = useState("all");
  const [filterCountries, setFilterCountries] = useState<string[]>([]);
  const [filterProtocols, setFilterProtocols] = useState<FilterProtocol[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [batchGroupId, setBatchGroupId] = useState("");
  const [groupingIds, setGroupingIds] = useState<string[]>([]);
  const [operation, setOperation] = useState("");
  const [testAccount, setTestAccount] = useState<Account | null>(null);
  const [testTo, setTestTo] = useState("");
  const [testText, setTestText] = useState("Parloq 连接测试消息");
  const [testPending, setTestPending] = useState(false);
  const [testResult, setTestResult] = useState("");
  const [detailAccount, setDetailAccount] = useState<Account | null>(null);
  const [importOpen, setImportOpen] = useState(
    searchParams.get("import") === "1",
  );
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importValidation, setImportValidation] = useState<{
    valid: boolean;
    message: string;
  } | null>(null);
  const [importValidating, setImportValidating] = useState(false);
  const [importPending, setImportPending] = useState(false);
  const [importGroupId, setImportGroupId] = useState("");
  const [importProtocolId, setImportProtocolId] = useState("");
  const [importProxyId, setImportProxyId] = useState("");
  const proxyEndpointById = useMemo(
    () =>
      new Map(
        proxies.map((proxy) => [
          proxy.id,
          `${proxy.endpoint}${proxy.countryCode ? ` · ${proxy.countryCode}` : ""}`,
        ]),
      ),
    [proxies],
  );

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    try {
      const query = new URLSearchParams({
        page: String(page),
        pageSize: String(pageSize),
      });
      if (debouncedKeyword) query.set("keyword", debouncedKeyword);
      if (statusFilter !== "all") query.set("status", statusFilter);
      if (sourceFilter !== "all") query.set("source", sourceFilter);
      if (groupFilter !== "all") query.set("groupId", groupFilter);
      if (countryFilter) query.set("countryCode", countryFilter);
      if (protocolFilter) query.set("protocolId", protocolFilter);
      if (metadataFilter) query.set("metadataStatus", metadataFilter);
      if (qualityFilter !== "all") {
        query.set("qualityKnown", qualityFilter === "known" ? "true" : "false");
      }
      const accountsPayload = await apiRequest(
        `/api/personal-accounts?${query.toString()}`,
      );
      const next = unwrapList<unknown>(accountsPayload);
      const nextRows = next.rows.map(accountRow);
      setRows(nextRows);
      setTotal(next.total);
      setSelectedIds((current) =>
        current.filter((id) => nextRows.some((row) => row.id === id)),
      );
    } catch (caught) {
      setRows([]);
      setTotal(0);
      toast.error(caught instanceof Error ? caught.message : "账号加载失败");
    } finally {
      setLoading(false);
    }
  }, [
    countryFilter,
    debouncedKeyword,
    groupFilter,
    metadataFilter,
    page,
    pageSize,
    protocolFilter,
    qualityFilter,
    sourceFilter,
    statusFilter,
  ]);

  const loadReferences = useCallback(async () => {
    try {
      const [groupsPayload, proxiesPayload, importOptionsPayload, filterPayload] =
        await Promise.all([
        apiRequest("/api/account-groups?pageSize=100"),
        apiRequest("/api/ip-proxies?pageSize=100").catch(() => null),
        apiRequest("/api/personal-accounts/import-options"),
        apiRequest("/api/personal-accounts/filter-options"),
      ]);
      setGroups(
        unwrapList<Record<string, unknown>>(groupsPayload)
          .rows.map((row) => {
            const id = snowflakeId(row, "id", "groupId", "group_id");
            return {
              id,
              readKey: groupRowKey(row, id),
              name: val(row, "name"),
              ownerId: val(
                row,
                "ownerId",
                "owner_id",
                "createdBy",
                "created_by",
              ),
            };
          })
          .filter((row) => row.id),
      );
      if (proxiesPayload) {
        setProxies(unwrapList<unknown>(proxiesPayload).rows.map(proxyRow));
      } else setProxies([]);
      const nextImportProtocols = unwrapList<unknown>(importOptionsPayload)
        .rows.map(importProtocol)
        .filter((row) => row.id);
      setImportProtocols(nextImportProtocols);
      setImportProtocolId((current) => {
        if (
          nextImportProtocols.some(
            (row) => row.id === current && row.available,
          )
        ) {
          return current;
        }
        const available = nextImportProtocols.filter((row) => row.available);
        return available.length === 1 ? available[0].id : "";
      });
      const filterData = ((filterPayload as { data?: unknown }).data ||
        filterPayload) as Record<string, unknown>;
      setFilterCountries(
        Array.isArray(filterData.countries)
          ? filterData.countries.map(String).filter(Boolean)
          : [],
      );
      setFilterProtocols(
        Array.isArray(filterData.protocols)
          ? filterData.protocols
              .map((input) => {
                const row = input as Record<string, unknown>;
                return {
                  id: snowflakeId(row, "id", "protocolId", "protocol_id"),
                  name: val(row, "name"),
                  type: val(row, "type", "protocolType", "protocol_type"),
                };
              })
              .filter((row) => row.id)
          : [],
      );
    } catch (caught) {
      setGroups([]);
      setImportProtocols([]);
      setFilterCountries([]);
      setFilterProtocols([]);
      toast.error(caught instanceof Error ? caught.message : "账号筛选项加载失败");
    }
  }, [user?.isAdmin]);

  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedKeyword(keyword.trim()),
      250,
    );
    return () => window.clearTimeout(timer);
  }, [keyword]);
  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);
  useEffect(() => {
    void loadReferences();
  }, [loadReferences]);
  useEffect(() => {
    if (searchParams.get("import") === "1") setImportOpen(true);
  }, [searchParams]);
  const importGroups = useMemo(() => {
    const currentUserId = String(user?.id || "");
    return groups.filter(
      (group) =>
        !user?.isAdmin ||
        !currentUserId ||
        group.ownerId === currentUserId,
    );
  }, [groups, user?.id, user?.isAdmin]);
  const visibleIds = rows.map((row) => row.id).filter(Boolean);
  const allVisibleSelected =
    Boolean(visibleIds.length) &&
    visibleIds.every((id) => selectedIds.includes(id));
  const selectedOwnerIds = new Set(
    rows
      .filter((row) => selectedIds.includes(row.id))
      .map((row) => row.ownerId),
  );
  const batchGroups = groups.filter(
    (group) =>
      selectedOwnerIds.size === 1 && selectedOwnerIds.has(group.ownerId),
  );
  const batchTargetValid =
    batchGroupId === "__ungrouped__" ||
    batchGroups.some((group) => group.id === batchGroupId);
  async function action(
    row: Account,
    name: "connect" | "disconnect" | "logout" | "sync",
  ) {
    if (!row.id) return;
    if (
      name === "logout" &&
      !(await confirmAction({
        title: `登出 ${row.phone}？`,
        description: "登出后需要重新配对设备，会话凭证将被清除。",
        confirmText: "确认登出",
      }))
    )
      return;
    setOperation(`${row.id}:${name}`);
    try {
      await apiRequest(`/api/personal-accounts/${row.id}/${name}`, {
        method: "POST",
      });
      await loadAccounts();
      if (name === "sync") toast.success("资料同步任务已提交到后台");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "操作失败");
    } finally {
      setOperation("");
    }
  }
  async function deleteAccount(row: Account) {
    if (!row.id) return;
    const label = formatPhoneDisplay(row.phone) || row.name || row.id;
    if (
      !(await confirmAction({
        title: `彻底删除账号 ${label}？`,
        description:
          "账号将从账号管理中移除，手机号会被释放，WhatsApp 凭证、代理绑定、头像和同步资料会被清除。已经产生的接入记录、访问监控、渠道统计、趋势数据和发送明细会继续保留。",
        confirmText: "确认删除账号",
        destructive: true,
      }))
    )
      return;
    setOperation(`${row.id}:delete`);
    try {
      await apiRequest(`/api/personal-accounts/${row.id}`, {
        method: "DELETE",
      });
      setSelectedIds((current) => current.filter((id) => id !== row.id));
      await Promise.all([loadAccounts(), loadReferences()]);
      toast.success("账号已彻底删除，历史业务记录已保留");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "账号删除失败");
    } finally {
      setOperation("");
    }
  }
  async function batchChangeGroup() {
    if (!selectedIds.length || !batchGroupId || !batchTargetValid) return;
    const groupId = batchGroupId === "__ungrouped__" ? null : batchGroupId;
    const targetIds = [...selectedIds];
    setGroupingIds((current) => [...new Set([...current, ...targetIds])]);
    const results = await Promise.allSettled(
      targetIds.map((id) =>
        apiRequest(`/api/personal-accounts/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ groupId }),
        }),
      ),
    );
    const failed = results.filter((result) => result.status === "rejected");
    setGroupingIds((current) =>
      current.filter((id) => !targetIds.includes(id)),
    );
    await loadAccounts();
    if (failed.length) {
      toast.warning(
        `批量改组完成：成功 ${targetIds.length - failed.length} 个，失败 ${failed.length} 个`,
      );
    } else {
      toast.success(`已更新 ${targetIds.length} 个账号的分组`);
      setSelectedIds([]);
    }
  }
  async function sendTest() {
    if (!testAccount?.id || !testTo.trim() || !testText.trim()) return;
    setTestPending(true);
    setTestResult("");
    try {
      const payload = await apiRequest(
        `/api/personal-accounts/${testAccount.id}/send`,
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
        val(delivery, "deliveryStatus", "status") || "server_accepted",
      );
    } catch (caught) {
      setTestResult(caught instanceof Error ? caught.message : "发送失败");
    } finally {
      setTestPending(false);
    }
  }
  function openImport() {
    setImportProtocolId((current) => {
      if (current) return current;
      const available = importProtocols.filter((row) => row.available);
      return available.length === 1 ? available[0].id : "";
    });
    setImportOpen(true);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("import", "1");
      return next;
    });
  }
  function closeImport() {
    if (importPending) return;
    setImportOpen(false);
    setImportFile(null);
    setImportValidation(null);
    setImportGroupId("");
    setImportProtocolId("");
    setImportProxyId("");
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.delete("import");
      return next;
    }, { replace: true });
  }
  async function chooseImport(next: File | null) {
    setImportFile(next);
    setImportValidation(null);
    if (!next) return;
    setImportValidating(true);
    try {
      if (!next.name.toLowerCase().endsWith(".json"))
        throw new Error("请选择 .json 文件");
      if (next.size > 10 * 1024 * 1024)
        throw new Error("JSON 文件不能超过 10 MB");
      const parsed = JSON.parse(await next.text()) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
        throw new Error("JSON 顶层必须是对象");
      setImportValidation({
        valid: true,
        message: "文件已读取，导入时将继续检查账号信息。",
      });
    } catch (caught) {
      setImportValidation({
        valid: false,
        message: caught instanceof Error ? caught.message : "JSON 无法解析",
      });
    } finally {
      setImportValidating(false);
    }
  }
  async function submitImport() {
    if (
      !importFile ||
      !importValidation?.valid ||
      !importGroupId ||
      !importProtocolId ||
      !canImport
    )
      return;
    setImportPending(true);
    try {
      const body = new FormData();
      body.set("file", importFile);
      body.set("groupId", importGroupId);
      body.set("protocolId", importProtocolId);
      if (importProxyId) body.set("proxyId", importProxyId);
      await apiRequest("/api/personal-accounts/import", {
        method: "POST",
        body,
      });
      await Promise.all([loadAccounts(), loadReferences()]);
      toast.success("账号 JSON 已导入统一账号池");
      setImportOpen(false);
      setImportFile(null);
      setImportValidation(null);
      setImportGroupId("");
      setImportProtocolId("");
      setImportProxyId("");
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        next.delete("import");
        return next;
      }, { replace: true });
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "导入失败");
    } finally {
      setImportPending(false);
    }
  }
  const advancedFilterCount = [
    countryFilter,
    protocolFilter,
    metadataFilter,
    qualityFilter === "all" ? "" : qualityFilter,
  ].filter(Boolean).length;
  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: (value) => {
            setKeyword(value);
            setPage(1);
          },
          placeholder: "搜索号码、名称或国家",
        }}
        filters={
          <>
            <SelectField
              ariaLabel="账号状态"
              className="w-[150px]"
              value={statusFilter}
              onValueChange={(value) => {
                setStatusFilter(value);
                setPage(1);
              }}
              options={[
                { value: "all", label: "全部账号状态" },
                { value: "online", label: "在线" },
                { value: "offline", label: "离线" },
                { value: "processing", label: "处理中" },
                { value: "pending_validation", label: "待验证" },
                { value: "validating", label: "验证中" },
                { value: "validation_failed", label: "验证失败" },
                { value: "pending_sync", label: "待同步" },
                { value: "syncing", label: "同步中" },
                { value: "sync_failed", label: "同步失败" },
                { value: "error", label: "账号异常" },
              ]}
            />
            <SelectField
              ariaLabel="账号来源"
              className="w-[145px]"
              value={sourceFilter}
              onValueChange={(value) => {
                setSourceFilter(value);
                setPage(1);
              }}
              options={[
                { value: "all", label: "全部来源" },
                { value: "landing_page", label: "落地页链接" },
                { value: "json_import", label: "会话包导入" },
              ]}
            />
            <SelectField
              ariaLabel="账号分组筛选"
              className="w-[155px]"
              value={groupFilter}
              onValueChange={(value) => {
                setGroupFilter(value);
                setPage(1);
              }}
              options={[
                { value: "all", label: "全部分组" },
                { value: "__ungrouped__", label: "未分组" },
                ...groups.map((group) => ({
                  value: group.id,
                  label: user?.isAdmin
                    ? `${group.name} · 客户 #${group.ownerId}`
                    : group.name,
                })),
              ]}
            />
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="outline">
                  <SlidersHorizontalIcon size={16} />
                  更多筛选
                  {advancedFilterCount ? (
                    <Badge tone="neutral">{advancedFilterCount}</Badge>
                  ) : null}
                </Button>
              </PopoverTrigger>
              <PopoverContent align="start" className="w-80 space-y-4">
                <div>
                  <strong className="text-sm">精细筛选</strong>
                  <p className="mt-1 text-xs text-muted-foreground">
                    按接入资源和资料完整度缩小账号范围。
                  </p>
                </div>
                <SelectField
                  ariaLabel="国家筛选"
                  className="w-full"
                  value={countryFilter}
                  onValueChange={(value) => {
                    setCountryFilter(value);
                    setPage(1);
                  }}
                  placeholder="全部国家"
                  clearable
                  options={filterCountries.map((country) => ({
                    value: country,
                    label: country,
                  }))}
                />
                <SelectField
                  ariaLabel="协议节点筛选"
                  className="w-full"
                  value={protocolFilter}
                  onValueChange={(value) => {
                    setProtocolFilter(value);
                    setPage(1);
                  }}
                  placeholder="全部协议"
                  clearable
                  options={filterProtocols.map((protocol) => ({
                    value: protocol.id,
                    label: `${protocol.name} · ${protocol.type || "未知类型"}`,
                  }))}
                />
                <SelectField
                  ariaLabel="资料同步状态筛选"
                  className="w-full"
                  value={metadataFilter}
                  onValueChange={(value) => {
                    setMetadataFilter(value);
                    setPage(1);
                  }}
                  placeholder="全部资料同步状态"
                  clearable
                  options={[
                    { value: "pending", label: "待同步" },
                    { value: "syncing", label: "同步中" },
                    { value: "ready", label: "已同步" },
                    { value: "failed", label: "同步失败" },
                    { value: "unsupported", label: "不支持同步" },
                  ]}
                />
                <SelectField
                  ariaLabel="基础资料完整度筛选"
                  className="w-full"
                  value={qualityFilter}
                  onValueChange={(value) => {
                    setQualityFilter(value);
                    setPage(1);
                  }}
                  options={[
                    { value: "all", label: "全部资料情况" },
                    { value: "known", label: "基础资料已知" },
                    { value: "unknown", label: "基础资料未知" },
                  ]}
                />
                <Button
                  variant="outline"
                  className="w-full"
                  disabled={!advancedFilterCount}
                  onClick={() => {
                    setCountryFilter("");
                    setProtocolFilter("");
                    setMetadataFilter("");
                    setQualityFilter("all");
                    setPage(1);
                  }}
                >
                  清除精细筛选
                </Button>
              </PopoverContent>
            </Popover>
          </>
        }
        meta={
          selectedIds.length
            ? `已选择 ${selectedIds.length} / ${total} 个账号`
            : `${total} 个账号`
        }
        actions={
          <>
            {canManage && selectedIds.length ? (
              <>
                <SelectField
                  ariaLabel="批量设置账号分组"
                  className="w-[170px]"
                  value={batchGroupId}
                  onValueChange={setBatchGroupId}
                  placeholder="选择目标分组"
                  options={[
                    { value: "__ungrouped__", label: "移出所有分组" },
                    ...batchGroups.map((group) => ({
                      value: group.id,
                      label: user?.isAdmin
                        ? `${group.name} · 客户 #${group.ownerId}`
                        : group.name,
                    })),
                  ]}
                />
                <Button
                  variant="outline"
                  disabled={
                    !batchGroupId ||
                    !batchTargetValid ||
                    Boolean(groupingIds.length)
                  }
                  onClick={() => void batchChangeGroup()}
                >
                  {groupingIds.length ? <Spinner /> : <FolderInputIcon size={16} />}
                  批量改组
                </Button>
              </>
            ) : null}
            <Button
              variant="outline"
              onClick={() =>
                void Promise.all([loadAccounts(), loadReferences()])
              }
              disabled={loading}
            >
              <RefreshCwIcon size={16} className={loading ? "spin" : ""} />
              刷新
            </Button>
            {canImport ? (
              <Button onClick={openImport}>
                <UploadCloudIcon size={16} />
                导入账号
              </Button>
            ) : null}
          </>
        }
      />
      <ListPagination
        page={page}
        pageSize={pageSize}
        total={total}
        disabled={loading}
        onPageChange={setPage}
        onPageSizeChange={(value) => {
          setPageSize(value);
          setPage(1);
        }}
      />
      <ListTableCard>
        {loading ? (
          <div className="loading-state">
            <Spinner />
            正在加载统一账号池…
          </div>
        ) : rows.length ? (
          <Table layout="list">
            <TableHeader>
              <TableRow>
                <TableHead>
                  <Checkbox
                    aria-label="选择全部可见账号"
                    checked={allVisibleSelected}
                    disabled={!canManage || !visibleIds.length}
                    onCheckedChange={(checked) =>
                      setSelectedIds((current) =>
                        checked
                          ? Array.from(new Set([...current, ...visibleIds]))
                          : current.filter((id) => !visibleIds.includes(id)),
                      )
                    }
                  />
                </TableHead>
                <TableHead adaptive>账号</TableHead>
                <TableHead className="text-center">号码国家</TableHead>
                <TableHead className="text-center">访问国家</TableHead>
                <TableHead className="text-center">头像</TableHead>
                <TableHead className="text-center">类型</TableHead>
                <TableHead className="text-center">系统</TableHead>
                <TableHead className="text-center">来源</TableHead>
                <TableHead className="text-center">好友数</TableHead>
                <TableHead className="text-center">群组数</TableHead>
                <TableHead className="text-center">评分</TableHead>
                <TableHead>分组</TableHead>
                <TableHead>代理</TableHead>
                <TableHead className="text-center">发送数据</TableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.readKey}>
                  <TableCell>
                    <Checkbox
                      aria-label={`选择账号 ${row.phone || row.name || "待迁移账号"}`}
                      checked={Boolean(row.id) && selectedIds.includes(row.id)}
                      disabled={!canManage || !row.id}
                      onCheckedChange={(checked) =>
                        row.id &&
                        setSelectedIds((current) =>
                          checked
                            ? [...new Set([...current, row.id])]
                            : current.filter((id) => id !== row.id),
                        )
                      }
                    />
                  </TableCell>
                  <TableCell primary>
                    <div className="flex min-w-[190px] items-center gap-3">
                      <AccountStatusIndicator
                        status={row.status}
                        connected={row.connected}
                        validationStatus={row.validationStatus}
                        metadataSyncStatus={row.metadataSyncStatus}
                        lastError={row.lastError}
                      />
                      <div className="cell-main min-w-0 max-w-[150px]">
                        <strong title={row.name || undefined}>
                          {row.phone || row.name || "账号待迁移"}
                        </strong>
                        {row.id ? (
                          <span title={row.id}>{row.id}</span>
                        ) : (
                          <span>等待 ID 迁移</span>
                        )}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    {row.countryCode ? (
                      <CountryDisplay code={row.countryCode} />
                    ) : (
                      "-"
                    )}
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    {row.visitorCountryCode ? (
                      <CountryDisplay code={row.visitorCountryCode} />
                    ) : (
                      "-"
                    )}
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    <div className="flex justify-center">
                      <AccountAvatar account={row} />
                    </div>
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    <strong className="min-w-[72px]">
                      {accountTypeLabel(row.accountType)}
                    </strong>
                  </TableCell>
                  <TableCell
                    className="text-center align-middle"
                    title={row.waPlatformRaw || undefined}
                  >
                    <DeviceOsDisplay value={row.deviceOs} />
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    <div className="cell-main mx-auto min-w-[120px] items-center text-center">
                      {sourceBadge(row)}
                      {row.importFormat || row.sourceRefType ? (
                        <span
                          className="max-w-32 truncate"
                          title={[row.sourceRefType, row.importFormat]
                            .filter(Boolean)
                            .join(" · ")}
                        >
                          {row.importFormat || row.sourceRefType}
                        </span>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    <strong className="tabular-nums">
                      {row.friendCount == null ? "-" : row.friendCount}
                    </strong>
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    <strong className="tabular-nums">
                      {row.groupCount == null ? "-" : row.groupCount}
                    </strong>
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    <strong className="tabular-nums">
                      {row.qualityScore == null ? "待同步" : `${row.qualityScore} 分`}
                    </strong>
                  </TableCell>
                  <TableCell>
                    <strong className="min-w-[140px]">
                      {row.groupName || "未分组"}
                    </strong>
                  </TableCell>
                  <TableCell>
                    <strong className="min-w-[180px]">
                      {row.proxyId
                        ? proxyEndpointById.get(row.proxyId) || "已绑定固定代理"
                        : "系统自动分配"}
                    </strong>
                  </TableCell>
                  <TableCell className="text-center align-middle">
                    <div className="cell-main mx-auto min-w-[160px] items-center text-center">
                      <div className="tick-stats">
                        <span><CheckCheckIcon size={14} />单勾 {row.accepted == null ? "-" : row.accepted}</span>
                        <span><CheckCheckIcon size={14} />双勾 {row.delivered == null ? "-" : row.delivered}</span>
                      </div>
                      {row.lastError ? (
                        <span
                          className="flex items-center gap-1 truncate text-destructive"
                          title={row.lastError}
                        >
                          <AlertTriangleIcon size={13} />
                          {row.lastError}
                        </span>
                      ) : null}
                      <span>最近连接 {formatDateTime(row.lastConnectedAt)}</span>
                    </div>
                  </TableCell>
                  <TableCell className="sticky right-0 bg-background">
                    <div className="flex min-w-max items-center justify-end gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!row.id}
                        onClick={() => setDetailAccount(row)}
                      >
                        <EyeIcon size={16} />
                        详情
                      </Button>
                      {canManage ? <>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={
                          !row.id ||
                          row.validationStatus !== "ready" ||
                          ["pairing", "reauth_required", "restricted"].includes(row.status) ||
                          Boolean(operation)
                        }
                        onClick={() => void action(row, "sync")}
                      >
                        {operation === `${row.id}:sync` ? <LoaderCircleIcon className="spin" size={16} /> : null}
                        同步资料
                      </Button>
                      {row.connected ? (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={!row.id || Boolean(operation)}
                          onClick={() => void action(row, "disconnect")}
                        >
                          断开
                        </Button>
                      ) : (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={!row.id || Boolean(operation)}
                          onClick={() => void action(row, "connect")}
                        >
                          连接
                        </Button>
                      )}
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!row.id || !row.connected}
                        onClick={() => {
                          setTestAccount(row);
                          setTestTo("");
                          setTestResult("");
                        }}
                      >
                        发测试消息
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        disabled={!row.id || Boolean(operation)}
                        onClick={() => void action(row, "logout")}
                      >
                        {operation === `${row.id}:logout` ? <LoaderCircleIcon className="spin" size={16} /> : null}
                        登出解绑
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        disabled={!row.id || Boolean(operation)}
                        onClick={() => void deleteAccount(row)}
                      >
                        {operation === `${row.id}:delete` ? (
                          <LoaderCircleIcon className="spin" size={16} />
                        ) : (
                          <Trash2Icon size={16} />
                        )}
                        删除账号
                      </Button>
                      </> : null}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <EmptyState
            title="还没有账号"
            description="账号通过推广落地页链接或账号 JSON 导入后，会进入这里统一管理。"
          />
        )}
      </ListTableCard>
      <AccountResourceDetailDrawer
        accountId={detailAccount?.id || ""}
        accountLabel={detailAccount?.phone || detailAccount?.name || ""}
        onClose={() => setDetailAccount(null)}
      />

      <Drawer
        open={importOpen}
        onClose={closeImport}
        title="导入账号会话包"
        description="选择账号分组和协议节点后，会话包会按对应协议校验并进入统一账号池。"
        footer={
          <>
            <Button variant="outline" disabled={importPending} onClick={closeImport}>
              取消
            </Button>
            <Button
              disabled={
                importPending ||
                importValidating ||
                !importFile ||
                !importValidation?.valid ||
                !importGroupId ||
                !importProtocolId
              }
              onClick={() => void submitImport()}
            >
              {importPending ? <Spinner /> : <UploadCloudIcon size={16} />}
              校验并导入
            </Button>
          </>
        }
      >
        <div className="drawer-form">
          <label className="upload-zone min-h-56">
            <Input
              type="file"
              accept=".json,application/json"
              disabled={importPending}
              onChange={(event) =>
                void chooseImport(event.target.files?.[0] || null)
              }
            />
            {importValidating ? <Spinner /> : <UploadCloudIcon size={30} />}
            <strong>
              <DrawerFieldLabel required>
                {importFile?.name || "选择账号会话 JSON 文件"}
              </DrawerFieldLabel>
            </strong>
            <span>
              支持账号 JSON 与完整备份，最大 10 MB
            </span>
          </label>
          {importValidation ? (
            <div
              className={`rounded-lg border p-3 text-sm ${
                importValidation.valid
                  ? "border-emerald-600/20 bg-emerald-600/5 text-emerald-700 dark:text-emerald-400"
                  : "border-destructive/20 bg-destructive/5 text-destructive"
              }`}
            >
              {importValidation.message}
            </div>
          ) : null}
          <label className="field">
            <DrawerFieldLabel required>账号分组</DrawerFieldLabel>
            <SelectField
              className="w-full"
              value={importGroupId}
              onValueChange={setImportGroupId}
              options={importGroups.map((group) => ({
                value: group.id,
                label: group.name,
              }))}
              placeholder="选择导入账号所属分组"
              disabled={importPending}
            />
            <small className="field-help">
              {importGroups.length
                ? "导入成功后，账号会直接进入所选分组。"
                : "当前没有可用账号分组，请先在账号分组页面创建。"}
            </small>
          </label>
          <label className="field">
            <DrawerFieldLabel required>导入协议</DrawerFieldLabel>
            <SelectField
              className="w-full"
              value={importProtocolId}
              onValueChange={setImportProtocolId}
              options={importProtocols.map((protocol) => ({
                value: protocol.id,
                label: `${protocol.name} · ${protocol.type || "未知类型"}${
                  protocol.unavailableReason
                    ? ` · ${protocol.unavailableReason}`
                    : ""
                }`,
                disabled: !protocol.available,
              }))}
              placeholder="选择用于解析和接入的协议节点"
              disabled={importPending}
            />
            <small className="field-help">
              {importProtocols.some((protocol) => protocol.available)
                ? "文件会按所选协议类型校验；不可用或暂不支持导入的协议不能选择。"
                : "当前没有允许进号且支持会话导入的协议节点。"}
            </small>
          </label>
          {user?.isAdmin ? (
            <label className="field">
              <DrawerFieldLabel>固定 IP</DrawerFieldLabel>
              <SelectField
                value={importProxyId}
                onValueChange={setImportProxyId}
                options={proxies
                  .filter((proxy) => proxy.enabled && proxy.id)
                  .map((proxy) => ({
                    value: proxy.id,
                    label: `${proxy.endpoint}${proxy.countryCode ? ` · ${proxy.countryCode}` : ""}`,
                  }))}
                placeholder="按当前 IP 分配策略自动选择"
                clearable
                disabled={importPending}
              />
              <small className="field-help">
                只有“仅手动分配”模式必须选择，其他模式可留空。
              </small>
            </label>
          ) : null}
          <div className="rounded-lg border bg-muted/30 p-4 text-sm text-muted-foreground">
            <strong className="text-foreground">入池规则</strong>
            <p className="mt-2 leading-6">
              导入后会检查账号状态，验证成功后即可使用；资料尚未完成同步时显示“待同步”。
            </p>
          </div>
        </div>
      </Drawer>
      <Modal
        open={Boolean(testAccount)}
        onClose={() => !testPending && setTestAccount(null)}
        title="发送测试消息"
        description={`使用 ${testAccount?.phone || testAccount?.id || ""} 验证连接和送达状态。`}
        footer={
          <>
            <Button variant="outline" onClick={() => setTestAccount(null)}>
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
          <span>接收号码（含国家码）</span>
          <Input
            value={testTo}
            onChange={(event) =>
              setTestTo(event.target.value.replace(/\D/g, ""))
            }
            placeholder="例如：8613800000000"
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
    </StandardListPage>
  );
}
