import { useEffect, useState } from "react";
import { AlertDialog } from "radix-ui";
import { Button } from "./button";

type ConfirmRequest = {
  title: string;
  description?: string;
  confirmText?: string;
  destructive?: boolean;
  resolve: (value: boolean) => void;
};
const listeners = new Set<(request: ConfirmRequest) => void>();

export function confirmAction({
  title,
  description,
  confirmText = "确认",
  destructive = true,
}: Omit<ConfirmRequest, "resolve">) {
  return new Promise<boolean>((resolve) =>
    listeners.forEach((listener) =>
      listener({ title, description, confirmText, destructive, resolve }),
    ),
  );
}

export function ConfirmDialogHost() {
  const [request, setRequest] = useState<ConfirmRequest | null>(null);
  useEffect(() => {
    const listener = (next: ConfirmRequest) => setRequest(next);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);
  const finish = (value: boolean) => {
    request?.resolve(value);
    setRequest(null);
  };
  return (
    <AlertDialog.Root
      open={Boolean(request)}
      onOpenChange={(open) => {
        if (!open && request) finish(false);
      }}
    >
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="modal-backdrop" />
        <AlertDialog.Content className="confirm-dialog">
          <AlertDialog.Title>{request?.title}</AlertDialog.Title>
          {request?.description ? (
            <AlertDialog.Description>
              {request.description}
            </AlertDialog.Description>
          ) : null}
          <div className="confirm-dialog-actions">
            <AlertDialog.Cancel asChild>
              <Button variant="outline" onClick={() => finish(false)}>
                取消
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <Button
                variant={request?.destructive ? "destructive" : "default"}
                onClick={() => finish(true)}
              >
                {request?.confirmText}
              </Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
