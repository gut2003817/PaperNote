import { createRef } from "react";
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NoteEditor, type NoteEditorHandle } from "./NoteEditor";

const mocks = vi.hoisted(() => ({
  editor: {
    document: [{ id: "p1", type: "paragraph", content: [{ type: "text", text: "筆記", styles: {} }] }],
    isEditable: true,
    replaceBlocks: vi.fn(),
    getSelection: vi.fn(),
    getTextCursorPosition: vi.fn(),
  },
  saveNote: vi.fn(),
  viewProps: {} as { onChange: () => void; onSelectionChange: () => void },
}));

vi.mock("./schema", () => ({ schema: {} }));
vi.mock("../api", () => ({ api: { saveNote: mocks.saveNote } }));
vi.mock("@blocknote/react", () => ({
  useCreateBlockNote: () => mocks.editor,
  SuggestionMenuController: () => null,
  getDefaultReactSlashMenuItems: () => [],
}));
vi.mock("@blocknote/mantine", () => ({
  BlockNoteView: (props: typeof mocks.viewProps) => { mocks.viewProps = props; return null; },
}));

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  mocks.saveNote.mockReset();
  mocks.saveNote.mockResolvedValue({ ok: true });
  mocks.editor.document = [{ id: "p1", type: "paragraph", content: [{ type: "text", text: "筆記", styles: {} }] }];
  mocks.editor.isEditable = true;
  mocks.editor.getSelection.mockReturnValue(null);
  mocks.editor.getTextCursorPosition.mockReturnValue({ block: mocks.editor.document[0] });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

function mount() {
  const ref = createRef<NoteEditorHandle>();
  const onSelection = vi.fn();
  const onSaveError = vi.fn();
  const { unmount } = render(<NoteEditor ref={ref} slug="paper-a" initial={{ blocks: [{ id: "p1", type: "paragraph", text: "筆記" }] }} onSelection={onSelection} onSaveError={onSaveError} />);
  return { ref, onSelection, onSaveError, unmount };
}

describe("NoteEditor", () => {
  it("最後一次修改後 1000ms 自動存檔", async () => {
    const { onSaveError } = mount();
    act(() => mocks.viewProps.onChange());
    await act(() => vi.advanceTimersByTimeAsync(900));
    act(() => mocks.viewProps.onChange());
    await act(() => vi.advanceTimersByTimeAsync(999));
    expect(mocks.saveNote).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(mocks.saveNote).toHaveBeenCalledExactlyOnceWith("paper-a", { blocks: [{ id: "p1", type: "paragraph", text: "筆記" }] });
    expect(onSaveError).toHaveBeenCalledWith(null);
  });

  it("flush 立即儲存尚未到期的修改並等待請求完成", async () => {
    let resolveSave!: () => void;
    mocks.saveNote.mockReturnValue(new Promise<void>((resolve) => { resolveSave = resolve; }));
    const { ref } = mount();
    act(() => mocks.viewProps.onChange());
    const flushed = vi.fn();
    const pending = ref.current!.flush().then(flushed);
    await act(async () => {});
    expect(mocks.saveNote).toHaveBeenCalledTimes(1);
    expect(flushed).not.toHaveBeenCalled();
    await act(async () => { resolveSave(); await pending; });
    expect(flushed).toHaveBeenCalledTimes(1);
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(mocks.saveNote).toHaveBeenCalledTimes(1);
  });

  it("進行中的存檔完成後才送出下一次存檔，flush 等待整條佇列", async () => {
    let resolveFirst!: () => void;
    let resolveSecond!: () => void;
    mocks.saveNote
      .mockReturnValueOnce(new Promise<void>((resolve) => { resolveFirst = resolve; }))
      .mockReturnValueOnce(new Promise<void>((resolve) => { resolveSecond = resolve; }));
    const { ref } = mount();
    act(() => mocks.viewProps.onChange());
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(mocks.saveNote).toHaveBeenCalledExactlyOnceWith("paper-a", { blocks: [{ id: "p1", type: "paragraph", text: "筆記" }] });

    mocks.editor.document[0].content[0].text = "第二版";
    act(() => mocks.viewProps.onChange());
    const flushed = vi.fn();
    const pending = ref.current!.flush().then(flushed);
    await act(async () => {});
    expect(mocks.saveNote).toHaveBeenCalledTimes(1);
    expect(flushed).not.toHaveBeenCalled();

    // 排隊後仍可能修改；實際送出時須讀取最新內容。
    mocks.editor.document[0].content[0].text = "最新內容";
    await act(async () => { resolveFirst(); });
    expect(mocks.saveNote).toHaveBeenCalledTimes(2);
    expect(mocks.saveNote).toHaveBeenLastCalledWith("paper-a", { blocks: [{ id: "p1", type: "paragraph", text: "最新內容" }] });
    expect(flushed).not.toHaveBeenCalled();

    await act(async () => { resolveSecond(); await pending; });
    expect(flushed).toHaveBeenCalledTimes(1);
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(mocks.saveNote).toHaveBeenCalledTimes(2);
  });

  it("第二次自動存檔也等待第一個請求完成", async () => {
    let resolveFirst!: () => void;
    mocks.saveNote.mockReturnValueOnce(new Promise<void>((resolve) => { resolveFirst = resolve; }));
    const { ref } = mount();
    act(() => mocks.viewProps.onChange());
    await act(() => vi.advanceTimersByTimeAsync(1000));
    mocks.editor.document[0].content[0].text = "自動存檔新版";
    act(() => mocks.viewProps.onChange());
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(mocks.saveNote).toHaveBeenCalledTimes(1);
    const pending = ref.current!.flush();
    await act(async () => { resolveFirst(); await pending; });
    expect(mocks.saveNote).toHaveBeenCalledTimes(2);
    expect(mocks.saveNote).toHaveBeenLastCalledWith("paper-a", { blocks: [{ id: "p1", type: "paragraph", text: "自動存檔新版" }] });
  });

  it("卸載時立即送出尚未到期的修改且不等待請求完成", async () => {
    let resolveSave!: () => void;
    mocks.saveNote.mockReturnValueOnce(new Promise<void>((resolve) => { resolveSave = resolve; }));
    const { unmount, onSaveError } = mount();
    mocks.editor.document[0].content[0].text = "離開前修改";
    act(() => mocks.viewProps.onChange());
    unmount();
    await act(async () => {});
    expect(mocks.saveNote).toHaveBeenCalledExactlyOnceWith("paper-a", { blocks: [{ id: "p1", type: "paragraph", text: "離開前修改" }] });
    expect(onSaveError).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(mocks.saveNote).toHaveBeenCalledTimes(1);
    await act(async () => { resolveSave(); });
    expect(onSaveError).toHaveBeenCalledWith(null);
  });

  it("存檔失敗回報繁體中文訊息", async () => {
    mocks.saveNote.mockRejectedValue(new Error("連線中斷"));
    const { ref, onSaveError } = mount();
    act(() => mocks.viewProps.onChange());
    await act(() => ref.current!.flush());
    expect(onSaveError).toHaveBeenCalledWith("存檔失敗：連線中斷（內容仍在畫面上，請勿關閉分頁）");
  });

  it("鎖定可切換，替換回傳新 ID 並高亮 2000ms，loadNote 替換整份文件", async () => {
    const { ref } = mount();
    ref.current!.setLocked(true);
    expect(mocks.editor.isEditable).toBe(false);
    ref.current!.setLocked(false);
    expect(mocks.editor.isEditable).toBe(true);
    const block = document.createElement("div");
    block.dataset.id = "new-id";
    document.body.append(block);
    mocks.editor.replaceBlocks.mockReturnValue({ insertedBlocks: [{ id: "new-id" }] });
    expect(ref.current!.applyReplace(["p1"], [{ id: "new-id", type: "paragraph", text: "新內容" }])).toEqual(["new-id"]);
    await act(() => vi.advanceTimersByTimeAsync(16));
    expect(block.classList.contains("ai-flash")).toBe(true);
    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(block.classList.contains("ai-flash")).toBe(false);
    ref.current!.loadNote({ blocks: [{ id: "loaded", type: "paragraph", text: "還原" }] });
    expect(mocks.editor.replaceBlocks).toHaveBeenLastCalledWith(mocks.editor.document, [{ id: "loaded", type: "paragraph", content: [{ type: "text", text: "還原", styles: {} }] }]);
    block.remove();
  });

  it("選取排除 column 並限制文字為 2000 字，無選取時提供游標區塊預覽", () => {
    const { onSelection } = mount();
    act(() => mocks.viewProps.onSelectionChange());
    expect(onSelection).toHaveBeenLastCalledWith({ blockIds: ["p1"], selectedText: "", preview: "筆記" });
    mocks.editor.getSelection.mockReturnValue({ blocks: [{ id: "col", type: "column" }, mocks.editor.document[0]] });
    const selection = vi.spyOn(window, "getSelection").mockReturnValue({ toString: () => "字".repeat(2001) } as Selection);
    act(() => mocks.viewProps.onSelectionChange());
    expect(onSelection).toHaveBeenLastCalledWith({ blockIds: ["p1"], selectedText: "字".repeat(2000), preview: "字".repeat(2000) });
    selection.mockRestore();
  });
});
