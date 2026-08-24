import { lazy, Suspense, useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Button, Spinner } from "../components/ui";

const ProtocolNodesPage = lazy(() =>
  import("./ProtocolManagementPage").then((module) => ({
    default: module.ProtocolManagementPage,
  })),
);
const ProtocolDefinitionsPage = lazy(() =>
  import("./ProtocolDefinitionsPage").then((module) => ({
    default: module.ProtocolDefinitionsPage,
  })),
);
const ProtocolRoutingPage = lazy(() =>
  import("./ProtocolRoutingPage").then((module) => ({
    default: module.ProtocolRoutingPage,
  })),
);

export const PROTOCOL_CENTER_PATH = "/resources/operations/protocol-center";

export type ProtocolCenterTab = "nodes" | "protocols" | "routing";

type TabOption = {
  value: ProtocolCenterTab;
  label: string;
  visible: boolean;
};

function ProtocolCenterTabs({
  value,
  options,
  onChange,
}: {
  value: ProtocolCenterTab;
  options: TabOption[];
  onChange: (value: ProtocolCenterTab) => void;
}) {
  return (
    <div
      className="flex min-w-0 flex-wrap items-center gap-2"
      role="tablist"
      aria-label="协议中心"
    >
      {options
        .filter((option) => option.visible)
        .map((option) => (
          <Button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={value === option.value}
            variant={value === option.value ? "secondary" : "outline"}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </Button>
        ))}
    </div>
  );
}

export function ProtocolCenterPage() {
  const { canView } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const options = useMemo<TabOption[]>(
    () => [
      {
        value: "nodes",
        label: "节点管理",
        visible:
          canView("resources.protocol.read") ||
          canView("resources.protocol_routing.read"),
      },
      {
        value: "protocols",
        label: "协议管理",
        visible: canView("resources.protocol_definitions.read"),
      },
      {
        value: "routing",
        label: "路由策略",
        visible: canView("resources.protocol_routing.read"),
      },
    ],
    [canView],
  );
  const availableTabs = options
    .filter((option) => option.visible)
    .map((option) => option.value);
  const requestedTab = searchParams.get("tab") as ProtocolCenterTab | null;
  const activeTab =
    requestedTab && availableTabs.includes(requestedTab)
      ? requestedTab
      : availableTabs[0] || "nodes";

  useEffect(() => {
    if (requestedTab === activeTab) return;
    setSearchParams({ tab: activeTab }, { replace: true });
  }, [activeTab, requestedTab, setSearchParams]);

  const tabs = (
    <ProtocolCenterTabs
      value={activeTab}
      options={options}
      onChange={(tab) => setSearchParams({ tab })}
    />
  );

  return (
    <Suspense
      fallback={
        <div className="loading-state min-h-64">
          <Spinner />正在加载协议中心…
        </div>
      }
    >
      {activeTab === "protocols" ? (
        <ProtocolDefinitionsPage toolbarTabs={tabs} />
      ) : activeTab === "routing" ? (
        <ProtocolRoutingPage toolbarTabs={tabs} />
      ) : (
        <ProtocolNodesPage toolbarTabs={tabs} />
      )}
    </Suspense>
  );
}
