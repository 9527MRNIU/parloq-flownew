import { CheckIcon, ChevronsUpDownIcon, SearchIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { cn } from "../../lib/utils";
import { Button } from "./button";
import { Input } from "./input";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";

export type SearchableSelectOption = {
  value: string;
  label: string;
  keywords?: string;
  disabled?: boolean;
};

export function SearchableSelect({
  value,
  onValueChange,
  options,
  placeholder = "请选择",
  searchPlaceholder = "搜索名称或代码",
  emptyText = "没有匹配项",
  className,
  disabled,
  ariaLabel,
}: {
  value?: string;
  onValueChange: (value: string) => void;
  options: SearchableSelectOption[];
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  className?: string;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const selected = options.find((option) => option.value === value);
  const visible = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    if (!needle) return options;
    return options.filter((option) =>
      `${option.label} ${option.value} ${option.keywords || ""}`
        .toLocaleLowerCase()
        .includes(needle),
    );
  }, [options, search]);

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setSearch("");
      }}
    >
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-label={ariaLabel}
          aria-expanded={open}
          disabled={disabled}
          className={cn("w-full justify-between px-2.5 font-normal", className)}
        >
          <span className={cn("truncate", !selected && "text-muted-foreground")}>
            {selected?.label || placeholder}
          </span>
          <ChevronsUpDownIcon className="text-muted-foreground" size={15} />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-(--radix-popover-trigger-width) p-1"
      >
        <div className="relative mb-1">
          <SearchIcon
            className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground"
            size={15}
          />
          <Input
            autoFocus
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
            className="pl-8"
          />
        </div>
        <div className="max-h-72 overflow-y-auto" role="listbox">
          {visible.length ? (
            visible.map((option) => (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={option.value === value}
                disabled={option.disabled}
                className="flex min-h-9 w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm outline-none hover:bg-accent focus-visible:bg-accent disabled:pointer-events-none disabled:opacity-50"
                onClick={() => {
                  onValueChange(option.value);
                  setOpen(false);
                  setSearch("");
                }}
              >
                <CheckIcon
                  size={15}
                  className={cn(
                    "shrink-0",
                    option.value === value ? "opacity-100" : "opacity-0",
                  )}
                />
                <span>{option.label}</span>
              </button>
            ))
          ) : (
            <div className="px-3 py-6 text-center text-sm text-muted-foreground">
              {emptyText}
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
