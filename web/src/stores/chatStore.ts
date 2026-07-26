/**
 * Zustand store for the director chat.
 *
 * Holds the chat message log + actions: send, delete (rolls back), retry.
 * Wraps /api/chat. Deleting a message syncs to backend
 * rollback — the DELETE endpoint returns the surviving messages and we
 * replace the local list with them. Retry rolls the backend back to
 * before the target message and appends a fresh exchange, so the local
 * list is refetched wholesale (listChat) instead of appended — mirroring
 * remove()'s replace semantics.
 */

import { create } from "zustand";
import {
  api as defaultApi,
  type ApiClient,
  type ChatMessage,
} from "@/api/client";
import { apiErrorMessage } from "@/api/errors";

export interface ChatStoreState {
  projectId: string | null;
  messages: ChatMessage[];
  loading: boolean;
  sending: boolean;
  error: string | null;
  lastBranch: string | null;

  load: (projectId: string) => Promise<void>;
  send: (text: string) => Promise<void>;
  remove: (messageId: string) => Promise<void>;
  retry: (messageId: string) => Promise<void>;
  clearError: () => void;
}

export function createChatStore(apiClient: ApiClient = defaultApi) {
  return create<ChatStoreState>((set, get) => ({
    projectId: null,
    messages: [],
    loading: false,
    sending: false,
    error: null,
    lastBranch: null,

    async load(projectId) {
      set({ loading: true, error: null, projectId });
      try {
        const messages = await apiClient.listChat(projectId);
        set({ messages, loading: false });
      } catch (e) {
        set({ loading: false, error: apiErrorMessage(e) });
      }
    },

    async send(text) {
      const pid = get().projectId;
      if (!pid) return;
      set({ sending: true, error: null });
      try {
        const res = await apiClient.sendChat(pid, text);
        set((s) => ({
          messages: [
            ...s.messages,
            res.user_message,
            ...(res.director_message ? [res.director_message] : []),
          ],
          sending: false,
        }));
      } catch (e) {
        set({ sending: false, error: apiErrorMessage(e) });
      }
    },

    async remove(messageId) {
      const pid = get().projectId;
      if (!pid) return;
      set({ sending: true, error: null });
      try {
        // DELETE returns the surviving messages after rollback.
        const surviving = await apiClient.deleteChat(pid, messageId);
        set({ messages: surviving, sending: false });
      } catch (e) {
        set({ sending: false, error: apiErrorMessage(e) });
      }
    },

    async retry(messageId) {
      const pid = get().projectId;
      if (!pid) return;
      set({ sending: true, error: null });
      try {
        const res = await apiClient.retryChat(pid, messageId);
        // The backend rolled back to before the target message and then
        // appended the new exchange — the old local list is stale, so
        // refetch the server's message log wholesale (same replace
        // semantics as remove()).
        const messages = await apiClient.listChat(pid);
        set({
          messages,
          lastBranch: res.branch,
          sending: false,
        });
      } catch (e) {
        set({ sending: false, error: apiErrorMessage(e) });
      }
    },

    clearError() {
      set({ error: null });
    },
  }));
}

export const useChatStore = createChatStore();
