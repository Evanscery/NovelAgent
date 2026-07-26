/**
 * Zustand store for the workflow canvas + run panel.
 *
 * Holds the user-editable CanvasGraph (nodes/wires) for the active project
 * and exposes actions to load it from the backend, mutate it, export/import
 * JSON, and persist per-agent attribute edits. The canvas graph is loaded
 * from GET /api/workflow/{id}/canvas (the real workflow.yaml shape) and
 * saved back via PUT .../canvas; agent attribute sets are loaded from
 * GET /api/config/{id}/agents for the node side panel.
 *
 * The canvas is comfy-UI-like, nodes/wires/
 * JSON-export. The canvas saves CONFIG (agent attribute
 * sets), NOT prompts — the parser generates prompts at runtime.
 */

import { create } from "zustand";
import {
  api as defaultApi,
  type AgentConfigResponse,
  type ApiClient,
  type CanvasGraphData,
  type CanvasNodeData,
  type CanvasWireData,
  type PutAgentConfigRequest,
} from "@/api/client";
import { apiErrorMessage } from "@/api/errors";
import { canvasGraphDataSchema } from "@/schemas/canvasGraph";

export type { CanvasGraphData, CanvasNodeData, CanvasWireData };

/** A node selected for side-panel editing. */
export interface SelectedNode {
  id: string;
  /** The agent attribute set loaded from /api/config/{id}/agents, or null
   * if the agent name is not yet registered (user-typed). */
  agent: AgentConfigResponse | null;
}

export interface WorkflowStoreState {
  projectId: string | null;
  canvas: CanvasGraphData;
  agents: AgentConfigResponse[];
  selected: SelectedNode | null;
  loading: boolean;
  saving: boolean;
  error: string | null;
  dirty: boolean;

  load: (projectId: string) => Promise<void>;
  selectNode: (nodeId: string) => void;
  clearSelection: () => void;
  addNode: (node: CanvasNodeData) => void;
  updateNode: (id: string, patch: Partial<CanvasNodeData>) => void;
  removeNode: (id: string) => void;
  addWire: (wire: CanvasWireData) => void;
  removeWire: (from: string, to: string) => void;
  exportJson: () => string;
  importJson: (raw: string) => void;
  saveCanvas: () => Promise<void>;
  saveAgent: (name: string, data: PutAgentConfigRequest) => Promise<void>;
  clearError: () => void;
}

const EMPTY_CANVAS: CanvasGraphData = { nodes: [], wires: [] };

export function createWorkflowStore(apiClient: ApiClient = defaultApi) {
  return create<WorkflowStoreState>((set, get) => ({
    projectId: null,
    canvas: EMPTY_CANVAS,
    agents: [],
    selected: null,
    loading: false,
    saving: false,
    error: null,
    dirty: false,

    async load(projectId) {
      set({ loading: true, error: null, projectId });
      try {
        // The canvas endpoint returns the REAL graph a round would run
        // (workflow.yaml or the shipped default); the agent list feeds
        // the node side panel for attribute editing.
        const [canvas, agents] = await Promise.all([
          apiClient.getCanvas(projectId),
          apiClient.getAgents(projectId),
        ]);
        set({
          canvas,
          agents,
          loading: false,
          dirty: false,
        });
      } catch (e) {
        set({ loading: false, error: apiErrorMessage(e) });
      }
    },

    selectNode(nodeId) {
      const node = get().canvas.nodes.find((n) => n.id === nodeId);
      if (!node) return;
      const agent = get().agents.find((a) => a.name === node.agent_name) ?? null;
      set({ selected: { id: nodeId, agent } });
    },

    clearSelection() {
      set({ selected: null });
    },

    addNode(node) {
      set((s) => ({
        canvas: { ...s.canvas, nodes: [...s.canvas.nodes, node] },
        dirty: true,
      }));
    },

    updateNode(id, patch) {
      set((s) => ({
        canvas: {
          ...s.canvas,
          nodes: s.canvas.nodes.map((n) => (n.id === id ? { ...n, ...patch } : n)),
        },
        dirty: true,
      }));
    },

    removeNode(id) {
      set((s) => ({
        canvas: {
          nodes: s.canvas.nodes.filter((n) => n.id !== id),
          wires: s.canvas.wires.filter((w) => w.from_node !== id && w.to_node !== id),
        },
        dirty: true,
        selected: s.selected?.id === id ? null : s.selected,
      }));
    },

    addWire(wire) {
      set((s) => {
        if (s.canvas.wires.some(
          (w) => w.from_node === wire.from_node && w.to_node === wire.to_node,
        )) {
          return s;
        }
        return { canvas: { ...s.canvas, wires: [...s.canvas.wires, wire] }, dirty: true };
      });
    },

    removeWire(from, to) {
      set((s) => ({
        canvas: {
          ...s.canvas,
          wires: s.canvas.wires.filter(
            (w) => !(w.from_node === from && w.to_node === to),
          ),
        },
        dirty: true,
      }));
    },

    exportJson() {
      return JSON.stringify(get().canvas, null, 2);
    },

    importJson(raw) {
      const parsed = canvasGraphDataSchema.parse(JSON.parse(raw));
      set({ canvas: parsed, dirty: true });
    },

    async saveCanvas() {
      const pid = get().projectId;
      if (!pid) return;
      set({ saving: true, error: null });
      try {
        const canvas = await apiClient.putCanvas(pid, get().canvas);
        set({ canvas, saving: false, dirty: false });
      } catch (e) {
        set({ saving: false, error: apiErrorMessage(e) });
      }
    },

    async saveAgent(name, data) {
      const pid = get().projectId;
      if (!pid) return;
      set({ saving: true, error: null });
      try {
        await apiClient.putAgent(pid, name, data);
        const agents = await apiClient.getAgents(pid);
        set({ agents, saving: false });
      } catch (e) {
        set({ saving: false, error: apiErrorMessage(e) });
      }
    },

    clearError() {
      set({ error: null });
    },
  }));
}

export const useWorkflowStore = createWorkflowStore();
