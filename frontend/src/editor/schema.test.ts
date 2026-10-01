import { describe, expect, it, vi } from "vitest";

vi.mock("@excalidraw/excalidraw", () => ({ Excalidraw: () => null }));
vi.mock("@excalidraw/excalidraw/index.css", () => ({}));
vi.mock("mermaid", () => ({ default: { initialize() {}, render: async () => ({ svg: "" }), parse: async () => true } }));
vi.mock("vega-embed", () => ({ default: async () => ({ finalize() {} }) }));

import { BlockNoteEditor } from "@blocknote/core";
import { schema } from "./schema";
import { editorToNote, noteToEditor, type BNBlock } from "../convert/note";
import { SAMPLE_NOTE } from "../convert/fixtures";

describe("BlockNote schema", () => {
  it("空筆記可作為 initialContent 開啟", () => {
    expect(() => BlockNoteEditor.create({
      schema, initialContent: noteToEditor({ blocks: [] }) as never,
    })).not.toThrow();
  });

  it("noteToEditor 的輸出能載入 BlockNote，editorToNote 還原後相同", () => {
    const editor = BlockNoteEditor.create({ schema });
    editor.mount(document.createElement("div"));
    editor.replaceBlocks(editor.document, noteToEditor(SAMPLE_NOTE) as never);
    expect(editorToNote(editor.document as unknown as BNBlock[])).toEqual(SAMPLE_NOTE);
  });
});
