/**
 * Tests for WorkflowCanvasView + workflowStore (todo 27).
 * Mocks the API client + react-flow DOM rendering; asserts canvas renders
 * nodes, export JSON round-trips, agent edit saves to the right endpoint.
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

let mock: MockAxiosInstance;

beforeEach(() => {
  vi.clearAllMocks();
  mock = makeMockInstance();
});

function makeStore() {
  const apiClient = new ApiClient(mock as unknown as AxiosInstance);
  return createWorkflowStore(apiClient);
}

describe("workflowStore.load", () => {
  it("loads agents and builds a linear canvas from the registry", async () => {
    const agents = [sampleAgent("recaller"), sampleAgent("writer"), sampleAgent("critic")];
    mock.get.mockResolvedValueOnce(data(agents));
    const store = makeStore();
    await store.getState().load("proj_1");
    expect(mock.get).toHaveBeenCalledWith("/config/proj_1/agents");
    const { canvas } = store.getState();
    expect(canvas.nodes).toHaveLength(3);
    expect(canvas.nodes.map((n) => n.id)).toEqual(["recaller", "writer", "critic"]);
    expect(canvas.wires).toHaveLength(2);
    expect(canvas.wires[0]).toEqual({
      from_node: "recaller",
      to_node: "writer",
      repeat_count: 1,
    });
    expect(store.getState().loading).toBe(false);
    expect(store.getState().dirty).toBe(false);
  });

  it("sets error on failure", async () => {
    mock.get.mockRejectedValueOnce(new Error("boom"));
    const store = makeStore();
    await store.getState().load("proj_1");
    expect(store.getState().error).toBe("boom");
    expect(store.getState().loading).toBe(false);
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

  it("importJson rejects invalid shape", () => {
    const store = makeStore();
    expect(() => store.getState().importJson('{"nodes": []}')).toThrow();
  });
});

describe("workflowStore.selectNode", () => {
  it("selects an existing node + finds its agent", async () => {
    const agents = [sampleAgent("writer")];
    mock.get.mockResolvedValueOnce(data(agents));
    const store = makeStore();
    await store.getState().load("p");
    store.getState().selectNode("writer");
    expect(store.getState().selected?.id).toBe("writer");
    expect(store.getState().selected?.agent?.name).toBe("writer");
  });

  it("selectNode with unknown id is a no-op", async () => {
    const agents = [sampleAgent("writer")];
    mock.get.mockResolvedValueOnce(data(agents));
    const store = makeStore();
    await store.getState().load("p");
    store.getState().selectNode("nope");
    expect(store.getState().selected).toBeNull();
  });
});

describe("workflowStore.saveAgent", () => {
  it("PUTs the agent and refreshes the registry", async () => {
    const agents = [sampleAgent("writer")];
    mock.get.mockResolvedValueOnce(data(agents)); // initial load
    mock.put.mockResolvedValueOnce(data(sampleAgent("writer")));
    const updated = [sampleAgent("writer")];
    updated[0].task = "new task";
    mock.get.mockResolvedValueOnce(data(updated)); // after save
    const store = makeStore();
    await store.getState().load("p1");
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
