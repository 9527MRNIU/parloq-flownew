import {
  CopyIcon,
  ExternalLinkIcon,
  ListIcon,
  PhoneIcon,
  ReplyIcon,
  type LucideIcon,
} from "lucide-react";

export type MessageTemplateButtonType =
  | "quick_reply"
  | "url"
  | "call"
  | "copy"
  | "single_select";

const BUTTON_PRESENTATION: Record<
  MessageTemplateButtonType,
  { label: string; icon: LucideIcon }
> = {
  quick_reply: { label: "自定义", icon: ReplyIcon },
  url: { label: "访问网站", icon: ExternalLinkIcon },
  call: { label: "拨打电话号码", icon: PhoneIcon },
  copy: { label: "复制内容", icon: CopyIcon },
  single_select: { label: "单选菜单", icon: ListIcon },
};

export function messageTemplateButtonLabel(type: MessageTemplateButtonType) {
  return BUTTON_PRESENTATION[type].label;
}

export function MessageTemplateButtonIcon({
  type,
  className,
}: {
  type: MessageTemplateButtonType;
  className?: string;
}) {
  const Icon = BUTTON_PRESENTATION[type].icon;
  return <Icon aria-hidden="true" focusable="false" className={className} />;
}
