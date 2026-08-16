import * as React from "react";
import { cva } from "class-variance-authority";
import { cn } from "../../lib/utils";

export type BadgeTone =
  "neutral" | "success" | "warning" | "danger" | "info" | "primary";
const badgeVariants = cva(
  "group/badge inline-flex h-5 w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-4xl border border-transparent px-2 py-0.5 text-xs font-medium whitespace-nowrap transition-all focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 [&>svg]:pointer-events-none [&>svg]:size-3!",
  {
    variants: {
      tone: {
        neutral: "badge-neutral text-muted-foreground",
        success: "badge-success",
        warning: "badge-warning",
        danger: "badge-danger",
        info: "badge-info",
        primary: "badge-primary",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);
export function Badge({
  className,
  tone = "neutral",
  ...props
}: React.ComponentProps<"span"> & { tone?: BadgeTone }) {
  return (
    <span
      data-slot="badge"
      data-variant={tone}
      className={cn(badgeVariants({ tone }), className)}
      {...props}
    />
  );
}
export { badgeVariants };
