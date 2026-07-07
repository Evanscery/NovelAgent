/**
 * Zustand store for project list + active project selection.
 *
 * Wraps the projects slice of ApiClient (app/api/routes/projects.py).
 * Stores hold UI-relevant snapshot only — canonical state is the backend
 * (file system is the single source of truth per refactor_guide).
 */

import { create } from "zustand";
import {
  api as defaultApi,
  type ApiClient,
  type ProjectMode,
  type ProjectSummary,
} from "@/api/client";

export interface ProjectStoreState {
  projects: ProjectSummary[];
  activeProject: ProjectSummary | null;
  loading: boolean;
  error: string | null;
  fetchProjects: () => Promise<void>;
  createProject: (displayName: string, mode: ProjectMode) => Promise<void>;
  selectProject: (id: string) => void;
  deleteProject: (id: string) => Promise<void>;
  clearError: () => void;
}

export function createProjectStore(apiClient: ApiClient = defaultApi) {
  return create<ProjectStoreState>((set, get) => ({
    projects: [],
    activeProject: null,
    loading: false,
    error: null,

    async fetchProjects() {
      set({ loading: true, error: null });
      try {
        const { projects } = await apiClient.listProjects();
        const prevActive = get().activeProject;
        const nextActive =
          prevActive === null
            ? (projects[0] ?? null)
            : (projects.find((p) => p.id === prevActive.id) ?? projects[0] ?? null);
        set({ projects, activeProject: nextActive, loading: false });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        set({ loading: false, error: msg });
      }
    },

    async createProject(displayName, mode) {
      set({ loading: true, error: null });
      try {
        await apiClient.createProject(displayName, mode);
        const { projects } = await apiClient.listProjects();
        const created =
          projects.find((p) => p.display_name === displayName) ?? projects[0] ?? null;
        set({ projects, activeProject: created, loading: false });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        set({ loading: false, error: msg });
      }
    },

    selectProject(id) {
      const found = get().projects.find((p) => p.id === id);
      if (found !== undefined) {
        set({ activeProject: found });
      }
    },

    async deleteProject(id) {
      set({ loading: true, error: null });
      try {
        await apiClient.deleteProject(id);
        const { projects } = await apiClient.listProjects();
        const prevActive = get().activeProject;
        const nextActive =
          prevActive !== null && prevActive.id === id
            ? (projects[0] ?? null)
            : prevActive;
        set({ projects, activeProject: nextActive, loading: false });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        set({ loading: false, error: msg });
      }
    },

    clearError() {
      set({ error: null });
    },
  }));
}

export const useProjectStore = createProjectStore();
