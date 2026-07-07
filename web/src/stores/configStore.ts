/**
 * Zustand store for the centralized config page (todo 30, guide:362-384).
 *
 * Holds the project's merged config + per-agent list. Save posts to
 * PUT /api/config/{project_id} (project config) + PUT /api/config/{id}/
 * agents/{name} (per-agent). Expert mode toggle is pure UI state (not
 * persisted server-side) per guide:354-355.
 */

import { create } from "zustand";
import {
  api as defaultApi,
  type AgentConfigResponse,
  type ApiClient,
  type ConfigResponse,
  type ProjectMode,
  type PutAgentConfigRequest,
  type PutProjectConfigRequest,
} from "@/api/client";

export interface ConfigStoreState {
  projectId: string | null;
  config: ConfigResponse | null;
  agents: AgentConfigResponse[];
  expertMode: boolean;
  loading: boolean;
  saving: boolean;
  error: string | null;

  load: (projectId: string) => Promise<void>;
  setExpertMode: (on: boolean) => void;
  saveProjectConfig: (data: PutProjectConfigRequest) => Promise<void>;
  saveAgent: (name: string, data: PutAgentConfigRequest) => Promise<void>;
  clearError: () => void;
}

export function createConfigStore(apiClient: ApiClient = defaultApi) {
  return create<ConfigStoreState>((set, get) => ({
    projectId: null,
    config: null,
    agents: [],
    expertMode: false,
    loading: false,
    saving: false,
    error: null,

    async load(projectId) {
      set({ loading: true, error: null, projectId });
      try {
        const [config, agents] = await Promise.all([
          apiClient.getProjectConfig(projectId),
          apiClient.getAgents(projectId),
        ]);
        set({ config, agents, loading: false });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        set({ loading: false, error: msg });
      }
    },

    setExpertMode(on) {
      set({ expertMode: on });
    },

    async saveProjectConfig(data) {
      const pid = get().projectId;
      if (!pid) return;
      set({ saving: true, error: null });
      try {
        const config = await apiClient.putProjectConfig(pid, data);
        set({ config, saving: false });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        set({ saving: false, error: msg });
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
        const msg = e instanceof Error ? e.message : String(e);
        set({ saving: false, error: msg });
      }
    },

    clearError() {
      set({ error: null });
    },
  }));
}

export const useConfigStore = createConfigStore();

/** Provider type options per guide:366. */
export const PROVIDER_TYPES = [
  "openai_compatible",
  "openai_response",
  "anthropic",
] as const;
export type ProviderType = (typeof PROVIDER_TYPES)[number];

/** Model tier options per guide:366. */
export const MODEL_TIERS = ["premium", "standard", "cheap"] as const;
export type ModelTier = (typeof MODEL_TIERS)[number];

export type { ProjectMode };
