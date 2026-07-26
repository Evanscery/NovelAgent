/**
 * NovelView — novel reader + edit/zoom.
 *
 * Left: chapter list (GET /api/novel/{id}). Right: chapter content
 * rendered as markdown (marked). Edit mode toggles a CodeMirror editor
 * (local draft — backend is read-only; saving would post to a future
 * /api/novel PUT). Zoom controls adjust font size 0.5×–2.5×.
 */

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { marked } from "marked";
import { useNovelStore } from "@/stores/novelStore";
import { useProjectStore } from "@/stores/projectStore";
import CodeMirrorEditor from "@/components/CodeMirrorEditor";

marked.setOptions({ breaks: true, gfm: true });

function ChapterList({
  chapters,
  activeFilename,
  onSelect,
}: {
  chapters: { filename: string; chapter_number: number | null; size_bytes: number }[];
  activeFilename: string | null;
  onSelect: (filename: string) => void;
}): ReactNode {
  if (chapters.length === 0) {
    return <p className="overview__empty-hint">还没有导出的章节。</p>;
  }
  return (
    <ul className="chapter-list">
      {chapters.map((c) => (
        <li key={c.filename}>
          <button
            type="button"
            className={`chapter-list__item${activeFilename === c.filename ? " chapter-list__item--active" : ""}`}
            onClick={() => onSelect(c.filename)}
          >
            <span className="chapter-list__title">
              {c.chapter_number !== null ? `第 ${c.chapter_number} 章` : c.filename}
            </span>
            <span className="chapter-list__meta">
              {Math.ceil(c.size_bytes / 1024)} KB
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export default function NovelView(): ReactNode {
  const {
    chapters,
    active,
    loading,
    error,
    zoom,
    loadChapters,
    openChapter,
    setZoom,
    clearError,
  } = useNovelStore();
  const activeProject = useProjectStore((s) => s.activeProject);
  const projectId = useNovelStore((s) => s.projectId);
  const [editMode, setEditMode] = useState(false);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    if (activeProject && activeProject.id !== projectId) {
      void loadChapters(activeProject.id);
    }
  }, [activeProject, projectId, loadChapters]);

  useEffect(() => {
    setDraft(active?.content ?? "");
  }, [active]);

  const html = useMemo(() => {
    if (!active) return "";
    const parsed = marked.parse(active.content);
    return typeof parsed === "string" ? parsed : "";
  }, [active]);

  return (
    <section className="view novel-view">
      <header className="view__header">
        <h1 className="view__title">作品阅读</h1>
        {activeProject && (
          <button
            type="button"
            className="btn"
            onClick={() => void loadChapters(activeProject.id)}
            disabled={loading}
          >
            {loading ? "加载中…" : "刷新章节列表"}
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

      {!activeProject && <p className="overview__empty-hint">请先在概览页选择一个项目。</p>}

      {activeProject && (
        <div className="novel-view__body">
          <aside className="novel-view__list">
            <h2 className="view__title">章节</h2>
            <ChapterList
              chapters={chapters}
              activeFilename={active?.filename ?? null}
              onSelect={(f) => {
                setEditMode(false);
                void openChapter(activeProject.id, f);
              }}
            />
          </aside>

          <main className="novel-view__reader">
            {!active && <p className="overview__empty-hint">选择左侧一个章节开始阅读。</p>}
            {active && (
              <>
                <div className="novel-view__toolbar">
                  <h2 className="view__title">
                    {active.chapter_number !== null
                      ? `第 ${active.chapter_number} 章`
                      : active.filename}
                  </h2>
                  <div className="novel-view__tools">
                    <button
                      type="button"
                      className="btn btn--sm"
                      onClick={() => setZoom(zoom - 0.1)}
                      title="缩小"
                    >
                      －
                    </button>
                    <span className="novel-view__zoom">{Math.round(zoom * 100)}%</span>
                    <button
                      type="button"
                      className="btn btn--sm"
                      onClick={() => setZoom(zoom + 0.1)}
                      title="放大"
                    >
                      ＋
                    </button>
                    <button
                      type="button"
                      className={`btn btn--sm${editMode ? " btn--primary" : ""}`}
                      onClick={() => setEditMode((v) => !v)}
                    >
                      {editMode ? "完成编辑" : "编辑"}
                    </button>
                  </div>
                </div>
                {editMode ? (
                  <CodeMirrorEditor value={draft} onChange={setDraft} />
                ) : (
                  <div
                    className="markdown novel-view__content"
                    style={{ fontSize: `${zoom}rem` }}
                    dangerouslySetInnerHTML={{ __html: html }}
                  />
                )}
              </>
            )}
          </main>
        </div>
      )}
    </section>
  );
}
