import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Badge, EmptyState } from "./ui";

export function RecordDetailSummaryGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{children}</div>;
}

export function RecordDetailSummaryCard({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </div>
  );
}

export function RecordDetailSection({
  title,
  icon: Icon,
  wide = false,
  children,
}: {
  title: string;
  icon?: LucideIcon;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <section className={`rounded-lg border p-4${wide ? " lg:col-span-2" : ""}`}>
      <div className="mb-3 flex items-center gap-2">
        {Icon ? <Icon className="size-4 text-muted-foreground" /> : null}
        <strong>{title}</strong>
      </div>
      {children}
    </section>
  );
}

export function RecordDetailField({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-all">{children || "-"}</dd>
    </>
  );
}

export function RecordDataSection({
  data,
  description,
  bytes,
  emptyTitle = "暂无附加数据",
  emptyDescription = "这条记录没有携带额外数据。",
}: {
  data: Record<string, unknown>;
  description: string;
  bytes?: number;
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  const serialized = JSON.stringify(data, null, 2);
  const byteCount =
    bytes ?? (serialized ? new TextEncoder().encode(serialized).length : 0);
  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <strong>记录数据</strong>
          <p className="mt-1 text-xs text-muted-foreground">{description}</p>
        </div>
        <Badge tone="neutral">{byteCount.toLocaleString()} 字节</Badge>
      </div>
      {Object.keys(data).length ? (
        <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted p-4 text-xs">
          {serialized}
        </pre>
      ) : (
        <EmptyState title={emptyTitle} description={emptyDescription} />
      )}
    </section>
  );
}
