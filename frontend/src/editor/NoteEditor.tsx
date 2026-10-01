import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef } from "react";
import { filterSuggestionItems } from "@blocknote/core";
import * as coreLocales from "@blocknote/core/locales";
import "@blocknote/core/fonts/inter.css";
import { BlockNoteView } from "@blocknote/mantine";
import "@blocknote/mantine/style.css";
import { SuggestionMenuController, getDefaultReactSlashMenuItems, useCreateBlockNote } from "@blocknote/react";
import { getMultiColumnSlashMenuItems, locales as multiColumnLocales, multiColumnDropCursor } from "@blocknote/xl-multi-column";
import { api } from "../api";
import { editorToNote, noteToEditor, type BNBlock } from "../convert/note";
import type { Note, NoteBlock } from "../types";
import { schema } from "./schema";
import { slugStore } from "./slugStore";

export interface Selection {
  blockIds: string[];
  selectedText: string;
  preview: string;
}

export interface NoteEditorHandle {
  flush(): Promise<void>;
  applyReplace(ids: string[], blocks: NoteBlock[]): string[];
  loadNote(note: Note): void;
  setLocked(locked: boolean): void;
}

interface Props {
  slug: string;
  initial: Note;
  onSelection: (sel: Selection) => void;
  onSaveError: (msg: string | null) => void;
}

function flash(ids: string[]) {
  requestAnimationFrame(() => {
    for (const id of ids) {
      const el = document.querySelector(`[data-id="${id}"]`);
      if (!el) continue;
      el.classList.add("ai-flash");
      window.setTimeout(() => el.classList.remove("ai-flash"), 2000);
    }
  });
}

function blockText(b: { content?: unknown; type: string }) {
  if (!Array.isArray(b.content)) return `［${b.type}］`;
  return b.content.map((c: { text?: string; content?: { text?: string }[] }) => c.text ?? c.content?.map((x) => x.text ?? "").join("") ?? "").join("");
}

export const NoteEditor = forwardRef<NoteEditorHandle, Props>(function NoteEditor({ slug, initial, onSelection, onSaveError }, ref) {
  slugStore.current = slug;
  const editor = useCreateBlockNote({
    schema,
    initialContent: noteToEditor(initial) as never,
    dropCursor: multiColumnDropCursor,
    dictionary: { ...coreLocales.zhTW, multi_column: multiColumnLocales.zh } as never,
  });
  const saveTimer = useRef<number | undefined>(undefined);
  const pending = useRef<Promise<void>>(Promise.resolve());

  const save = useCallback(() => {
    saveTimer.current = undefined;
    pending.current = pending.current
      .then(() => {
        const note = editorToNote(editor.document as unknown as BNBlock[]);
        return api.saveNote(slug, note);
      })
      .then(() => onSaveError(null))
      .catch((e: Error) => onSaveError(`存檔失敗：${e.message}（內容仍在畫面上，請勿關閉分頁）`));
    return pending.current;
  }, [editor, slug, onSaveError]);

  const onChange = () => {
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(save, 1000);
  };

  const latestSave = useRef(save);
  latestSave.current = save;
  useEffect(() => () => {
    if (saveTimer.current !== undefined) {
      window.clearTimeout(saveTimer.current);
      void latestSave.current();
    }
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      async flush() {
        if (saveTimer.current !== undefined) {
          window.clearTimeout(saveTimer.current);
          void save();
        }
        let queued: Promise<void>;
        do {
          queued = pending.current;
          await queued;
        } while (queued !== pending.current);
      },
      applyReplace(ids, blocks) {
        const { insertedBlocks } = editor.replaceBlocks(ids, noteToEditor({ blocks }) as never);
        const selectedBlocks = insertedBlocks.filter((b) => b.type !== "column");
        onSelection({
          blockIds: selectedBlocks.map((b) => b.id),
          selectedText: "",
          preview: selectedBlocks[0] ? blockText(selectedBlocks[0]) : "",
        });
        const newIds = insertedBlocks.map((b) => b.id);
        flash(newIds);
        return newIds;
      },
      loadNote(note) {
        editor.replaceBlocks(editor.document, noteToEditor(note) as never);
      },
      setLocked(locked) {
        editor.isEditable = !locked;
      },
    }),
    [editor, save, onSelection],
  );

  const onSelectionChange = () => {
    const sel = editor.getSelection();
    const blocks = (sel ? sel.blocks : [editor.getTextCursorPosition().block]).filter((b) => b.type !== "column");
    const text = (window.getSelection()?.toString() ?? "").slice(0, 2000);
    onSelection({
      blockIds: blocks.map((b) => b.id),
      selectedText: text,
      preview: text || (blocks[0] ? blockText(blocks[0] as never) : ""),
    });
  };

  return (
    <BlockNoteView editor={editor} onChange={onChange} onSelectionChange={onSelectionChange} slashMenu={false} theme="light">
      <SuggestionMenuController
        triggerCharacter="/"
        getItems={async (query) =>
          filterSuggestionItems(
            [
              ...getDefaultReactSlashMenuItems(editor),
              ...getMultiColumnSlashMenuItems(editor),
              ...paperNotesItems(editor),
            ],
            query,
          )
        }
      />
    </BlockNoteView>
  );
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function paperNotesItems(editor: any) {
  const insert = (type: string) => () => editor.insertBlocks([{ type }], editor.getTextCursorPosition().block, "after");
  const group = "Paper Notes";
  return [
    { title: "白話解釋（ELI5）", aliases: ["eli5", "白話"], group, onItemClick: insert("eli5") },
    { title: "數據圖", aliases: ["chart", "圖表", "長條圖"], group, onItemClick: insert("chart") },
    { title: "概念圖", aliases: ["diagram", "mermaid", "流程圖"], group, onItemClick: insert("diagram") },
    { title: "論文原圖", aliases: ["figure", "原圖", "圖片"], group, onItemClick: insert("figure") },
    { title: "白板", aliases: ["whiteboard", "excalidraw", "手繪"], group, onItemClick: insert("whiteboard") },
  ];
}
