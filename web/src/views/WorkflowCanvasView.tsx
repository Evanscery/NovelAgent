/**
 * WorkflowCanvasView — Comfy-UI-like canvas.
 *
 * Nodes = agents from the registry; edges = wires with repeat_count labels.
 * Drag-to-create edge (react-flow onConnect), click node to open the side
 * panel for editing the agent's attribute set (Name/Task/Model/
 * Tools/Permission/Input/Output/allow_recursive + head/tail in expert
 * mode). Export/import JSON. Save posts per-agent
 * to PUT /api/config/{projectId}/agents/{name}. The canvas does NOT execute
 * the workflow — that is RunView.
 */

import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  Background,
  Controls,
  ReactFlow,
  addEdge,
  type Connection,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type OnConnect,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect } from "react";
import { useWorkflowStore, type CanvasWireData } from "@/stores/workflowStore";
import { useProjectStore } from "@/stores/projectStore";
import type { AgentConfigResponse, PutAgentConfigRequest } from "@/api/client";
import AgentNode from "@/components/AgentNode";

const NODE_TYPES = { agent: AgentNode } as const;

function toFlowNodes(
  canvas: { nodes: { id: string; agent_name: string; description: string }[] },
): Node[] {
  return canvas.nodes.map((n, i) => {
    const col = i % 3;
    const row = Math.floor(i / 3);
    return {
      id: n.id,
      type: "agent",
      position: { x: 80 + col * 240, y: 60 + row * 140 },
      data: { agentName: n.agent_name, description: n.description },
    };
  });
}

function toFlowEdges(canvas: { wires: CanvasWireData[] }): Edge[] {
  return canvas.wires.map((w, i) => ({
    id: `e${i}-${w.from_node}-${w.to_node}`,
    source: w.from_node,
    target: w.to_node,
    label: w.repeat_count > 1 ? `×${w.repeat_count}` : undefined,
    animated: w.repeat_count > 1,
  }));
}

function AgentEditForm({
  agent,
  onSave,
  saving,
}: {
  agent: AgentConfigResponse;
  onSave: (data: PutAgentConfigRequest) => void;
  saving: boolean;
}): ReactNode {
  const [form, setForm] = useState<PutAgentConfigRequest>({ ...agent });
  const [expert, setExpert] = useState(false);

  const set = <K extends keyof PutAgentConfigRequest>(
    key: K,
    value: PutAgentConfigRequest[K],
  ): void => {
    setForm((f) => ({ ...f, [key]: value }));
  };

  const setPerm = (action: string, raw: string) => {
    const vector = raw.split(",").map((s) => s.trim()).filter(Boolean);
    setForm((f) => ({ ...f, permission: { ...f.permission, [action]: vector } }));
  };

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    onSave(form);
  };

  return (
    <form className="agent-form" onSubmit={handleSubmit}>
      <label className="field">
        <span className="field__label">Name</span>
        <input
          className="field__input"
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
          required
        />
      </label>
      <label className="field">
        <span className="field__label">Task</span>
        <textarea
          className="field__input"
          rows={3}
          value={form.task}
          onChange={(e) => set("task", e.target.value)}
          required
        />
      </label>
      <label className="field">
        <span className="field__label">Model</span>
        <input
          className="field__input"
          value={form.model ?? ""}
          onChange={(e) => set("model", e.target.value || null)}
          placeholder="（使用全局默认）"
        />
      </label>
      <label className="field">
        <span className="field__label">Tools (逗号分隔)</span>
        <input
          className="field__input"
          value={form.tools.join(", ")}
          onChange={(e) =>
            set("tools", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))
          }
        />
      </label>
      <label className="field">
        <span className="field__label">Permission.read</span>
        <input
          className="field__input"
          value={form.permission.read?.join(", ") ?? ""}
          onChange={(e) => setPerm("read", e.target.value)}
          placeholder="state, outline, ..."
        />
      </label>
      <label className="field">
        <span className="field__label">Permission.write</span>
        <input
          className="field__input"
          value={form.permission.write?.join(", ") ?? ""}
          onChange={(e) => setPerm("write", e.target.value)}
          placeholder="notes, short_goal, ..."
        />
      </label>
      <label className="field">
        <span className="field__label">Input</span>
        <input
          className="field__input"
          value={form.input}
          onChange={(e) => set("input", e.target.value)}
        />
      </label>
      <label className="field">
        <span className="field__label">Output</span>
        <input
          className="field__input"
          value={form.output}
          onChange={(e) => set("output", e.target.value)}
        />
      </label>
      <label className="field field--checkbox">
        <input
          type="checkbox"
          checked={form.allow_recursive}
          onChange={(e) => set("allow_recursive", e.target.checked)}
        />
        <span className="field__label">允许递归调用</span>
      </label>
      <label className="field field--checkbox">
        <input
          type="checkbox"
          checked={expert}
          onChange={(e) => setExpert(e.target.checked)}
        />
        <span className="field__label">专家模式（head/tail）</span>
      </label>
      {expert && (
        <>
          <label className="field">
            <span className="field__label">Head</span>
            <textarea
              className="field__input"
              rows={2}
              value={form.head ?? ""}
              onChange={(e) => set("head", e.target.value || null)}
            />
          </label>
          <label className="field">
            <span className="field__label">Tail</span>
            <textarea
              className="field__input"
              rows={2}
              value={form.tail ?? ""}
              onChange={(e) => set("tail", e.target.value || null)}
            />
          </label>
        </>
      )}
      <div className="agent-form__actions">
        <button type="submit" className="btn btn--primary" disabled={saving}>
          {saving ? "保存中…" : "保存 Agent"}
        </button>
      </div>
    </form>
  );
}

export default function WorkflowCanvasView(): ReactNode {
  const {
    canvas,
    selected,
    loading,
    saving,
    error,
    dirty,
    load,
    selectNode,
    clearSelection,
    addWire,
    saveAgent,
  } = useWorkflowStore();

  const activeProject = useProjectStore((s) => s.activeProject);
  const projectId = useWorkflowStore((s) => s.projectId);
  useEffect(() => {
    if (activeProject && activeProject.id !== projectId) {
      void load(activeProject.id);
    }
  }, [activeProject, projectId, load]);

  const initialNodes = useMemo(() => toFlowNodes(canvas), [canvas]);
  const initialEdges = useMemo(() => toFlowEdges(canvas), [canvas]);
  const [nodes, setNodes] = useState<Node[]>(initialNodes);
  const [edges, setEdges] = useState<Edge[]>(initialEdges);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Re-sync local react-flow state when the store canvas changes (load/import).
  useMemo(() => {
    setNodes(toFlowNodes(canvas));
    setEdges(toFlowEdges(canvas));
  }, [canvas]);

  const onConnect: OnConnect = useCallback(
    (conn: Connection) => {
      if (!conn.source || !conn.target) return;
      addWire({ from_node: conn.source, to_node: conn.target, repeat_count: 1 });
      setEdges((eds) => addEdge(conn, eds));
    },
    [addWire],
  );

  const onNodeClick: NodeMouseHandler = useCallback(
    (_e, node) => selectNode(node.id),
    [selectNode],
  );

  const handleLoad = () => {
    if (projectId) void load(projectId);
  };

  const handleExport = () => {
    const blob = new Blob([JSON.stringify(canvas, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "workflow.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    file.text().then((raw) => {
      try {
        useWorkflowStore.getState().importJson(raw);
      } catch (err) {
        window.alert(`导入失败：${err instanceof Error ? err.message : String(err)}`);
      }
    }).catch(() => {
      // ignore read errors
    });
    e.target.value = "";
  };

  return (
    <section className="view workflow-view">
      <header className="view__header">
        <h1 className="view__title">工作流画布</h1>
        <div className="view__actions">
          <button type="button" className="btn" onClick={handleLoad} disabled={loading || !projectId}>
            {loading ? "加载中…" : "重新加载"}
          </button>
          <button type="button" className="btn" onClick={handleExport} disabled={canvas.nodes.length === 0}>
            导出 JSON
          </button>
          <button type="button" className="btn" onClick={() => fileInputRef.current?.click()}>
            导入 JSON
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json,.json"
            onChange={handleImport}
            style={{ display: "none" }}
          />
        </div>
      </header>

      {error !== null && <p className="overview__error">出错了：{error}</p>}
      {dirty && <p className="overview__loading">有未保存的更改（保存各 Agent 配置即生效）。</p>}

      <div className="workflow-view__body">
        <div className="workflow-view__canvas">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onPaneClick={clearSelection}
            fitView
          >
            <Background />
            <Controls />
          </ReactFlow>
        </div>
        <aside className="workflow-view__side">
          <h2 className="view__title">节点详情</h2>
          {!selected && <p className="overview__loading">点击节点以编辑 Agent 配置。</p>}
          {selected && !selected.agent && (
            <p className="overview__loading">
              节点 <code>{selected.id}</code> 引用的 Agent 未在注册表中。
            </p>
          )}
          {selected?.agent && (
            <AgentEditForm
              agent={selected.agent}
              saving={saving}
              onSave={(data) => void saveAgent(selected.agent!.name, data)}
            />
          )}
        </aside>
      </div>
    </section>
  );
}
