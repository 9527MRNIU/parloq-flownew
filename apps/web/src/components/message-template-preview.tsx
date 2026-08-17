import {
  FileTextIcon,
  ImageIcon,
  VideoIcon,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import {
  MessageTemplateButtonIcon,
  type MessageTemplateButtonType,
} from "./message-template-buttons";

export type MessagePreviewHeaderType =
  | "none"
  | "text"
  | "image"
  | "video"
  | "document";

export type MessagePreviewButtonType = MessageTemplateButtonType;

export type MessagePreviewButton = {
  id: string;
  type: MessagePreviewButtonType;
  text: string;
  value?: string;
};

type MessageTemplatePreviewProps = {
  headerType: MessagePreviewHeaderType;
  headerText?: string;
  mediaUrl?: string;
  fileName?: string;
  body?: string;
  footer?: string;
  buttons?: MessagePreviewButton[];
  compact?: boolean;
};

function previewTime() {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(new Date());
}

function richText(value: string) {
  const nodes: ReactNode[] = [];
  const pattern = /(```[\s\S]+?```|\*[^*\n]+\*|_[^_\n]+_|~[^~\n]+~)/g;
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(value)) !== null) {
    const token = match[0];
    if (match.index > cursor) nodes.push(value.slice(cursor, match.index));
    if (token.startsWith("```") && token.endsWith("```")) {
      nodes.push(
        <code
          key={`code-${match.index}`}
          className="rounded-sm bg-black/5 px-1 py-0.5 font-mono text-[0.92em]"
        >
          {token.slice(3, -3)}
        </code>,
      );
    } else if (token.startsWith("*") && token.endsWith("*")) {
      nodes.push(<strong key={`bold-${match.index}`}>{token.slice(1, -1)}</strong>);
    } else if (token.startsWith("_") && token.endsWith("_")) {
      nodes.push(<em key={`italic-${match.index}`}>{token.slice(1, -1)}</em>);
    } else if (token.startsWith("~") && token.endsWith("~")) {
      nodes.push(
        <span key={`strike-${match.index}`} className="line-through">
          {token.slice(1, -1)}
        </span>,
      );
    }
    cursor = match.index + token.length;
  }

  if (cursor < value.length) nodes.push(value.slice(cursor));
  return nodes.length ? nodes : value;
}

function safeButtonHref(button: MessagePreviewButton) {
  const value = String(button.value || "").trim();
  if (button.type === "call") {
    const phone = value.replace(/\D/g, "");
    return phone ? `tel:${phone}` : undefined;
  }
  if (button.type !== "url" || !value || /\{\{.*\}\}/.test(value)) return undefined;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? value : undefined;
  } catch {
    return undefined;
  }
}

const chatBackground = {
  backgroundColor: "#efe7dd",
  backgroundImage:
    "linear-gradient(rgba(239,231,221,.82),rgba(239,231,221,.82)),url('/whatsapp-assets/chat-background.webp')",
  backgroundPosition: "center",
  backgroundRepeat: "no-repeat",
  backgroundSize: "100% 100%",
};

export function MessageTemplatePreview({
  headerType,
  headerText = "",
  mediaUrl = "",
  fileName = "document",
  body = "",
  footer = "",
  buttons = [],
  compact = false,
}: MessageTemplatePreviewProps) {
  const [time, setTime] = useState(previewTime);
  const hasMedia = ["image", "video", "document"].includes(headerType);
  const hasTextHeader = headerType === "text" && Boolean(headerText.trim());
  const hasContent =
    hasMedia || hasTextHeader || Boolean(body.trim()) || Boolean(footer.trim()) || buttons.length > 0;

  useEffect(() => {
    const timer = window.setInterval(() => setTime(previewTime()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <aside className="flex min-w-0 items-start justify-center" aria-label="消息预览">
      <div className={compact ? "w-full max-w-[220px]" : "sticky top-4 w-full max-w-[300px]"}>
        <div
          className="relative aspect-[550/999] w-full overflow-hidden rounded-2xl shadow-[0_18px_50px_rgba(15,23,42,0.24)] ring-1 ring-black/5"
          style={chatBackground}
        >
          <div
            className="absolute inset-0 overflow-y-auto overscroll-contain px-5 py-7 [scrollbar-gutter:stable]"
            aria-label="可滚动模板消息预览"
            tabIndex={0}
          >
            {hasContent ? (
              <div className="relative w-full max-w-full break-words rounded-[7px] rounded-tl-none bg-white px-3 py-2 text-[#111b21] shadow-[0_1px_0.5px_rgba(11,20,26,0.22)]">
                <svg
                  aria-hidden="true"
                  viewBox="0 0 8 13"
                  className="absolute -left-2 top-0 h-[13px] w-2 text-white"
                >
                  <path d="M8 0H2.2C1 0 .5 1.5 1.3 2.4L8 10.7V0Z" fill="currentColor" />
                </svg>

                {hasMedia ? (
                  <div className="mb-2 overflow-hidden rounded-md">
                    {headerType === "image" && mediaUrl ? (
                      <img
                        src={mediaUrl}
                        alt="模板图片预览"
                        className="mx-auto block h-auto max-h-56 w-auto max-w-full rounded-md object-contain"
                      />
                    ) : headerType === "video" && mediaUrl ? (
                      <video
                        src={mediaUrl}
                        className="mx-auto block h-auto max-h-56 w-auto max-w-full rounded-md object-contain"
                        controls
                        muted
                      />
                    ) : headerType === "document" ? (
                      <div className="flex min-h-20 items-center gap-3 px-3 py-3">
                        <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-[#e9edef] text-[#008069]">
                          <FileTextIcon className="size-5" />
                        </div>
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium">{fileName || "document"}</div>
                          <div className="truncate text-xs text-[#667781]">文档</div>
                        </div>
                      </div>
                    ) : (
                      <div className="flex h-40 flex-col items-center justify-center gap-2 text-[#667781]">
                        {headerType === "image" ? <ImageIcon className="size-6" /> : null}
                        {headerType === "video" ? <VideoIcon className="size-6" /> : null}
                        <span className="text-xs">
                          {headerType === "image" ? "图片预览" : "视频预览"}
                        </span>
                      </div>
                    )}
                  </div>
                ) : null}

                {hasTextHeader ? (
                  <div className="mb-1 whitespace-pre-wrap text-sm font-semibold leading-relaxed">
                    {richText(headerText.trim())}
                  </div>
                ) : null}
                {body.trim() ? (
                  <div className="whitespace-pre-wrap text-sm leading-relaxed">
                    {richText(body.trim())}
                  </div>
                ) : null}
                {footer.trim() ? (
                  <div className="mt-1 text-xs leading-relaxed text-[#667781]">{footer.trim()}</div>
                ) : null}
                <div className="mt-1 text-right text-[11px] leading-none text-[#8696a0]">{time}</div>

                {buttons.length ? (
                  <div className="-mx-3 -mb-2 mt-3 divide-y divide-[#d9dee2] border-t border-[#d9dee2] text-sm font-medium text-[#008069]">
                    {buttons.map((button) => {
                      const href = safeButtonHref(button);
                      const content = (
                        <span className="inline-flex max-w-full items-center justify-center gap-2">
                          <span
                            className="flex size-4 shrink-0 items-center justify-center"
                            data-preview-button-icon
                          >
                            <MessageTemplateButtonIcon
                              type={button.type}
                              className="block size-4 shrink-0 stroke-[1.75]"
                            />
                          </span>
                          <span
                            className="min-w-0 truncate leading-5"
                            data-preview-button-label
                          >
                            {button.text}
                          </span>
                        </span>
                      );
                      const className =
                        "flex min-h-11 items-center justify-center px-3 text-center transition-colors hover:bg-black/5";
                      return href ? (
                        <a
                          key={button.id}
                          href={href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={className}
                          data-preview-button-type={button.type}
                        >
                          {content}
                        </a>
                      ) : (
                        <div
                          key={button.id}
                          className={className}
                          data-preview-button-type={button.type}
                        >
                          {content}
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </aside>
  );
}
