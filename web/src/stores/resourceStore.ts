/**
 * Zustand store for the per-type resource editor (todo 29, guide:386-400).
 *
 * Holds the active resource type's content + history + list of all 8 types.
 * Wraps /api/resources. Per guide:210-211 the variables type is read-only
 * (the backend PUT refuses it; the store surfaces read_only from the GET
 * response so the UI can disable the editor).
 */

import { create } from "zustand";
import {
  api as defaultApi,
  type ApiClient,
  type ResourceContentResponse,
  type ResourceHistoryEntry,
  type ResourceListEntry,
} from "@/api/client";

export interface ResourceStoreState {
  projectId: string | null;
  types: ResourceListEntry[];
  activeType: string | null;
  content: ResourceContentResponse | null;
  history: ResourceHistoryEntry[];
  loading: boolean;
  saving: boolean;
  error: string | null;
  dirty: boolean;

  loadTypes: (projectId: string) => Promise<void>;
  selectType: (projectId: string, type: string) => Promise<void>;
  save: (content: string, filename?: string) => Promise<void>;
  setLocalContent: (content: string) => void;
  clearError: () => void;
}

export function createResourceStore(apiClient: ApiClient = defaultApi) {
  return create<ResourceStoreState>((set, get) => ({
    projectId: null,
    types: [],
    activeType: null,
    content: null,
    history: [],
    loading: false,
    saving: false,
    error: null,
    dirty: false,

    async loadTypes(projectId) {
      set({ loading: true, error: null, projectId });
      try {
        const res = await apiClient.listResources(projectId);
        set({ types: res.resources, loading: false });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        set({ loading: false, error: msg });
      }
    },

    async selectType(projectId, type) {
      set({ loading: true, error: null, activeType: type, projectId });
      try {
        const [content, hist] = await Promise.all([
          apiClient.getResource(projectId, type),
          apiClient.resourceHistory(projectId, type),
        ]);
        set({ content, history: hist.commits, loading: false, dirty: false });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        set({ loading: false, error: msg });
      }
    },

    async save(content, filename) {
      const pid = get().projectId;
      const type = get().activeType;
      if (!pid || !type) return;
      if (get().content?.read_only) {
        set({ error: "变量类型只读，不允许保存" });
        return;
      }
      set({ saving: true, error: null });
      try {
        const updated = await apiClient.putResource(pid, type, content, filename);
        const hist = await apiClient.resourceHistory(pid, type);
        set({ content: updated, history: hist.commits, saving: false, dirty: false });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        set({ saving: false, error: msg });
      }
    },

    setLocalContent(content) {
      set((s) => ({
        dirty: s.content?.content !== content,
        content: s.content ? { ...s.content, content } : null,
      }));
    },

    clearError() {
      set({ error: null });
    },
  }));
}

export const useResourceStore = createResourceStore();
