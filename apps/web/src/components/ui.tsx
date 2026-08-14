import type { ReactNode } from "react";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { EmptyState, Spinner } from "./ui/empty";
import { Input } from "./ui/input";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "./ui/sheet";

export function Modal({
  open,
  title,
  description,
  children,
  footer,
  onClose,
}: {
  open: boolean;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description ? (
            <DialogDescription>{description}</DialogDescription>
          ) : null}
        </DialogHeader>
        <DialogBody>{children}</DialogBody>
        {footer ? <DialogFooter>{footer}</DialogFooter> : null}
      </DialogContent>
    </Dialog>
  );
}

export function Drawer({
  open,
  title,
  description,
  children,
  footer,
  wide = false,
  onClose,
}: {
  open: boolean;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
  onClose: () => void;
}) {
  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <SheetContent
        className={
          wide
            ? "gap-0 data-[side=right]:sm:max-w-[1080px]"
            : "gap-0 data-[side=right]:sm:max-w-[870px]"
        }
      >
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          {description ? (
            <SheetDescription>{description}</SheetDescription>
          ) : null}
        </SheetHeader>
        <SheetBody>{children}</SheetBody>
        {footer ? <SheetFooter>{footer}</SheetFooter> : null}
      </SheetContent>
    </Sheet>
  );
}

export { Badge, Button, EmptyState, Input, Spinner };
export { DatePickerField } from "./date-picker-field";
export * from "./ui/checkbox";
export * from "./ui/confirm-dialog";
export * from "./ui/dropdown-menu";
export * from "./ui/icon-button";
export * from "./ui/multi-select";
export * from "./ui/popover";
export * from "./ui/select";
export * from "./ui/searchable-select";
export * from "./ui/sonner";
export * from "./ui/switch";
export * from "./ui/table";
export * from "./ui/textarea";
export * from "./ui/tooltip";
