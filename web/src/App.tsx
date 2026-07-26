/**
 * App shell layout: NavRail (left, collapsible) + active view (center) +
 * Inspector (right, collapsible + drag-resize, context per active view).
 *
 * 标签页+多级导航；风格现代简洁.
 */

import { useEffect, useRef, useState } from "react";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import NavRail, { type NavTabId } from "@/components/NavRail";
import Inspector from "@/components/Inspector";
import OverviewView from "@/views/OverviewView";
import WorkflowCanvasView from "@/views/WorkflowCanvasView";
import ChatView from "@/views/ChatView";
import ResourceEditorView from "@/views/ResourceEditorView";
import ConfigView from "@/views/ConfigView";
import NovelView from "@/views/NovelView";
import RpView from "@/views/RpView";
import RunView from "@/views/RunView";
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
  const [inspectorWidth, setInspectorWidth] = useState<number>(() => {
    const raw = localStorage.getItem("inspector.width");
    const parsed = raw === null ? NaN : Number(raw);
    return Number.isFinite(parsed) && parsed > 200 && parsed < 700 ? parsed : 320;
  });
  const resizingRef = useRef(false);

  useEffect(() => {
    localStorage.setItem("navrail.collapsed", railCollapsed ? "1" : "0");
  }, [railCollapsed]);

  useEffect(() => {
    localStorage.setItem("inspector.collapsed", inspectorCollapsed ? "1" : "0");
  }, [inspectorCollapsed]);

  useEffect(() => {
    localStorage.setItem("inspector.width", String(inspectorWidth));
  }, [inspectorWidth]);

  useEffect(() => {
    void fetchProjects();
  }, [fetchProjects]);

  // Drag-to-resize the Inspector from its left edge.
  useEffect(() => {
    if (inspectorCollapsed) return;
    const onMove = (e: MouseEvent) => {
      if (!resizingRef.current) return;
      const next = window.innerWidth - e.clientX;
      setInspectorWidth(Math.max(220, Math.min(640, next)));
    };
    const onUp = () => {
      resizingRef.current = false;
      document.body.style.cursor = "";
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [inspectorCollapsed]);

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
          <Route path="/workflow" element={<WorkflowCanvasView />} />
          <Route path="/chat" element={<ChatView />} />
          <Route path="/resources" element={<ResourceEditorView />} />
          <Route path="/config" element={<ConfigView />} />
          <Route path="/novel" element={<NovelView />} />
          <Route path="/rp" element={<RpView />} />
          <Route path="/run" element={<RunView />} />
          <Route path="*" element={<OverviewView />} />
        </Routes>
      </main>
      {!inspectorCollapsed && (
        <div
          className="inspector__resizer"
          onMouseDown={() => {
            resizingRef.current = true;
            document.body.style.cursor = "col-resize";
          }}
        />
      )}
      <Inspector
        activeView={activeView}
        collapsed={inspectorCollapsed}
        width={inspectorWidth}
        onToggleCollapse={() => setInspectorCollapsed((v) => !v)}
      />
    </div>
  );
}
