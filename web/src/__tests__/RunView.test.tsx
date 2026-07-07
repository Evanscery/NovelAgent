// @vitest-environment jsdom
/**
 * Tests for RunView rendering (todo 32).
 * Uses @testing-library/react to mount RunView against store-prepared
 * state. Asserts the start button renders, clicking it calls
 * runStore.startRound (posting to /api/workflow/{id}/run), the round
 * status + live logs appear, and the stop button is enabled while a
 * round is running.
 */

import { describe, expect, it, beforeEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import RunView from "@/views/RunView";
import { useRunStore } from "@/stores/runStore";
import { useProjectStore } from "@/stores/projectStore";
import { api } from "@/api/client";

beforeEach(() => {
  cleanup();
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
  vi.restoreAllMocks();
});

describe("RunView rendering", () => {
  it("prompts to select a project when none is active", () => {
    useProjectStore.setState({
      projects: [],
      activeProject: null,
      loading: false,
      error: null,
    });
    render(<RunView />);
    expect(screen.getByText("请先在概览页选择一个项目。")).toBeTruthy();
  });

  it("renders the start button when a project is active", () => {
    useProjectStore.setState({
      projects: [{ id: "p1", display_name: "Demo", mode: "novel" }],
      activeProject: { id: "p1", display_name: "Demo", mode: "novel" },
      loading: false,
      error: null,
    });
    render(<RunView />);
    expect(screen.getByRole("button", { name: "开始一轮" })).toBeTruthy();
  });

  it("starts a round on click, posting to /api/workflow/{id}/run", async () => {
    useProjectStore.setState({
      projects: [{ id: "p1", display_name: "Demo", mode: "novel" }],
      activeProject: { id: "p1", display_name: "Demo", mode: "novel" },
      loading: false,
      error: null,
    });
    const runSpy = vi.spyOn(api, "runWorkflow").mockResolvedValueOnce({
      round_id: "r_abc",
      state: "running",
      logs: ["round r_abc started", "director called recaller"],
      result: null,
      error: null,
    });
    render(<RunView />);
    fireEvent.click(screen.getByRole("button", { name: "开始一轮" }));
    await waitFor(() => {
      expect(runSpy).toHaveBeenCalledWith("p1", {});
    });
    await waitFor(() => {
      expect(useRunStore.getState().round?.round_id).toBe("r_abc");
    });
    runSpy.mockRestore();
  });

  it("shows round status + live logs when a round is active", () => {
    useProjectStore.setState({
      projects: [{ id: "p1", display_name: "Demo", mode: "novel" }],
      activeProject: { id: "p1", display_name: "Demo", mode: "novel" },
      loading: false,
      error: null,
    });
    useRunStore.setState({
      projectId: "p1",
      round: {
        round_id: "r_abc",
        state: "running",
        logs: ["started", "director called recaller", "writer producing text"],
        result: null,
        error: null,
      },
      polling: false,
      starting: false,
      stopping: false,
      error: null,
    });
    render(<RunView />);
    expect(screen.getByText("r_abc")).toBeTruthy();
    expect(screen.getByText("运行中")).toBeTruthy();
    expect(screen.getByText(/director called recaller/)).toBeTruthy();
    // Stop button is enabled while running.
    expect(screen.getByRole("button", { name: "停止" })).toHaveProperty("disabled", false);
  });

  it("disables start when a round is already running", () => {
    useProjectStore.setState({
      projects: [{ id: "p1", display_name: "Demo", mode: "novel" }],
      activeProject: { id: "p1", display_name: "Demo", mode: "novel" },
      loading: false,
      error: null,
    });
    useRunStore.setState({
      projectId: "p1",
      round: {
        round_id: "r_abc",
        state: "running",
        logs: [],
        result: null,
        error: null,
      },
      polling: false,
      starting: false,
      stopping: false,
      error: null,
    });
    render(<RunView />);
    expect(screen.getByRole("button", { name: "开始一轮" })).toHaveProperty("disabled", true);
  });

  it("shows empty hint when no round has been started", () => {
    useProjectStore.setState({
      projects: [{ id: "p1", display_name: "Demo", mode: "novel" }],
      activeProject: { id: "p1", display_name: "Demo", mode: "novel" },
      loading: false,
      error: null,
    });
    render(<RunView />);
    expect(screen.getByText(/点击「开始一轮」启动/)).toBeTruthy();
  });
});
