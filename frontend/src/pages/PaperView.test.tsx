import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { PaperView } from "./PaperView";
import type { Selection } from "../editor/NoteEditor";

vi.mock("../editor/NoteEditor", () => ({
  NoteEditor: ({ slug, onSelection, onSaveError }: {
    slug: string; onSelection: (value: Selection) => void; onSaveError: (value: string) => void;
  }) => <button onClick={() => {
    onSelection({ blockIds: ["old"], selectedText: "舊選取", preview: "舊選取" });
    onSaveError("舊存檔錯誤");
  }}>筆記 {slug}</button>,
}));
vi.mock("../chat/ChatPanel", () => ({
  ChatPanel: ({ selection }: { selection: Selection | null }) => <div>{selection?.preview ?? "尚未選取"}</div>,
}));
beforeEach(() => { vi.spyOn(api, "note").mockResolvedValue({ blocks: [] }); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it.each(["舊選取", "舊存檔錯誤"])("切換 slug 清除上一篇的 %s", async (stale) => {
  const { rerender } = render(<PaperView slug="a" />);
  fireEvent.click(await screen.findByText("筆記 a"));
  expect(screen.getByText("舊選取")).toBeTruthy();
  expect(screen.getByText("舊存檔錯誤")).toBeTruthy();
  rerender(<PaperView slug="b" />);
  await screen.findByText("筆記 b");
  expect(screen.queryByText(stale)).toBeNull();
  expect(screen.getByText("尚未選取")).toBeTruthy();
});

it("切換 slug 清除上一篇的載入 error", async () => {
  vi.mocked(api.note).mockRejectedValueOnce(new Error("舊載入錯誤"));
  const { rerender } = render(<PaperView slug="a" />);
  await screen.findByText("舊載入錯誤");
  rerender(<PaperView slug="b" />);
  await act(async () => {});
  expect(screen.queryByText("舊載入錯誤")).toBeNull();
  expect(screen.getByText("筆記 b")).toBeTruthy();
});
