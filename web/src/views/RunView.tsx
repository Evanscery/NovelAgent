/**
 * RunView — workflow run panel (todo 32, guide:352-353).
 *
 * "开始一轮" button (POST /api/workflow/{id}/run). Polls the round
 * status (GET /api/workflow/{id}/round/{rid}) every 1.5s while the
 * round is pending/running. Live logs. Stop button (POST .../stop).
 */

import { useEffect, useRef, type ReactNode } from "react";
import { useRunStore } from "@/stores/runStore";
import { useProjectStore } from "@/stores/projectStore";

const POLL_MS = 1500;

function StateBadge({ state }: { state: string }): ReactNode {
  const cls = `run-state run-state--${state}`;
  const label = {
    pending: "等待",
    running: "运行中",
    completed: "完成",
    failed: "失败",
  }[state] ?? state;
  return <span className={cls}>{label}</span>;
}

export default function RunView(): ReactNode {
  const {
    round,
    starting,
    stopping,
    error,
    polling,
    startRound,
    refresh,
    stop,
    setPolling,
    clearError,
  } = useRunStore();
  const activeProject = useProjectStore((s) => s.activeProject);
  const projectId = useProjectStore((s) => s.activeProject?.id ?? null);
  const logRef = useRef<HTMLDivElement>(null);

  const isTerminal = round?.state === "completed" || round?.state === "failed";
  const shouldPoll = polling && !isTerminal && round !== null;

  useEffect(() => {
    if (!shouldPoll) return;
    const handle = window.setInterval(() => {
      void refresh();
    }, POLL_MS);
    return () => window.clearInterval(handle);
  }, [shouldPoll, refresh]);

  useEffect(() => {
    const el = logRef.current;
    // Guard: some environments (jsdom) don't implement Element.scrollTo.
    if (el && typeof el.scrollTo === "function") {
      el.scrollTo({ top: el.scrollHeight });
    }
  }, [round?.logs.length]);

  const handleStart = () => {
    if (!projectId) return;
    setPolling(true);
    void startRound(projectId);
  };

  const handleStop = () => {
    if (!projectId) return;
    void stop(projectId).finally(() => {
      void refresh();
    });
  };

  return (
    <section className="view run-view">
      <header className="view__header">
        <h1 className="view__title">运行面板</h1>
        <div className="view__actions">
          <button
            type="button"
            className="btn btn--primary"
            onClick={handleStart}
            disabled={starting || !activeProject || (round !== null && !isTerminal)}
          >
            {starting ? "启动中…" : "开始一轮"}
          </button>
          <button
            type="button"
            className="btn btn--danger"
            onClick={handleStop}
            disabled={stopping || !round || isTerminal}
          >
            {stopping ? "停止中…" : "停止"}
          </button>
        </div>
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
        <div className="run-view__body">
          {round && (
            <>
              <div className="run-view__status">
                <span className="run-view__label">回合：</span>
                <code className="run-view__round-id">{round.round_id}</code>
                <StateBadge state={round.state} />
                {round.result && (
                  <span className="run-view__summary">
                    {round.result.completed_agents.length} agents · {round.result.finalize_reason} ·{" "}
                    {round.result.total_tokens} tokens
                  </span>
                )}
              </div>
              {round.error && (
                <p className="overview__error">{round.error}</p>
              )}
              <div className="run-view__logs" ref={logRef}>
                <h3 className="view__title">实时日志</h3>
                {round.logs.length === 0 ? (
                  <p className="overview__empty-hint">暂无日志。</p>
                ) : (
                  <pre className="run-view__log-pre">{round.logs.join("\n")}</pre>
                )}
              </div>
            </>
          )}
          {!round && (
            <p className="overview__empty-hint">
              点击「开始一轮」启动一个工作流回合。默认使用 Mock runner（不消耗 LLM 配额）。
            </p>
          )}
        </div>
      )}
    </section>
  );
}
