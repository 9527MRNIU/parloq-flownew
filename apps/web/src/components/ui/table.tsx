import * as React from "react";
import { cn } from "../../lib/utils";

type TableProps = React.ComponentProps<"table"> & {
  layout?: "default" | "list";
};

export function Table({
  className,
  layout = "default",
  style,
  ...props
}: TableProps) {
  return (
    <div
      data-slot="table-container"
      className="relative w-full overflow-x-auto"
    >
      <table
        data-slot="table"
        data-table-layout={layout === "list" ? "list" : undefined}
        className={cn(
          "w-full caption-bottom text-sm",
          layout === "list" && "standard-list-table table-auto",
          className,
        )}
        style={style}
        {...props}
      />
    </div>
  );
}
export function TableHeader({
  className,
  ...props
}: React.ComponentProps<"thead">) {
  return (
    <thead
      data-slot="table-header"
      className={cn("[&_tr]:border-b", className)}
      {...props}
    />
  );
}
export function TableBody({
  className,
  ...props
}: React.ComponentProps<"tbody">) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  );
}
export function TableFooter({
  className,
  ...props
}: React.ComponentProps<"tfoot">) {
  return (
    <tfoot
      data-slot="table-footer"
      className={cn(
        "border-t bg-muted/50 font-medium [&>tr]:last:border-b-0",
        className,
      )}
      {...props}
    />
  );
}
export function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        "border-b transition-colors hover:bg-muted/50 has-aria-expanded:bg-muted/50 data-[state=selected]:bg-muted",
        className,
      )}
      {...props}
    />
  );
}
type TableHeadProps = React.ComponentProps<"th"> & {
  adaptive?: boolean;
};

export function TableHead({
  className,
  children,
  adaptive = false,
  style,
  ...props
}: TableHeadProps) {
  const isActionColumn =
    typeof children === "string" && children.trim() === "操作";

  return (
    <th
      data-slot="table-head"
      data-table-action-column={isActionColumn ? "" : undefined}
      data-table-adaptive-column={adaptive ? "" : undefined}
      scope="col"
      className={cn(
        "h-10 px-2 text-left align-middle font-medium whitespace-nowrap text-foreground [&:has([role=checkbox])]:pr-0",
        className,
      )}
      style={style}
      {...props}
    >
      {children}
    </th>
  );
}
type TableCellProps = React.ComponentProps<"td"> & {
  primary?: boolean;
};

export function TableCell({
  className,
  primary = false,
  ...props
}: TableCellProps) {
  return (
    <td
      data-slot="table-cell"
      data-table-primary-cell={primary ? "" : undefined}
      className={cn(
        "p-2 align-middle whitespace-nowrap [&:has([role=checkbox])]:pr-0",
        className,
      )}
      {...props}
    />
  );
}
export function TableCaption({
  className,
  ...props
}: React.ComponentProps<"caption">) {
  return (
    <caption
      data-slot="table-caption"
      className={cn("mt-4 text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}
