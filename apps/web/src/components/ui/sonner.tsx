import {
  CircleCheckIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react";
import {
  Toaster as Sonner,
  type ToasterProps,
  toast as sonnerToast,
} from "sonner";

const toast = {
  success: sonnerToast.success,
  warning: sonnerToast.warning,
  error: sonnerToast.error,
  dismiss: sonnerToast.dismiss,
};

export function Toaster(props: ToasterProps) {
  return (
    <Sonner
      theme="system"
      className="toaster group"
      position="top-center"
      richColors
      closeButton
      offset={{ top: 16, right: 16, left: 16 }}
      mobileOffset={{ top: 16, right: 16, left: 16 }}
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--success-bg": "var(--status-success-bg)",
          "--success-text": "var(--success)",
          "--success-border": "var(--status-success-border)",
          "--warning-bg": "var(--status-warning-bg)",
          "--warning-text": "var(--warning)",
          "--warning-border": "var(--status-warning-border)",
          "--error-bg": "var(--status-danger-bg)",
          "--error-text": "var(--danger)",
          "--error-border": "var(--status-danger-border)",
          "--border-radius": "var(--radius)",
        } as React.CSSProperties
      }
      toastOptions={{
        closeButtonAriaLabel: "关闭通知",
        classNames: { toast: "cn-toast" },
      }}
      {...props}
    />
  );
}
export { toast };
