/**
 * Tests for projectStore (zustand) â€?state + actions with mocked ApiClient.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import type { AxiosInstance } from "axios";
import { createProjectStore } from "@/stores/projectStore";
import { ApiClient } from "@/api/client";

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

let mock: MockAxiosInstance;

beforeEach(() => {
  vi.clearAllMocks();
  mock = makeMockInstance();
});

function makeStore() {
  const apiClient = new ApiClient(mock as unknown as AxiosInstance);
  return createProjectStore(apiClient);
}

describe("projectStore", () => {
  it("initial state is empty + idle", () => {
    const store = makeStore();
    expect(store.getState().projects).toEqual([]);
    expect(store.getState().activeProject).toBeNull();
    expect(store.getState().loading).toBe(false);
    expect(store.getState().error).toBeNull();
  });

  it("fetchProjects populates list + sets first active", async () => {
    const projects = [
      { id: "a", display_name: "A", mode: "novel" as const },
      { id: "b", display_name: "B", mode: "rp" as const },
    ];
    mock.get.mockResolvedValueOnce(data({ projects }));
    const store = makeStore();
    await store.getState().fetchProjects();
    expect(store.getState().projects).toEqual(projects);
    expect(store.getState().activeProject).toEqual(projects[0]);
    expect(store.getState().loading).toBe(false);
    expect(store.getState().error).toBeNull();
  });

  it("fetchProjects sets error on failure", async () => {
    mock.get.mockRejectedValueOnce(new Error("boom"));
    const store = makeStore();
    await store.getState().fetchProjects();
    expect(store.getState().projects).toEqual([]);
    expect(store.getState().error).toBe("boom");
    expect(store.getState().loading).toBe(false);
  });

  it("createProject creates then refreshes + sets active", async () => {
    mock.post.mockResolvedValueOnce(
      data({
        id: "c",
        display_name: "C",
        mode: "novel" as const,
        path: "/x",
      }),
    );
    mock.get.mockResolvedValueOnce(
      data({
        projects: [
          { id: "c", display_name: "C", mode: "novel" as const },
        ],
      }),
    );
    const store = makeStore();
    await store.getState().createProject("C", "novel");
    expect(mock.post).toHaveBeenCalledWith("/projects", {
      display_name: "C",
      mode: "novel",
    });
    expect(store.getState().projects).toHaveLength(1);
    expect(store.getState().activeProject?.id).toBe("c");
  });

  it("selectProject sets active when id matches", () => {
    const store = makeStore();
    store.setState({
      projects: [
        { id: "a", display_name: "A", mode: "novel" },
        { id: "b", display_name: "B", mode: "rp" },
      ],
    });
    store.getState().selectProject("b");
    expect(store.getState().activeProject?.id).toBe("b");
  });

  it("selectProject is a no-op when id not found", () => {
    const store = makeStore();
    store.setState({
      projects: [{ id: "a", display_name: "A", mode: "novel" }],
      activeProject: null,
    });
    store.getState().selectProject("zzz");
    expect(store.getState().activeProject).toBeNull();
  });

  it("deleteProject deletes then refreshes + clears active if needed", async () => {
    mock.delete.mockResolvedValueOnce({ status: 204 });
    mock.get.mockResolvedValueOnce(data({ projects: [] }));
    const store = makeStore();
    store.setState({
      projects: [{ id: "a", display_name: "A", mode: "novel" }],
      activeProject: { id: "a", display_name: "A", mode: "novel" },
    });
    await store.getState().deleteProject("a");
    expect(mock.delete).toHaveBeenCalledWith("/projects/a");
    expect(store.getState().projects).toEqual([]);
    expect(store.getState().activeProject).toBeNull();
  });

  it("clearError resets error to null", () => {
    const store = makeStore();
    store.setState({ error: "something" });
    store.getState().clearError();
    expect(store.getState().error).toBeNull();
  });
});
