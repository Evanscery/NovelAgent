/**
 * Tests for RpView + rpStore (todo 31).
 * Mocks the API client; asserts send posts the action to /api/chat/{id},
 * stores the director response, clears the action input, and surfaces
 * errors. Also verifies setAction + reset + clearError.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import type { AxiosInstance } from "axios";
import { createRpStore } from "@/stores/rpStore";
import { ApiClient } from "@/api/client";

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

function makeStore() {
  const apiClient = new ApiClient(mock as unknown as AxiosInstance);
  return createRpStore(apiClient);
}

describe("rpStore initial state", () => {
  it("starts empty + idle", () => {
    const store = makeStore();
    expect(store.getState().action).toBe("");
    expect(store.getState().response).toBeNull();
    expect(store.getState().sending).toBe(false);
    expect(store.getState().error).toBeNull();
    expect(store.getState().projectId).toBeNull();
  });
});

describe("rpStore.setAction", () => {
  it("updates the action input", () => {
    const store = makeStore();
    store.getState().setAction("对酒馆老板说：最近镇上有什么怪事？");
    expect(store.getState().action).toBe("对酒馆老板说：最近镇上有什么怪事？");
  });
});

describe("rpStore.send", () => {
  it("posts the action to /api/chat/{id} and stores the director response", async () => {
    mock.post.mockResolvedValueOnce(
      data({
        user_message: {
          message_id: "u1",
          role: "user" as const,
          content: "我拔出剑。",
          turn_id: "t1",
          timestamp: "ts",
        },
        director_message: {
          message_id: "d1",
          role: "director" as const,
          content: "酒馆老板后退一步…",
          turn_id: "t1",
          timestamp: "ts",
        },
      }),
    );
    const store = makeStore();
    store.getState().setAction("我拔出剑。");
    await store.getState().send("p1", "我拔出剑。");
    expect(mock.post).toHaveBeenCalledWith("/chat/p1", { content: "我拔出剑。" });
    expect(store.getState().response?.message_id).toBe("d1");
    expect(store.getState().response?.content).toBe("酒馆老板后退一步…");
    expect(store.getState().action).toBe("");
    expect(store.getState().sending).toBe(false);
    expect(store.getState().projectId).toBe("p1");
  });

  it("stores null response when director returns null", async () => {
    mock.post.mockResolvedValueOnce(
      data({
        user_message: {
          message_id: "u1",
          role: "user" as const,
          content: "hi",
          turn_id: "t1",
          timestamp: "ts",
        },
        director_message: null,
      }),
    );
    const store = makeStore();
    await store.getState().send("p1", "hi");
    expect(store.getState().response).toBeNull();
    expect(store.getState().sending).toBe(false);
  });

  it("ignores empty/whitespace action", async () => {
    const store = makeStore();
    await store.getState().send("p1", "   ");
    expect(mock.post).not.toHaveBeenCalled();
    expect(store.getState().sending).toBe(false);
  });

  it("sets error on failure and clears sending", async () => {
    mock.post.mockRejectedValueOnce(new Error("network"));
    const store = makeStore();
    await store.getState().send("p1", "act");
    expect(store.getState().error).toBe("network");
    expect(store.getState().sending).toBe(false);
  });
});

describe("rpStore.clearError + reset", () => {
  it("clears error", () => {
    const store = makeStore();
    store.setState({ error: "boom" });
    store.getState().clearError();
    expect(store.getState().error).toBeNull();
  });

  it("reset returns to empty state", () => {
    const store = makeStore();
    store.setState({
      projectId: "p1",
      action: "x",
      response: {
        message_id: "d",
        role: "director",
        content: "r",
        turn_id: "t",
        timestamp: "ts",
      },
      sending: true,
      error: "e",
    });
    store.getState().reset();
    expect(store.getState().projectId).toBeNull();
    expect(store.getState().action).toBe("");
    expect(store.getState().response).toBeNull();
    expect(store.getState().sending).toBe(false);
    expect(store.getState().error).toBeNull();
  });
});
