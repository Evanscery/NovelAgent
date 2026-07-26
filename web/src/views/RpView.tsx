/**
 * RpView — RP dynamic front.
 *
 * Deliberately SIMPLE for now — basic RP action input
 * that sends to the director via POST /api/chat/{projectId}. The
 * card-bound front rendering (regex→html) lives in the compat layer
 * and is not wired into this view yet. The action input + last
 * director response are owned by
 * rpStore; the full chat log (for the running RP history) is read
 * from chatStore so RP actions and regular chat share one backend
 * log.
 */

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useRpStore } from "@/stores/rpStore";
import { useChatStore } from "@/stores/chatStore";
import { useProjectStore } from "@/stores/projectStore";

export default function RpView(): ReactNode {
  const {
    action,
    response,
    sending,
    error: rpError,
    setAction,
    send: sendRp,
    clearError: clearRpError,
  } = useRpStore();
  const {
    messages,
    sending: chatSending,
    error: chatError,
    load,
    clearError: clearChatError,
  } = useChatStore();
  const activeProject = useProjectStore((s) => s.activeProject);
  const chatProjectId = useChatStore((s) => s.projectId);
  const [loadedProject, setLoadedProject] = useState<string | null>(null);

  useEffect(() => {
    if (activeProject && activeProject.id !== chatProjectId) {
      void load(activeProject.id);
    }
    if (activeProject && activeProject.id !== loadedProject) {
      setLoadedProject(activeProject.id);
    }
  }, [activeProject, chatProjectId, loadedProject, load]);

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!activeProject || action.trim().length === 0) return;
    void sendRp(activeProject.id, action);
  };

  const busy = sending || chatSending;

  return (
    <section className="view rp-view">
      <header className="view__header">
        <h1 className="view__title">RP 互动</h1>
        {activeProject && (
          <button
            type="button"
            className="btn"
            onClick={() => void load(activeProject.id)}
            disabled={busy}
          >
            刷新
          </button>
        )}
      </header>

      <p className="overview__empty-hint">
        输入玩家行动，Director 将推进一回合。卡片绑定前端渲染（regex→html）将在兼容层完成。
      </p>

      {rpError !== null && (
        <p className="overview__error">
          出错了：{rpError}
          <button type="button" className="btn btn--sm" onClick={clearRpError}>
            关闭
          </button>
        </p>
      )}
      {chatError !== null && (
        <p className="overview__error">
          出错了：{chatError}
          <button type="button" className="btn btn--sm" onClick={clearChatError}>
            关闭
          </button>
        </p>
      )}

      {!activeProject && <p className="overview__empty-hint">请先在概览页选择一个项目。</p>}

      {activeProject && (
        <>
          <div className="rp-view__log">
            {messages.length === 0 && response === null && (
              <p className="overview__empty-hint">还没有 RP 记录。</p>
            )}
            {messages.map((m) => (
              <article key={m.message_id} className={`chat-msg chat-msg--${m.role}`}>
                <header className="chat-msg__head">
                  <span className="chat-msg__role">
                    {m.role === "user" ? "玩家" : m.role === "director" ? "Director" : "系统"}
                  </span>
                  <span className="chat-msg__turn">{m.turn_id}</span>
                </header>
                <div className="chat-msg__body">{m.content}</div>
              </article>
            ))}
          </div>

          <form className="chat-view__input rp-view__input" onSubmit={handleSubmit}>
            <textarea
              className="field__input chat-view__textarea"
              placeholder="描述玩家行动…"
              value={action}
              onChange={(e) => setAction(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  if (action.trim().length > 0 && !busy && activeProject) {
                    void sendRp(activeProject.id, action);
                  }
                }
              }}
              rows={3}
              disabled={busy}
            />
            <button
              type="submit"
              className="btn btn--primary"
              disabled={busy || action.trim().length === 0}
            >
              {busy ? "提交中…" : "提交行动"}
            </button>
          </form>
        </>
      )}
    </section>
  );
}
