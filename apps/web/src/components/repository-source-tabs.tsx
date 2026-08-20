import { Button } from "./ui";
import type { RepositoryView } from "../lib/promotion-repository";

export function RepositorySourceTabs({
  value,
  localLabel,
  onChange,
  disabled = false,
}: {
  value: RepositoryView;
  localLabel: string;
  onChange: (value: RepositoryView) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-center gap-2" role="tablist" aria-label="内容来源">
      <Button
        role="tab"
        aria-selected={value === "local"}
        variant={value === "local" ? "secondary" : "outline"}
        disabled={disabled}
        onClick={() => onChange("local")}
      >
        {localLabel}
      </Button>
      <Button
        role="tab"
        aria-selected={value === "repository"}
        variant={value === "repository" ? "secondary" : "outline"}
        disabled={disabled}
        onClick={() => onChange("repository")}
      >
        远程仓库
      </Button>
    </div>
  );
}
