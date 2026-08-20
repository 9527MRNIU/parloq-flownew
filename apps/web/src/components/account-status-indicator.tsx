import {
  CircleAlertIcon,
  CircleCheckIcon,
  Clock3Icon,
  PowerIcon,
} from "lucide-react";
import { Badge, type BadgeTone } from "./ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";

type AccountStatusIndicatorProps = {
  status: string;
  connected?: boolean;
  validationStatus?: string;
  metadataSyncStatus?: string;
  lastError?: string;
};
export type UnifiedAccountStatusKey =
  | "online"
  | "offline"
  | "processing"
  | "error"
  | "pending_validation"
  | "validating"
  | "validation_failed"
  | "pending_sync"
  | "syncing"
  | "sync_failed";

const validationLabel = (status?: string) => {
  if (status === "ready") return "验证通过";
  if (status === "validating") return "验证中";
  if (status === "failed") return "验证失败";
  return "待验证";
};

const metadataLabel = (status?: string) => {
  if (status === "ready" || status === "synced") return "资料已同步";
  if (status === "syncing") return "资料同步中";
  if (status === "failed") return "资料同步失败";
  if (status === "unsupported") return "资料同步不支持";
  return "资料待同步";
};

function statusMeta(status: string, connected?: boolean): {
  key: UnifiedAccountStatusKey;
  label: string;
  description: string;
  tone: BadgeTone;
  Icon: typeof CircleCheckIcon;
} {
  if (connected || ["online", "online_idle", "sending"].includes(status)) {
    return {
      key: "online",
      label: "在线",
      description: "连接正常，可参与已启用的营销任务。",
      tone: "success",
      Icon: CircleCheckIcon,
    };
  }
  if (["pairing", "connecting", "warming", "draining"].includes(status)) {
    return {
      key: "processing",
      label: "处理中",
      description: "账号正在配对、连接或切换运行状态。",
      tone: "warning",
      Icon: Clock3Icon,
    };
  }
  if (
    [
      "logged_out",
      "reauth_required",
      "revoked",
      "restricted",
      "disabled",
      "failed",
    ].includes(status)
  ) {
    return {
      key: "error",
      label: "异常",
      description: "账号需要重新配对、解除限制或人工检查。",
      tone: "danger",
      Icon: CircleAlertIcon,
    };
  }
  return {
    key: "offline",
    label: "离线",
    description: "账号已入池但当前未建立 WhatsApp 连接。",
    tone: "neutral",
    Icon: PowerIcon,
  };
}

function unifiedStatusMeta(
  status: string,
  connected: boolean | undefined,
  validationStatus: string | undefined,
  metadataSyncStatus: string | undefined,
) {
  const connection = statusMeta(status, connected);
  if (connection.tone === "danger") return connection;
  if (validationStatus === "failed") {
    return {
      key: "validation_failed" as const,
      label: "验证失败",
      description: "账号未通过验证，需要检查或重新导入。",
      tone: "danger" as const,
      Icon: CircleAlertIcon,
    };
  }
  if (metadataSyncStatus === "failed") {
    return {
      key: "sync_failed" as const,
      label: "同步失败",
      description: "账号已入池，但资料同步失败，需要重新同步。",
      tone: "danger" as const,
      Icon: CircleAlertIcon,
    };
  }
  if (connection.tone === "warning") return connection;
  if (validationStatus === "validating") {
    return {
      key: "validating" as const,
      label: "验证中",
      description: "系统正在验证账号，完成后即可使用。",
      tone: "warning" as const,
      Icon: Clock3Icon,
    };
  }
  if (!validationStatus || validationStatus === "pending") {
    return {
      key: "pending_validation" as const,
      label: "待验证",
      description: "账号尚未完成验证。",
      tone: "warning" as const,
      Icon: Clock3Icon,
    };
  }
  if (metadataSyncStatus === "syncing") {
    return {
      key: "syncing" as const,
      label: "同步中",
      description: "账号连接可用，系统正在同步头像、群组与联系人资料。",
      tone: "warning" as const,
      Icon: Clock3Icon,
    };
  }
  if (!metadataSyncStatus || metadataSyncStatus === "pending") {
    return {
      key: "pending_sync" as const,
      label: "待同步",
      description: "账号已通过验证，资料信息尚未同步完成。",
      tone: "warning" as const,
      Icon: Clock3Icon,
    };
  }
  return connection;
}

export function accountUnifiedStatusKey(
  input: AccountStatusIndicatorProps,
): UnifiedAccountStatusKey {
  return unifiedStatusMeta(
    input.status,
    input.connected,
    input.validationStatus,
    input.metadataSyncStatus,
  ).key;
}

export function AccountStatusIndicator({
  status,
  connected,
  validationStatus,
  metadataSyncStatus,
  lastError,
}: AccountStatusIndicatorProps) {
  const meta = unifiedStatusMeta(
    status,
    connected,
    validationStatus,
    metadataSyncStatus,
  );
  const Icon = meta.Icon;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="inline-flex cursor-help rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`账号状态：${meta.label}`}
        >
          <Badge tone={meta.tone} className="size-8 rounded-lg p-0">
            <Icon size={16} />
          </Badge>
        </button>
      </TooltipTrigger>
      <TooltipContent
        side="right"
        align="center"
        sideOffset={8}
        collisionPadding={12}
        className="grid w-80 max-w-[calc(100vw-24px)] items-start gap-1.5 p-3 text-xs shadow-lg"
      >
        <strong className="text-xs">账号状态：{meta.label}</strong>
        <span className="text-background/80">{meta.description}</span>
        <div className="mt-1 grid grid-cols-[64px_minmax(0,1fr)] gap-x-2 gap-y-1">
          <span className="text-background/65">连接</span>
          <span>{status || "未知"}</span>
          <span className="text-background/65">验证</span>
          <span>{validationLabel(validationStatus)}</span>
          <span className="text-background/65">资料</span>
          <span>{metadataLabel(metadataSyncStatus)}</span>
          {lastError ? (
            <>
              <span className="text-background/65">异常</span>
              <span className="break-words">{lastError}</span>
            </>
          ) : null}
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
