/**
 * Tests for WorkflowCanvasView + workflowStore (todo 27).
 * Mocks the API client; asserts load pulls the REAL canvas graph from
 * GET /api/workflow/{id}/canvas (plus the agent registry for the side
 * panel), saveCanvas PUTs the current graph, export JSON round-trips,
 * and agent edit saves to the right endpoint.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import type { AxiosInstance } from "axios";
import { createWorkflowStore, type CanvasGraphData } from "@/stores/workflowStore";
import { ApiClient, type AgentConfigResponse } from "@/api/client";

interface MockAxiosInstance {
  get: ReturnType<typeof vi.fn>;
  post: ReturnType<typeof vi.fn>;
  put: ReturnType<typeof vi.fn>;
  patch: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
}

function makeMockInstance(): MockAxiosInstance {
  return {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  };
}

function data<T>(value: T): { data: T } {
  return { data: value };
}

const sampleAgent = (name: string): AgentConfigResponse => ({
  id: `agent_${name}`,
  name,
  task: `task-${name}`,
  input: "in",
  output: "out",
  permission: { read: ["state"], write: ["notes"] },
  model: null,
  tools: ["read", "search", "write"],
  head: null,
  tail: null,
  allow_recursive: true,
});

const sampleCanvas = (): CanvasGraphData => ({
  nodes: [
    { id: "n_recall", agent_name: "recaller", description: "回忆", params: {} },
    { id: "n_write", agent_name: "writer", description: "写作", params: { chapter: 1 } },
  ],
  wires: [{ from_node: "n_recall", to_node: "n_write", repeat_count: 2 }],
});

let mock: MockAxiosInstance;

beforeEach(() => {
  vi.clearAllMocks();
  mock = makeMockInstance();
});

function makeStore() {
  const apiClient = new ApiClient(mock as unknown as AxiosInstance);
  return createWorkflowStore(apiClient);
}

/** Route GETs by url so Promise.all ordering does not matter. */
function mockLoad(projectId: string, canvas: CanvasGraphData, agents: AgentConfigResponse[]) {
  mock.get.mockImplementation((url: string) => {
    if (url === `/workflow/${projectId}/canvas`) return Promise.resolve(data(canvas));
    if (url === `/config/${projectId}/agents`) return Promise.resolve(data(agents));
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
}

describe("workflowStore.load", () => {
  it("loads the real canvas from GET /workflow/{id}/canvas + the agent registry", async () => {
    const canvas = sampleCanvas();
    const agents = [sampleAgent("recaller"), sampleAgent("writer")];
    mockLoad("proj_1", canvas, agents);
    const store = makeStore();
    await store.getState().load("proj_1");
    expect(mock.get).toHaveBeenCalledWith("/workflow/proj_1/canvas");
    expect(mock.get).toHaveBeenCalledWith("/config/proj_1/agents");
    expect(store.getState().canvas).toEqual(canvas);
    expect(store.getState().agents).toEqual(agents);
    expect(store.getState().loading).toBe(false);
    expect(store.getState().dirty).toBe(false);
  });

  it("does NOT synthesize a linear chain from the agent list", async () => {
    // Empty workflow → empty canvas, even with agents registered.
    mockLoad("proj_1", { nodes: [], wires: [] }, [sampleAgent("a"), sampleAgent("b")]);
    const store = makeStore();
    await store.getState().load("proj_1");
    expect(store.getState().canvas.nodes).toEqual([]);
    expect(store.getState().canvas.wires).toEqual([]);
  });

  it("sets error on failure", async () => {
    mock.get.mockRejectedValue(new Error("boom"));
    const store = makeStore();
    await store.getState().load("proj_1");
    expect(store.getState().error).toBe("boom");
    expect(store.getState().loading).toBe(false);
  });
});

describe("workflowStore.saveCanvas", () => {
  it("PUTs the current graph to /workflow/{id}/canvas and clears dirty", async () => {
    const canvas = sampleCanvas();
    mockLoad("p1", canvas, []);
    const store = makeStore();
    await store.getState().load("p1");
    store.getState().addWire({ from_node: "n_write", to_node: "n_recall", repeat_count: 1 });
    expect(store.getState().dirty).toBe(true);
    const expected = store.getState().canvas;
    mock.put.mockResolvedValueOnce(data(expected));
    await store.getState().saveCanvas();
    expect(mock.put).toHaveBeenCalledWith("/workflow/p1/canvas", expected);
    expect(store.getState().canvas).toEqual(expected);
    expect(store.getState().dirty).toBe(false);
    expect(store.getState().saving).toBe(false);
  });

  it("surfaces the backend detail on 422", async () => {
    mockLoad("p1", sampleCanvas(), []);
    const store = makeStore();
    await store.getState().load("p1");
    store.getState().addWire({ from_node: "n_write", to_node: "n_recall", repeat_count: 1 });
    const axiosErr = Object.assign(new Error("Request failed with status code 422"), {
      isAxiosError: true,
      response: { data: { detail: "Invalid canvas: cycle detected" } },
    });
    mock.put.mockRejectedValueOnce(axiosErr);
    await store.getState().saveCanvas();
    expect(store.getState().error).toBe("Invalid canvas: cycle detected");
    expect(store.getState().saving).toBe(false);
    expect(store.getState().dirty).toBe(true);
  });

  it("is a no-op without a project id", async () => {
    const store = makeStore();
    await store.getState().saveCanvas();
    expect(mock.put).not.toHaveBeenCalled();
  });
});

describe("workflowStore canvas mutations", () => {
  it("addNode appends + sets dirty", () => {
    const store = makeStore();
    store.getState().addNode({
      id: "n1",
      agent_name: "writer",
      description: "writes",
      params: {},
    });
    expect(store.getState().canvas.nodes).toHaveLength(1);
    expect(store.getState().dirty).toBe(true);
  });

  it("removeNode also removes connected wires", () => {
    const store = makeStore();
    store.getState().addNode({ id: "a", agent_name: "a", description: "", params: {} });
    store.getState().addNode({ id: "b", agent_name: "b", description: "", params: {} });
    store.getState().addWire({ from_node: "a", to_node: "b", repeat_count: 1 });
    store.getState().removeNode("a");
    expect(store.getState().canvas.nodes.map((n) => n.id)).toEqual(["b"]);
    expect(store.getState().canvas.wires).toEqual([]);
  });

  it("addWire ignores duplicates", () => {
    const store = makeStore();
    store.getState().addNode({ id: "a", agent_name: "a", description: "", params: {} });
    store.getState().addNode({ id: "b", agent_name: "b", description: "", params: {} });
    store.getState().addWire({ from_node: "a", to_node: "b", repeat_count: 1 });
    store.getState().addWire({ from_node: "a", to_node: "b", repeat_count: 1 });
    expect(store.getState().canvas.wires).toHaveLength(1);
  });

  it("removeWire removes only matching", () => {
    const store = makeStore();
    store.getState().addNode({ id: "a", agent_name: "a", description: "", params: {} });
    store.getState().addNode({ id: "b", agent_name: "b", description: "", params: {} });
    store.getState().addNode({ id: "c", agent_name: "c", description: "", params: {} });
    store.getState().addWire({ from_node: "a", to_node: "b", repeat_count: 1 });
    store.getState().addWire({ from_node: "b", to_node: "c", repeat_count: 1 });
    store.getState().removeWire("a", "b");
    expect(store.getState().canvas.wires).toEqual([
      { from_node: "b", to_node: "c", repeat_count: 1 },
    ]);
  });
});

describe("workflowStore.exportJson / importJson round-trip", () => {
  it("export → import is a structural round-trip", () => {
    const store = makeStore();
    const original: CanvasGraphData = {
      nodes: [
        { id: "a", agent_name: "a", description: "x", params: { foo: 1 } },
        { id: "b", agent_name: "b", description: "y", params: {} },
      ],
      wires: [
        { from_node: "a", to_node: "b", repeat_count: 3 },
      ],
    };
    store.getState().importJson(JSON.stringify(original));
    const exported = store.getState().exportJson();
    const reparsed = JSON.parse(exported) as CanvasGraphData;
    expect(reparsed).toEqual(original);
  });

  it("an imported graph can then be saved via PUT canvas", async () => {
    mockLoad("p1", { nodes: [], wires: [] }, []);
    const store = makeStore();
    await store.getState().load("p1");
    const imported: CanvasGraphData = {
      nodes: [{ id: "x", agent_name: "writer", description: "", params: {} }],
      wires: [],
    };
    store.getState().importJson(JSON.stringify(imported));
    mock.put.mockResolvedValueOnce(data(imported));
    await store.getState().saveCanvas();
    expect(mock.put).toHaveBeenCalledWith("/workflow/p1/canvas", imported);
  });

  it("importJson rejects invalid shape", () => {
    const store = makeStore();
    expect(() => store.getState().importJson('{"nodes": []}')).toThrow();
  });
});

describe("workflowStore.selectNode", () => {
  it("selects an existing node + finds its agent by agent_name", async () => {
    mockLoad("p", sampleCanvas(), [sampleAgent("writer")]);
    const store = makeStore();
    await store.getState().load("p");
    store.getState().selectNode("n_write");
    expect(store.getState().selected?.id).toBe("n_write");
    expect(store.getState().selected?.agent?.name).toBe("writer");
  });

  it("selectNode with unknown id is a no-op", async () => {
    mockLoad("p", sampleCanvas(), [sampleAgent("writer")]);
    const store = makeStore();
    await store.getState().load("p");
    store.getState().selectNode("nope");
    expect(store.getState().selected).toBeNull();
  });
});

describe("workflowStore.saveAgent", () => {
  it("PUTs the agent and refreshes the registry", async () => {
    mockLoad("p1", sampleCanvas(), [sampleAgent("writer")]);
    const store = makeStore();
    await store.getState().load("p1");
    mock.put.mockResolvedValueOnce(data(sampleAgent("writer")));
    const updated = [sampleAgent("writer")];
    updated[0].task = "new task";
    mock.get.mockImplementation((url: string) => {
      if (url === "/config/p1/agents") return Promise.resolve(data(updated));
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });
    await store.getState().saveAgent("writer", {
      ...sampleAgent("writer"),
      task: "new task",
    });
    expect(mock.put).toHaveBeenCalledWith("/config/p1/agents/writer", expect.objectContaining({
      name: "writer",
      task: "new task",
    }));
    expect(store.getState().agents[0].task).toBe("new task");
    expect(store.getState().saving).toBe(false);
  });
});
