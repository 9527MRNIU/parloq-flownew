import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { AppLayout } from "./components/AppLayout";
import {
  ConfirmDialogHost,
  Spinner,
  Toaster,
  TooltipProvider,
} from "./components/ui";
import type { GroupMarketingPageKind } from "./pages/GroupMarketingPages";

const DirectShortLinksPage = lazy(() => import("./pages/DirectShortLinksPage").then((module) => ({ default: module.DirectShortLinksPage })));
const LoginPage = lazy(() => import("./pages/LoginPage").then((module) => ({ default: module.LoginPage })));
const AccountSecurityPage = lazy(() => import("./pages/AccountSecurityPage").then((module) => ({ default: module.AccountSecurityPage })));
const IpManagementPage = lazy(() => import("./pages/IpManagementPage").then((module) => ({ default: module.IpManagementPage })));
const PersonalAccountsPage = lazy(() => import("./pages/PersonalAccountsPage").then((module) => ({ default: module.PersonalAccountsPage })));
const AccountResourceDetailPage = lazy(() => import("./pages/AccountResourceDetailPage").then((module) => ({ default: module.AccountResourceDetailPage })));
const PromotionTemplatePreviewPage = lazy(() => import("./pages/PromotionPages").then((module) => ({ default: module.PromotionTemplatePreviewPage })));
const PromotionChannelsPage = lazy(() => import("./pages/PromotionPages").then((module) => ({ default: module.PromotionChannelsPage })));
const PromotionTemplatesPage = lazy(() => import("./pages/PromotionPages").then((module) => ({ default: module.PromotionTemplatesPage })));
const PromotionIntegrationsPage = lazy(() => import("./pages/PromotionIntegrationsPage"));
const DomainsPage = lazy(() => import("./pages/DomainsPage").then((module) => ({ default: module.DomainsPage })));
const PromotionChannelStatisticsPage = lazy(() => import("./pages/PromotionDataPages").then((module) => ({ default: module.PromotionChannelStatisticsPage })));
const PromotionTrendPage = lazy(() => import("./pages/PromotionDataPages").then((module) => ({ default: module.PromotionTrendPage })));
const PromotionMonitoringPage = lazy(() => import("./pages/PromotionMonitoringPage"));
const HyperlinkDataPackagesPage = lazy(() => import("./pages/HyperlinkResourcePages").then((module) => ({ default: module.HyperlinkDataPackagesPage })));
const HyperlinkStrategiesPage = lazy(() => import("./pages/HyperlinkResourcePages").then((module) => ({ default: module.HyperlinkStrategiesPage })));
const HyperlinkTasksPage = lazy(() => import("./pages/HyperlinkResourcePages").then((module) => ({ default: module.HyperlinkTasksPage })));
const HyperlinkTemplatesPage = lazy(() => import("./pages/HyperlinkResourcePages").then((module) => ({ default: module.HyperlinkTemplatesPage })));
const MaterialsPage = lazy(() => import("./pages/HyperlinkMaterialsPage").then((module) => ({ default: module.MaterialsPage })));
const HyperlinkMarketInsightsPage = lazy(() => import("./pages/HyperlinkMarketInsightsPage").then((module) => ({ default: module.HyperlinkMarketInsightsPage })));
const UserGroupsPage = lazy(() => import("./pages/UserGroupsPage").then((module) => ({ default: module.UserGroupsPage })));
const UsersPage = lazy(() => import("./pages/UsersPage").then((module) => ({ default: module.UsersPage })));
const SystemConfigurationPage = lazy(() => import("./pages/SystemConfigurationPage").then((module) => ({ default: module.SystemConfigurationPage })));
const AccountGroupsPage = lazy(() => import("./pages/AccountCenterPages").then((module) => ({ default: module.AccountGroupsPage })));
const AccountIntakePage = lazy(() => import("./pages/AccountCenterPages").then((module) => ({ default: module.AccountIntakePage })));
const AccountStatisticsPage = lazy(() => import("./pages/AccountStatisticsPage").then((module) => ({ default: module.AccountStatisticsPage })));
const ProtocolCenterPage = lazy(() => import("./pages/ProtocolCenterPage").then((module) => ({ default: module.ProtocolCenterPage })));
const HomePage = lazy(() => import("./pages/HomePage").then((module) => ({ default: module.HomePage })));
const DeveloperDocsPage = lazy(() => import("./pages/DeveloperDocsPage").then((module) => ({ default: module.DeveloperDocsPage })));
const GroupMarketingConstructionPage = lazy(() => import("./pages/GroupMarketingPages").then((module) => ({ default: module.GroupMarketingConstructionPage })));

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

function ProtectedPage({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading)
    return (
      <div className="boot-screen">
        <Spinner />
        <span>正在加载 Parloq…</span>
      </div>
    );
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function ProtocolCenterRedirect({
  tab,
}: {
  tab: "nodes" | "protocols" | "routing";
}) {
  const location = useLocation();
  const search = new URLSearchParams(location.search);
  search.set("tab", tab);
  return (
    <Navigate
      to={`/resources/operations/protocol-center?${search.toString()}`}
      replace
    />
  );
}

export default function App() {
  return (
    <TooltipProvider>
      <Suspense
        fallback={
          <div className="boot-screen">
            <Spinner />
            <span>正在加载页面…</span>
          </div>
        }
      >
        <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/promotion/templates/:templateId/preview"
          element={
            <ProtectedPage>
              <PromotionTemplatePreviewPage />
            </ProtectedPage>
          }
        />
        <Route element={<ProtectedLayout />}>
          <Route index element={<HomePage />} />
          <Route path="/account/security" element={<AccountSecurityPage />} />
          <Route
            path="/promotion/templates"
            element={<PromotionTemplatesPage />}
          />
          <Route
            path="/promotion/integrations"
            element={<PromotionIntegrationsPage />}
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
          <Route path="/promotion/monitoring" element={<PromotionMonitoringPage />} />
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
          <Route
            path="/resources/accounts/import"
            element={<Navigate to="/resources/accounts/manage?import=1" replace />}
          />
          <Route path="/resources/accounts/manage" element={<PersonalAccountsPage />} />
          <Route path="/resources/accounts/manage/:accountId" element={<AccountResourceDetailPage />} />
          <Route path="/resources/accounts/groups" element={<AccountGroupsPage />} />
          <Route path="/resources/accounts/intake" element={<AccountIntakePage />} />
          <Route path="/resources/accounts/statistics" element={<AccountStatisticsPage />} />
          <Route path="/resources/materials" element={<MaterialsPage />} />
          <Route path="/resources/operations/protocol-center" element={<ProtocolCenterPage />} />
          <Route path="/resources/operations/protocols" element={<ProtocolCenterRedirect tab="protocols" />} />
          <Route path="/resources/operations/nodes" element={<ProtocolCenterRedirect tab="nodes" />} />
          <Route path="/resources/operations/protocol" element={<ProtocolCenterRedirect tab="nodes" />} />
          <Route path="/resources/operations/routing" element={<ProtocolCenterRedirect tab="routing" />} />
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
            element={<Navigate to="/resources/materials" replace />}
          />
          <Route
            path="/hyperlink/market-insights"
            element={<HyperlinkMarketInsightsPage />}
          />
          <Route
            path="/direct-short-links"
            element={<DirectShortLinksPage />}
          />
          <Route
            path="/contact-marketing"
            element={<GroupMarketingConstructionPage title="好友营销" />}
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
          <Route path="/system/developer-docs" element={<DeveloperDocsPage />} />
          <Route
            path="/system/configuration"
            element={
              <AdminOnly>
                <SystemConfigurationPage />
              </AdminOnly>
            }
          />
        </Route>
        <Route
          path="*"
          element={<Navigate to="/" replace />}
        />
        </Routes>
      </Suspense>
      <Toaster />
      <ConfirmDialogHost />
    </TooltipProvider>
  );
}
