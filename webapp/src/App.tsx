// 應用殼層：HashRouter（PWA 友善，免伺服器路由設定）+ 條件式底部導覽。
// 重的頁面（卡片詳情含 ECharts、掃描含 OCR）用 lazy 切分，縮小首屏體積。
import { lazy, Suspense } from "react";
import {
  HashRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { BottomNav } from "./components/BottomNav";
import { AuthScreen } from "./screens/AuthScreen";
import { DashboardScreen } from "./screens/DashboardScreen";
import { CardSearchScreen } from "./screens/CardSearchScreen";
import { InventoryScreen } from "./screens/InventoryScreen";
import { MysteryPackScreen } from "./screens/MysteryPackScreen";
import { useApp } from "./store";

const CardDetailScreen = lazy(() =>
  import("./screens/CardDetailScreen").then((m) => ({ default: m.CardDetailScreen })),
);
const ScanScreen = lazy(() =>
  import("./scan/ScanScreen").then((m) => ({ default: m.ScanScreen })),
);

function Loading() {
  return <div className="screen-pad muted">載入中…</div>;
}

function ScanRoute() {
  const userId = useApp((s) => s.userId);
  const nav = useNavigate();
  return <ScanScreen userId={userId} onClose={() => nav("/")} />;
}

function Shell() {
  const loc = useLocation();
  // 掃描頁全螢幕沉浸，不顯示底部導覽。
  const hideNav = loc.pathname.startsWith("/scan");
  return (
    <>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/" element={<DashboardScreen />} />
          <Route path="/inventory" element={<InventoryScreen />} />
          <Route path="/search" element={<CardSearchScreen />} />
          <Route path="/packs" element={<MysteryPackScreen />} />
          <Route path="/cards/:cardId" element={<CardDetailScreen />} />
          <Route path="/scan" element={<ScanRoute />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
      {!hideNav && <BottomNav />}
    </>
  );
}

export function App() {
  const userId = useApp((s) => s.userId);
  if (!userId) return <AuthScreen />;
  return (
    <HashRouter>
      <Shell />
    </HashRouter>
  );
}
