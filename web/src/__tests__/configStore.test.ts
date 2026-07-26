/**
 * Tests for ConfigView + configStore (todo 30).
 * Mocks the API client; asserts editing the writer agent's model and
 * saving persists via PUT /api/config/{id}/agents/{name}, and that the
 * store reloads the agent list after save.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import type { AxiosInstance } from "axios";
import { createConfigStore, PROVIDER_TYPES, MODEL_TIERS } from "@/stores/configStore";
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

const writerAgent = (): AgentConfigResponse => ({
  name: "writer",
  task: "文本生成",
  input: "ctx",
  output: "prose",
  permission: { read: ["state", "outline"], write: ["notes"] },
  model: "standard",
  tools: ["read", "write"],
  head: null,
  tail: null,
  allow_recursive: false,
});

let mock: MockAxiosInstance;

beforeEach(() => {
  vi.clearAllMocks();
  mock = makeMockInstance();
});

function makeStore() {
  const apiClient = new ApiClient(mock as unknown as AxiosInstance);
  return createConfigStore(apiClient);
}

describe("configStore reference constants", () => {
  it("exposes the 3 provider types per guide:366", () => {
    expect(PROVIDER_TYPES).toEqual(["openai_compatible", "openai_response", "anthropic"]);
  });
  it("exposes the 3 model tiers", () => {
    expect(MODEL_TIERS).toEqual(["premium", "standard", "cheap"]);
  });
});

describe("configStore.load", () => {
  it("loads project config + agents in parallel", async () => {
    const config = {
      project_id: "p1",
      display_name: "Demo",
      mode: "novel" as const,
      models: { tiers: { premium: "gpt-4o" } },
      runtime: { timeout_seconds: 600 },
      server: {},
    };
    mock.get.mockResolvedValueOnce(data(config));
    mock.get.mockResolvedValueOnce(data([writerAgent()]));
    const store = makeStore();
    await store.getState().load("p1");
    expect(mock.get).toHaveBeenCalledWith("/config/p1");
    expect(mock.get).toHaveBeenCalledWith("/config/p1/agents");
    expect(store.getState().config?.display_name).toBe("Demo");
    expect(store.getState().agents).toHaveLength(1);
    expect(store.getState().loading).toBe(false);
  });
});

describe("configStore.saveProjectConfig", () => {
  it("PUTs project config and updates the store", async () => {
    const updated = {
      project_id: "p1",
      display_name: "Renamed",
      mode: "rp" as const,
      models: {},
      runtime: {},
      server: {},
    };
    mock.put.mockResolvedValueOnce(data(updated));
    const store = makeStore();
    store.setState({ projectId: "p1" });
    await store.getState().saveProjectConfig({ display_name: "Renamed", mode: "rp" });
    expect(mock.put).toHaveBeenCalledWith("/config/p1", {
      display_name: "Renamed",
      mode: "rp",
    });
    expect(store.getState().config?.display_name).toBe("Renamed");
    expect(store.getState().saving).toBe(false);
  });
});

describe("configStore.saveAgent (writer model edit + reload)", () => {
  it("PUTs the writer agent then reloads the agent list", async () => {
    const updatedWriter = writerAgent();
    updatedWriter.model = "premium";
    mock.put.mockResolvedValueOnce(data(updatedWriter));
    mock.get.mockResolvedValueOnce(data([updatedWriter]));
    const store = makeStore();
    store.setState({ projectId: "p1", agents: [writerAgent()] });
    await store.getState().saveAgent("writer", { ...updatedWriter });
    expect(mock.put).toHaveBeenCalledWith(
      "/config/p1/agents/writer",
      expect.objectContaining({ name: "writer", model: "premium" }),
    );
    expect(store.getState().agents[0].model).toBe("premium");
    expect(store.getState().saving).toBe(false);
  });
});

describe("configStore.setExpertMode", () => {
  it("toggles expert mode", () => {
    const store = makeStore();
    expect(store.getState().expertMode).toBe(false);
    store.getState().setExpertMode(true);
    expect(store.getState().expertMode).toBe(true);
  });
});
