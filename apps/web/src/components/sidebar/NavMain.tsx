import type { ReactNode } from "react";
import { ChevronRightIcon } from "lucide-react";
import { NavLink } from "react-router-dom";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "../ui/collapsible";
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
} from "../ui/sidebar";

export type NavMainItem = {
  key: string;
  title: string;
  url?: string;
  icon: ReactNode;
  isActive?: boolean;
  defaultOpen?: boolean;
  items?: Array<{
    title: string;
    url: string;
    isActive?: boolean;
  }>;
};

export function NavMain({
  items,
  label,
  onNavigate,
}: {
  items: NavMainItem[];
  label?: string;
  onNavigate?: () => void;
}) {
  if (!items.length) return null;

  return (
    <SidebarGroup className="px-2 py-1.5">
      {label ? <SidebarGroupLabel>{label}</SidebarGroupLabel> : null}
      <SidebarMenu className="gap-0.5">
        {items.map((item) => {
          const hasSubItems = Boolean(item.items?.length);
          const itemContent = (
            <>
              {item.icon}
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <span className="truncate">{item.title}</span>
              </div>
            </>
          );

          return (
            <Collapsible
              key={item.key}
              asChild
              defaultOpen={item.defaultOpen}
            >
              <SidebarMenuItem>
                {hasSubItems ? (
                  <CollapsibleTrigger asChild>
                    <SidebarMenuButton
                      tooltip={item.title}
                      isActive={item.isActive}
                    >
                      {itemContent}
                      <ChevronRightIcon className="ml-auto transition-transform group-data-[state=open]/menu-button:rotate-90" />
                      <span className="sr-only">切换{item.title}</span>
                    </SidebarMenuButton>
                  </CollapsibleTrigger>
                ) : item.url ? (
                  <SidebarMenuButton
                    asChild
                    tooltip={item.title}
                    isActive={item.isActive}
                  >
                    <NavLink to={item.url} onClick={onNavigate}>
                      {itemContent}
                    </NavLink>
                  </SidebarMenuButton>
                ) : (
                  <SidebarMenuButton
                    tooltip={item.title}
                    isActive={item.isActive}
                  >
                    {itemContent}
                  </SidebarMenuButton>
                )}
                {hasSubItems ? (
                  <CollapsibleContent>
                    <SidebarMenuSub>
                      {item.items?.map((subItem) => (
                        <SidebarMenuSubItem key={subItem.url}>
                          <SidebarMenuSubButton
                            asChild
                            isActive={subItem.isActive}
                          >
                            <NavLink to={subItem.url} onClick={onNavigate}>
                              <span>{subItem.title}</span>
                            </NavLink>
                          </SidebarMenuSubButton>
                        </SidebarMenuSubItem>
                      ))}
                    </SidebarMenuSub>
                  </CollapsibleContent>
                ) : null}
              </SidebarMenuItem>
            </Collapsible>
          );
        })}
      </SidebarMenu>
    </SidebarGroup>
  );
}
