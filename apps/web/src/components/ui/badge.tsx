import * as React from "react";
import { cva } from "class-variance-authority";
import { cn } from "../../lib/utils";

export type BadgeTone =
  "neutral" | "success" | "warning" | "danger" | "primary";
const badgeVariants = cva(
  "group/badge inline-flex h-5 w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-4xl border border-transparent px-2 py-0.5 text-xs font-medium whitespace-nowrap transition-all focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 [&>svg]:pointer-events-none [&>svg]:size-3!",
  {
    variants: {
      tone: {
        neutral: "bg-secondary text-secondary-foreground",
        success:
          "border-emerald-600/20 bg-emerald-600/10 text-emerald-700 dark:text-emerald-400",
        warning:
          "border-amber-600/20 bg-amber-600/10 text-amber-700 dark:text-amber-400",
        danger: "bg-destructive/10 text-destructive",
        primary: "bg-primary text-primary-foreground",
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
