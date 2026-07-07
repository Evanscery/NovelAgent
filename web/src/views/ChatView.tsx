/**
 * ChatView — director chat (todo 28, guide:410-413).
 *
 * Message list (user + director), input box, send button. Each message
 * has a delete button (DELETE /api/chat/{id}/{mid} → backend rolls back
 * a git Turn and returns the surviving messages) and a retry button
 * (POST .../retry → rolls back + re-runs, returns the new exchange).
 * Messages render markdown via marked. Per guide:413 default user only
 * chats with the director.
 */

import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { marked } from "marked";
import { useChatStore } from "@/stores/chatStore";
import { useProjectStore } from "@/stores/projectStore";
import type { ChatMessage } from "@/api/client";

marked.setOptions({ breaks: true, gfm: true });

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderMarkdown(content: string): string {
  // marked output is sanitized at the markdown level (no raw html passthrough
  // in default gfm). Escape any pre-existing html before parsing to be safe.
  return marked.parse(escapeHtml(content)) as string;
}

function MessageBubble({
  msg,
  onDelete,
  onRetry,
  busy,
}: {
  msg: ChatMessage;
  onDelete: () => void;
  onRetry: () => void;
  busy: boolean;
}): ReactNode {
  const isUser = msg.role === "user";
  const html = useMemo(() => renderMarkdown(msg.content), [msg.content]);
  return (
    <article className={`chat-msg chat-msg--${msg.role}`}>
      <header className="chat-msg__head">
        <span className="chat-msg__role">
          {isUser ? "你" : msg.role === "director" ? "Director" : "系统"}
        </span>
        <span className="chat-msg__turn">{msg.turn_id}</span>
        <span className="chat-msg__actions">
          {isUser && (
            <>
              <button
                type="button"
                className="btn btn--sm"
                onClick={onRetry}
                disabled={busy}
                title="从此消息重发（后端会回滚后重跑）"
              >
                重发
              </button>
              <button
                type="button"
                className="btn btn--sm btn--danger"
                onClick={onDelete}
                disabled={busy}
                title="删除此消息并回滚到该消息之前"
              >
                删除
              </button>
            </>
          )}
        </span>
      </header>
      <div
        className="chat-msg__body markdown"
        // marked output is escaped-then-parsed; safe per our escapeHtml wrap.
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </article>
  );
}

export default function ChatView(): ReactNode {
  const {
    messages,
    loading,
    sending,
    error,
    load,
    send,
    remove,
    retry,
    clearError,
  } = useChatStore();
  const activeProject = useProjectStore((s) => s.activeProject);
  const projectId = useChatStore((s) => s.projectId);
  const [text, setText] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (activeProject && activeProject.id !== projectId) {
      void load(activeProject.id);
    }
  }, [activeProject, projectId, load]);

  useEffect(() => {
    const el = listRef.current;
    if (el && typeof el.scrollTo === "function") {
      el.scrollTo({ top: el.scrollHeight });
    }
  }, [messages.length]);

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (text.trim().length === 0) return;
    const payload = text;
    setText("");
    void send(payload);
  };

  return (
    <section className="view chat-view">
      <header className="view__header">
        <h1 className="view__title">Director 对话</h1>
        {activeProject && (
          <button
            type="button"
            className="btn"
            onClick={() => void load(activeProject.id)}
            disabled={loading}
          >
            {loading ? "加载中…" : "刷新"}
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

      <div className="chat-view__list" ref={listRef}>
        {!loading && messages.length === 0 && (
          <p className="overview__empty-hint">还没有对话。在下方输入消息开始与 Director 交流。</p>
        )}
        {messages.map((m) => (
          <MessageBubble
            key={m.message_id}
            msg={m}
            busy={sending}
            onDelete={() => void remove(m.message_id)}
            onRetry={() => void retry(m.message_id)}
          />
        ))}
      </div>

      <form className="chat-view__input" onSubmit={handleSubmit}>
        <textarea
          className="field__input chat-view__textarea"
          placeholder="输入消息…（Enter 发送，Shift+Enter 换行）"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (text.trim().length > 0 && !sending) {
                const payload = text;
                setText("");
                void send(payload);
              }
            }
          }}
          rows={2}
          disabled={sending}
        />
        <button
          type="submit"
          className="btn btn--primary"
          disabled={sending || text.trim().length === 0}
        >
          {sending ? "发送中…" : "发送"}
        </button>
      </form>
    </section>
  );
}
