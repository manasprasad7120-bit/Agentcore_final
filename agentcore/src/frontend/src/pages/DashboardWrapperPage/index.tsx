import { Outlet } from "react-router-dom";
import AppHeader from "@/components/core/appHeaderComponent";
import CostLimitBanner from "@/components/core/CostLimitBanner";
import useTheme from "@/customization/hooks/use-custom-theme";

export function DashboardWrapperPage() {
  useTheme();

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden">
      <AppHeader />
      <CostLimitBanner />
      <div className="flex w-full flex-1 flex-row overflow-hidden">
        <Outlet />
      </div>
    </div>
  );
}
