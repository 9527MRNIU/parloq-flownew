import { InfoIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "./ui/tooltip";

function DrawerHelpTip({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="inline-flex size-5 shrink-0 items-center justify-center rounded-full text-muted-foreground/70 transition-colors hover:bg-muted hover:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
          aria-label={`${label}说明`}
        >
          <InfoIcon className="size-4" />
        </button>
      </TooltipTrigger>
      <TooltipContent
        side="top"
        align="start"
        sideOffset={6}
        className="max-w-72 whitespace-normal text-left leading-5"
      >
        {children}
      </TooltipContent>
    </Tooltip>
  );
}

export function DrawerRequiredMark() {
  return (
    <>
      <span aria-hidden="true" className="ml-1 text-destructive">
        *
      </span>
      <span className="sr-only">（必填）</span>
    </>
  );
}

export function DrawerFieldLabel({
  children,
  required = false,
}: {
  children: ReactNode;
  required?: boolean;
}) {
  return (
    <span>
      {children}
      {required ? <DrawerRequiredMark /> : null}
    </span>
  );
}

export function DrawerFormLayout({
  children,
  aside,
  className,
}: {
  children: ReactNode;
  aside?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid min-w-0 gap-[var(--drawer-form-layout-gap)]",
        aside
          ? "lg:grid-cols-[minmax(0,1fr)_var(--drawer-form-preview-width)]"
          : "grid-cols-1",
        className,
      )}
    >
      <div className="min-w-0 space-y-[var(--drawer-form-section-gap)]">
        {children}
      </div>
      {aside ? (
        <aside className="min-w-0 lg:sticky lg:top-0 lg:self-start">
          {aside}
        </aside>
      ) : null}
    </div>
  );
}

export function DrawerFormSection({
  title,
  description,
  action,
  children,
  hideHeader = false,
  className,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  hideHeader?: boolean;
  className?: string;
}) {
  return (
    <section className={cn("min-w-0", className)}>
      {!hideHeader ? (
        <header className="flex min-h-8 min-w-0 items-center gap-2.5">
          <div className="flex shrink-0 items-center gap-1">
            <h3 className="drawer-form-section-title">{title}</h3>
            {description ? (
              <DrawerHelpTip label={title}>{description}</DrawerHelpTip>
            ) : null}
          </div>
          <div className="h-px min-w-4 flex-1 bg-border" aria-hidden="true" />
          {action ? <div className="shrink-0">{action}</div> : null}
        </header>
      ) : null}
      <div
        className={cn(
          "grid min-w-0 gap-[var(--drawer-form-field-gap)]",
          !hideHeader && "mt-4",
        )}
      >
        {children}
      </div>
    </section>
  );
}

export function DrawerFormField({
  label,
  htmlFor,
  children,
  hint,
  meta,
  required = false,
  align = "center",
  className,
}: {
  label: ReactNode;
  htmlFor?: string;
  children: ReactNode;
  hint?: ReactNode;
  meta?: ReactNode;
  required?: boolean;
  align?: "center" | "start";
  className?: string;
}) {
  const labelClassName = cn(
    "text-sm font-medium leading-5 text-foreground",
  );
  const labelNode = (
    <div
      className={cn(
        "drawer-form-field-label flex min-w-0 gap-1 md:self-start",
        align === "start"
          ? "items-start md:min-h-8 md:pt-1.5"
          : "items-center md:h-8",
      )}
    >
      {hint ? (
        <DrawerHelpTip label={String(label)}>{hint}</DrawerHelpTip>
      ) : null}
      {htmlFor ? (
        <label htmlFor={htmlFor} className={labelClassName}>
          {label}
          {required ? <DrawerRequiredMark /> : null}
        </label>
      ) : (
        <div className={labelClassName}>
          {label}
          {required ? <DrawerRequiredMark /> : null}
        </div>
      )}
    </div>
  );

  return (
    <div
      className={cn(
        "drawer-form-field grid min-w-0 gap-2 md:grid-cols-[var(--drawer-form-label-width)_minmax(0,1fr)] md:gap-x-[var(--drawer-form-label-gap)]",
        className,
      )}
    >
      {labelNode}
      <div className="min-w-0">
        {children}
        {meta ? (
          <div className="mt-1.5 flex min-h-4 items-start justify-between gap-3 text-xs leading-4 text-muted-foreground">
            <span className="min-w-0 flex-1" />
            <span className="shrink-0 tabular-nums">{meta}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function DrawerChoiceGroup({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: Array<{ value: string; label: string; disabled?: boolean }>;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div
      className="grid min-w-0 grid-cols-2 gap-2 sm:auto-cols-fr sm:grid-flow-col"
      role="radiogroup"
      aria-label={label}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={option.disabled}
            className={cn(
              "flex h-8 min-w-0 items-center justify-center gap-2 rounded-lg border px-3 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
              selected
                ? "border-primary bg-primary/5 text-primary ring-1 ring-primary/15"
                : "border-input bg-background text-foreground hover:bg-muted/60",
            )}
            onClick={() => onChange(option.value)}
          >
            <span
              aria-hidden="true"
              className={cn(
                "flex size-4 shrink-0 items-center justify-center rounded-full border",
                selected
                  ? "border-primary bg-primary"
                  : "border-input bg-background",
              )}
            >
              {selected ? (
                <span className="size-1.5 rounded-full bg-primary-foreground" />
              ) : null}
            </span>
            <span className="truncate">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
