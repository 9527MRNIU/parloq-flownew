import { type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { AppLayout } from "./components/AppLayout";
import {
  ConfirmDialogHost,
  Spinner,
  Toaster,
  TooltipProvider,
} from "./components/ui";
import { DirectShortLinksPage } from "./pages/DirectShortLinksPage";
import { LoginPage } from "./pages/LoginPage";
import { IpManagementPage } from "./pages/IpManagementPage";
import { PersonalAccountsPage } from "./pages/PersonalAccountsPage";
import {
  PromotionChannelsPage,
  PromotionTemplatesPage,
} from "./pages/PromotionPages";
import { DomainsPage } from "./pages/DomainsPage";
import {
  PromotionChannelStatisticsPage,
  PromotionTrendPage,
} from "./pages/PromotionDataPages";
import {
  HyperlinkDataPackagesPage,
  HyperlinkMaterialsPage,
  HyperlinkStrategiesPage,
  HyperlinkTasksPage,
  HyperlinkTemplatesPage,
} from "./pages/HyperlinkResourcePages";
import { HyperlinkMarketInsightsPage } from "./pages/HyperlinkMarketInsightsPage";
import { UserGroupsPage } from "./pages/UserGroupsPage";
import { UsersPage } from "./pages/UsersPage";
import { SystemMenusPage } from "./pages/SystemMenusPage";
import {
  AccountExportPage,
  AccountGroupsPage,
  AccountImportPage,
} from "./pages/AccountCenterPages";
import { AccountStatisticsPage } from "./pages/AccountStatisticsPage";
import { ProtocolManagementPage } from "./pages/ProtocolManagementPage";
import {
  GroupMarketingConstructionPage,
  type GroupMarketingPageKind,
} from "./pages/GroupMarketingPages";

const groupMarketingPages: Array<{ path: string; title: GroupMarketingPageKind }> = [
  { path: "/group-marketing/blast/tasks", title: "拉群任务-炸群" },
  { path: "/group-marketing/blast/templates", title: "模板管理-炸群" },
  { path: "/group-marketing/script/tasks", title: "拉群任务-剧本" },
  { path: "/group-marketing/script/templates", title: "模板管理-剧本" },
  { path: "/group-marketing/verification-tasks", title: "收群验群任务" },
  { path: "/group-marketing/data-packages", title: "数据包" },
  { path: "/group-marketing/market-analysis", title: "拉群市场分析" },
];

function ProtectedLayout() {
  const { user, loading } = useAuth();
  if (loading)
    return (
      <div className="boot-screen">
        <Spinner />
        <span>正在加载 Parloq…</span>
      </div>
    );
  if (!user) return <Navigate to="/login" replace />;
  return <AppLayout />;
}

function AdminOnly({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  return user?.isAdmin ? (
    children
  ) : (
    <Navigate to="/resources/accounts/manage" replace />
  );
}

export default function App() {
  return (
    <TooltipProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedLayout />}>
          <Route
            index
            element={<Navigate to="/promotion/templates" replace />}
          />
          <Route
            path="/promotion/templates"
            element={<PromotionTemplatesPage />}
          />
          <Route
            path="/promotion/channels"
            element={<PromotionChannelsPage />}
          />
          <Route path="/promotion/domains" element={<DomainsPage />} />
          <Route
            path="/promotion/statistics"
            element={<PromotionChannelStatisticsPage />}
          />
          <Route path="/promotion/trends" element={<PromotionTrendPage />} />
          <Route
            path="/promotion/data-center"
            element={<Navigate to="/promotion/statistics" replace />}
          />
          <Route
            path="/promotion/ad-metrics"
            element={<Navigate to="/promotion/statistics" replace />}
          />
          <Route
            path="/personal-accounts"
            element={<Navigate to="/resources/accounts/manage" replace />}
          />
          <Route path="/resources/accounts/import" element={<AccountImportPage />} />
          <Route path="/resources/accounts/export" element={<AccountExportPage />} />
          <Route path="/resources/accounts/manage" element={<PersonalAccountsPage />} />
          <Route path="/resources/accounts/groups" element={<AccountGroupsPage />} />
          <Route path="/resources/accounts/statistics" element={<AccountStatisticsPage />} />
          <Route path="/resources/operations/protocol" element={<ProtocolManagementPage />} />
          <Route
            path="/ip-management"
            element={<Navigate to="/resources/operations/ip" replace />}
          />
          <Route
            path="/resources/operations/ip"
            element={
              <AdminOnly>
                <IpManagementPage />
              </AdminOnly>
            }
          />
          <Route path="/hyperlink/tasks" element={<HyperlinkTasksPage />} />
          <Route
            path="/hyperlink/data-packages"
            element={<HyperlinkDataPackagesPage />}
          />
          <Route
            path="/hyperlink/templates"
            element={<HyperlinkTemplatesPage />}
          />
          <Route
            path="/hyperlink/strategies"
            element={<HyperlinkStrategiesPage />}
          />
          <Route
            path="/hyperlink/materials"
            element={<HyperlinkMaterialsPage />}
          />
          <Route
            path="/hyperlink/market-insights"
            element={<HyperlinkMarketInsightsPage />}
          />
          <Route
            path="/direct-short-links"
            element={<DirectShortLinksPage />}
          />
          {groupMarketingPages.map((page) => (
            <Route
              key={page.path}
              path={page.path}
              element={<GroupMarketingConstructionPage title={page.title} />}
            />
          ))}
          <Route
            path="/domains"
            element={<Navigate to="/promotion/domains" replace />}
          />
          <Route
            path="/system/users"
            element={
              <AdminOnly>
                <UsersPage />
              </AdminOnly>
            }
          />
          <Route
            path="/system/roles"
            element={
              <AdminOnly>
                <UserGroupsPage />
              </AdminOnly>
            }
          />
          <Route
            path="/system/user-groups"
            element={<Navigate to="/system/roles" replace />}
          />
          <Route
            path="/system/menus"
            element={
              <AdminOnly>
                <SystemMenusPage />
              </AdminOnly>
            }
          />
        </Route>
        <Route
          path="*"
          element={<Navigate to="/promotion/templates" replace />}
        />
      </Routes>
      <Toaster />
      <ConfirmDialogHost />
    </TooltipProvider>
  );
}
