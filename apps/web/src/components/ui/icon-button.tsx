import * as React from "react";
import { Button } from "./button";
import { Tooltip, TooltipContent, TooltipTrigger } from "./tooltip";

export function IconButton({
  label,
  className,
  ...props
}: Omit<React.ComponentProps<typeof Button>, "children"> & {
  label: string;
  children: React.ReactNode;
}) {
  const { children, ...buttonProps } = props;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          aria-label={label}
          variant="ghost"
          size="icon-sm"
          className={className}
          {...buttonProps}
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}
