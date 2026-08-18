import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  ChevronsLeftIcon,
  ChevronsRightIcon,
  SearchIcon,
} from "lucide-react";
import { cn } from "../lib/utils";
import { Button, Input, SelectField } from "./ui";

export function StandardListPage({
  children,
  viewport = false,
}: {
  children: ReactNode;
  viewport?: boolean;
}) {
  return (
    <div
      className={cn(
        "standard-list-page flex min-w-0 flex-1 flex-col gap-4",
        viewport && "standard-list-page--viewport",
      )}
    >
      {children}
    </div>
  );
}

export function ListToolbar({
  search,
  filters,
  meta,
  actions,
}: {
  search?: {
    value: string;
    onChange: (value: string) => void;
    placeholder: string;
    onSubmit?: () => void;
  };
  filters?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
}) {
  const searchControl = search ? (
    <div className="relative w-full max-w-80">
      <SearchIcon className="pointer-events-none absolute top-1/2 left-3 z-10 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        className="pl-9"
        value={search.value}
        placeholder={search.placeholder}
        onChange={(event) => search.onChange(event.target.value)}
      />
    </div>
  ) : null;

  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex min-w-0 flex-1 flex-col gap-3 lg:flex-row lg:flex-wrap lg:items-center [&>form]:w-full [&>form]:max-w-80">
        {search?.onSubmit ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              search.onSubmit?.();
            }}
          >
            {searchControl}
          </form>
        ) : (
          searchControl
        )}
        {filters}
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2">
        {meta ? (
          <span className="whitespace-nowrap text-sm text-muted-foreground">
            {meta}
          </span>
        ) : null}
        {actions}
      </div>
    </div>
  );
}

export function ListTableCard({ children }: { children: ReactNode }) {
  return (
    <section className="list-table-card min-h-60 overflow-auto rounded-lg border bg-background">
      {children}
    </section>
  );
}

export function ListPagination({
  page,
  pageSize,
  total,
  pageSizeOptions = [20, 50, 100],
  onPageChange,
  onPageSizeChange,
  disabled,
  ariaLabel = "列表分页",
  className,
}: {
  page: number;
  pageSize: number;
  total: number;
  pageSizeOptions?: number[];
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
  disabled?: boolean;
  ariaLabel?: string;
  className?: string;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const start = total ? (page - 1) * pageSize + 1 : 0;
  const end = Math.min(page * pageSize, total);

  return (
    <nav
      aria-label={ariaLabel}
      className={cn(
        "list-pagination flex flex-col gap-3 rounded-xl border border-border/60 bg-card/40 px-3 py-2.5 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <strong className="font-medium text-foreground">
          {start}-{end} 条
        </strong>
        <span>共 {total.toLocaleString()} 条</span>
        <SelectField
          ariaLabel="每页条数"
          value={String(pageSize)}
          onValueChange={(value) => onPageSizeChange(Number(value))}
          options={pageSizeOptions.map((value) => ({
            value: String(value),
            label: `${value} 条`,
          }))}
          className="h-7 w-[96px] bg-background/60"
        />
      </div>
      <div className="flex items-center gap-2">
        <span>
          第 {page} / {totalPages} 页
        </span>
        <Button
          variant="outline"
          size="icon-sm"
          aria-label="第一页"
          disabled={disabled || page <= 1}
          onClick={() => onPageChange(1)}
        >
          <ChevronsLeftIcon />
        </Button>
        <Button
          variant="outline"
          size="icon-sm"
          aria-label="上一页"
          disabled={disabled || page <= 1}
          onClick={() => onPageChange(Math.max(1, page - 1))}
        >
          <ChevronLeftIcon size={16} />
        </Button>
        <Button
          variant="outline"
          size="icon-sm"
          aria-label="下一页"
          disabled={disabled || page >= totalPages}
          onClick={() => onPageChange(Math.min(totalPages, page + 1))}
        >
          <ChevronRightIcon size={16} />
        </Button>
        <Button
          variant="outline"
          size="icon-sm"
          aria-label="最后一页"
          disabled={disabled || page >= totalPages}
          onClick={() => onPageChange(totalPages)}
        >
          <ChevronsRightIcon />
        </Button>
      </div>
    </nav>
  );
}

export function useClientPagination<T>(
  rows: T[],
  options: {
    initialPageSize?: number;
    resetKey?: string;
  } = {},
) {
  const { initialPageSize = 20, resetKey = "" } = options;
  const [page, setPage] = useState(1);
  const [pageSize, setPageSizeState] = useState(initialPageSize);
  const total = rows.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const currentPage = Math.min(page, totalPages);

  useEffect(() => {
    setPage(1);
  }, [resetKey]);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const paginatedRows = useMemo(
    () =>
      rows.slice(
        (currentPage - 1) * pageSize,
        currentPage * pageSize,
      ),
    [currentPage, pageSize, rows],
  );

  const setPageSize = useCallback((value: number) => {
    setPageSizeState(value);
    setPage(1);
  }, []);

  return {
    page: currentPage,
    pageSize,
    total,
    rows: paginatedRows,
    setPage,
    setPageSize,
  };
}
