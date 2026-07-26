/**
 * Inspector — right-side collapsible context panel.
 *
 * Renders a context body per active view (multi-level
 * nav + per-view inspector context):
 *   workflow  → selected node detail (Name/Task/permissions)
 *   chat      → director reasoning trace (last director message + branch)
 *   resources → git diff summary (last commit sha + message)
 *   config    → field hints (per-field guidance)
 *   novel     → chapter meta (filename/number/size)
 *   rp        → state/dice log (RP action log tail)
 *   run       → job logs (live round log tail)
 *   overview  → project meta
 *
 * The Inspector subscribes to the relevant stores to surface live state.
 * Width + collapsed state are owned by App.tsx (localStorage persistence).
 */

import { type ReactNode } from "react";
import type { NavTabId } from "@/components/NavRail";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useChatStore } from "@/stores/chatStore";
import { useResourceStore } from "@/stores/resourceStore";
import { useNovelStore } from "@/stores/novelStore";
import { useRunStore } from "@/stores/runStore";
import { useProjectStore } from "@/stores/projectStore";

interface InspectorProps {
  activeView: NavTabId;
  collapsed: boolean;
  width: number;
  onToggleCollapse: () => void;
}

function Section({ title, children }: { title: string; children: ReactNode }): ReactNode {
  return (
    <div className="inspector__section">
      <h4 className="inspector__section-title">{title}</h4>
      <div className="inspector__section-body">{children}</div>
    </div>
  );
}

function Empty({ hint }: { hint: string }): ReactNode {
  return <p className="overview__empty-hint">{hint}</p>;
}

function WorkflowContext(): ReactNode {
  const selected = useWorkflowStore((s) => s.selected);
  if (!selected) return <Empty hint="点击画布上的节点查看详情。" />;
  const a = selected.agent;
  return (
    <Section title={`节点 · ${selected.id}`}>
      {a ? (
        <dl className="inspector__dl">
          <dt>Agent</dt><dd>{a.name}</dd>
          <dt>Task</dt><dd>{a.task}</dd>
          <dt>Model</dt><dd>{a.model ?? "（默认）"}</dd>
          <dt>Permission.read</dt><dd>{a.permission.read?.join(", ") ?? "—"}</dd>
          <dt>Permission.write</dt><dd>{a.permission.write?.join(", ") ?? "—"}</dd>
          <dt>允许递归</dt><dd>{a.allow_recursive ? "是" : "否"}</dd>
        </dl>
      ) : (
        <Empty hint={`节点 ${selected.id} 引用的 Agent 未注册。`} />
      )}
    </Section>
  );
}

function ChatContext(): ReactNode {
  const messages = useChatStore((s) => s.messages);
  const lastBranch = useChatStore((s) => s.lastBranch);
  const lastDirector = [...messages].reverse().find((m) => m.role === "director");
  return (
    <Section title="Director 推理追踪">
      {lastDirector ? (
        <dl className="inspector__dl">
          <dt>最近回复</dt><dd>{lastDirector.content.slice(0, 200)}</dd>
          <dt>Turn</dt><dd>{lastDirector.turn_id}</dd>
          {lastBranch && <><dt>最新分支</dt><dd>{lastBranch}</dd></>}
        </dl>
      ) : (
        <Empty hint="尚无 Director 回复。" />
      )}
    </Section>
  );
}

function ResourceContext(): ReactNode {
  const activeType = useResourceStore((s) => s.activeType);
  const history = useResourceStore((s) => s.history);
  const lastCommit = history[0];
  return (
    <Section title={`资源 · ${activeType ?? "—"}`}>
      {lastCommit ? (
        <dl className="inspector__dl">
          <dt>最新提交</dt><dd><code>{lastCommit.sha.slice(0, 8)}</code></dd>
          <dt>消息</dt><dd>{lastCommit.message || lastCommit.turn_id}</dd>
          <dt>分支</dt><dd>{lastCommit.branch}</dd>
          <dt>历史长度</dt><dd>{history.length} 条</dd>
        </dl>
      ) : (
        <Empty hint="选择资源类型查看历史。" />
      )}
    </Section>
  );
}

const CONFIG_HINTS: Record<string, string> = {
  Name: "Agent 的唯一标识，与节点 id 对应。",
  Task: "该 Agent 的工作职责（运行时由 parser 注入 prompt）。",
  Model: "模型档位或具体模型名（留空使用全局默认）。",
  Tools: "逗号分隔的工具名（read / write / list_files / glob_files / grep_lines / read_lines）。",
  Permission: "hash<string, vector>，向量=资源目录名或文件名。",
  Input: "Agent 接收的输入描述（低频编辑）。",
  Output: "Agent 输出格式描述（低频编辑）。",
  "允许递归调用": "运行时允许该 Agent 被递归调用的开关。",
};

function ConfigContext(): ReactNode {
  return (
    <Section title="字段提示">
      <dl className="inspector__dl">
        {Object.entries(CONFIG_HINTS).map(([k, v]) => (
          <div key={k} className="inspector__dl-row">
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </Section>
  );
}

function NovelContext(): ReactNode {
  const active = useNovelStore((s) => s.active);
  const zoom = useNovelStore((s) => s.zoom);
  return (
    <Section title="章节元数据">
      {active ? (
        <dl className="inspector__dl">
          <dt>文件名</dt><dd>{active.filename}</dd>
          <dt>章号</dt><dd>{active.chapter_number ?? "—"}</dd>
          <dt>缩放</dt><dd>{Math.round(zoom * 100)}%</dd>
          <dt>字符数</dt><dd>{active.content.length}</dd>
        </dl>
      ) : (
        <Empty hint="选择一个章节查看元数据。" />
      )}
    </Section>
  );
}

function RpContext(): ReactNode {
  const messages = useChatStore((s) => s.messages);
  const recent = messages.slice(-5);
  return (
    <Section title="RP 状态 / 行动日志">
      {recent.length > 0 ? (
        <ul className="inspector__log">
          {recent.map((m) => (
            <li key={m.message_id} className="inspector__log-item">
              <span className="inspector__log-role">{m.role === "user" ? "玩家" : "Director"}</span>
              <span className="inspector__log-text">{m.content.slice(0, 80)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <Empty hint="尚无 RP 行动记录。" />
      )}
    </Section>
  );
}

function RunContext(): ReactNode {
  const round = useRunStore((s) => s.round);
  const lastLogs = round?.logs.slice(-8) ?? [];
  return (
    <Section title="作业日志（尾部）">
      {round ? (
        <>
          <dl className="inspector__dl">
            <dt>回合</dt><dd><code>{round.round_id}</code></dd>
            <dt>状态</dt><dd>{round.state}</dd>
          </dl>
          <ul className="inspector__log">
            {lastLogs.map((line, i) => (
              <li key={i} className="inspector__log-text">{line}</li>
            ))}
          </ul>
        </>
      ) : (
        <Empty hint="尚未启动回合。" />
      )}
    </Section>
  );
}

function OverviewContext(): ReactNode {
  const active = useProjectStore((s) => s.activeProject);
  const count = useProjectStore((s) => s.projects.length);
  return (
    <Section title="项目元数据">
      {active ? (
        <dl className="inspector__dl">
          <dt>显示名</dt><dd>{active.display_name}</dd>
          <dt>项目 ID</dt><dd><code>{active.id}</code></dd>
          <dt>模式</dt><dd>{active.mode === "novel" ? "小说" : "RP"}</dd>
          <dt>项目总数</dt><dd>{count}</dd>
        </dl>
      ) : (
        <Empty hint="尚未选择项目。" />
      )}
    </Section>
  );
}

const CONTEXTS: Record<NavTabId, () => ReactNode> = {
  overview: OverviewContext,
  workflow: WorkflowContext,
  chat: ChatContext,
  resources: ResourceContext,
  config: ConfigContext,
  novel: NovelContext,
  rp: RpContext,
  run: RunContext,
};

const CONTEXT_TITLES: Record<NavTabId, string> = {
  overview: "项目",
  workflow: "节点详情",
  chat: "Director 推理",
  resources: "Git Diff",
  config: "字段提示",
  novel: "章节元数据",
  rp: "状态 / 骰子",
  run: "作业日志",
};

export default function Inspector({
  activeView,
  collapsed,
  width,
  onToggleCollapse,
}: InspectorProps): ReactNode {
  const Body = CONTEXTS[activeView];
  return (
    <aside
      className={`inspector${collapsed ? " inspector--collapsed" : ""}`}
      aria-label="检查器"
      style={collapsed ? undefined : { flexBasis: `${width}px`, width: `${width}px` }}
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
          <h3 className="inspector__title">{CONTEXT_TITLES[activeView]}</h3>
          <Body />
        </div>
      )}
    </aside>
  );
}
