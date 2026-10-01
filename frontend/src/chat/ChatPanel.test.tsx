import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { ChatPanel } from "./ChatPanel";
import { ApiError, api } from "../api";
import type { NoteEditorHandle } from "../editor/NoteEditor";

function fakeEditor() {
  const calls: string[] = [];
  const handle: NoteEditorHandle = {
    flush: vi.fn(async () => { calls.push("flush"); }),
    setLocked: vi.fn((l: boolean) => { calls.push(l ? "lock" : "unlock"); }),
    applyReplace: vi.fn(() => { calls.push("apply"); return ["n1"]; }),
    loadNote: vi.fn(() => { calls.push("load"); }),
  };
  const ref = createRef<NoteEditorHandle>() as { current: NoteEditorHandle | null };
  ref.current = handle;
  return { ref, handle, calls };
}

const selection = { blockIds: ["p1"], selectedText: "這句", preview: "這句" };

beforeEach(() => {
  vi.spyOn(api, "chat").mockResolvedValue([]);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function send(text: string) {
  fireEvent.change(screen.getByPlaceholderText(/例如/), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: /送出/ }));
}

describe("ChatPanel", () => {
  it("修改：flush → lock → edit → unlock → apply，並顯示回覆與還原按鈕", async () => {
    const { ref, handle, calls } = fakeEditor();
    const edit = vi.spyOn(api, "edit").mockResolvedValue({
      reply: "已改寫", replace: [{ id: "x", type: "paragraph", text: "新" }], snapshot: "20261001-120000-abcd.json",
    });
    render(<ChatPanel slug="s" selection={selection} editorRef={ref} />);
    await send("改白話");
    await screen.findByText("已改寫");
    expect(edit).toHaveBeenCalledWith("s", { engine: "claude", message: "改白話", block_ids: ["p1"], selected_text: "這句" });
    expect(calls).toEqual(["flush", "lock", "unlock", "apply"]);
    expect(handle.applyReplace).toHaveBeenCalledWith(["p1"], [{ id: "x", type: "paragraph", text: "新" }]);
    expect(screen.getByRole("button", { name: "還原到此修改前" })).toBeTruthy();
  });

  it("只討論：不套用修改", async () => {
    const { ref, handle } = fakeEditor();
    vi.spyOn(api, "edit").mockResolvedValue({ reply: "這是在說…", replace: null, snapshot: null });
    render(<ChatPanel slug="s" selection={selection} editorRef={ref} />);
    await send("什麼意思？");
    await screen.findByText("這是在說…");
    expect(handle.applyReplace).not.toHaveBeenCalled();
  });

  it("錯誤：顯示錯誤與原始輸出，並解鎖", async () => {
    const { ref, calls } = fakeEditor();
    vi.spyOn(api, "edit").mockRejectedValue(new ApiError("AI 回傳格式錯誤", 502, "[{]"));
    render(<ChatPanel slug="s" selection={selection} editorRef={ref} />);
    await send("改");
    await screen.findByText("AI 回傳格式錯誤");
    expect(screen.getByText("[{]")).toBeTruthy();
    expect(calls).toEqual(["flush", "lock", "unlock"]);
  });

  it("切換引擎為 Codex", async () => {
    const { ref } = fakeEditor();
    const edit = vi.spyOn(api, "edit").mockResolvedValue({ reply: "ok", replace: null, snapshot: null });
    render(<ChatPanel slug="s" selection={selection} editorRef={ref} />);
    fireEvent.change(screen.getByLabelText("AI 引擎"), { target: { value: "codex" } });
    await send("hi");
    await waitFor(() => expect(edit.mock.calls[0][1].engine).toBe("codex"));
  });

  it("沒有選取時不能送出", () => {
    const { ref } = fakeEditor();
    render(<ChatPanel slug="s" selection={null} editorRef={ref} />);
    fireEvent.change(screen.getByPlaceholderText(/例如/), { target: { value: "x" } });
    expect((screen.getByRole("button", { name: /送出/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("還原：flush → restore → loadNote", async () => {
    const { ref, handle } = fakeEditor();
    vi.spyOn(api, "chat").mockResolvedValue([
      { role: "assistant", text: "已改寫", snapshot: "20261001-120000-abcd.json", ts: 1 },
    ]);
    const restore = vi.spyOn(api, "restore").mockResolvedValue({ blocks: [] });
    render(<ChatPanel slug="s" selection={selection} editorRef={ref} />);
    fireEvent.click(await screen.findByRole("button", { name: "還原到此修改前" }));
    await waitFor(() => expect(handle.loadNote).toHaveBeenCalledWith({ blocks: [] }));
    expect(restore).toHaveBeenCalledWith("s", "20261001-120000-abcd.json");
    expect(handle.flush).toHaveBeenCalled();
  });
});
