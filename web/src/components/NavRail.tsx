/**
 * NavRail — vertical rail with 8 tabs (icon + label).
 * Collapsible (icon-only when collapsed), localStorage memory.
 * 标签页+多级导航.
 */

import { type ReactNode } from "react";

export type NavTabId =
  | "overview"
  | "workflow"
  | "chat"
  | "resources"
  | "config"
  | "novel"
  | "rp"
  | "run";

interface NavTabDef {
  id: NavTabId;
  label: string;
  glyph: ReactNode;
}

const TABS: readonly NavTabDef[] = [
  { id: "overview", label: "概览", glyph: <span aria-hidden>◯</span> },
  { id: "workflow", label: "工作流", glyph: <span aria-hidden>◈</span> },
  { id: "chat", label: "对话", glyph: <span aria-hidden>✎</span> },
  { id: "resources", label: "资源", glyph: <span aria-hidden>▤</span> },
  { id: "config", label: "配置", glyph: <span aria-hidden>⚙</span> },
  { id: "novel", label: "作品", glyph: <span aria-hidden>📖</span> },
  { id: "rp", label: "RP", glyph: <span aria-hidden>♪</span> },
  { id: "run", label: "运行", glyph: <span aria-hidden>▶</span> },
] as const;

interface NavRailProps {
  active: NavTabId;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onSelect: (tab: NavTabId) => void;
}

export default function NavRail({
  active,
  collapsed,
  onToggleCollapse,
  onSelect,
}: NavRailProps): ReactNode {
  return (
    <nav
      className={`navrail${collapsed ? " navrail--collapsed" : ""}`}
      aria-label="主导航"
    >
      <button
        type="button"
        className="navrail__toggle"
        onClick={onToggleCollapse}
        aria-label={collapsed ? "展开导航" : "折叠导航"}
        aria-expanded={!collapsed}
      >
        {collapsed ? "»" : "«"}
      </button>
      <ul className="navrail__list">
        {TABS.map((tab) => {
          const isActive = tab.id === active;
          return (
            <li key={tab.id} className="navrail__item">
              <button
                type="button"
                className={`navrail__tab${isActive ? " navrail__tab--active" : ""}`}
                onClick={() => onSelect(tab.id)}
                aria-current={isActive ? "page" : undefined}
                title={tab.label}
              >
                <span className="navrail__glyph">{tab.glyph}</span>
                {!collapsed && <span className="navrail__label">{tab.label}</span>}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
