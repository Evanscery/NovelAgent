/**
 * Tests for RunView + runStore (todo 32).
 * Mocks the API client; asserts starting a round populates the store,
 * refresh polls the round, stop cancels. Also covers Inspector context
 * rendering by checking the run + chat + workflow store subscriptions
 * return the expected content for each active view.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import type { AxiosInstance } from "axios";
import { createRunStore } from "@/stores/runStore";
import { createChatStore } from "@/stores/chatStore";
import { createWorkflowStore } from "@/stores/workflowStore";
import { ApiClient, type AgentConfigResponse } from "@/api/client";

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

describe("runStore.startRound", () => {
  it("posts /run and stores the round response", async () => {
    mock.post.mockResolvedValueOnce(
      data({
        round_id: "round_abc",
        state: "pending" as const,
        logs: ["round round_abc started"],
        result: null,
        error: null,
      }),
    );
    const apiClient = new ApiClient(mock as unknown as AxiosInstance);
    const store = createRunStore(apiClient);
    await store.getState().startRound("p1");
    expect(mock.post).toHaveBeenCalledWith("/workflow/p1/run", {});
    expect(store.getState().round?.round_id).toBe("round_abc");
    expect(store.getState().round?.state).toBe("pending");
    expect(store.getState().starting).toBe(false);
  });

  it("sets error on failure", async () => {
    mock.post.mockRejectedValueOnce(new Error("409"));
    const apiClient = new ApiClient(mock as unknown as AxiosInstance);
    const store = createRunStore(apiClient);
    await store.getState().startRound("p1");
    expect(store.getState().error).toBe("409");
    expect(store.getState().starting).toBe(false);
  });
});

describe("runStore.refresh", () => {
  it("polls the round and updates state + logs", async () => {
    mock.post.mockResolvedValueOnce(
      data({
        round_id: "r1",
        state: "pending" as const,
        logs: [],
        result: null,
        error: null,
      }),
    );
    mock.get.mockResolvedValueOnce(
      data({
        round_id: "r1",
        state: "running" as const,
        logs: ["started", "director called recaller"],
        result: null,
        error: null,
      }),
    );
    const apiClient = new ApiClient(mock as unknown as AxiosInstance);
    const store = createRunStore(apiClient);
    await store.getState().startRound("p1");
    await store.getState().refresh();
    expect(mock.get).toHaveBeenCalledWith("/workflow/p1/round/r1");
    expect(store.getState().round?.state).toBe("running");
    expect(store.getState().round?.logs).toContain("director called recaller");
  });
});

describe("runStore.stop", () => {
  it("posts /stop and updates the round", async () => {
    mock.post.mockResolvedValueOnce(
      data({
        round_id: "r1",
        state: "pending" as const,
        logs: [],
        result: null,
        error: null,
      }),
    );
    // The stop call (second post).
    mock.post.mockResolvedValueOnce(
      data({
        round_id: "r1",
        state: "failed" as const,
        logs: ["stop requested"],
        result: null,
        error: "round stopped by user",
      }),
    );
    const apiClient = new ApiClient(mock as unknown as AxiosInstance);
    const store = createRunStore(apiClient);
    await store.getState().startRound("p1");
    await store.getState().stop("p1");
    expect(mock.post).toHaveBeenCalledWith("/workflow/p1/stop");
    expect(store.getState().round?.state).toBe("failed");
    expect(store.getState().stopping).toBe(false);
  });
});

describe("runStore.setPolling + clearError", () => {
  it("toggles polling + clears error", () => {
    const apiClient = new ApiClient(mock as unknown as AxiosInstance);
    const store = createRunStore(apiClient);
    store.getState().setPolling(true);
    expect(store.getState().polling).toBe(true);
    store.setState({ error: "x" });
    store.getState().clearError();
    expect(store.getState().error).toBeNull();
  });
});

describe("Inspector context (via store subscriptions)", () => {
  it("workflow store exposes selected node detail for Inspector", async () => {
    const agents: AgentConfigResponse[] = [
      {
        name: "writer",
        task: "文本生成",
        input: "ctx",
        output: "prose",
        permission: { read: ["state"], write: ["notes"] },
        model: "premium",
        tools: ["read", "write"],
        head: null,
        tail: null,
        allow_recursive: true,
      },
    ];
    mock.get.mockResolvedValueOnce(data(agents));
    const apiClient = new ApiClient(mock as unknown as AxiosInstance);
    const wfStore = createWorkflowStore(apiClient);
    await wfStore.getState().load("p1");
    wfStore.getState().selectNode("writer");
    expect(wfStore.getState().selected?.agent?.name).toBe("writer");
    expect(wfStore.getState().selected?.agent?.model).toBe("premium");
  });

  it("chat store exposes last director message + branch for Inspector", async () => {
    mock.post.mockResolvedValueOnce(
      data({
        user_message: { message_id: "u", role: "user" as const, content: "hi", turn_id: "t1", timestamp: "x" },
        director_message: { message_id: "d", role: "director" as const, content: "hello", turn_id: "t1", timestamp: "y" },
      }),
    );
    const apiClient = new ApiClient(mock as unknown as AxiosInstance);
    const chatStore = createChatStore(apiClient);
    chatStore.setState({ projectId: "p1" });
    await chatStore.getState().send("hi");
    const lastDirector = [...chatStore.getState().messages].reverse().find((m) => m.role === "director");
    expect(lastDirector?.content).toBe("hello");
  });

  it("run store round + logs are available for Inspector context", async () => {
    mock.post.mockResolvedValueOnce(
      data({
        round_id: "r1",
        state: "running" as const,
        logs: ["started", "director called recaller"],
        result: null,
        error: null,
      }),
    );
    const apiClient = new ApiClient(mock as unknown as AxiosInstance);
    const runStore = createRunStore(apiClient);
    await runStore.getState().startRound("p1");
    expect(runStore.getState().round?.logs).toContain("director called recaller");
  });
});
