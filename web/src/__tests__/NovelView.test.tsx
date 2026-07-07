// @vitest-environment jsdom
/**
 * Tests for NovelView rendering (todo 31).
 * Uses @testing-library/react to mount NovelView against a store-prepared
 * state. Asserts the chapter list renders, selecting a chapter shows
 * content, and zoom controls adjust the font size.
 *
 * The store state is set directly (no API mock needed) so the view's
 * load effect is a no-op (projectId already matches activeProject).
 */

import { describe, expect, it, beforeEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import NovelView from "@/views/NovelView";
import { useNovelStore } from "@/stores/novelStore";
import { useProjectStore } from "@/stores/projectStore";
import type { NovelChapterSummary } from "@/api/client";

beforeEach(() => {
  cleanup();
  useNovelStore.setState({
    projectId: null,
    chapters: [],
    active: null,
    loading: false,
    error: null,
    zoom: 1,
  });
  useProjectStore.setState({
    projects: [],
    activeProject: null,
    loading: false,
    error: null,
  });
});

const CHAPTERS: NovelChapterSummary[] = [
  { filename: "chapter_01.txt", chapter_number: 1, size_bytes: 4096 },
  { filename: "chapter_02.txt", chapter_number: 2, size_bytes: 8192 },
];

describe("NovelView rendering", () => {
  it("renders the chapter list when chapters are loaded", () => {
    useProjectStore.setState({
      projects: [{ id: "p1", display_name: "Demo", mode: "novel" }],
      activeProject: { id: "p1", display_name: "Demo", mode: "novel" },
      loading: false,
      error: null,
    });
    useNovelStore.setState({
      projectId: "p1",
      chapters: CHAPTERS,
      active: null,
      loading: false,
      error: null,
      zoom: 1,
    });
    render(<NovelView />);
    expect(screen.getByText("第 1 章")).toBeTruthy();
    expect(screen.getByText("第 2 章")).toBeTruthy();
  });

  it("shows an empty hint when no chapters exist", () => {
    useProjectStore.setState({
      projects: [{ id: "p1", display_name: "Demo", mode: "novel" }],
      activeProject: { id: "p1", display_name: "Demo", mode: "novel" },
      loading: false,
      error: null,
    });
    useNovelStore.setState({
      projectId: "p1",
      chapters: [],
      active: null,
      loading: false,
      error: null,
      zoom: 1,
    });
    render(<NovelView />);
    expect(screen.getByText("还没有导出的章节。")).toBeTruthy();
  });

  it("shows chapter content when a chapter is active", () => {
    useProjectStore.setState({
      projects: [{ id: "p1", display_name: "Demo", mode: "novel" }],
      activeProject: { id: "p1", display_name: "Demo", mode: "novel" },
      loading: false,
      error: null,
    });
    useNovelStore.setState({
      projectId: "p1",
      chapters: CHAPTERS,
      active: {
        project_id: "p1",
        filename: "chapter_01.txt",
        chapter_number: 1,
        content: "# Chapter 1\n\nIt was a dark and stormy night.",
      },
      loading: false,
      error: null,
      zoom: 1,
    });
    render(<NovelView />);
    // marked renders the markdown; the <h1> "Chapter 1" + paragraph appear.
    expect(screen.getByText("Chapter 1")).toBeTruthy();
    expect(screen.getByText(/dark and stormy night/)).toBeTruthy();
  });

  it("zoom in button increases the displayed zoom percent", () => {
    useProjectStore.setState({
      projects: [{ id: "p1", display_name: "Demo", mode: "novel" }],
      activeProject: { id: "p1", display_name: "Demo", mode: "novel" },
      loading: false,
      error: null,
    });
    useNovelStore.setState({
      projectId: "p1",
      chapters: CHAPTERS,
      active: {
        project_id: "p1",
        filename: "chapter_01.txt",
        chapter_number: 1,
        content: "body",
      },
      loading: false,
      error: null,
      zoom: 1,
    });
    render(<NovelView />);
    expect(screen.getByText("100%")).toBeTruthy();
    fireEvent.click(screen.getByTitle("放大"));
    // 1 + 0.1 = 1.1 → 110%
    expect(screen.getByText("110%")).toBeTruthy();
  });

  it("prompts to select a project when none is active", () => {
    useProjectStore.setState({
      projects: [],
      activeProject: null,
      loading: false,
      error: null,
    });
    render(<NovelView />);
    expect(screen.getByText("请先在概览页选择一个项目。")).toBeTruthy();
  });
});
