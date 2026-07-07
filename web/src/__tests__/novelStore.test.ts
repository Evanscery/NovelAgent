/**
 * Tests for NovelView + novelStore (todo 31).
 * Mocks the API client; asserts chapter list loads and openChapter
 * fetches content. Also verifies RpView sends an action via chat store
 * (reusing chatStore.test patterns).
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import type { AxiosInstance } from "axios";
import { createNovelStore } from "@/stores/novelStore";
import { createChatStore } from "@/stores/chatStore";
import { ApiClient, type NovelChapterSummary } from "@/api/client";

interface MockAxiosInstance {
  get: ReturnType<typeof vi.fn>;
  post: ReturnType<typeof vi.fn>;
  put: ReturnType<typeof vi.fn>;
  patch: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
}

function makeMockInstance(): MockAxiosInstance {
  return { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() };
}

function data<T>(value: T): { data: T } {
  return { data: value };
}

let mock: MockAxiosInstance;

beforeEach(() => {
  vi.clearAllMocks();
  mock = makeMockInstance();
});

describe("novelStore.loadChapters", () => {
  it("lists chapters from /api/novel/{id}", async () => {
    const chapters: NovelChapterSummary[] = [
      { filename: "chapter_01.txt", chapter_number: 1, size_bytes: 4096 },
      { filename: "chapter_02.txt", chapter_number: 2, size_bytes: 8192 },
    ];
    mock.get.mockResolvedValueOnce(data({ project_id: "p1", chapters }));
    const apiClient = new ApiClient(mock as unknown as AxiosInstance);
    const store = createNovelStore(apiClient);
    await store.getState().loadChapters("p1");
    expect(mock.get).toHaveBeenCalledWith("/novel/p1");
    expect(store.getState().chapters).toHaveLength(2);
    expect(store.getState().loading).toBe(false);
  });

  it("sets error on failure", async () => {
    mock.get.mockRejectedValueOnce(new Error("boom"));
    const apiClient = new ApiClient(mock as unknown as AxiosInstance);
    const store = createNovelStore(apiClient);
    await store.getState().loadChapters("p1");
    expect(store.getState().error).toBe("boom");
  });
});

describe("novelStore.openChapter", () => {
  it("fetches chapter content", async () => {
    mock.get.mockResolvedValueOnce(
      data({
        project_id: "p1",
        filename: "chapter_01.txt",
        chapter_number: 1,
        content: "# Chapter 1\n\nIt was a dark and stormy night.",
      }),
    );
    const apiClient = new ApiClient(mock as unknown as AxiosInstance);
    const store = createNovelStore(apiClient);
    await store.getState().openChapter("p1", "chapter_01.txt");
    expect(mock.get).toHaveBeenCalledWith("/novel/p1/chapter_01.txt");
    expect(store.getState().active?.content).toContain("dark and stormy");
  });
});

describe("novelStore.setZoom", () => {
  it("clamps zoom to [0.5, 2.5]", () => {
    const apiClient = new ApiClient(mock as unknown as AxiosInstance);
    const store = createNovelStore(apiClient);
    store.getState().setZoom(0.1);
    expect(store.getState().zoom).toBe(0.5);
    store.getState().setZoom(5);
    expect(store.getState().zoom).toBe(2.5);
    store.getState().setZoom(1.2);
    expect(store.getState().zoom).toBe(1.2);
  });
});

describe("RpView (via chatStore) — sending an RP action", () => {
  it("posts the action to /api/chat/{id}", async () => {
    mock.post.mockResolvedValueOnce(
      data({
        user_message: {
          message_id: "u1",
          role: "user" as const,
          content: "对酒馆老板说：最近镇上有什么怪事？",
          turn_id: "t1",
          timestamp: "ts",
        },
        director_message: {
          message_id: "d1",
          role: "director" as const,
          content: "酒馆老板抬起头…",
          turn_id: "t1",
          timestamp: "ts",
        },
      }),
    );
    const apiClient = new ApiClient(mock as unknown as AxiosInstance);
    const store = createChatStore(apiClient);
    store.setState({ projectId: "p1" });
    await store.getState().send("对酒馆老板说：最近镇上有什么怪事？");
    expect(mock.post).toHaveBeenCalledWith("/chat/p1", {
      content: "对酒馆老板说：最近镇上有什么怪事？",
    });
    expect(store.getState().messages).toHaveLength(2);
    expect(store.getState().messages[0].role).toBe("user");
    expect(store.getState().messages[1].role).toBe("director");
  });
});
