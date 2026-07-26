/**
 * ConfigView — centralized config (todo 30, guide:362-384).
 *
 * Two sections:
 *  1. Project config — display_name + mode (novel/rp) + models/runtime
 *     blobs (raw yaml-shape editing in expert mode).
 *  2. Per-agent config — one card per agent editing Name/Task/Model/
 *     Skills/Tools/Permission/Input/Output/allow_recursive; expert mode
 *     reveals head/tail. Save posts to PUT /api/config/{id}/agents/{name}.
 *
 * Default mode = 傻瓜式 (guide:353): only the friendly fields show;
 * Expert toggle (guide:355) reveals advanced fields + raw model yaml.
 * Per guide:378-384 the canvas/config saves CONFIG not PROMPT — the
 * parser generates prompts at runtime.
 */

import {
  useEffect,
  useMemo,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { z } from "zod";
import { useConfigStore, PROVIDER_TYPES, MODEL_TIERS } from "@/stores/configStore";
import { useProjectStore } from "@/stores/projectStore";
import type {
  AgentConfigResponse,
  ProjectMode,
  PutAgentConfigRequest,
  PutProjectConfigRequest,
} from "@/api/client";

function ProjectConfigSection({
  displayName,
  mode,
  expertMode,
  saving,
  onSave,
}: {
  displayName: string;
  mode: ProjectMode;
  expertMode: boolean;
  saving: boolean;
  onSave: (data: PutProjectConfigRequest) => void;
}): ReactNode {
  const [name, setName] = useState(displayName);
  const [projMode, setProjMode] = useState<ProjectMode>(mode);
  useEffect(() => {
    setName(displayName);
    setProjMode(mode);
  }, [displayName, mode]);

  const [modelsYaml, setModelsYaml] = useState("");
  const [runtimeYaml, setRuntimeYaml] = useState("");

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const data: PutProjectConfigRequest = {
      display_name: name,
      mode: projMode,
    };
    if (expertMode) {
      try {
        if (modelsYaml.trim()) data.models = z.record(z.unknown()).parse(JSON.parse(modelsYaml));
        if (runtimeYaml.trim()) data.runtime = z.record(z.unknown()).parse(JSON.parse(runtimeYaml));
      } catch {
        window.alert("models/runtime 必须是合法 JSON 对象");
        return;
      }
    }
    onSave(data);
  };

  return (
    <form className="config-section" onSubmit={handleSubmit}>
      <h2 className="view__title">项目配置</h2>
      <label className="field">
        <span className="field__label">项目名称</span>
        <input
          className="field__input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </label>
      <label className="field">
        <span className="field__label">模式</span>
        <select
          className="field__select"
          value={projMode}
          onChange={(e) => {
            const val = e.target.value;
            if (val !== "novel" && val !== "rp") return;
            setProjMode(val);
          }}
        >
          <option value="novel">小说创作</option>
          <option value="rp">RP 互动</option>
        </select>
      </label>
      {expertMode && (
        <>
          <label className="field">
            <span className="field__label">Models（JSON 覆盖，专家模式）</span>
            <textarea
              className="field__input"
              rows={4}
              value={modelsYaml}
              onChange={(e) => setModelsYaml(e.target.value)}
              placeholder='{"tiers": {"premium": "gpt-4o"}}'
            />
          </label>
          <label className="field">
            <span className="field__label">Runtime（JSON 覆盖，专家模式）</span>
            <textarea
              className="field__input"
              rows={4}
              value={runtimeYaml}
              onChange={(e) => setRuntimeYaml(e.target.value)}
              placeholder='{"timeout_seconds": 600}'
            />
          </label>
        </>
      )}
      <div className="agent-form__actions">
        <button type="submit" className="btn btn--primary" disabled={saving}>
          {saving ? "保存中…" : "保存项目配置"}
        </button>
      </div>
    </form>
  );
}

function AgentConfigCard({
  agent,
  expertMode,
  saving,
  onSave,
}: {
  agent: AgentConfigResponse;
  expertMode: boolean;
  saving: boolean;
  onSave: (data: PutAgentConfigRequest) => void;
}): ReactNode {
  const [form, setForm] = useState<PutAgentConfigRequest>({ ...agent });
  useEffect(() => {
    setForm({ ...agent });
  }, [agent]);

  const set = <K extends keyof PutAgentConfigRequest>(
    key: K,
    value: PutAgentConfigRequest[K],
  ): void => {
    setForm((f) => ({ ...f, [key]: value }));
  };

  const setPerm = (action: string, raw: string) => {
    const vector = raw.split(",").map((s) => s.trim()).filter(Boolean);
    setForm((f) => ({ ...f, permission: { ...f.permission, [action]: vector } }));
  };

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    onSave(form);
  };

  return (
    <form className="config-section" onSubmit={handleSubmit}>
      <h3 className="config-section__title">Agent · {agent.name}</h3>
      <label className="field">
        <span className="field__label">Name</span>
        <input
          className="field__input"
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
          required
        />
      </label>
      <label className="field">
        <span className="field__label">Task</span>
        <textarea
          className="field__input"
          rows={2}
          value={form.task}
          onChange={(e) => set("task", e.target.value)}
          required
        />
      </label>
      <label className="field">
        <span className="field__label">Model</span>
        <input
          className="field__input"
          value={form.model ?? ""}
          onChange={(e) => set("model", e.target.value || null)}
          placeholder="（使用全局默认）"
        />
      </label>
      <label className="field">
        <span className="field__label">Tools（逗号分隔）</span>
        <input
          className="field__input"
          value={form.tools.join(", ")}
          onChange={(e) =>
            set("tools", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))
          }
        />
      </label>
      <label className="field">
        <span className="field__label">Permission.read</span>
        <input
          className="field__input"
          value={form.permission.read?.join(", ") ?? ""}
          onChange={(e) => setPerm("read", e.target.value)}
        />
      </label>
      <label className="field">
        <span className="field__label">Permission.write</span>
        <input
          className="field__input"
          value={form.permission.write?.join(", ") ?? ""}
          onChange={(e) => setPerm("write", e.target.value)}
        />
      </label>
      <label className="field">
        <span className="field__label">Input</span>
        <input
          className="field__input"
          value={form.input}
          onChange={(e) => set("input", e.target.value)}
        />
      </label>
      <label className="field">
        <span className="field__label">Output</span>
        <input
          className="field__input"
          value={form.output}
          onChange={(e) => set("output", e.target.value)}
        />
      </label>
      <label className="field field--checkbox">
        <input
          type="checkbox"
          checked={form.allow_recursive}
          onChange={(e) => set("allow_recursive", e.target.checked)}
        />
        <span className="field__label">允许递归调用</span>
      </label>
      {expertMode && (
        <>
          <label className="field">
            <span className="field__label">Head（专家模式）</span>
            <textarea
              className="field__input"
              rows={2}
              value={form.head ?? ""}
              onChange={(e) => set("head", e.target.value || null)}
            />
          </label>
          <label className="field">
            <span className="field__label">Tail（专家模式）</span>
            <textarea
              className="field__input"
              rows={2}
              value={form.tail ?? ""}
              onChange={(e) => set("tail", e.target.value || null)}
            />
          </label>
        </>
      )}
      <div className="agent-form__actions">
        <button type="submit" className="btn btn--primary" disabled={saving}>
          保存 {agent.name}
        </button>
      </div>
    </form>
  );
}

function ProviderReferencePanel(): ReactNode {
  /** Static reference card per guide:366 — provider types + model tiers. */
  return (
    <aside className="config-section">
      <h2 className="view__title">供应商 / 模型 参考速查</h2>
      <p className="overview__empty-hint">
        可用的 Provider 类型（在 models.yaml 中按 provider.type 指定）：
      </p>
      <ul className="config-ref">
        {PROVIDER_TYPES.map((t) => (
          <li key={t}><code>{t}</code></li>
        ))}
      </ul>
      <p className="overview__empty-hint">模型档位：</p>
      <ul className="config-ref">
        {MODEL_TIERS.map((t) => (
          <li key={t}><code>{t}</code></li>
        ))}
      </ul>
      <p className="overview__empty-hint">
        切换专家模式以编辑 models/runtime 的 JSON 覆盖。
      </p>
    </aside>
  );
}

export default function ConfigView(): ReactNode {
  const {
    config,
    agents,
    expertMode,
    loading,
    saving,
    error,
    load,
    setExpertMode,
    saveProjectConfig,
    saveAgent,
    clearError,
  } = useConfigStore();
  const activeProject = useProjectStore((s) => s.activeProject);
  const projectId = useConfigStore((s) => s.projectId);

  useEffect(() => {
    if (activeProject && activeProject.id !== projectId) {
      void load(activeProject.id);
    }
  }, [activeProject, projectId, load]);

  const displayName = useMemo(() => {
    if (config?.display_name) return config.display_name;
    if (activeProject) return activeProject.display_name;
    return "";
  }, [config, activeProject]);
  const mode: ProjectMode = config?.mode ?? activeProject?.mode ?? "novel";

  return (
    <section className="view config-view">
      <header className="view__header">
        <h1 className="view__title">配置</h1>
        <label className="field field--checkbox field--inline">
          <input
            type="checkbox"
            checked={expertMode}
            onChange={(e) => setExpertMode(e.target.checked)}
          />
          <span className="field__label">专家模式</span>
        </label>
      </header>

      {error !== null && (
        <p className="overview__error">
          出错了：{error}
          <button type="button" className="btn btn--sm" onClick={clearError}>
            关闭
          </button>
        </p>
      )}
      {loading && <p className="overview__loading">加载中…</p>}
      {!activeProject && <p className="overview__empty-hint">请先在概览页选择一个项目。</p>}

      {activeProject && (
        <div className="config-view__body">
          <ProjectConfigSection
            displayName={displayName}
            mode={mode}
            expertMode={expertMode}
            saving={saving}
            onSave={(d) => void saveProjectConfig(d)}
          />
          <ProviderReferencePanel />
          <section className="config-view__agents">
            <h2 className="view__title">Agent 配置</h2>
            {agents.length === 0 && (
              <p className="overview__empty-hint">未加载到 Agent。点击下方刷新。</p>
            )}
            {agents.map((a) => (
              <AgentConfigCard
                key={a.name}
                agent={a}
                expertMode={expertMode}
                saving={saving}
                onSave={(d) => void saveAgent(a.name, d)}
              />
            ))}
          </section>
        </div>
      )}
    </section>
  );
}
