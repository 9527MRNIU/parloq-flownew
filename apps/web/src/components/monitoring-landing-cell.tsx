import { CopyIcon, ExternalLinkIcon } from "lucide-react";
import { IconButton } from "./ui";

export function MonitoringLandingCell({
  hostname,
  url,
  slug,
  onCopy,
}: {
  hostname?: string | null;
  url: string;
  slug: string;
  onCopy: (value: string) => void;
}) {
  return (
    <div className="cell-main mx-auto min-w-[190px] justify-items-center text-center">
      <strong title={hostname || undefined}>{hostname || "内部访问地址"}</strong>
      <span className="inline-link">
        /{slug}
        <IconButton
          label="打开访问地址"
          className="mini-icon"
          onClick={() => window.open(url, "_blank", "noopener,noreferrer")}
        >
          <ExternalLinkIcon size={14} />
        </IconButton>
        <IconButton
          label="复制访问地址"
          className="mini-icon"
          onClick={() => onCopy(url)}
        >
          <CopyIcon size={14} />
        </IconButton>
      </span>
    </div>
  );
}
