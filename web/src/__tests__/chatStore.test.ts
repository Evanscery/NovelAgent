/**
 * Tests for ChatView + chatStore (todo 28).
 * Mocks the API client; asserts send appends user+director messages,
 * delete replaces the list with the surviving messages (rollback),
 * retry appends the new exchange + records the new branch.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import type { AxiosInstance } from "axios";
import { createChatStore } from "@/stores/chatStore";
import { ApiClient, type ChatMessage } from "@/api/client";

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

function msg(id: string, role: "user" | "director", content: string, turn: string): ChatMessage {
  return { message_id: id, role, content, turn_id: turn, timestamp: "t" };
}

let mock: MockAxiosInstance;

beforeEach(() => {
  vi.clearAllMocks();
  mock = makeMockInstance();
});

function makeStore() {
  const apiClient = new ApiClient(mock as unknown as AxiosInstance);
  return createChatStore(apiClient);
}

describe("chatStore.load", () => {
  it("loads the message history", async () => {
    const history = [msg("m1", "user", "hi", "t1"), msg("m2", "director", "hello", "t1")];
    mock.get.mockResolvedValueOnce(data(history));
    const store = makeStore();
    await store.getState().load("p1");
    expect(mock.get).toHaveBeenCalledWith("/chat/p1");
    expect(store.getState().messages).toEqual(history);
    expect(store.getState().loading).toBe(false);
  });

  it("sets error on failure", async () => {
    mock.get.mockRejectedValueOnce(new Error("boom"));
    const store = makeStore();
    await store.getState().load("p1");
    expect(store.getState().error).toBe("boom");
  });
});

describe("chatStore.send", () => {
  it("appends user + director messages from the response", async () => {
    mock.post.mockResolvedValueOnce(
      data({
        user_message: msg("u1", "user", "hi", "t1"),
        director_message: msg("d1", "director", "hello", "t1"),
      }),
    );
    const store = makeStore();
    store.setState({ projectId: "p1" });
    await store.getState().send("hi");
    expect(mock.post).toHaveBeenCalledWith("/chat/p1", { content: "hi" });
    const ids = store.getState().messages.map((m) => m.message_id);
    expect(ids).toEqual(["u1", "d1"]);
    expect(store.getState().sending).toBe(false);
  });

  it("appends only the user message when director is null", async () => {
    mock.post.mockResolvedValueOnce(
      data({ user_message: msg("u1", "user", "hi", "t1"), director_message: null }),
    );
    const store = makeStore();
    store.setState({ projectId: "p1" });
    await store.getState().send("hi");
    expect(store.getState().messages).toHaveLength(1);
  });

  it("sets error on failure and clears sending", async () => {
    mock.post.mockRejectedValueOnce(new Error("nope"));
    const store = makeStore();
    store.setState({ projectId: "p1" });
    await store.getState().send("hi");
    expect(store.getState().error).toBe("nope");
    expect(store.getState().sending).toBe(false);
  });
});

describe("chatStore.remove (rollback)", () => {
  it("replaces messages with the surviving list from DELETE", async () => {
    const store = makeStore();
    store.setState({
      projectId: "p1",
      messages: [
        msg("m1", "user", "a", "t1"),
        msg("m2", "director", "A", "t1"),
        msg("m3", "user", "b", "t2"),
        msg("m4", "director", "B", "t2"),
      ],
    });
    // After deleting m3 the backend rolls back to t1 and returns the survivors.
    const survivors = [msg("m1", "user", "a", "t1"), msg("m2", "director", "A", "t1")];
    mock.delete.mockResolvedValueOnce(data(survivors));
    await store.getState().remove("m3");
    expect(mock.delete).toHaveBeenCalledWith("/chat/p1/m3");
    expect(store.getState().messages).toEqual(survivors);
  });

  it("sets error when DELETE fails", async () => {
    mock.delete.mockRejectedValueOnce(new Error("404"));
    const store = makeStore();
    store.setState({ projectId: "p1", messages: [msg("m1", "user", "a", "t1")] });
    await store.getState().remove("m1");
    expect(store.getState().error).toBe("404");
  });
});

describe("chatStore.retry", () => {
  it("appends the retried exchange + records the new branch", async () => {
    mock.post.mockResolvedValueOnce(
      data({
        branch: "branch_abc",
        user_message: msg("u2", "user", "again", "t3"),
        director_message: msg("d2", "director", "redo", "t3"),
      }),
    );
    const store = makeStore();
    store.setState({ projectId: "p1", messages: [msg("m1", "user", "a", "t1")] });
    await store.getState().retry("m1");
    expect(mock.post).toHaveBeenCalledWith("/chat/p1/m1/retry");
    expect(store.getState().messages.map((m) => m.message_id)).toEqual(["m1", "u2", "d2"]);
    expect(store.getState().lastBranch).toBe("branch_abc");
  });
});
