import * as React from "react";
import * as RechartsPrimitive from "recharts";
import { cn } from "../../lib/utils";

const themes = { light: "", dark: ".dark" } as const;

export type ChartConfig = Record<
  string,
  {
    label?: React.ReactNode;
  } & (
    | { color?: string; theme?: never }
    | { color?: never; theme: Record<keyof typeof themes, string> }
  )
>;

const ChartContext = React.createContext<ChartConfig>({});

export function ChartContainer({
  id,
  className,
  children,
  config,
  ...props
}: React.ComponentProps<"div"> & {
  config: ChartConfig;
  children: React.ComponentProps<typeof RechartsPrimitive.ResponsiveContainer>["children"];
}) {
  const uniqueId = React.useId();
  const chartId = `chart-${id ?? uniqueId.replace(/:/g, "")}`;
  const colors = Object.entries(config).filter(([, value]) => value.color || value.theme);
  const css = Object.entries(themes)
    .map(
      ([theme, prefix]) => `${prefix} [data-chart=${chartId}] {\n${colors
        .map(([key, value]) => {
          const color = value.theme?.[theme as keyof typeof themes] ?? value.color;
          return color ? `  --color-${key}: ${color};` : "";
        })
        .join("\n")}\n}`,
    )
    .join("\n");

  return (
    <ChartContext.Provider value={config}>
      <div
        data-slot="chart"
        data-chart={chartId}
        className={cn("chart-container select-none", className)}
        {...props}
      >
        {css ? <style dangerouslySetInnerHTML={{ __html: css }} /> : null}
        <RechartsPrimitive.ResponsiveContainer width="100%" height="100%">
          {children}
        </RechartsPrimitive.ResponsiveContainer>
      </div>
    </ChartContext.Provider>
  );
}

export const ChartTooltip = RechartsPrimitive.Tooltip;

export function ChartTooltipContent({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: ReadonlyArray<{
    dataKey?: string | number;
    name?: string | number;
    color?: string;
    value?: string | number | ReadonlyArray<string | number>;
  }>;
  label?: React.ReactNode;
}) {
  const config = React.useContext(ChartContext);
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      {label != null ? <strong>{String(label)}</strong> : null}
      {payload.map((item) => {
        const key = String(item.dataKey ?? item.name ?? "value");
        return (
          <div key={key}>
            <span>
              <i style={{ background: item.color }} />
              {config[key]?.label ?? item.name ?? key}
            </span>
            <b>{typeof item.value === "number" ? item.value.toLocaleString() : String(item.value ?? "-")}</b>
          </div>
        );
      })}
    </div>
  );
}
