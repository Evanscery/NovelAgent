/**
 * OverviewView — project hub.
 * 默认傻瓜式, 面向零技术用户.
 * Lists existing projects as cards, "新建项目" button opens a modal with
 * display_name + mode select. Empty state when no projects.
 */

import { type FormEvent, type ReactNode, useState } from "react";
import { useProjectStore } from "@/stores/projectStore";
import type { ProjectMode } from "@/api/client";

function EmptyState({ onCreate }: { onCreate: () => void }): ReactNode {
  return (
    <div className="overview__empty">
      <h2 className="overview__empty-title">还没有项目</h2>
      <p className="overview__empty-hint">
        点击「新建项目」开始你的第一个创作/RP 工作区。
      </p>
      <button type="button" className="btn btn--primary" onClick={onCreate}>
        + 新建项目
      </button>
    </div>
  );
}

function ProjectCard({
  id,
  displayName,
  mode,
  active,
  onSelect,
  onDelete,
}: {
  id: string;
  displayName: string;
  mode: ProjectMode;
  active: boolean;
  onSelect: () => void;
  onDelete: () => void;
}): ReactNode {
  return (
    <article
      className={`project-card${active ? " project-card--active" : ""}`}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      role="button"
      tabIndex={0}
    >
      <header className="project-card__header">
        <h3 className="project-card__name">{displayName}</h3>
        <span className={`project-card__mode project-card__mode--${mode}`}>
          {mode === "novel" ? "小说" : "RP"}
        </span>
      </header>
      <p className="project-card__id">{id}</p>
      <footer className="project-card__footer">
        <button
          type="button"
          className="btn btn--danger btn--sm"
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
        >
          删除
        </button>
      </footer>
    </article>
  );
}

function CreateProjectModal({
  open,
  onClose,
  onSubmit,
  submitting,
  error,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (displayName: string, mode: ProjectMode) => void;
  submitting: boolean;
  error: string | null;
}): ReactNode {
  const [displayName, setDisplayName] = useState("");
  const [mode, setMode] = useState<ProjectMode>("novel");

  if (!open) return null;

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (displayName.trim().length === 0) return;
    onSubmit(displayName.trim(), mode);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-project-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="create-project-title" className="modal__title">
          新建项目
        </h2>
        <form className="modal__form" onSubmit={handleSubmit}>
          <label className="field">
            <span className="field__label">项目名称</span>
            <input
              type="text"
              className="field__input"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="例如：我的第一部小说"
              autoFocus
              required
              minLength={1}
            />
          </label>
          <label className="field">
            <span className="field__label">模式</span>
            <select
              className="field__select"
              value={mode}
              onChange={(e) => {
                const val = e.target.value;
                if (val !== "novel" && val !== "rp") return;
                setMode(val);
              }}
            >
              <option value="novel">小说创作</option>
              <option value="rp">RP 互动</option>
            </select>
          </label>
          {error !== null && <p className="modal__error">{error}</p>}
          <div className="modal__actions">
            <button
              type="button"
              className="btn"
              onClick={onClose}
              disabled={submitting}
            >
              取消
            </button>
            <button
              type="submit"
              className="btn btn--primary"
              disabled={submitting || displayName.trim().length === 0}
            >
              {submitting ? "创建中…" : "创建"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function OverviewView(): ReactNode {
  const {
    projects,
    activeProject,
    loading,
    error,
    fetchProjects,
    createProject,
    selectProject,
    deleteProject,
    clearError,
  } = useProjectStore();

  const [modalOpen, setModalOpen] = useState(false);

  const handleCreate = (displayName: string, mode: ProjectMode) => {
    void createProject(displayName, mode).then(() => {
      setModalOpen(false);
    });
  };

  const handleDelete = (id: string) => {
    if (window.confirm("确定删除该项目？此操作不可撤销。")) {
      void deleteProject(id).then(() => void fetchProjects());
    }
  };

  return (
    <section className="view overview">
      <header className="view__header">
        <h1 className="view__title">项目概览</h1>
        <button
          type="button"
          className="btn btn--primary"
          onClick={() => {
            clearError();
            setModalOpen(true);
          }}
        >
          + 新建项目
        </button>
      </header>

      {loading && projects.length === 0 && (
        <p className="overview__loading">加载中…</p>
      )}
      {error !== null && <p className="overview__error">出错了：{error}</p>}

      {!loading && projects.length === 0 && (
        <EmptyState onCreate={() => setModalOpen(true)} />
      )}

      {projects.length > 0 && (
        <div className="overview__grid">
          {projects.map((p) => (
            <ProjectCard
              key={p.id}
              id={p.id}
              displayName={p.display_name}
              mode={p.mode}
              active={activeProject?.id === p.id}
              onSelect={() => selectProject(p.id)}
              onDelete={() => handleDelete(p.id)}
            />
          ))}
        </div>
      )}

      <CreateProjectModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSubmit={handleCreate}
        submitting={loading}
        error={error}
      />
    </section>
  );
}
