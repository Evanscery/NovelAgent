/**
 * Zustand store for the novel viewer.
 *
 * Holds the chapter list + the currently-open chapter's content. The
 * backend /api/novel endpoints are read-only; editing/zoom is a pure
 * front-end concern — the store keeps a local draft for
 * the edit mode and the view renders it.
 */

import { create } from "zustand";
import {
  api as defaultApi,
  type ApiClient,
  type NovelChapterResponse,
  type NovelChapterSummary,
} from "@/api/client";
import { apiErrorMessage } from "@/api/errors";

export interface NovelStoreState {
  projectId: string | null;
  chapters: NovelChapterSummary[];
  active: NovelChapterResponse | null;
  loading: boolean;
  error: string | null;
  zoom: number;

  loadChapters: (projectId: string) => Promise<void>;
  openChapter: (projectId: string, filename: string) => Promise<void>;
  setZoom: (zoom: number) => void;
  clearError: () => void;
}

export function createNovelStore(apiClient: ApiClient = defaultApi) {
  return create<NovelStoreState>((set) => ({
    projectId: null,
    chapters: [],
    active: null,
    loading: false,
    error: null,
    zoom: 1,

    async loadChapters(projectId) {
      set({ loading: true, error: null, projectId });
      try {
        const res = await apiClient.listChapters(projectId);
        set({ chapters: res.chapters, loading: false });
      } catch (e) {
        const msg = apiErrorMessage(e);
        set({ loading: false, error: msg });
      }
    },

    async openChapter(projectId, filename) {
      set({ loading: true, error: null });
      try {
        const chapter = await apiClient.readChapter(projectId, filename);
        set({ active: chapter, loading: false });
      } catch (e) {
        const msg = apiErrorMessage(e);
        set({ loading: false, error: msg });
      }
    },

    setZoom(zoom) {
      set({ zoom: Math.max(0.5, Math.min(2.5, zoom)) });
    },

    clearError() {
      set({ error: null });
    },
  }));
}

export const useNovelStore = createNovelStore();
