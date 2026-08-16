import { useEffect, useMemo, useState } from "react";
import {
  AlertCircleIcon,
  CpuIcon,
  HardDriveIcon,
  MemoryStickIcon,
  type LucideIcon,
} from "lucide-react";
import { apiRequest } from "../api/client";
import { cn } from "../lib/utils";
import { Button, Tooltip, TooltipContent, TooltipTrigger } from "./ui";

type ResourceMetric = {
  percent: number | null;
  usedBytes?: number | null;
  totalBytes?: number | null;
  freeBytes?: number | null;
  cores?: number | null;
  path?: string | null;
  source: string;
};

type SystemMetrics = {
  cpu: ResourceMetric;
  memory: ResourceMetric;
  disk: ResourceMetric;
  updatedAt: string;
  refreshIntervalSeconds: number;
};

type MetricsState = {
  metrics: SystemMetrics | null;
  error: string | null;
};

function percentText(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${Math.round(value)}%`
    : "--";
}

function progressValue(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(value, 100));
}

function progressColor(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "bg-muted-foreground/30";
  }
  if (value >= 80) return "bg-destructive";
  if (value >= 65) return "bg-[var(--warning)]";
  return "bg-primary";
}

function formatBytes(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let next = value;
  let index = 0;
  while (next >= 1024 && index < units.length - 1) {
    next /= 1024;
    index += 1;
  }
  return `${next.toFixed(next >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function sourceText(source: string | undefined) {
  if (source === "host-procfs" || source === "host-statvfs") return "生产宿主机";
  if (source === "cgroup") return "当前服务容器";
  if (source === "procfs" || source === "statvfs") return "当前运行环境";
  return "暂不可用";
}

function ProgressBar({ value }: { value: number | null | undefined }) {
  return (
    <span className="block h-1 overflow-hidden rounded-full bg-muted">
      <span
        className={cn("block h-full rounded-full transition-[width]", progressColor(value))}
        style={{ width: `${progressValue(value)}%` }}
      />
    </span>
  );
}

function MiniMetric({
  className,
  icon: Icon,
  label,
  metric,
}: {
  className?: string;
  icon: LucideIcon;
  label: string;
  metric: ResourceMetric | undefined;
}) {
  return (
    <span className={cn("items-center gap-1.5", className)}>
      <Icon className="size-[18px]" />
      <span className="flex w-14 flex-col gap-1">
        <span className="flex items-center justify-between gap-1 text-[11px] leading-none">
          <span>{label}</span>
          <span className="tabular-nums">{percentText(metric?.percent)}</span>
        </span>
        <ProgressBar value={metric?.percent} />
      </span>
    </span>
  );
}

function TooltipMetric({
  icon: Icon,
  label,
  metric,
  detail,
}: {
  icon: LucideIcon;
  label: string;
  metric: ResourceMetric;
  detail: string;
}) {
  return (
    <div className="grid gap-1.5">
      <div className="flex items-center justify-between gap-6">
        <span className="inline-flex items-center gap-1.5">
          <Icon className="size-3.5" />
          {label}
        </span>
        <span className="tabular-nums">{percentText(metric.percent)}</span>
      </div>
      <ProgressBar value={metric.percent} />
      <div className="flex items-center justify-between gap-4 text-[11px] opacity-75">
        <span>{detail}</span>
        <span>{sourceText(metric.source)}</span>
      </div>
    </div>
  );
}

export function SystemMetricsIndicator() {
  const [{ metrics, error }, setState] = useState<MetricsState>({
    metrics: null,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    let timeoutId: number | undefined;

    async function load() {
      let refreshMs = 3000;
      try {
        const response = await apiRequest<{ data: SystemMetrics }>("/api/system/metrics");
        refreshMs = Math.max(1000, response.data.refreshIntervalSeconds * 1000);
        if (!cancelled) setState({ metrics: response.data, error: null });
      } catch (nextError) {
        if (!cancelled) {
          setState((current) => ({
            metrics: current.metrics,
            error: nextError instanceof Error ? nextError.message : "系统资源读取失败",
          }));
        }
      } finally {
        if (!cancelled) timeoutId = window.setTimeout(load, refreshMs);
      }
    }

    void load();
    return () => {
      cancelled = true;
      if (timeoutId) window.clearTimeout(timeoutId);
    };
  }, []);

  const ariaLabel = useMemo(
    () =>
      error && !metrics
        ? `系统资源读取失败：${error}`
        : `系统资源：CPU ${percentText(metrics?.cpu.percent)}，内存 ${percentText(metrics?.memory.percent)}，磁盘 ${percentText(metrics?.disk.percent)}`,
    [error, metrics],
  );
  const updatedAt = metrics?.updatedAt
    ? new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).format(new Date(metrics.updatedAt))
    : "--";

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          className="h-9 min-w-9 gap-2 px-2 font-normal"
          aria-label={ariaLabel}
        >
          {error ? <AlertCircleIcon className="size-4 text-destructive" /> : null}
          <span className="flex items-center gap-1.5 sm:hidden">
            <CpuIcon className="size-[18px]" />
            <span className="w-7 text-left text-xs tabular-nums">
              {percentText(metrics?.cpu.percent)}
            </span>
          </span>
          <MiniMetric
            className="hidden sm:flex"
            icon={CpuIcon}
            label="CPU"
            metric={metrics?.cpu}
          />
          <MiniMetric
            className="hidden md:flex"
            icon={MemoryStickIcon}
            label="内存"
            metric={metrics?.memory}
          />
          <MiniMetric
            className="hidden lg:flex"
            icon={HardDriveIcon}
            label="磁盘"
            metric={metrics?.disk}
          />
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom" align="end" sideOffset={6} className="max-w-80">
        <div className="grid min-w-64 gap-2.5 py-0.5">
          {error ? <div className="text-[11px]">读取失败：{error}</div> : null}
          {metrics ? (
            <>
              <TooltipMetric
                icon={CpuIcon}
                label="CPU"
                metric={metrics.cpu}
                detail={
                  typeof metrics.cpu.cores === "number"
                    ? `${metrics.cpu.cores} 核`
                    : "核心数未知"
                }
              />
              <TooltipMetric
                icon={MemoryStickIcon}
                label="内存"
                metric={metrics.memory}
                detail={`${formatBytes(metrics.memory.usedBytes)} / ${formatBytes(metrics.memory.totalBytes)}`}
              />
              <TooltipMetric
                icon={HardDriveIcon}
                label="磁盘"
                metric={metrics.disk}
                detail={`${formatBytes(metrics.disk.usedBytes)} / ${formatBytes(metrics.disk.totalBytes)}`}
              />
              <div className="border-t border-background/20 pt-1 text-[11px] opacity-75">
                每 3 秒刷新 · 更新时间 {updatedAt}
              </div>
            </>
          ) : (
            <div className="text-[11px] opacity-75">正在读取系统资源</div>
          )}
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
