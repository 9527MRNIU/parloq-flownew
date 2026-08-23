import { useEffect, useMemo, useState } from "react";
import {
  BookUserIcon,
  ChartNoAxesCombinedIcon,
  ChevronsUpDownIcon,
  LayoutTemplateIcon,
  Link2Icon,
  LogOutIcon,
  HouseIcon,
  ImagesIcon,
  MoonIcon,
  SettingsIcon,
  ShieldCheckIcon,
  UsersRoundIcon,
  SunIcon,
  UserCircleIcon,
  WrenchIcon,
  WorkflowIcon,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { apiRequest } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { BoringAvatar } from "./boring-avatar";
import { NavMain } from "./sidebar/NavMain";
import { SystemMetricsIndicator } from "./SystemMetricsIndicator";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  IconButton,
} from "./ui";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
  useSidebar,
} from "./ui/sidebar";

type NavChild = {
  label: string;
  to: string;
  icon?: LucideIcon;
  permissionKey?: string;
  adminOnly?: boolean;
};
type NavItem = {
  label: string;
  to?: string;
  icon: LucideIcon;
  children?: NavChild[];
  adminOnly?: boolean;
  permissionKey?: string;
};
type NavSection = { label: string; items: NavItem[] };

export const navigation: NavSection[] = [
  {
    label: "工作台",
    items: [
      {
        label: "首页",
        to: "/",
        icon: HouseIcon,
      },
    ],
  },
  {
    label: "推广",
    items: [
      {
        label: "推广管理",
        icon: LayoutTemplateIcon,
        children: [
          {
            label: "模板管理",
            to: "/promotion/templates",
            permissionKey: "promotion.templates.read",
          },
          {
            label: "集成管理",
            to: "/promotion/integrations",
            permissionKey: "promotion.integrations.read",
          },
          {
            label: "渠道管理",
            to: "/promotion/channels",
            permissionKey: "promotion.channels.read",
          },
          {
            label: "域名管理",
            to: "/promotion/domains",
            permissionKey: "promotion.domain.read",
          },
        ],
      },
      {
        label: "数据中心",
        icon: ChartNoAxesCombinedIcon,
        children: [
          {
            label: "访问监控",
            to: "/promotion/monitoring",
            permissionKey: "promotion.monitoring.read",
          },
          {
            label: "渠道统计",
            to: "/promotion/statistics",
            permissionKey: "promotion.statistics.read",
          },
          {
            label: "趋势图",
            to: "/promotion/trends",
            permissionKey: "promotion.trends.read",
          },
        ],
      },
    ],
  },
  {
    label: "营销",
    items: [
      {
        label: "超链营销",
        icon: WorkflowIcon,
        children: [
          {
            label: "超链任务",
            to: "/hyperlink/tasks",
            permissionKey: "marketing.hyperlink_tasks.read",
          },
          {
            label: "数据包",
            to: "/hyperlink/data-packages",
            permissionKey: "marketing.data_packages.read",
          },
          {
            label: "超链模板",
            to: "/hyperlink/templates",
            permissionKey: "marketing.hyperlink_templates.read",
          },
          {
            label: "超链策略",
            to: "/hyperlink/strategies",
            permissionKey: "marketing.hyperlink_strategies.read",
          },
          {
            label: "超链市场透视",
            to: "/hyperlink/market-insights",
            permissionKey: "marketing.insights.read",
          },
        ],
      },
      {
        label: "拉群营销",
        icon: UsersRoundIcon,
        children: [
          {
            label: "拉群任务-炸群",
            to: "/group-marketing/blast/tasks",
            permissionKey: "marketing.group_blast_tasks.read",
          },
          {
            label: "模板管理-炸群",
            to: "/group-marketing/blast/templates",
            permissionKey: "marketing.group_blast_templates.read",
          },
          {
            label: "拉群任务-剧本",
            to: "/group-marketing/script/tasks",
            permissionKey: "marketing.group_script_tasks.read",
          },
          {
            label: "模板管理-剧本",
            to: "/group-marketing/script/templates",
            permissionKey: "marketing.group_script_templates.read",
          },
          {
            label: "收群验群任务",
            to: "/group-marketing/verification-tasks",
            permissionKey: "marketing.group_verification_tasks.read",
          },
          {
            label: "数据包",
            to: "/group-marketing/data-packages",
            permissionKey: "marketing.group_data_packages.read",
          },
          {
            label: "拉群市场分析",
            to: "/group-marketing/market-analysis",
            permissionKey: "marketing.group_market_analysis.read",
          },
        ],
      },
      {
        label: "直接短链",
        to: "/direct-short-links",
        icon: Link2Icon,
        permissionKey: "marketing.direct_short_links.read",
      },
    ],
  },
  {
    label: "资源",
    items: [
      {
        label: "账号中心",
        icon: BookUserIcon,
        children: [
          {
            label: "账号统计",
            to: "/resources/accounts/statistics",
            permissionKey: "resources.account_statistics.read",
          },
          {
            label: "账号分组",
            to: "/resources/accounts/groups",
            permissionKey: "resources.account_groups.read",
          },
          {
            label: "账号管理",
            to: "/resources/accounts/manage",
            permissionKey: "resources.accounts.read",
          },
          {
            label: "接入记录",
            to: "/resources/accounts/intake",
            permissionKey: "resources.account_intake.read",
          },
          {
            label: "账号导出",
            to: "/resources/accounts/export",
            permissionKey: "resources.accounts.export",
          },
        ],
      },
      {
        label: "素材库",
        to: "/resources/materials",
        icon: ImagesIcon,
        permissionKey: "resources.materials.read",
      },
      {
        label: "运营管理",
        icon: WrenchIcon,
        children: [
          {
            label: "协议管理",
            to: "/resources/operations/protocol",
            permissionKey: "resources.protocol.read",
          },
          {
            label: "IP 管理",
            to: "/resources/operations/ip",
            permissionKey: "resources.ip.manage",
          },
        ],
      },
    ],
  },
  {
    label: "系统",
    items: [
      {
        label: "系统管理",
        icon: SettingsIcon,
        children: [
          {
            label: "用户管理",
            to: "/system/users",
            permissionKey: "system.users.manage",
            adminOnly: true,
          },
          {
            label: "角色管理",
            to: "/system/roles",
            permissionKey: "system.roles.manage",
            adminOnly: true,
          },
          {
            label: "开发文档",
            to: "/system/developer-docs",
            permissionKey: "system.developer_docs.read",
          },
          {
            label: "系统配置",
            to: "/system/configuration",
            permissionKey: "system.configuration.manage",
            adminOnly: true,
          },
        ],
      },
    ],
  },
];

const titleMap: Record<string, { section: string; title: string }> = {
  ...Object.fromEntries(
    navigation.flatMap((section) =>
      section.items.flatMap((item) => {
        if (item.children) {
          return item.children.map((child) => [
            child.to,
            { section: item.label, title: child.label },
          ]);
        }
        return item.to
          ? [[item.to, { section: section.label, title: item.label }]]
          : [];
      }),
    ),
  ),
  "/account/security": { section: "个人账户", title: "账户安全" },
};

type MenuOverride = {
  name: string;
  routePath: string;
  permissionKey: string;
  sortOrder: number;
  enabled: boolean;
  visible: boolean;
};

function SidebarNav() {
  const location = useLocation();
  const { user } = useAuth();
  const { setOpenMobile } = useSidebar();
  const [menuOverrides, setMenuOverrides] = useState<Map<string, MenuOverride>>(
    new Map(),
  );
  const [menuAuthority, setMenuAuthority] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiRequest("/api/system/menus/me")
      .then((payload) => {
        if (cancelled) return;
        const body = (payload as { data?: { tree?: unknown[] } }).data;
        const rows: unknown[] = [];
        const visit = (items: unknown[]) =>
          items.forEach((value) => {
            if (!value || typeof value !== "object") return;
            const row = value as Record<string, unknown>;
            rows.push(row);
            if (Array.isArray(row.children)) visit(row.children);
          });
        visit(Array.isArray(body?.tree) ? body.tree : []);
        const next = new Map<string, MenuOverride>();
        rows.forEach((value) => {
          const row = value as Record<string, unknown>;
          const item = {
            name: String(row.name || ""),
            routePath: String(row.routePath || ""),
            permissionKey: String(row.permissionKey || ""),
            sortOrder: Number(row.sortOrder || 0),
            enabled: Boolean(row.enabled ?? true),
            visible: Boolean(row.visible ?? true),
          };
          if (item.routePath) next.set(`path:${item.routePath}`, item);
          if (item.permissionKey) {
            next.set(`permission:${item.permissionKey}`, item);
          }
        });
        setMenuOverrides(next);
        setMenuAuthority(true);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const overrideFor = (permissionKey?: string, to?: string) =>
    (to ? menuOverrides.get(`path:${to}`) : undefined) ??
    (permissionKey
      ? menuOverrides.get(`permission:${permissionKey}`)
      : undefined);

  const visibleNavigation = navigation
    .map((section) => ({
      ...section,
      items: section.items
        .filter((item) => !item.adminOnly || user?.isAdmin)
        .flatMap((item) => {
          const override = overrideFor(item.permissionKey, item.to);
          const children = item.children
            ?.filter((child) => !child.adminOnly || user?.isAdmin)
            ?.map((child, index) => ({
              child,
              index,
              override: overrideFor(child.permissionKey, child.to),
            }))
            .filter(({ override: childOverride }) =>
              menuAuthority
                ? Boolean(childOverride?.enabled && childOverride.visible)
                : !childOverride ||
                  (childOverride.enabled && childOverride.visible),
            )
            .sort(
              (left, right) =>
                (left.override?.sortOrder ?? left.index) -
                (right.override?.sortOrder ?? right.index),
            )
            .map(({ child, override: childOverride }) => ({
              ...child,
              label: childOverride?.name || child.label,
            }));
          if (item.children && menuAuthority && !children?.length) return [];
          if (!item.children && menuAuthority && !override && item.to !== "/") return [];
          if (override && (!override.enabled || !override.visible)) return [];
          return [
            {
              ...item,
              label: override?.name || item.label,
              children,
            },
          ];
        }),
    }))
    .filter((section) => section.items.length);

  const closeMobile = () => setOpenMobile(false);

  return (
    <>
      {visibleNavigation.map((section) => (
        <NavMain
          key={section.label}
          label={section.label}
          onNavigate={closeMobile}
          items={section.items.map((item) => {
            const Icon = item.icon;
            const active = item.children
              ? item.children.some((child) =>
                  location.pathname.startsWith(child.to),
                )
              : item.to === "/"
                ? location.pathname === "/"
                : location.pathname.startsWith(item.to!);
            return {
              key: `${section.label}-${item.label}`,
              title: item.label,
              url: item.to,
              icon: <Icon className="size-4" />,
              isActive: active,
              defaultOpen: active,
              items: item.children?.map((child) => ({
                title: child.label,
                url: child.to,
                isActive: location.pathname.startsWith(child.to),
              })),
            };
          })}
        />
      ))}
    </>
  );
}

export function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout, can } = useAuth();
  const [dark, setDark] = useState(
    () => window.localStorage.getItem("parloq-theme") === "dark",
  );
  const current = useMemo(
    () => titleMap[location.pathname] || { section: "", title: "Parloq" },
    [location.pathname],
  );

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    window.localStorage.setItem("parloq-theme", dark ? "dark" : "light");
  }, [dark]);

  async function signOut() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <SidebarProvider>
      <Sidebar variant="inset" collapsible="icon">
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton asChild size="lg" tooltip="Parloq">
                <NavLink
                  to="/"
                  className="flex items-center gap-2"
                >
                  <img
                    src="/brand/parloq-icon.svg"
                    alt="Parloq"
                    className="size-8 flex-shrink-0"
                  />
                  <div className="flex min-w-0 flex-1 items-center gap-2 group-data-[collapsible=icon]:hidden">
                    <span className="truncate text-[16px] leading-none font-semibold text-primary">
                      Parloq
                    </span>
                  </div>
                </NavLink>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>
        <SidebarContent>
          <SidebarNav />
        </SidebarContent>
        <SidebarFooter>
          <SidebarMenu>
            <SidebarMenuItem>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <SidebarMenuButton
                    size="lg"
                    className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
                  >
                    <BoringAvatar
                      name={user?.username || "user"}
                      size={32}
                      square
                      className="shrink-0"
                    />
                    <div className="grid flex-1 text-left text-sm leading-tight group-data-[collapsible=icon]:hidden">
                      <span className="truncate font-medium">
                        {user?.username || "admin"}
                      </span>
                      <span className="truncate text-xs text-muted-foreground">
                        {user?.groupName || "管理员"}
                      </span>
                    </div>
                    <ChevronsUpDownIcon className="ml-auto size-4 group-data-[collapsible=icon]:hidden" />
                  </SidebarMenuButton>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  side="right"
                  align="end"
                  sideOffset={4}
                  className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
                >
                  <DropdownMenuLabel className="flex min-w-0 flex-col gap-1">
                    <span className="truncate">{user?.username || "admin"}</span>
                    <span className="truncate text-xs font-normal text-muted-foreground">
                      {user?.groupName || "管理员"}
                    </span>
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuGroup>
                    <DropdownMenuItem asChild>
                      <NavLink to="/account/security">
                        <ShieldCheckIcon />
                        账户安全
                      </NavLink>
                    </DropdownMenuItem>
                    {can("system.users.manage") ? (
                      <DropdownMenuItem asChild>
                        <NavLink to="/system/users">
                          <UserCircleIcon />
                          用户管理
                        </NavLink>
                      </DropdownMenuItem>
                    ) : null}
                  </DropdownMenuGroup>
                  <DropdownMenuSeparator />
                  <DropdownMenuGroup>
                    <DropdownMenuItem onClick={() => void signOut()}>
                      <LogOutIcon />
                      退出登录
                    </DropdownMenuItem>
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </Sidebar>

      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b px-4">
          <div className="flex min-w-0 items-center gap-2 text-sm">
            <SidebarTrigger className="-ml-1" />
            {current.section ? (
              <>
                <span className="truncate text-muted-foreground">
                  {current.section}
                </span>
                <span className="text-muted-foreground">/</span>
              </>
            ) : null}
            <strong className="truncate">{current.title}</strong>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <SystemMetricsIndicator />
            <IconButton
              label={dark ? "切换浅色主题" : "切换深色主题"}
              onClick={() => setDark((value) => !value)}
            >
              {dark ? <SunIcon /> : <MoonIcon />}
            </IconButton>
          </div>
        </header>
        <main className="flex min-w-0 flex-1 p-4">
          <div className="flex w-full min-w-0 flex-1 flex-col gap-4">
            <Outlet />
          </div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
