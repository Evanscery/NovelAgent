/**
 * Typed API client — wires to FastAPI backend (app/api/routes/*).
 *
 * Backend route prefixes (verified from app/api/routes/*.py):
 *   /api/projects  /api/workflow  /api/chat  /api/resources
 *   /api/config    /api/novel     /api/import
 *
 * Schemas mirror app/api/schemas.py exactly (Pydantic v2 wire contract).
 * NO `as any`, NO @ts-ignore — strict types end to end.
 */

import axios, { type AxiosInstance } from "axios";

// ── Wire types (mirror app/api/schemas.py) ────────────────────────────────

export type ProjectMode = "novel" | "rp";
export type ChatMessageRole = "user" | "director" | "system";
export type RoundState = "pending" | "running" | "completed" | "failed";

export interface ProjectSummary {
  id: string;
  display_name: string;
  mode: ProjectMode;
}

export interface ProjectResponse {
  id: string;
  display_name: string;
  mode: ProjectMode;
  path: string;
}

export interface ProjectListResponse {
  projects: ProjectSummary[];
}

export interface PatchProjectRequest {
  display_name?: string;
  mode?: ProjectMode;
}

export interface CreateProjectRequest {
  display_name: string;
  mode: ProjectMode;
}

export interface ChatMessage {
  message_id: string;
  role: ChatMessageRole;
  content: string;
  turn_id: string;
  timestamp: string;
}

export interface ChatResponse {
  user_message: ChatMessage;
  director_message: ChatMessage | null;
}

export interface RetryResponse {
  branch: string;
  user_message: ChatMessage;
  director_message: ChatMessage | null;
}

export interface RunWorkflowRequest {
  context?: string;
  max_iterations?: number;
  maximal_recursive_calling_depth?: number;
}

export interface RoundResultSummary {
  completed_agents: string[];
  finalize_reason: string;
  total_tokens: number;
  recursive_calls: Array<Record<string, unknown>>;
  rejected_calls: Array<Record<string, unknown>>;
}

export interface RoundStatusResponse {
  round_id: string;
  state: RoundState;
  logs: string[];
  result: RoundResultSummary | null;
  error: string | null;
}

export interface ResourceListEntry {
  type: string;
  title: string;
  exists: boolean;
  file_count: number;
  content_summary: string;
}

export interface ResourceListResponse {
  project_id: string;
  resources: ResourceListEntry[];
}

export interface ResourceContentResponse {
  project_id: string;
  type: string;
  title: string;
  read_only: boolean;
  content: string;
  files: string[];
}

export interface PutResourceRequest {
  content: string;
  filename?: string;
}

export interface ResourceHistoryEntry {
  sha: string;
  turn_id: string;
  message: string;
  timestamp: string;
  branch: string;
}

export interface ResourceHistoryResponse {
  project_id: string;
  type: string;
  commits: ResourceHistoryEntry[];
}

export interface ConfigResponse {
  project_id: string;
  display_name: string | null;
  mode: ProjectMode | null;
  models: Record<string, unknown>;
  runtime: Record<string, unknown>;
  server: Record<string, unknown>;
}

export interface PutGlobalConfigRequest {
  models?: Record<string, unknown>;
  runtime?: Record<string, unknown>;
  server?: Record<string, unknown>;
}

export interface PutProjectConfigRequest {
  display_name?: string;
  mode?: ProjectMode;
  models?: Record<string, unknown>;
  runtime?: Record<string, unknown>;
  server?: Record<string, unknown>;
}

export interface AgentConfigResponse {
  name: string;
  task: string;
  input: string;
  output: string;
  permission: Record<string, string[]>;
  model: string | null;
  skills: string[];
  tools: string[];
  head: string | null;
  tail: string | null;
  allow_recursive: boolean;
}

export interface PutAgentConfigRequest {
  name: string;
  task: string;
  input: string;
  output: string;
  permission: Record<string, string[]>;
  model: string | null;
  skills: string[];
  tools: string[];
  head: string | null;
  tail: string | null;
  allow_recursive: boolean;
}

export interface NovelChapterSummary {
  filename: string;
  chapter_number: number | null;
  size_bytes: number;
}

export interface NovelChapterListResponse {
  project_id: string;
  chapters: NovelChapterSummary[];
}

export interface NovelChapterResponse {
  project_id: string;
  filename: string;
  chapter_number: number | null;
  content: string;
}

export interface ImportRequest {
  source?: string | null;
  project_id?: string | null;
  format?: string | null;
}

// ── Client ────────────────────────────────────────────────────────────────

const defaultInstance: AxiosInstance = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
  timeout: 30_000,
});

export class ApiClient {
  private readonly http: AxiosInstance;

  constructor(instance: AxiosInstance = defaultInstance) {
    this.http = instance;
  }

  // ── projects: /api/projects ────────────────────────────────────────────
  async listProjects(): Promise<ProjectListResponse> {
    const res = await this.http.get<ProjectListResponse>("/projects");
    return res.data;
  }

  async createProject(
    displayName: string,
    mode: ProjectMode,
  ): Promise<ProjectResponse> {
    const res = await this.http.post<ProjectResponse>("/projects", {
      display_name: displayName,
      mode,
    } satisfies CreateProjectRequest);
    return res.data;
  }

  async getProject(id: string): Promise<ProjectResponse> {
    const res = await this.http.get<ProjectResponse>(
      `/projects/${encodeURIComponent(id)}`,
    );
    return res.data;
  }

  async patchProject(
    id: string,
    data: PatchProjectRequest,
  ): Promise<ProjectResponse> {
    const res = await this.http.patch<ProjectResponse>(
      `/projects/${encodeURIComponent(id)}`,
      data,
    );
    return res.data;
  }

  async deleteProject(id: string): Promise<void> {
    await this.http.delete(`/projects/${encodeURIComponent(id)}`);
  }

  // ── workflow: /api/workflow ────────────────────────────────────────────
  async runWorkflow(
    projectId: string,
    body: RunWorkflowRequest = {},
  ): Promise<RoundStatusResponse> {
    const res = await this.http.post<RoundStatusResponse>(
      `/workflow/${encodeURIComponent(projectId)}/run`,
      body,
    );
    return res.data;
  }

  async getRound(
    projectId: string,
    roundId: string,
  ): Promise<RoundStatusResponse> {
    const res = await this.http.get<RoundStatusResponse>(
      `/workflow/${encodeURIComponent(projectId)}/round/${encodeURIComponent(roundId)}`,
    );
    return res.data;
  }

  async stopWorkflow(projectId: string): Promise<RoundStatusResponse> {
    const res = await this.http.post<RoundStatusResponse>(
      `/workflow/${encodeURIComponent(projectId)}/stop`,
    );
    return res.data;
  }

  // ── chat: /api/chat ────────────────────────────────────────────────────
  async listChat(projectId: string): Promise<ChatMessage[]> {
    const res = await this.http.get<ChatMessage[]>(
      `/chat/${encodeURIComponent(projectId)}`,
    );
    return res.data;
  }

  async sendChat(projectId: string, text: string): Promise<ChatResponse> {
    const res = await this.http.post<ChatResponse>(
      `/chat/${encodeURIComponent(projectId)}`,
      { content: text },
    );
    return res.data;
  }

  async deleteChat(projectId: string, messageId: string): Promise<ChatMessage[]> {
    const res = await this.http.delete<ChatMessage[]>(
      `/chat/${encodeURIComponent(projectId)}/${encodeURIComponent(messageId)}`,
    );
    return res.data;
  }

  async retryChat(
    projectId: string,
    messageId: string,
  ): Promise<RetryResponse> {
    const res = await this.http.post<RetryResponse>(
      `/chat/${encodeURIComponent(projectId)}/${encodeURIComponent(messageId)}/retry`,
    );
    return res.data;
  }

  // ── resources: /api/resources ──────────────────────────────────────────
  async listResources(projectId: string): Promise<ResourceListResponse> {
    const res = await this.http.get<ResourceListResponse>(
      `/resources/${encodeURIComponent(projectId)}`,
    );
    return res.data;
  }

  async getResource(
    projectId: string,
    type: string,
  ): Promise<ResourceContentResponse> {
    const res = await this.http.get<ResourceContentResponse>(
      `/resources/${encodeURIComponent(projectId)}/${encodeURIComponent(type)}`,
    );
    return res.data;
  }

  async putResource(
    projectId: string,
    type: string,
    content: string,
    filename?: string,
  ): Promise<ResourceContentResponse> {
    const body: PutResourceRequest =
      filename === undefined ? { content } : { content, filename };
    const res = await this.http.put<ResourceContentResponse>(
      `/resources/${encodeURIComponent(projectId)}/${encodeURIComponent(type)}`,
      body,
    );
    return res.data;
  }

  async resourceHistory(
    projectId: string,
    type: string,
  ): Promise<ResourceHistoryResponse> {
    const res = await this.http.get<ResourceHistoryResponse>(
      `/resources/${encodeURIComponent(projectId)}/${encodeURIComponent(type)}/history`,
    );
    return res.data;
  }

  // ── config: /api/config ────────────────────────────────────────────────
  async getGlobalConfig(): Promise<ConfigResponse> {
    const res = await this.http.get<ConfigResponse>("/config");
    return res.data;
  }

  async putGlobalConfig(data: PutGlobalConfigRequest): Promise<ConfigResponse> {
    const res = await this.http.put<ConfigResponse>("/config", data);
    return res.data;
  }

  async getProjectConfig(projectId: string): Promise<ConfigResponse> {
    const res = await this.http.get<ConfigResponse>(
      `/config/${encodeURIComponent(projectId)}`,
    );
    return res.data;
  }

  async putProjectConfig(
    projectId: string,
    data: PutProjectConfigRequest,
  ): Promise<ConfigResponse> {
    const res = await this.http.put<ConfigResponse>(
      `/config/${encodeURIComponent(projectId)}`,
      data,
    );
    return res.data;
  }

  async getAgents(projectId: string): Promise<AgentConfigResponse[]> {
    const res = await this.http.get<AgentConfigResponse[]>(
      `/config/${encodeURIComponent(projectId)}/agents`,
    );
    return res.data;
  }

  async putAgent(
    projectId: string,
    name: string,
    data: PutAgentConfigRequest,
  ): Promise<AgentConfigResponse> {
    const res = await this.http.put<AgentConfigResponse>(
      `/config/${encodeURIComponent(projectId)}/agents/${encodeURIComponent(name)}`,
      data,
    );
    return res.data;
  }

  // ── novel: /api/novel ──────────────────────────────────────────────────
  async listChapters(projectId: string): Promise<NovelChapterListResponse> {
    const res = await this.http.get<NovelChapterListResponse>(
      `/novel/${encodeURIComponent(projectId)}`,
    );
    return res.data;
  }

  async readChapter(
    projectId: string,
    chapter: string,
  ): Promise<NovelChapterResponse> {
    const res = await this.http.get<NovelChapterResponse>(
      `/novel/${encodeURIComponent(projectId)}/${encodeURIComponent(chapter)}`,
    );
    return res.data;
  }

  // ── import: /api/import ────────────────────────────────────────────────
  async postImport(data: ImportRequest): Promise<void> {
    await this.http.post("/import", data);
  }
}

export const api = new ApiClient();
export default api;
