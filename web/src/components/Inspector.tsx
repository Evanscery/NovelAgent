/**
 * Inspector — right-side collapsible context panel.
 * Placeholder only in todo 26; detailed per-view content lands in todo 32.
 * Per refactor_guide:348 标签页+多级导航 — inspector is part of multi-level nav.
 */

import { type ReactNode } from "react";

interface InspectorProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export default function Inspector({
  collapsed,
  onToggleCollapse,
}: InspectorProps): ReactNode {
  return (
    <aside
      className={`inspector${collapsed ? " inspector--collapsed" : ""}`}
      aria-label="检查器"
    >
      <button
        type="button"
        className="inspector__toggle"
        onClick={onToggleCollapse}
        aria-label={collapsed ? "展开检查器" : "折叠检查器"}
        aria-expanded={!collapsed}
      >
        {collapsed ? "«" : "»"}
      </button>
      {!collapsed && (
        <div className="inspector__body">
          <h3 className="inspector__title">检查器</h3>
          <p className="inspector__hint">上下文详情面板（todo 32 实装）。</p>
        </div>
      )}
    </aside>
  );
}
