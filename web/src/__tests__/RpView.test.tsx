// @vitest-environment jsdom
/**
 * Tests for RpView rendering (todo 31).
 * Uses @testing-library/react to mount RpView against store-prepared
 * state. Asserts the action input renders, typing + submit sends the
 * action via rpStore.send (posting to /api/chat/{id}), and the
 * director response appears.
 *
 * The API call is mocked at the rpStore level by pre-setting store
 * state; the view's own load effect is a no-op because chatStore's
 * projectId is pre-aligned with the active project.
 */

import { describe, expect, it, beforeEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import RpView from "@/views/RpView";
import { useRpStore } from "@/stores/rpStore";
import { useChatStore } from "@/stores/chatStore";
import { useProjectStore } from "@/stores/projectStore";
import { api } from "@/api/client";

beforeEach(() => {
  cleanup();
  useRpStore.setState({
    projectId: null,
    action: "",
    response: null,
    sending: false,
    error: null,
  });
  useChatStore.setState({
    projectId: null,
    messages: [],
    loading: false,
    sending: false,
    error: null,
    lastBranch: null,
  });
  useProjectStore.setState({
    projects: [],
    activeProject: null,
    loading: false,
    error: null,
  });
  vi.restoreAllMocks();
});

describe("RpView rendering", () => {
  it("prompts to select a project when none is active", () => {
    useProjectStore.setState({
      projects: [],
      activeProject: null,
      loading: false,
      error: null,
    });
    render(<RpView />);
    expect(screen.getByText("请先在概览页选择一个项目。")).toBeTruthy();
  });

  it("renders the action input + submit button when a project is active", () => {
    useProjectStore.setState({
      projects: [{ id: "p1", display_name: "Demo", mode: "rp" }],
      activeProject: { id: "p1", display_name: "Demo", mode: "rp" },
      loading: false,
      error: null,
    });
    useChatStore.setState({
      projectId: "p1",
      messages: [],
      loading: false,
      sending: false,
      error: null,
      lastBranch: null,
    });
    render(<RpView />);
    expect(screen.getByPlaceholderText("描述玩家行动…")).toBeTruthy();
    expect(screen.getByRole("button", { name: "提交行动" })).toBeTruthy();
  });

  it("sends an RP action via rpStore.send, posting to /api/chat/{id}", async () => {
    useProjectStore.setState({
      projects: [{ id: "p1", display_name: "Demo", mode: "rp" }],
      activeProject: { id: "p1", display_name: "Demo", mode: "rp" },
      loading: false,
      error: null,
    });
    useChatStore.setState({
      projectId: "p1",
      messages: [],
      loading: false,
      sending: false,
      error: null,
      lastBranch: null,
    });
    const sendSpy = vi.spyOn(api, "sendChat").mockResolvedValueOnce({
      user_message: {
        message_id: "u1",
        role: "user",
        content: "我拔出剑。",
        turn_id: "t1",
        timestamp: "ts",
      },
      director_message: {
        message_id: "d1",
        role: "director",
        content: "酒馆老板后退一步。",
        turn_id: "t1",
        timestamp: "ts",
      },
    });
    render(<RpView />);
    const input = screen.getByPlaceholderText("描述玩家行动…");
    fireEvent.change(input, { target: { value: "我拔出剑。" } });
    fireEvent.click(screen.getByRole("button", { name: "提交行动" }));
    // Wait for the async send to flush.
    await vi.waitFor(() => {
      expect(sendSpy).toHaveBeenCalledWith("p1", "我拔出剑。");
    });
    await vi.waitFor(() => {
      expect(useRpStore.getState().response?.content).toBe("酒馆老板后退一步。");
    });
    sendSpy.mockRestore();
  });

  it("disables submit when the action is empty", () => {
    useProjectStore.setState({
      projects: [{ id: "p1", display_name: "Demo", mode: "rp" }],
      activeProject: { id: "p1", display_name: "Demo", mode: "rp" },
      loading: false,
      error: null,
    });
    useChatStore.setState({
      projectId: "p1",
      messages: [],
      loading: false,
      sending: false,
      error: null,
      lastBranch: null,
    });
    render(<RpView />);
    expect(screen.getByRole("button", { name: "提交行动" })).toHaveProperty("disabled", true);
  });
});
