import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Engine, PaperInfo } from "../types";

export function PaperList() {
  const [papers, setPapers] = useState<PaperInfo[]>([]);
  const [title, setTitle] = useState("");
  const [engine, setEngine] = useState<Engine>("claude");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.papers().then(setPapers).catch((e: Error) => setError(e.message));
  }, []);

  const upload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return setError("請先選擇 PDF 檔");
    setError(null);
    setStatus("上傳中…");
    try {
      const { slug, job_id } = await api.upload(file, title, engine);
      for (;;) {
        const job = await api.job(job_id);
        if (job.status === "done") {
          location.hash = `#/paper/${slug}`;
          return;
        }
        if (job.status === "error") throw new Error(job.error ?? "匯入失敗");
        setStatus(`處理中：${job.step}（整篇論文通常需要 1–3 分鐘）`);
        await new Promise((r) => setTimeout(r, 2000));
      }
    } catch (e) {
      setStatus(null);
      setError(`匯入失敗：${(e as Error).message}`);
    }
  };

  return (
    <div className="paper-list">
      <div className="upload-form">
        <strong>匯入論文</strong>
        <input ref={fileRef} type="file" accept="application/pdf" aria-label="論文 PDF" />
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="標題（可留空，用檔名）" aria-label="標題" />
        <label>
          使用 AI：
          <select value={engine} onChange={(e) => setEngine(e.target.value as Engine)}>
            <option value="claude">Claude</option>
            <option value="codex">Codex</option>
          </select>
        </label>
        <button onClick={upload} disabled={status !== null}>開始整理</button>
        {status && <span className="job-status">{status}</span>}
        {error && <span className="job-error">{error}</span>}
      </div>
      {papers.map((p) => (
        <a key={p.slug} className="paper-item" href={`#/paper/${p.slug}`}>
          {p.title}
          <br />
          <small>{new Date(p.created * 1000).toLocaleString()}{!p.has_note && " · 尚無筆記（匯入中或失敗）"}</small>
        </a>
      ))}
    </div>
  );
}
