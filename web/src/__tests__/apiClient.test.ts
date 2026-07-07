/**
 * Tests for the typed API client (web/src/api/client.ts).
 * Mocks axios so no network calls; asserts each method calls the right
 * HTTP verb + path and returns the typed shape.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import type { AxiosInstance } from "axios";
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

function asAxiosInstance(mock: MockAxiosInstance): AxiosInstance {
  return mock as unknown as AxiosInstance;
}

function data<T>(value: T): { data: T } {
  return { data: value };
}

let mock: MockAxiosInstance;

beforeEach(() => {
  vi.clearAllMocks();
  mock = makeMockInstance();
});

function client(): ApiClient {
  return new ApiClient(asAxiosInstance(mock));
}

describe("ApiClient.projects", () => {
  it("listProjects GET /projects -> ProjectListResponse", async () => {
    const payload = {
      projects: [
        { id: "abc", display_name: "Demo", mode: "novel" as const },
      ],
    };
    mock.get.mockResolvedValueOnce(data(payload));
    const c = client();
    const result = await c.listProjects();
    expect(mock.get).toHaveBeenCalledWith("/projects");
    expect(result).toEqual(payload);
  });

  it("createProject POST /projects with body", async () => {
    const payload = {
      id: "abc",
      display_name: "Demo",
      mode: "novel" as const,
      path: "/workspaces/abc",
    };
    mock.post.mockResolvedValueOnce(data(payload));
    const c = client();
    const result = await c.createProject("Demo", "novel");
    expect(mock.post).toHaveBeenCalledWith("/projects", {
      display_name: "Demo",
      mode: "novel",
    });
    expect(result).toEqual(payload);
  });

  it("getProject GET /projects/{id}", async () => {
    mock.get.mockResolvedValueOnce(
      data({
        id: "abc",
        display_name: "Demo",
        mode: "novel" as const,
        path: "/x",
      }),
    );
    const c = client();
    await c.getProject("abc");
    expect(mock.get).toHaveBeenCalledWith("/projects/abc");
  });

  it("patchProject PATCH /projects/{id}", async () => {
    mock.patch.mockResolvedValueOnce(
      data({
        id: "abc",
        display_name: "Renamed",
        mode: "rp" as const,
        path: "/x",
      }),
    );
    const c = client();
    await c.patchProject("abc", { mode: "rp" });
    expect(mock.patch).toHaveBeenCalledWith("/projects/abc", { mode: "rp" });
  });

  it("deleteProject DELETE /projects/{id}", async () => {
    mock.delete.mockResolvedValueOnce({ status: 204 });
    const c = client();
    await c.deleteProject("abc");
    expect(mock.delete).toHaveBeenCalledWith("/projects/abc");
  });
});

describe("ApiClient.workflow", () => {
  it("runWorkflow POST /workflow/{id}/run", async () => {
    mock.post.mockResolvedValueOnce(
      data({
        round_id: "round_1",
        state: "pending" as const,
        logs: [],
        result: null,
        error: null,
      }),
    );
    const c = client();
    await c.runWorkflow("abc");
    expect(mock.post).toHaveBeenCalledWith("/workflow/abc/run", {});
  });

  it("getRound GET /workflow/{id}/round/{rid}", async () => {
    mock.get.mockResolvedValueOnce(
      data({
        round_id: "round_1",
        state: "completed" as const,
        logs: [],
        result: null,
        error: null,
      }),
    );
    const c = client();
    await c.getRound("abc", "round_1");
    expect(mock.get).toHaveBeenCalledWith("/workflow/abc/round/round_1");
  });

  it("stopWorkflow POST /workflow/{id}/stop", async () => {
    mock.post.mockResolvedValueOnce(
      data({
        round_id: "round_1",
        state: "failed" as const,
        logs: [],
        result: null,
        error: null,
      }),
    );
    const c = client();
    await c.stopWorkflow("abc");
    expect(mock.post).toHaveBeenCalledWith("/workflow/abc/stop");
  });
});

describe("ApiClient.chat", () => {
  it("listChat GET /chat/{id}", async () => {
    mock.get.mockResolvedValueOnce(data([]));
    const c = client();
    await c.listChat("abc");
    expect(mock.get).toHaveBeenCalledWith("/chat/abc");
  });

  it("sendChat POST /chat/{id} with content", async () => {
    mock.post.mockResolvedValueOnce(
      data({
        user_message: {
          message_id: "msg_1",
          role: "user" as const,
          content: "hi",
          turn_id: "turn_1",
          timestamp: "t",
        },
        director_message: null,
      }),
    );
    const c = client();
    await c.sendChat("abc", "hi");
    expect(mock.post).toHaveBeenCalledWith("/chat/abc", { content: "hi" });
  });

  it("deleteChat DELETE /chat/{id}/{mid}", async () => {
    mock.delete.mockResolvedValueOnce(data([]));
    const c = client();
    await c.deleteChat("abc", "msg_1");
    expect(mock.delete).toHaveBeenCalledWith("/chat/abc/msg_1");
  });

  it("retryChat POST /chat/{id}/{mid}/retry", async () => {
    mock.post.mockResolvedValueOnce(
      data({
        branch: "br",
        user_message: {
          message_id: "msg_1",
          role: "user" as const,
          content: "hi",
          turn_id: "turn_1",
          timestamp: "t",
        },
        director_message: null,
      }),
    );
    const c = client();
    await c.retryChat("abc", "msg_1");
    expect(mock.post).toHaveBeenCalledWith("/chat/abc/msg_1/retry");
  });
});

describe("ApiClient.resources", () => {
  it("listResources GET /resources/{id}", async () => {
    mock.get.mockResolvedValueOnce(
      data({ project_id: "abc", resources: [] }),
    );
    const c = client();
    await c.listResources("abc");
    expect(mock.get).toHaveBeenCalledWith("/resources/abc");
  });

  it("getResource GET /resources/{id}/{type}", async () => {
    mock.get.mockResolvedValueOnce(
      data({
        project_id: "abc",
        type: "state",
        title: "current-state",
        read_only: false,
        content: "x",
        files: ["content.md"],
      }),
    );
    const c = client();
    await c.getResource("abc", "state");
    expect(mock.get).toHaveBeenCalledWith("/resources/abc/state");
  });

  it("putResource PUT /resources/{id}/{type} with content only", async () => {
    mock.put.mockResolvedValueOnce(
      data({
        project_id: "abc",
        type: "state",
        title: "current-state",
        read_only: false,
        content: "new",
        files: ["content.md"],
      }),
    );
    const c = client();
    await c.putResource("abc", "state", "new");
    expect(mock.put).toHaveBeenCalledWith("/resources/abc/state", {
      content: "new",
    });
  });

  it("putResource PUT with filename includes it", async () => {
    mock.put.mockResolvedValueOnce(
      data({
        project_id: "abc",
        type: "state",
        title: "current-state",
        read_only: false,
        content: "new",
        files: ["scene.md"],
      }),
    );
    const c = client();
    await c.putResource("abc", "state", "new", "scene.md");
    expect(mock.put).toHaveBeenCalledWith("/resources/abc/state", {
      content: "new",
      filename: "scene.md",
    });
  });

  it("resourceHistory GET /resources/{id}/{type}/history", async () => {
    mock.get.mockResolvedValueOnce(
      data({ project_id: "abc", type: "state", commits: [] }),
    );
    const c = client();
    await c.resourceHistory("abc", "state");
    expect(mock.get).toHaveBeenCalledWith("/resources/abc/state/history");
  });
});

describe("ApiClient.config", () => {
  it("getGlobalConfig GET /config", async () => {
    mock.get.mockResolvedValueOnce(
      data({
        project_id: "",
        display_name: null,
        mode: null,
        models: {},
        runtime: {},
        server: {},
      }),
    );
    const c = client();
    await c.getGlobalConfig();
    expect(mock.get).toHaveBeenCalledWith("/config");
  });

  it("putGlobalConfig PUT /config", async () => {
    mock.put.mockResolvedValueOnce(
      data({
        project_id: "",
        display_name: null,
        mode: null,
        models: { a: 1 },
        runtime: {},
        server: {},
      }),
    );
    const c = client();
    await c.putGlobalConfig({ models: { a: 1 } });
    expect(mock.put).toHaveBeenCalledWith("/config", { models: { a: 1 } });
  });

  it("getProjectConfig GET /config/{id}", async () => {
    mock.get.mockResolvedValueOnce(
      data({
        project_id: "abc",
        display_name: "Demo",
        mode: "novel" as const,
        models: {},
        runtime: {},
        server: {},
      }),
    );
    const c = client();
    await c.getProjectConfig("abc");
    expect(mock.get).toHaveBeenCalledWith("/config/abc");
  });

  it("putProjectConfig PUT /config/{id}", async () => {
    mock.put.mockResolvedValueOnce(
      data({
        project_id: "abc",
        display_name: "Demo",
        mode: "novel" as const,
        models: {},
        runtime: {},
        server: {},
      }),
    );
    const c = client();
    await c.putProjectConfig("abc", { display_name: "Demo" });
    expect(mock.put).toHaveBeenCalledWith("/config/abc", {
      display_name: "Demo",
    });
  });

  it("getAgents GET /config/{id}/agents", async () => {
    mock.get.mockResolvedValueOnce(data([]));
    const c = client();
    await c.getAgents("abc");
    expect(mock.get).toHaveBeenCalledWith("/config/abc/agents");
  });

  it("putAgent PUT /config/{id}/agents/{name}", async () => {
    const body = {
      name: "writer",
      task: "write",
      input: "ctx",
      output: "prose",
      permission: { read: ["state"] },
      model: null,
      skills: [],
      tools: [],
      head: null,
      tail: null,
      allow_recursive: true,
    };
    mock.put.mockResolvedValueOnce(data(body));
    const c = client();
    await c.putAgent("abc", "writer", body);
    expect(mock.put).toHaveBeenCalledWith("/config/abc/agents/writer", body);
  });
});

describe("ApiClient.novel", () => {
  it("listChapters GET /novel/{id}", async () => {
    mock.get.mockResolvedValueOnce(
      data({ project_id: "abc", chapters: [] }),
    );
    const c = client();
    await c.listChapters("abc");
    expect(mock.get).toHaveBeenCalledWith("/novel/abc");
  });

  it("readChapter GET /novel/{id}/{chapter}", async () => {
    mock.get.mockResolvedValueOnce(
      data({
        project_id: "abc",
        filename: "chapter_01.txt",
        chapter_number: 1,
        content: "body",
      }),
    );
    const c = client();
    await c.readChapter("abc", "chapter_01.txt");
    expect(mock.get).toHaveBeenCalledWith("/novel/abc/chapter_01.txt");
  });
});

describe("ApiClient.import", () => {
  it("postImport POST /import", async () => {
    mock.post.mockResolvedValueOnce({ status: 501 });
    const c = client();
    await expect(c.postImport({ source: "card.json" })).resolves.toBeUndefined();
    expect(mock.post).toHaveBeenCalledWith("/import", { source: "card.json" });
  });
});
