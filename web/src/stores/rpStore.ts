/**
 * Zustand store for the RP view.
 *
 * Holds the RP action input + the last director response. send() posts
 * the player's action to /api/chat/{projectId} (RP actions reuse the
 * director chat contract). The full chat history is
 * owned by chatStore; this store tracks only the RP-specific action/
 * response pair so the RpView input box and last-response display can
 * render without re-reading the whole log.
 */

import { create } from "zustand";
import {
  api as defaultApi,
  type ApiClient,
  type ChatMessage,
} from "@/api/client";

export interface RpStoreState {
  projectId: string | null;
  action: string;
  response: ChatMessage | null;
  sending: boolean;
  error: string | null;

  setAction: (text: string) => void;
  send: (projectId: string, text: string) => Promise<void>;
  clearError: () => void;
  reset: () => void;
}

export function createRpStore(apiClient: ApiClient = defaultApi) {
  return create<RpStoreState>((set) => ({
    projectId: null,
    action: "",
    response: null,
    sending: false,
    error: null,

    setAction(text) {
      set({ action: text });
    },

    async send(projectId, text) {
      const trimmed = text.trim();
      if (trimmed.length === 0) return;
      set({ sending: true, error: null, projectId, action: "" });
      try {
        const res = await apiClient.sendChat(projectId, trimmed);
        set({ response: res.director_message, sending: false });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        set({ sending: false, error: msg });
      }
    },

    clearError() {
      set({ error: null });
    },

    reset() {
      set({ projectId: null, action: "", response: null, error: null, sending: false });
    },
  }));
}

export const useRpStore = createRpStore();
