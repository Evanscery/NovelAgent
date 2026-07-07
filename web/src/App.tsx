/**
 * App shell layout: NavRail (left, collapsible) + active view (center) +
 * Inspector (right, collapsible placeholder — detailed in todo 32).
 *
 * Per refactor_guide:348 标签页+多级导航, guide:350 风格现代简洁.
 */

import { useEffect, useState } from "react";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import NavRail, { type NavTabId } from "@/components/NavRail";
import Inspector from "@/components/Inspector";
import OverviewView from "@/views/OverviewView";
import { useProjectStore } from "@/stores/projectStore";

type ViewId = NavTabId;

const VIEW_TO_PATH: Record<ViewId, string> = {
  overview: "/",
  workflow: "/workflow",
  chat: "/chat",
  resources: "/resources",
  config: "/config",
  novel: "/novel",
  rp: "/rp",
  run: "/run",
};

function pathToView(pathname: string): ViewId {
  for (const key of Object.keys(VIEW_TO_PATH) as ViewId[]) {
    if (VIEW_TO_PATH[key] === pathname) {
      return key;
    }
  }
  return "overview";
}

function PlaceholderView({ title }: { title: string }) {
  return (
    <section className="view view--placeholder">
      <h2 className="view__title">{title}</h2>
      <p className="view__hint">此视图将在后续 todo 中实现。</p>
    </section>
  );
}

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const activeView = pathToView(location.pathname);
  const fetchProjects = useProjectStore((s) => s.fetchProjects);

  const [railCollapsed, setRailCollapsed] = useState<boolean>(() => {
    return localStorage.getItem("navrail.collapsed") === "1";
  });
  const [inspectorCollapsed, setInspectorCollapsed] = useState<boolean>(() => {
    return localStorage.getItem("inspector.collapsed") === "1";
  });

  useEffect(() => {
    localStorage.setItem("navrail.collapsed", railCollapsed ? "1" : "0");
  }, [railCollapsed]);

  useEffect(() => {
    localStorage.setItem("inspector.collapsed", inspectorCollapsed ? "1" : "0");
  }, [inspectorCollapsed]);

  useEffect(() => {
    void fetchProjects();
  }, [fetchProjects]);
  const handleTabChange = (tab: ViewId) => {
    void navigate(VIEW_TO_PATH[tab]);
  };

  return (
    <div className="app-shell">
      <NavRail
        active={activeView}
        collapsed={railCollapsed}
        onToggleCollapse={() => setRailCollapsed((v) => !v)}
        onSelect={handleTabChange}
      />
      <main className="app-main">
        <Routes>
          <Route path="/" element={<OverviewView />} />
          <Route path="/workflow" element={<PlaceholderView title="工作流" />} />
          <Route path="/chat" element={<PlaceholderView title="Director 对话" />} />
          <Route path="/resources" element={<PlaceholderView title="资源编辑器" />} />
          <Route path="/config" element={<PlaceholderView title="配置" />} />
          <Route path="/novel" element={<PlaceholderView title="作品阅读" />} />
          <Route path="/rp" element={<PlaceholderView title="RP 互动" />} />
          <Route path="/run" element={<PlaceholderView title="运行面板" />} />
          <Route path="*" element={<OverviewView />} />
        </Routes>
      </main>
      <Inspector
        collapsed={inspectorCollapsed}
        onToggleCollapse={() => setInspectorCollapsed((v) => !v)}
      />
    </div>
  );
}
