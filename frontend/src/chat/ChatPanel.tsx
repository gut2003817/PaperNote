import { useEffect, useState, type RefObject } from "react";
import { ApiError, api } from "../api";
import type { NoteEditorHandle, Selection } from "../editor/NoteEditor";
import type { ChatEntry, Engine } from "../types";

interface Props {
  slug: string;
  selection: Selection | null;
  editorRef: RefObject<NoteEditorHandle | null>;
}

export function ChatPanel({ slug, selection, editorRef }: Props) {
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [engine, setEngine] = useState<Engine>("claude");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.chat(slug).then(setEntries).catch(() => setEntries([]));
  }, [slug]);

  const push = (e: Omit<ChatEntry, "ts">) => setEntries((prev) => [...prev, { ...e, ts: Date.now() / 1000 }]);

  const send = async () => {
    const editor = editorRef.current;
    const originalMessage = message;
    const text = originalMessage.trim();
    if (!editor || !selection || !text || busy) return;
    const sel = selection;
    setBusy(true);
    setMessage("");
    push({ role: "user", text, engine });
    let locked = false;
    try {
      await editor.flush();
      editor.setLocked(true);
      locked = true;
      const res = await api.edit(slug, { engine, message: text, block_ids: sel.blockIds, selected_text: sel.selectedText });
      editor.setLocked(false);
      locked = false;
      if (res.replace) editor.applyReplace(sel.blockIds, res.replace);
      push({ role: "assistant", text: res.reply, engine, snapshot: res.snapshot });
    } catch (e) {
      setMessage(originalMessage);
      push({ role: "error", text: (e as Error).message, raw: e instanceof ApiError ? e.raw : null });
    } finally {
      if (locked) editor.setLocked(false);
      setBusy(false);
    }
  };

  const restore = async (snapshot: string) => {
    const editor = editorRef.current;
    if (!editor || busy) return;
    try {
      await editor.flush();
      editor.loadNote(await api.restore(slug, snapshot));
      push({ role: "assistant", text: "已還原到這次修改之前的版本" });
    } catch (e) {
      push({ role: "error", text: `還原失敗：${(e as Error).message}` });
    }
  };

  return (
    <aside className="chat-panel">
      <div className="chat-head">
        <span>與 AI 討論</span>
        <select aria-label="AI 引擎" value={engine} onChange={(e) => setEngine(e.target.value as Engine)} disabled={busy}>
          <option value="claude">Claude</option>
          <option value="codex">Codex</option>
        </select>
      </div>
      <div className="chat-log">
        {entries.map((e, i) => (
          <div key={i} className={`chat-msg chat-${e.role}`}>
            <div>{e.text}</div>
            {e.role === "assistant" && e.snapshot && (
              <button className="chat-restore" onClick={() => restore(e.snapshot!)}>還原到此修改前</button>
            )}
            {e.role === "error" && e.raw && (
              <details>
                <summary>AI 原始輸出</summary>
                <pre>{e.raw}</pre>
              </details>
            )}
          </div>
        ))}
        {busy && <div className="chat-msg chat-pending">AI 處理中…（可能需要 30 秒到幾分鐘，期間筆記暫時鎖定）</div>}
      </div>
      <div className="chat-selection">
        {selection ? <>已選取：「{selection.preview.slice(0, 80)}」</> : "先在左側筆記點選或反白要討論的內容"}
      </div>
      <div className="chat-input">
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="例如：把這段改得更白話、幫我加一張比較圖、這裡的實驗設定是什麼意思？"
          disabled={busy}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send();
          }}
        />
        <button onClick={send} disabled={busy || !selection || !message.trim()}>送出（⌘/Ctrl + Enter）</button>
      </div>
    </aside>
  );
}
