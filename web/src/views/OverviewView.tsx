/**
 * OverviewView — project hub.
 * 默认傻瓜式, 面向零技术用户.
 * Lists existing projects as cards, "新建项目" button opens a modal with
 * display_name + mode select. Empty state when no projects.
 */

import { type ChangeEvent, type FormEvent, type ReactNode, useRef, useState } from "react";
import { useProjectStore } from "@/stores/projectStore";
import { api, type ProjectMode } from "@/api/client";
import { apiErrorMessage } from "@/api/errors";

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

function ImportCardModal({
  open,
  onClose,
  onImported,
}: {
  open: boolean;
  onClose: () => void;
  onImported: () => void;
}): ReactNode {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [card, setCard] = useState<Record<string, unknown> | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [mode, setMode] = useState<"" | ProjectMode>("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const handleFile = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setError(null);
    file
      .text()
      .then((raw) => {
        const parsed: unknown = JSON.parse(raw);
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
          throw new Error("角色卡必须是 JSON 对象");
        }
        setCard(parsed as Record<string, unknown>);
        setFileName(file.name);
      })
      .catch((err: unknown) => {
        setCard(null);
        setFileName(null);
        setError(`解析失败：${apiErrorMessage(err)}`);
      });
  };

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!card || submitting) return;
    setSubmitting(true);
    setError(null);
    api
      .postImport({
        card,
        ...(displayName.trim().length > 0 ? { display_name: displayName.trim() } : {}),
        ...(mode !== "" ? { mode } : {}),
      })
      .then((res) => {
        setSubmitting(false);
        window.alert(
          `导入成功：${res.display_name}（${res.mode === "novel" ? "小说" : "RP"}）\n` +
            `创建资源：${res.resources_created.length > 0 ? res.resources_created.join("、") : "无"}`,
        );
        setCard(null);
        setFileName(null);
        setDisplayName("");
        setMode("");
        onImported();
        onClose();
      })
      .catch((err: unknown) => {
        setSubmitting(false);
        setError(apiErrorMessage(err));
      });
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-card-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="import-card-title" className="modal__title">
          导入角色卡
        </h2>
        <form className="modal__form" onSubmit={handleSubmit}>
          <div className="field">
            <span className="field__label">角色卡文件（.json）</span>
            <button
              type="button"
              className="btn"
              onClick={() => fileInputRef.current?.click()}
              disabled={submitting}
            >
              {fileName ?? "选择文件…"}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="application/json,.json"
              onChange={handleFile}
              style={{ display: "none" }}
            />
          </div>
          <label className="field">
            <span className="field__label">显示名（可选，默认取卡名）</span>
            <input
              type="text"
              className="field__input"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="留空使用角色卡名称"
            />
          </label>
          <label className="field">
            <span className="field__label">模式（可选，默认按卡推荐）</span>
            <select
              className="field__select"
              value={mode}
              onChange={(e) => {
                const val = e.target.value;
                if (val !== "" && val !== "novel" && val !== "rp") return;
                setMode(val);
              }}
            >
              <option value="">自动（推荐模式）</option>
              <option value="novel">小说创作</option>
              <option value="rp">RP 互动</option>
            </select>
          </label>
          {error !== null && <p className="modal__error">{error}</p>}
          <div className="modal__actions">
            <button type="button" className="btn" onClick={onClose} disabled={submitting}>
              取消
            </button>
            <button
              type="submit"
              className="btn btn--primary"
              disabled={submitting || card === null}
            >
              {submitting ? "导入中…" : "导入"}
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
  const [importOpen, setImportOpen] = useState(false);

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
        <button
          type="button"
          className="btn"
          onClick={() => setImportOpen(true)}
        >
          导入角色卡
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
      <ImportCardModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={() => void fetchProjects()}
      />
    </section>
  );
}
