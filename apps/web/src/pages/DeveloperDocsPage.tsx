import {
  ArrowLeftIcon,
  ArrowRightIcon,
  BookOpenIcon,
  FileTextIcon,
  SearchIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { Link, useSearchParams } from "react-router-dom";
import remarkGfm from "remark-gfm";
import { apiRequest } from "../api/client";
import { Input, Spinner } from "../components/ui";

type DocPageSummary = {
  slug: string;
  title: string;
  summary: string;
  menuPath?: string;
  routePath?: string;
  keywords: string[];
};

type DocSection = {
  id: string;
  title: string;
  pages: DocPageSummary[];
};

type DocPage = DocPageSummary & {
  sectionId: string;
  sectionTitle: string;
};

type TocItem = {
  id: string;
  title: string;
  level: 2 | 3;
};

function responseData<T>(payload: unknown): T {
  const body = payload as { data?: T };
  return (body.data ?? payload) as T;
}

function nodeText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join("");
  if (node && typeof node === "object" && "props" in node) {
    return nodeText((node as { props?: { children?: ReactNode } }).props?.children);
  }
  return "";
}

function headingId(title: string): string {
  return title
    .trim()
    .toLowerCase()
    .replace(/[`*_~]/g, "")
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-");
}

function tableOfContents(markdown: string): TocItem[] {
  return markdown
    .split("\n")
    .map((line) => {
      const match = /^(##|###)\s+(.+?)\s*$/.exec(line);
      if (!match) return null;
      const title = match[2].replace(/[`*_~]/g, "").trim();
      return {
        id: headingId(title),
        title,
        level: match[1].length as 2 | 3,
      };
    })
    .filter((item): item is TocItem => Boolean(item?.id));
}

function InternalDocLink({ href = "", children }: { href?: string; children?: ReactNode }) {
  if (href.startsWith("/")) return <Link to={href}>{children}</Link>;
  return (
    <a href={href} target={href.startsWith("http") ? "_blank" : undefined} rel="noreferrer">
      {children}
    </a>
  );
}

export function DeveloperDocsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedSlug = searchParams.get("page") || "overview";
  const [sections, setSections] = useState<DocSection[]>([]);
  const [page, setPage] = useState<DocPage | null>(null);
  const [content, setContent] = useState("");
  const [keyword, setKeyword] = useState("");
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [pageLoading, setPageLoading] = useState(true);
  const [error, setError] = useState("");
  const articleRef = useRef<HTMLElement>(null);

  useEffect(() => {
    let cancelled = false;
    setCatalogLoading(true);
    apiRequest("/api/developer-docs")
      .then((payload) => {
        if (cancelled) return;
        const data = responseData<{ defaultPage: string; sections: DocSection[] }>(payload);
        setSections(data.sections);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "文档目录加载失败");
      })
      .finally(() => {
        if (!cancelled) setCatalogLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!sections.length) return;
    const known = sections.some((section) =>
      section.pages.some((item) => item.slug === requestedSlug),
    );
    if (!known) setSearchParams({ page: "overview" }, { replace: true });
  }, [requestedSlug, sections, setSearchParams]);

  useEffect(() => {
    let cancelled = false;
    setPageLoading(true);
    setError("");
    apiRequest(`/api/developer-docs/${encodeURIComponent(requestedSlug)}`)
      .then((payload) => {
        if (cancelled) return;
        const data = responseData<{ page: DocPage; content: string }>(payload);
        setPage(data.page);
        setContent(data.content);
        articleRef.current?.scrollTo({ top: 0 });
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "文档内容加载失败");
      })
      .finally(() => {
        if (!cancelled) setPageLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [requestedSlug]);

  const allPages = useMemo(() => sections.flatMap((section) => section.pages), [sections]);
  const currentIndex = allPages.findIndex((item) => item.slug === requestedSlug);
  const previousPage = currentIndex > 0 ? allPages[currentIndex - 1] : null;
  const nextPage = currentIndex >= 0 ? allPages[currentIndex + 1] ?? null : null;
  const toc = useMemo(() => tableOfContents(content), [content]);
  const normalizedKeyword = keyword.trim().toLowerCase();
  const filteredSections = useMemo(
    () =>
      sections
        .map((section) => ({
          ...section,
          pages: normalizedKeyword
            ? section.pages.filter((item) =>
                [item.title, item.summary, item.menuPath, ...item.keywords]
                  .filter(Boolean)
                  .join(" ")
                  .toLowerCase()
                  .includes(normalizedKeyword),
              )
            : section.pages,
        }))
        .filter((section) => section.pages.length),
    [normalizedKeyword, sections],
  );
  const filteredPages = filteredSections.flatMap((section) => section.pages);
  const mobileSelection = filteredPages.some((item) => item.slug === requestedSlug)
    ? requestedSlug
    : "";

  function openPage(slug: string) {
    setSearchParams({ page: slug });
    setKeyword("");
  }

  return (
    <section className="developer-docs-shell">
      <aside className="developer-docs-sidebar">
        <div className="developer-docs-sidebar-head">
          <div className="developer-docs-brand">
            <span><BookOpenIcon size={18} /></span>
            <div><strong>开发文档</strong><small>仅包含已上线功能</small></div>
          </div>
          <label className="developer-docs-search">
            <SearchIcon size={15} />
            <Input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="搜索菜单或规范"
              aria-label="搜索开发文档"
            />
          </label>
        </div>
        <nav className="developer-docs-navigation" aria-label="开发文档目录">
          {catalogLoading ? (
            <div className="developer-docs-loading"><Spinner />正在加载目录…</div>
          ) : filteredSections.length ? (
            filteredSections.map((section) => (
              <div className="developer-docs-nav-section" key={section.id}>
                <strong>{section.title}</strong>
                {section.pages.map((item) => (
                  <button
                    type="button"
                    key={item.slug}
                    className={item.slug === requestedSlug ? "active" : ""}
                    onClick={() => openPage(item.slug)}
                  >
                    <FileTextIcon size={14} />
                    <span>{item.title}</span>
                  </button>
                ))}
              </div>
            ))
          ) : (
            <div className="developer-docs-empty">没有匹配的文档</div>
          )}
        </nav>
      </aside>

      <div className="developer-docs-mobile-tools">
        <label className="developer-docs-search">
          <SearchIcon size={15} />
          <Input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索文档" />
        </label>
        <select value={mobileSelection} onChange={(event) => event.target.value && openPage(event.target.value)}>
          {!mobileSelection ? <option value="">选择搜索结果</option> : null}
          {filteredSections.flatMap((section) =>
            section.pages.map((item) => <option value={item.slug} key={item.slug}>{section.title} / {item.title}</option>),
          )}
        </select>
      </div>

      <article className="developer-docs-article" ref={articleRef}>
        {pageLoading ? (
          <div className="developer-docs-page-state"><Spinner />正在加载文档…</div>
        ) : error || !page ? (
          <div className="developer-docs-page-state error-state"><strong>文档暂时无法打开</strong><span>{error}</span></div>
        ) : (
          <div className="developer-docs-document">
            <header className="developer-docs-title">
              <span>{page.sectionTitle}</span>
              <h1>{page.title}</h1>
              <p>{page.summary}</p>
              {page.menuPath || page.routePath ? (
                <dl>
                  {page.menuPath ? <div><dt>菜单位置</dt><dd>{page.menuPath}</dd></div> : null}
                  {page.routePath ? <div><dt>页面路由</dt><dd><code>{page.routePath}</code></dd></div> : null}
                </dl>
              ) : null}
            </header>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h2: ({ children }) => <h2 id={headingId(nodeText(children))}>{children}</h2>,
                h3: ({ children }) => <h3 id={headingId(nodeText(children))}>{children}</h3>,
                a: ({ href, children }) => <InternalDocLink href={href}>{children}</InternalDocLink>,
              }}
            >
              {content}
            </ReactMarkdown>
            <footer className="developer-docs-pager">
              {previousPage ? (
                <button type="button" onClick={() => openPage(previousPage.slug)}>
                  <ArrowLeftIcon size={16} /><span><small>上一篇</small><strong>{previousPage.title}</strong></span>
                </button>
              ) : <span />}
              {nextPage ? (
                <button type="button" className="next" onClick={() => openPage(nextPage.slug)}>
                  <span><small>下一篇</small><strong>{nextPage.title}</strong></span><ArrowRightIcon size={16} />
                </button>
              ) : null}
            </footer>
          </div>
        )}
      </article>

      <aside className="developer-docs-toc">
        <strong>本页目录</strong>
        {toc.map((item) => (
          <a key={`${item.level}-${item.id}`} className={item.level === 3 ? "nested" : ""} href={`#${item.id}`}>
            {item.title}
          </a>
        ))}
      </aside>
    </section>
  );
}
