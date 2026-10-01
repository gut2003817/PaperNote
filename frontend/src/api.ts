import type { ChatEntry, EditResponse, Engine, EngineHealth, Job, Note, PaperInfo } from "./types";

export class ApiError extends Error {
  constructor(message: string, public status: number, public raw?: string | null) {
    super(message);
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    let raw: string | null = null;
    try {
      const detail = (await res.json()).detail;
      if (typeof detail === "string") message = detail;
      else if (detail && typeof detail === "object" && "message" in detail) {
        message = String(detail.message);
        raw = detail.raw ?? null;
      } else if (detail) message = JSON.stringify(detail);
    } catch {
      /* 非 JSON 回應，保留 HTTP 狀態訊息 */
    }
    throw new ApiError(message, res.status, raw);
  }
  return (await res.json()) as T;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => req<Record<Engine, EngineHealth>>("/api/health"),
  papers: () => req<PaperInfo[]>("/api/papers"),
  upload: (file: File, title: string, engine: Engine) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("title", title);
    fd.append("engine", engine);
    return req<{ slug: string; job_id: string }>("/api/papers", { method: "POST", body: fd });
  },
  job: (id: string) => req<Job>(`/api/jobs/${id}`),
  note: (slug: string) => req<Note>(`/api/papers/${slug}/note`),
  saveNote: (slug: string, note: Note) => req<{ ok: boolean }>(`/api/papers/${slug}/note`, json("PUT", note)),
  figures: (slug: string) => req<string[]>(`/api/papers/${slug}/figures`),
  figureUrl: (slug: string, name: string) => `/api/papers/${slug}/figures/${encodeURIComponent(name)}`,
  chat: (slug: string) => req<ChatEntry[]>(`/api/papers/${slug}/chat`),
  edit: (slug: string, body: { engine: Engine; message: string; block_ids: string[]; selected_text: string }) =>
    req<EditResponse>(`/api/papers/${slug}/edit`, json("POST", body)),
  restore: (slug: string, snapshot: string) => req<Note>(`/api/papers/${slug}/restore`, json("POST", { snapshot })),
};
