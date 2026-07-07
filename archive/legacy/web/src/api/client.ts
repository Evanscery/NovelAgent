// 后端 API 客户端。所有请求经此处统一处理 JSON 与错误，
// 视图/store 只调用这些函数，不直接 fetch（保持窄契约、可插拔）。

export interface StoryItem {
  name: string
  path: string
}

export interface StoryPayload {
  project: string
  state: string
  player_visible: string
  summaries: string
  index: string
  chapters: string[]
  archives: string[]
  evaluation: string
  journal: string
  last_response: string
  card_ir: string
  runtime_plan: string
}

export interface CardPayload {
  card_view: {
    name: string
    persona: string
    opening: string
    alternate_greetings: string[]
    world_rules: string[]
  }
  card_html: string
  widgets: { html: string; scripts: any[]; total_matches: number; source_chars: number }
  front_script_count: number
}

export interface FileEntry {
  rel: string
  dir: string
  name: string
  suffix: string
  size: number
}

export interface RunJob {
  job_id: string
  kind: string
  status: 'pending' | 'running' | 'done' | 'error'
  result: any
  error: string | null
  logs: string[]
}

// NOVEL-A2：小说阅读通道（只读）。
export interface ChapterSummary {
  number: number
  file: string
  title: string
  char_count: number
  size: number
  scene_ids: string[]
}
export interface SceneSummary {
  scene_id: string
  chapter: number
  char_count: number
  size: number
}
export interface NovelIndex {
  path: string
  chapters: ChapterSummary[]
  scenes: SceneSummary[]
  has_novel: boolean
}
export interface ChapterContent {
  path: string
  chapter: number
  file: string
  title: string
  body: string
  char_count: number
}
export interface SceneContent {
  path: string
  scene_id: string
  chapter: number
  body: string
  char_count: number
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// 可启动的后台运行任务类型。后端 VALID_KINDS（api_run.py）为唯一真相源，
// 未知 kind 会被后端以 400 拒绝（非 500），故前端用联合类型在编译期收窄。
export type RunKind = 'run-scene' | 'rp-turn' | 'import' | 'init-story' | 'write-book' | 'evaluate-book'

// createWorkspace 返回：未传 runner 时仅 {name,path}；
// 传入合法 runner 时附带 job_id（bootstrap 后台任务句柄）。
export interface CreateWorkspaceResponse extends StoryItem {
  job_id?: string
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const opts: RequestInit = { method, headers: {} }
  if (body !== undefined) {
    opts.headers = { 'Content-Type': 'application/json' }
    opts.body = JSON.stringify(body)
  }
  const res = await fetch(url, opts)
  const text = await res.text()
  let data: any = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }
  if (!res.ok) {
    const msg = data && typeof data === 'object' && data.error ? data.error : `HTTP ${res.status}`
    throw new ApiError(res.status, msg)
  }
  return data as T
}

export const api = {
  // 读
  listStories: () => request<StoryItem[]>('GET', '/api/stories'),
  getStory: (path: string) => request<StoryPayload>('GET', `/api/story?path=${encodeURIComponent(path)}`),
  getCard: (path: string) => request<CardPayload>('GET', `/api/card?path=${encodeURIComponent(path)}`),

  // 工作区
  createWorkspace: (name: string, theme: string, runner?: string) => {
    const body: Record<string, string> = { name, theme }
    if (runner) body.runner = runner
    return request<CreateWorkspaceResponse>('POST', '/api/workspace', body)
  },
  deleteWorkspace: (path: string) =>
    request<{ deleted: boolean }>('DELETE', `/api/workspace?path=${encodeURIComponent(path)}`),

  // 文件
  listFiles: (path: string) =>
    request<{ path: string; files: FileEntry[]; editable_dirs: string[] }>(
      'GET',
      `/api/files?path=${encodeURIComponent(path)}`,
    ),
  readFile: (path: string, rel: string) =>
    request<{ rel: string; content: string; suffix: string }>(
      'GET',
      `/api/file?path=${encodeURIComponent(path)}&rel=${encodeURIComponent(rel)}`,
    ),
  writeFile: (path: string, rel: string, content: string) =>
    request<{ saved: boolean; bytes: number }>('PUT', '/api/file', { path, rel, content }),
  moveFile: (path: string, src: string, dst: string, overwrite?: boolean) => {
    const body: Record<string, unknown> = { path, src, dst }
    if (overwrite) body.overwrite = true
    return request<{ path: string; src: string; dst: string; moved: boolean }>('POST', '/api/file/move', body)
  },

  // 配置
  listConfigs: () => request<{ configs: { name: string; exists: boolean }[] }>('GET', '/api/configs'),
  readConfig: (name: string) => request<{ name: string; content: string }>('GET', `/api/config?name=${encodeURIComponent(name)}`),
  writeConfig: (name: string, content: string) =>
    request<{ saved: boolean }>('PUT', '/api/config', { name, content }),

  // RP
  rpTurn: (story_path: string, text: string, resolve?: { scene_id: string; notation: string; total: number }) =>
    request<any>('POST', '/api/rp-turn', resolve ? { story_path, resolve } : { story_path, text }),

  // 小说阅读（只读）
  listNovel: (path: string) =>
    request<NovelIndex>('GET', `/api/novel?path=${encodeURIComponent(path)}`),
  readChapter: (path: string, chapter: string) =>
    request<ChapterContent>('GET', `/api/novel/chapter?path=${encodeURIComponent(path)}&chapter=${encodeURIComponent(chapter)}`),
  readScene: (path: string, sceneId: string) =>
    request<SceneContent>('GET', `/api/novel/scene?path=${encodeURIComponent(path)}&scene_id=${encodeURIComponent(sceneId)}`),

  // 运行
  startRun: (kind: RunKind, params: Record<string, unknown>) =>
    request<RunJob>('POST', '/api/run', { kind, ...params }),
  getJob: (jobId: string) => request<RunJob>('GET', `/api/run/${encodeURIComponent(jobId)}`),
}
