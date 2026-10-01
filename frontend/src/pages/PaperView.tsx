import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api";
import { ChatPanel } from "../chat/ChatPanel";
import { NoteEditor, type NoteEditorHandle, type Selection } from "../editor/NoteEditor";
import type { Note } from "../types";

export function PaperView({ slug }: { slug: string }) {
  const [note, setNote] = useState<Note | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const editorRef = useRef<NoteEditorHandle>(null);

  useEffect(() => {
    setNote(null);
    api
      .note(slug)
      .then(setNote)
      .catch((e: ApiError) => setError(e.status === 404 ? "這篇論文還沒有筆記（匯入可能失敗或尚未完成）" : e.message));
  }, [slug]);

  if (error) return <div className="paper-list"><p className="job-error">{error}</p><a href="#/">回列表</a></div>;
  if (!note) return <div className="paper-list">載入中…</div>;

  return (
    <div className="paper-view">
      <main className="note-pane">
        {saveError && <div className="banner-error">{saveError}</div>}
        <NoteEditor ref={editorRef} key={slug} slug={slug} initial={note} onSelection={setSelection} onSaveError={setSaveError} />
      </main>
      <ChatPanel slug={slug} selection={selection} editorRef={editorRef} />
    </div>
  );
}
