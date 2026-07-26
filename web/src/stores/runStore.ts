/**
 * Zustand store for the workflow run panel.
 *
 * Holds the active round status + live logs. Wraps POST /api/workflow/
 * {id}/run (start), GET /api/workflow/{id}/round/{rid} (poll), and
 * POST /api/workflow/{id}/stop. Polling is driven by the view via
 * setInterval; the store exposes a single refresh() that hits the GET.
 */

import { create } from "zustand";
import {
  api as defaultApi,
  type ApiClient,
  type RoundState,
  type RoundStatusResponse,
  type RunWorkflowRequest,
} from "@/api/client";
import { apiErrorMessage } from "@/api/errors";

export interface RunStoreState {
  projectId: string | null;
  round: RoundStatusResponse | null;
  polling: boolean;
  starting: boolean;
  stopping: boolean;
  error: string | null;

  startRound: (projectId: string, body?: RunWorkflowRequest) => Promise<void>;
  refresh: () => Promise<void>;
  stop: (projectId: string) => Promise<void>;
  setPolling: (on: boolean) => void;
  clearError: () => void;
}

export function createRunStore(apiClient: ApiClient = defaultApi) {
  return create<RunStoreState>((set, get) => ({
    projectId: null,
    round: null,
    polling: false,
    starting: false,
    stopping: false,
    error: null,

    async startRound(projectId, body = {}) {
      set({ starting: true, error: null, projectId });
      try {
        const round = await apiClient.runWorkflow(projectId, body);
        set({ round, starting: false });
      } catch (e) {
        const msg = apiErrorMessage(e);
        set({ starting: false, error: msg });
      }
    },

    async refresh() {
      const pid = get().projectId;
      const rid = get().round?.round_id;
      if (!pid || !rid) return;
      try {
        const round = await apiClient.getRound(pid, rid);
        set({ round });
      } catch (e) {
        const msg = apiErrorMessage(e);
        set({ error: msg });
      }
    },

    async stop(projectId) {
      set({ stopping: true, error: null });
      try {
        const round = await apiClient.stopWorkflow(projectId);
        set({ round, stopping: false });
      } catch (e) {
        const msg = apiErrorMessage(e);
        set({ stopping: false, error: msg });
      }
    },

    setPolling(on) {
      set({ polling: on });
    },

    clearError() {
      set({ error: null });
    },
  }));
}

export const useRunStore = createRunStore();

export type { RoundState };
