import {
  CircleAlertIcon,
  CircleCheckIcon,
  CircleHelpIcon,
  Clock3Icon,
  InfoIcon,
  PowerIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../lib/utils";
import { Badge, type BadgeTone } from "./ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";

export type EntityStatusMeta = {
  label: string;
  description: string;
  tone?: BadgeTone;
  details?: Array<{ label: string; value: ReactNode }>;
};

const toneIcons = {
  success: CircleCheckIcon,
  warning: Clock3Icon,
  danger: CircleAlertIcon,
  info: InfoIcon,
  primary: CircleHelpIcon,
  neutral: PowerIcon,
} satisfies Record<BadgeTone, typeof CircleCheckIcon>;

export function EntityStatusIndicator({ status }: { status: EntityStatusMeta }) {
  const tone = status.tone || "neutral";
  const Icon = toneIcons[tone];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="inline-flex shrink-0 cursor-help rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`状态：${status.label}`}
        >
          <Badge tone={tone} className="size-8 rounded-lg p-0">
            <Icon size={16} />
          </Badge>
        </button>
      </TooltipTrigger>
      <TooltipContent
        side="right"
        align="center"
        sideOffset={8}
        collisionPadding={12}
        className="grid w-72 max-w-[calc(100vw-24px)] items-start gap-1.5 p-3 text-xs shadow-lg"
      >
        <strong className="text-xs">状态：{status.label}</strong>
        <span className="text-background/80">{status.description}</span>
        {status.details?.length ? (
          <div className="mt-1 grid grid-cols-[64px_minmax(0,1fr)] gap-x-2 gap-y-1">
            {status.details.map((detail) => (
              <div className="contents" key={detail.label}>
                <span className="text-background/65">{detail.label}</span>
                <span className="break-words">{detail.value || "-"}</span>
              </div>
            ))}
          </div>
        ) : null}
      </TooltipContent>
    </Tooltip>
  );
}

export function EntityPrimaryCell({
  title,
  id,
  status,
  description,
  idFallback = "等待 ID 迁移",
  className,
}: {
  title: ReactNode;
  id?: string;
  status: EntityStatusMeta;
  description?: ReactNode;
  idFallback?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-[210px] items-start gap-3", className)}>
      <EntityStatusIndicator status={status} />
      <div className="cell-main min-w-0 max-w-[220px]">
        <strong>{title || "未命名"}</strong>
        <span title={id || undefined}>{id || idFallback}</span>
        {description ? <span>{description}</span> : null}
      </div>
    </div>
  );
}
