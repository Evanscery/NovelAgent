// @vitest-environment jsdom
/**
 * Tests for the Inspector component (todo 32) — renders context per active
 * view. Uses @testing-library/react to mount the Inspector against a
 * store-prepared state and assert the per-view context body appears.
 *
 * We do NOT try to render the full view tree (which pulls in react-flow +
 * CodeMirror with heavy DOM dependencies); instead we set the relevant
 * store state directly and assert the Inspector reads it.
 */

import { describe, expect, it, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import Inspector from "@/components/Inspector";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useChatStore } from "@/stores/chatStore";
import { useResourceStore } from "@/stores/resourceStore";
import { useNovelStore } from "@/stores/novelStore";
import { useRunStore } from "@/stores/runStore";
import { useProjectStore } from "@/stores/projectStore";
import type { AgentConfigResponse, ChatMessage, ResourceHistoryEntry } from "@/api/client";

beforeEach(() => {
  cleanup();
  // Reset all stores to empty state.
  useWorkflowStore.setState({
    projectId: null,
    canvas: { nodes: [], wires: [] },
    agents: [],
    selected: null,
    loading: false,
    saving: false,
    error: null,
    dirty: false,
  });
  useChatStore.setState({
    projectId: null,
    messages: [],
    loading: false,
    sending: false,
    error: null,
    lastBranch: null,
  });
  useResourceStore.setState({
    projectId: null,
    types: [],
    activeType: null,
    content: null,
    history: [],
    loading: false,
    saving: false,
    error: null,
    dirty: false,
  });
  useNovelStore.setState({
    projectId: null,
    chapters: [],
    active: null,
    loading: false,
    error: null,
    zoom: 1,
  });
  useRunStore.setState({
    projectId: null,
    round: null,
    polling: false,
    starting: false,
    stopping: false,
    error: null,
  });
  useProjectStore.setState({
    projects: [],
    activeProject: null,
    loading: false,
    error: null,
  });
});

describe("Inspector rendering", () => {
  it("renders collapsed (no body)", () => {
    render(
      <Inspector activeView="overview" collapsed={true} width={320} onToggleCollapse={() => {}} />,
    );
    // The toggle button is always present; the body is hidden when collapsed.
    expect(screen.getByRole("button", { name: "展开检查器" })).toBeTruthy();
  });

  it("renders the overview context with active project", () => {
    useProjectStore.setState({
      projects: [{ id: "p1", display_name: "Demo", mode: "novel" }],
      activeProject: { id: "p1", display_name: "Demo", mode: "novel" },
      loading: false,
      error: null,
    });
    render(
      <Inspector activeView="overview" collapsed={false} width={320} onToggleCollapse={() => {}} />,
    );
    expect(screen.getByText("项目")).toBeTruthy();
    expect(screen.getByText("Demo")).toBeTruthy();
    expect(screen.getByText("p1")).toBeTruthy();
  });

  it("renders the workflow context with a selected node", () => {
    const agent: AgentConfigResponse = {
      name: "writer",
      task: "文本生成",
      input: "ctx",
      output: "prose",
      permission: { read: ["state", "outline"], write: ["notes"] },
      model: "premium",
      tools: ["read", "write"],
      head: null,
      tail: null,
      allow_recursive: true,
    };
    useWorkflowStore.setState({
      projectId: "p1",
      canvas: { nodes: [], wires: [] },
      agents: [agent],
      selected: { id: "writer", agent },
      loading: false,
      saving: false,
      error: null,
      dirty: false,
    });
    render(
      <Inspector activeView="workflow" collapsed={false} width={320} onToggleCollapse={() => {}} />,
    );
    expect(screen.getByText("节点详情")).toBeTruthy();
    expect(screen.getByText("文本生成")).toBeTruthy();
    expect(screen.getByText("premium")).toBeTruthy();
  });

  it("renders the chat context with last director message", () => {
    const msgs: ChatMessage[] = [
      { message_id: "u1", role: "user", content: "hi", turn_id: "t1", timestamp: "x" },
      { message_id: "d1", role: "director", content: "hello there", turn_id: "t1", timestamp: "y" },
    ];
    useChatStore.setState({
      projectId: "p1",
      messages: msgs,
      lastBranch: "br_abc",
      loading: false,
      sending: false,
      error: null,
    });
    render(
      <Inspector activeView="chat" collapsed={false} width={320} onToggleCollapse={() => {}} />,
    );
    expect(screen.getByText("Director 推理")).toBeTruthy();
    // The Inspector truncates to 200 chars; the substring should still appear.
    expect(screen.getByText(/hello there/)).toBeTruthy();
    expect(screen.getByText("br_abc")).toBeTruthy();
  });

  it("renders the resources context with last commit", () => {
    const commits: ResourceHistoryEntry[] = [
      { sha: "abcdef123456", turn_id: "t1", message: "edit state", timestamp: "x", branch: "main" },
    ];
    useResourceStore.setState({
      projectId: "p1",
      types: [],
      activeType: "state",
      content: null,
      history: commits,
      loading: false,
      saving: false,
      error: null,
      dirty: false,
    });
    render(
      <Inspector activeView="resources" collapsed={false} width={320} onToggleCollapse={() => {}} />,
    );
    expect(screen.getByText("资源 · state")).toBeTruthy();
    expect(screen.getByText("edit state")).toBeTruthy();
    expect(screen.getByText("main")).toBeTruthy();
  });

  it("renders the config context with field hints", () => {
    render(
      <Inspector activeView="config" collapsed={false} width={320} onToggleCollapse={() => {}} />,
    );
    expect(screen.getAllByText("字段提示").length).toBeGreaterThan(0);
    expect(screen.getByText(/Agent 的唯一标识/)).toBeTruthy();
    expect(screen.getByText(/hash<string, vector>/)).toBeTruthy();
  });

  it("renders the novel context with chapter meta", () => {
    useNovelStore.setState({
      projectId: "p1",
      chapters: [],
      active: {
        project_id: "p1",
        filename: "chapter_01.txt",
        chapter_number: 1,
        content: "It was a dark and stormy night. " + "x".repeat(100),
      },
      loading: false,
      error: null,
      zoom: 1.2,
    });
    render(
      <Inspector activeView="novel" collapsed={false} width={320} onToggleCollapse={() => {}} />,
    );
    expect(screen.getAllByText("章节元数据").length).toBeGreaterThan(0);
    expect(screen.getByText("chapter_01.txt")).toBeTruthy();
    expect(screen.getByText("120%")).toBeTruthy();
  });

  it("renders the rp context with the last 5 messages", () => {
    useChatStore.setState({
      projectId: "p1",
      messages: [
        { message_id: "m1", role: "user", content: "action A", turn_id: "t1", timestamp: "x" },
        { message_id: "m2", role: "director", content: "reply A", turn_id: "t1", timestamp: "y" },
      ],
      loading: false,
      sending: false,
      error: null,
    });
    render(
      <Inspector activeView="rp" collapsed={false} width={320} onToggleCollapse={() => {}} />,
    );
    expect(screen.getByText("RP 状态 / 行动日志")).toBeTruthy();
    expect(screen.getByText("玩家")).toBeTruthy();
    expect(screen.getByText("Director")).toBeTruthy();
  });

  it("renders the run context with round + logs tail", () => {
    useRunStore.setState({
      projectId: "p1",
      round: {
        round_id: "r_abc",
        state: "running",
        logs: ["started", "director called recaller", "writer producing text"],
        result: null,
        error: null,
      },
      polling: true,
      starting: false,
      stopping: false,
      error: null,
    });
    render(
      <Inspector activeView="run" collapsed={false} width={320} onToggleCollapse={() => {}} />,
    );
    expect(screen.getByText("作业日志（尾部）")).toBeTruthy();
    expect(screen.getByText(/director called recaller/)).toBeTruthy();
    expect(screen.getByText("r_abc")).toBeTruthy();
  });
});
