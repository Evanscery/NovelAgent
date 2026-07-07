/**
 * ResourceEditorView — per-type data editor + version history
 * (todo 29, guide:386-400).
 *
 * Left tree: 8 resource types (大纲/细纲/当前状态/变量/世界书/客观事实/
 * 人物记忆/创作笔记 — titles come from the backend list response).
 * Selecting a type loads its content into a CodeMirror markdown editor
 * and its git commit history into the right panel. Save (PUT) writes
 * new content; history refreshes. The variables type is read-only
 * (guide:210-211) — editor disabled + save button disabled.
 */

import { useEffect, useState, type ReactNode } from "react";
import { useResourceStore } from "@/stores/resourceStore";
import { useProjectStore } from "@/stores/projectStore";
import CodeMirrorEditor from "@/components/CodeMirrorEditor";
import type { ResourceHistoryEntry } from "@/api/client";

function ResourceTree({
  types,
  active,
  onSelect,
}: {
  types: { type: string; title: string; file_count: number; exists: boolean }[];
  active: string | null;
  onSelect: (type: string) => void;
}): ReactNode {
  return (
    <ul className="resource-tree">
      {types.map((t) => (
        <li key={t.type}>
          <button
            type="button"
            className={`resource-tree__item${active === t.type ? " resource-tree__item--active" : ""}`}
            onClick={() => onSelect(t.type)}
          >
            <span className="resource-tree__title">{t.title}</span>
            <span className="resource-tree__meta">
              {t.exists ? `${t.file_count} 文件` : "空"}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function HistoryPanel({
  commits,
  onSelect,
}: {
  commits: ResourceHistoryEntry[];
  onSelect?: (c: ResourceHistoryEntry) => void;
}): ReactNode {
  if (commits.length === 0) {
    return <p className="overview__empty-hint">暂无历史版本。</p>;
  }
  return (
    <ul className="history-list">
      {commits.map((c) => (
        <li key={c.sha} className="history-list__item">
          <button
            type="button"
            className="history-list__entry"
            onClick={() => onSelect?.(c)}
            title="查看该版本元数据"
          >
            <span className="history-list__sha">{c.sha.slice(0, 8)}</span>
            <span className="history-list__msg">{c.message || c.turn_id}</span>
            <span className="history-list__branch">{c.branch}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export default function ResourceEditorView(): ReactNode {
  const {
    types,
    activeType,
    content,
    history,
    loading,
    saving,
    error,
    dirty,
    loadTypes,
    selectType,
    save,
    setLocalContent,
    clearError,
  } = useResourceStore();
  const activeProject = useProjectStore((s) => s.activeProject);
  const projectId = useResourceStore((s) => s.projectId);
  const [localValue, setLocalValue] = useState("");

  useEffect(() => {
    if (activeProject && activeProject.id !== projectId) {
      void loadTypes(activeProject.id);
    }
  }, [activeProject, projectId, loadTypes]);

  useEffect(() => {
    setLocalValue(content?.content ?? "");
  }, [content]);

  const readOnly = content?.read_only ?? false;
  const projectReady = activeProject !== null;

  const handleSelect = (type: string) => {
    if (!activeProject) return;
    void selectType(activeProject.id, type);
  };

  const handleSave = () => {
    void save(localValue);
  };

  return (
    <section className="view resource-view">
      <header className="view__header">
        <h1 className="view__title">资源编辑器</h1>
        {activeProject && (
          <button
            type="button"
            className="btn"
            onClick={() => void loadTypes(activeProject.id)}
            disabled={loading}
          >
            {loading ? "加载中…" : "刷新列表"}
          </button>
        )}
      </header>

      {error !== null && (
        <p className="overview__error">
          出错了：{error}
          <button type="button" className="btn btn--sm" onClick={clearError}>
            关闭
          </button>
        </p>
      )}

      {!projectReady && (
        <p className="overview__empty-hint">请先在概览页选择一个项目。</p>
      )}

      {projectReady && (
        <div className="resource-view__body">
          <aside className="resource-view__tree">
            <h2 className="view__title">资源类型</h2>
            <ResourceTree
              types={types}
              active={activeType}
              onSelect={handleSelect}
            />
          </aside>

          <main className="resource-view__editor">
            {!activeType && <p className="overview__empty-hint">选择左侧一个资源类型开始编辑。</p>}
            {activeType && (
              <>
                <div className="resource-view__toolbar">
                  <h2 className="view__title">
                    {content?.title ?? activeType}
                    {readOnly && <span className="resource-view__ro">（只读）</span>}
                  </h2>
                  <button
                    type="button"
                    className="btn btn--primary"
                    onClick={handleSave}
                    disabled={saving || readOnly || !dirty}
                    title={readOnly ? "变量类型只读，不允许保存" : undefined}
                  >
                    {saving ? "保存中…" : "保存"}
                  </button>
                </div>
                {dirty && !readOnly && (
                  <p className="overview__loading">有未保存的更改。</p>
                )}
                <CodeMirrorEditor
                  value={localValue}
                  onChange={(v) => {
                    setLocalValue(v);
                    setLocalContent(v);
                  }}
                  readOnly={readOnly}
                  placeholder="在此输入 Markdown 内容…"
                />
              </>
            )}
          </main>

          <aside className="resource-view__history">
            <h2 className="view__title">版本历史</h2>
            <HistoryPanel commits={history} />
          </aside>
        </div>
      )}
    </section>
  );
}
