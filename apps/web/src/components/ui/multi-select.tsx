import { ChevronDownIcon, XIcon } from "lucide-react";
import { useId } from "react";
import type { SelectOption } from "./select";
import { cn } from "../../lib/utils";
import { Button } from "./button";
import { Checkbox } from "./checkbox";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";

export function MultiSelect({
  value,
  onValueChange,
  options,
  placeholder = "请选择",
  className,
  disabled,
}: {
  value: string[];
  onValueChange: (value: string[]) => void;
  options: SelectOption[];
  placeholder?: string;
  className?: string;
  disabled?: boolean;
}) {
  const id = useId();
  const toggle = (item: string) =>
    onValueChange(
      value.includes(item)
        ? value.filter((current) => current !== item)
        : [...value, item],
    );
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          data-slot="multi-select-trigger"
          className={cn(
            "h-8 w-full justify-between px-2.5 font-normal",
            className,
          )}
          disabled={disabled}
        >
          <span>
            {value.length ? `已选择 ${value.length} 项` : placeholder}
          </span>
          <ChevronDownIcon size={15} />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-(--radix-popover-trigger-width)"
      >
        {value.length ? (
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start"
            onClick={() => onValueChange([])}
          >
            <XIcon size={13} />
            清空选择
          </Button>
        ) : null}
        {options.map((option) => {
          const optionId = `${id}-${option.value}`;
          const checked = value.includes(option.value);
          return (
            <div
              className={cn(
                "flex min-h-8 items-center gap-2 rounded-md px-2 py-1.5 hover:bg-accent",
                option.disabled && "pointer-events-none opacity-50",
              )}
              key={option.value}
            >
              <Checkbox
                id={optionId}
                checked={checked}
                disabled={option.disabled}
                onCheckedChange={() => toggle(option.value)}
              />
              <label
                className="min-w-0 flex-1 cursor-pointer"
                htmlFor={optionId}
              >
                {option.label}
              </label>
            </div>
          );
        })}
      </PopoverContent>
    </Popover>
  );
}
