import { useMemo, useState } from "react";
import { format } from "date-fns";
import { CalendarIcon, ChevronDownIcon } from "lucide-react";
import { zhCN } from "react-day-picker/locale";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";
import { Calendar } from "./ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "./ui/popover";
import { Separator } from "./ui/separator";

function inputDateToLocalDate(value: string): Date | undefined {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return undefined;

  const year = Number.parseInt(match[1] ?? "", 10);
  const month = Number.parseInt(match[2] ?? "", 10);
  const day = Number.parseInt(match[3] ?? "", 10);
  const date = new Date(year, month - 1, day);
  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return undefined;
  }
  return date;
}

function localDateToInputDate(date: Date): string {
  const year = `${date.getFullYear()}`.padStart(4, "0");
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function DatePickerField({
  id,
  value,
  onValueChange,
  placeholder = "选择日期",
  className,
  ariaLabel,
}: {
  id?: string;
  value: string;
  onValueChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const selectedDate = useMemo(() => inputDateToLocalDate(value), [value]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          variant="outline"
          data-empty={!selectedDate}
          aria-label={ariaLabel ?? placeholder}
          className={cn(
            "w-full justify-between border-border/70 bg-background/60 font-normal data-[empty=true]:text-muted-foreground",
            className,
          )}
        >
          <CalendarIcon data-icon="inline-start" />
          <span className="mr-auto tabular-nums">
            {selectedDate ? format(selectedDate, "yyyy/MM/dd") : placeholder}
          </span>
          <ChevronDownIcon data-icon="inline-end" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-auto overflow-hidden p-0">
        <Calendar
          mode="single"
          locale={zhCN}
          selected={selectedDate}
          captionLayout="dropdown"
          defaultMonth={selectedDate}
          onSelect={(date) => {
            if (date) onValueChange(localDateToInputDate(date));
            setOpen(false);
          }}
        />
        {value ? (
          <>
            <Separator />
            <div className="p-2">
              <Button
                variant="ghost"
                className="w-full justify-center"
                onClick={() => {
                  onValueChange("");
                  setOpen(false);
                }}
              >
                清空
              </Button>
            </div>
          </>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
