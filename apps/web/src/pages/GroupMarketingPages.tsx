import { ConstructionIcon } from "lucide-react";
import { EmptyState } from "../components/ui";

export type GroupMarketingPageKind =
  | "拉群任务-炸群"
  | "模板管理-炸群"
  | "拉群任务-剧本"
  | "模板管理-剧本"
  | "收群验群任务"
  | "数据包"
  | "拉群市场分析";

export function GroupMarketingConstructionPage({
  title,
}: {
  title: GroupMarketingPageKind;
}) {
  return (
    <section className="flex min-h-[520px] flex-1 items-center justify-center rounded-lg border bg-background">
      <div className="flex max-w-md flex-col items-center gap-4 px-6 text-center">
        <span className="summary-icon size-11">
          <ConstructionIcon size={22} />
        </span>
        <EmptyState
          title={`${title} · 建设中`}
          description="当前仅建立菜单与页面入口，任务逻辑、数据和操作能力尚未开放。"
        />
      </div>
    </section>
  );
}
