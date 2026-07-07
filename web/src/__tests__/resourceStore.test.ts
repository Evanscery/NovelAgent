/**
 * Tests for ResourceEditorView + resourceStore (todo 29).
 * Mocks the API client; asserts the 8-type tree loads, editor load/save
 * round-trips, history lists commits, and the variables type is read-only.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import type { AxiosInstance } from "axios";
import { createResourceStore } from "@/stores/resourceStore";
import { ApiClient, type ResourceListEntry } from "@/api/client";

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

const EIGHT_TYPES: ResourceListEntry[] = [
  { type: "outline", title: "大纲", exists: true, file_count: 1, content_summary: "" },
  { type: "short_goal", title: "细纲", exists: false, file_count: 0, content_summary: "" },
  { type: "state", title: "当前状态", exists: true, file_count: 1, content_summary: "" },
  { type: "variables", title: "变量", exists: true, file_count: 1, content_summary: "" },
  { type: "worldbook", title: "世界书", exists: true, file_count: 2, content_summary: "" },
  { type: "facts", title: "客观事实", exists: false, file_count: 0, content_summary: "" },
  { type: "character_memory", title: "人物记忆", exists: true, file_count: 3, content_summary: "" },
  { type: "notes", title: "创作笔记", exists: true, file_count: 1, content_summary: "" },
];

let mock: MockAxiosInstance;

beforeEach(() => {
  vi.clearAllMocks();
  mock = makeMockInstance();
});

function makeStore() {
  const apiClient = new ApiClient(mock as unknown as AxiosInstance);
  return createResourceStore(apiClient);
}

describe("resourceStore.loadTypes", () => {
  it("loads all 8 resource types", async () => {
    mock.get.mockResolvedValueOnce(data({ project_id: "p1", resources: EIGHT_TYPES }));
    const store = makeStore();
    await store.getState().loadTypes("p1");
    expect(mock.get).toHaveBeenCalledWith("/resources/p1");
    expect(store.getState().types).toHaveLength(8);
    const titles = store.getState().types.map((t) => t.title);
    expect(titles).toContain("大纲");
    expect(titles).toContain("创作笔记");
  });
});

describe("resourceStore.selectType", () => {
  it("loads content + history in parallel", async () => {
    mock.get.mockResolvedValueOnce(
      data({
        project_id: "p1",
        type: "state",
        title: "当前状态",
        read_only: false,
        content: "# State\nfoo",
        files: ["content.md"],
      }),
    );
    mock.get.mockResolvedValueOnce(
      data({
        project_id: "p1",
        type: "state",
        commits: [
          { sha: "abc123def", turn_id: "t1", message: "first", timestamp: "x", branch: "main" },
          { sha: "fff000aaa", turn_id: "t2", message: "second", timestamp: "y", branch: "main" },
        ],
      }),
    );
    const store = makeStore();
    await store.getState().selectType("p1", "state");
    expect(mock.get).toHaveBeenCalledWith("/resources/p1/state");
    expect(mock.get).toHaveBeenCalledWith("/resources/p1/state/history");
    expect(store.getState().content?.content).toBe("# State\nfoo");
    expect(store.getState().history).toHaveLength(2);
    expect(store.getState().history[0].sha).toBe("abc123def");
    expect(store.getState().loading).toBe(false);
  });

  it("surfaces read_only=true for variables", async () => {
    mock.get.mockResolvedValueOnce(
      data({
        project_id: "p1",
        type: "variables",
        title: "变量",
        read_only: true,
        content: "x: 1",
        files: ["content.md"],
      }),
    );
    mock.get.mockResolvedValueOnce(
      data({ project_id: "p1", type: "variables", commits: [] }),
    );
    const store = makeStore();
    await store.getState().selectType("p1", "variables");
    expect(store.getState().content?.read_only).toBe(true);
  });
});

describe("resourceStore.save", () => {
  it("PUTs content + refreshes history", async () => {
    mock.put.mockResolvedValueOnce(
      data({
        project_id: "p1",
        type: "state",
        title: "当前状态",
        read_only: false,
        content: "new content",
        files: ["content.md"],
      }),
    );
    mock.get.mockResolvedValueOnce(
      data({
        project_id: "p1",
        type: "state",
        commits: [{ sha: "new", turn_id: "t3", message: "edit", timestamp: "z", branch: "main" }],
      }),
    );
    const store = makeStore();
    store.setState({
      projectId: "p1",
      activeType: "state",
      content: {
        project_id: "p1",
        type: "state",
        title: "当前状态",
        read_only: false,
        content: "old",
        files: ["content.md"],
      },
    });
    await store.getState().save("new content");
    expect(mock.put).toHaveBeenCalledWith("/resources/p1/state", { content: "new content" });
    expect(store.getState().content?.content).toBe("new content");
    expect(store.getState().history).toHaveLength(1);
    expect(store.getState().dirty).toBe(false);
  });

  it("refuses to save read-only variables", async () => {
    const store = makeStore();
    store.setState({
      projectId: "p1",
      activeType: "variables",
      content: {
        project_id: "p1",
        type: "variables",
        title: "变量",
        read_only: true,
        content: "x: 1",
        files: ["content.md"],
      },
    });
    await store.getState().save("mutated");
    expect(mock.put).not.toHaveBeenCalled();
    expect(store.getState().error).toContain("只读");
  });
});

describe("resourceStore.setLocalContent", () => {
  it("sets dirty when content differs", () => {
    const store = makeStore();
    store.setState({
      content: {
        project_id: "p1",
        type: "state",
        title: "当前状态",
        read_only: false,
        content: "orig",
        files: ["content.md"],
      },
    });
    store.getState().setLocalContent("edited");
    expect(store.getState().content?.content).toBe("edited");
    expect(store.getState().dirty).toBe(true);
  });
});
