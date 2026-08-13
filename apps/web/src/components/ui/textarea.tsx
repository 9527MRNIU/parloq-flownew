import * as React from "react";
import { cn } from "../../lib/utils";

export function Textarea({
  className,
  ...props
}: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex min-h-16 max-h-64 w-full resize-none overflow-y-auto rounded-lg border border-input bg-transparent px-2.5 py-2 text-base transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-input focus-visible:ring-3 focus-visible:ring-primary/20 disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 md:text-sm dark:bg-input/30 dark:focus-visible:ring-primary/25 dark:disabled:bg-input/80",
        className,
      )}
      {...props}
    />
  );
}
