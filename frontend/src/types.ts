export type Align = "left" | "center" | "right";
export type Engine = "claude" | "codex";

export interface Layout {
  widthPct: number;
  heightPx?: number;
  marginTopPx: number;
  marginBottomPx: number;
  align: Align;
}

interface Base {
  id: string;
  layout?: Layout;
}

export type LeafBlock =
  | (Base & { type: "heading"; level: 1 | 2 | 3; text: string })
  | (Base & { type: "paragraph"; text: string })
  | (Base & { type: "eli5"; text: string })
  | (Base & { type: "chart"; spec: Record<string, unknown>; source: string; verified: boolean })
  | (Base & { type: "diagram"; mermaid: string })
  | (Base & { type: "figure"; path: string; caption: string; page: number })
  | (Base & { type: "whiteboard"; scene: Record<string, unknown> });

export interface Column {
  widthPct: number;
  blocks: LeafBlock[];
}

export type NoteBlock = LeafBlock | (Base & { type: "columns"; columns: Column[] });

export interface Note {
  blocks: NoteBlock[];
}

export interface PaperInfo {
  slug: string;
  title: string;
  created: number;
  has_note: boolean;
}

export interface EngineHealth {
  ok: boolean;
  detail: string;
  fix?: string;
}

export interface Job {
  status: "running" | "done" | "error";
  step: string;
  error: string | null;
  slug: string;
}

export interface ChatEntry {
  role: "user" | "assistant" | "error";
  text: string;
  engine?: Engine;
  snapshot?: string | null;
  raw?: string | null;
  ts: number;
}

export interface EditResponse {
  reply: string;
  replace: NoteBlock[] | null;
  snapshot: string | null;
}
