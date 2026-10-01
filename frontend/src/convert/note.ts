import type { Align, Column, Layout, LeafBlock, Note, NoteBlock } from "../types";
import { inlineToMarkdown, markdownToInline } from "./inline";

export interface BNBlock {
  id?: string;
  type: string;
  props?: Record<string, unknown>;
  content?: unknown;
  children?: BNBlock[];
}

export const DEFAULT_LAYOUT: Layout = { widthPct: 100, marginTopPx: 8, marginBottomPx: 8, align: "center" };
export const DEFAULT_CHART_SPEC: Record<string, unknown> = {
  mark: "bar",
  data: { values: [{ 類別: "A", 數值: 1 }, { 類別: "B", 數值: 2 }] },
  encoding: { x: { field: "類別", type: "nominal" }, y: { field: "數值", type: "quantitative" } },
};
export const DEFAULT_MERMAID = "flowchart LR\n  A[輸入] --> B[處理] --> C[輸出]";
const VEGA_VIEW_KEYS = ["mark", "layer", "concat", "hconcat", "vconcat", "facet", "repeat"];

const num = (v: unknown, d: number) => (typeof v === "number" && Number.isFinite(v) ? v : d);
const str = (v: unknown) => (typeof v === "string" ? v : "");
const round1 = (v: number) => Math.round(v * 10) / 10;

export function layoutToProps(l?: Layout) {
  const x = { ...DEFAULT_LAYOUT, ...l };
  return { widthPct: x.widthPct, heightPx: x.heightPx ?? 0, marginTopPx: x.marginTopPx, marginBottomPx: x.marginBottomPx, align: x.align };
}

export function propsToLayout(p: Record<string, unknown>): Layout {
  const align = (["left", "center", "right"].includes(p.align as string) ? p.align : "center") as Align;
  const l: Layout = { widthPct: num(p.widthPct, 100), marginTopPx: num(p.marginTopPx, 8), marginBottomPx: num(p.marginBottomPx, 8), align };
  const h = num(p.heightPx, 0);
  if (h > 0) l.heightPx = h;
  return l;
}

function isDefaultLayout(l: Layout) {
  return l.widthPct === 100 && l.heightPx === undefined && l.marginTopPx === 8 && l.marginBottomPx === 8 && l.align === "center";
}

function withLayout<T extends LeafBlock>(b: T, props: Record<string, unknown>): T {
  const layout = propsToLayout(props);
  return isDefaultLayout(layout) ? b : { ...b, layout };
}

function parseObj(v: unknown): Record<string, unknown> | null {
  try {
    const o = JSON.parse(str(v));
    return o && typeof o === "object" && !Array.isArray(o) ? o : null;
  } catch {
    return null;
  }
}

function leafToBN(b: LeafBlock): BNBlock {
  switch (b.type) {
    case "heading":
      return { id: b.id, type: "heading", props: { level: b.level }, content: markdownToInline(b.text) };
    case "paragraph":
      return { id: b.id, type: "paragraph", content: markdownToInline(b.text) };
    case "eli5":
      return { id: b.id, type: "eli5", content: markdownToInline(b.text) };
    case "chart":
      return { id: b.id, type: "chart", props: { spec: JSON.stringify(b.spec), source: b.source, verified: b.verified, ...layoutToProps(b.layout) } };
    case "diagram":
      return { id: b.id, type: "diagram", props: { mermaid: b.mermaid, ...layoutToProps(b.layout) } };
    case "figure":
      return { id: b.id, type: "figure", props: { path: b.path, caption: b.caption, page: b.page, ...layoutToProps(b.layout) } };
    case "whiteboard":
      return { id: b.id, type: "whiteboard", props: { scene: JSON.stringify(b.scene), ...layoutToProps(b.layout) } };
  }
}

export function noteToEditor(note: Note): BNBlock[] {
  return note.blocks.map((b) =>
    b.type === "columns"
      ? {
          id: b.id,
          type: "columnList",
          children: b.columns.map((c, i) => ({
            id: `${b.id}-c${i}`,
            type: "column",
            props: { width: c.widthPct / (100 / b.columns.length) },
            children: c.blocks.map(leafToBN),
          })),
        }
      : leafToBN(b),
  );
}

function bnToLeaf(b: BNBlock): LeafBlock | null {
  const p = b.props ?? {};
  const id = b.id ?? "";
  const text = Array.isArray(b.content) ? inlineToMarkdown(b.content) : "";
  switch (b.type) {
    case "heading":
      return { id, type: "heading", level: Math.min(3, Math.max(1, num(p.level, 1))) as 1 | 2 | 3, text };
    case "paragraph":
      return { id, type: "paragraph", text };
    case "eli5":
      return { id, type: "eli5", text };
    case "chart": {
      const spec = parseObj(p.spec);
      const valid = spec && VEGA_VIEW_KEYS.some((k) => k in spec);
      return withLayout({ id, type: "chart", spec: valid ? spec : DEFAULT_CHART_SPEC, source: str(p.source), verified: p.verified === true }, p);
    }
    case "diagram":
      return withLayout({ id, type: "diagram", mermaid: str(p.mermaid).trim() ? str(p.mermaid) : DEFAULT_MERMAID }, p);
    case "figure":
      if (!str(p.path)) return null;
      return withLayout({ id, type: "figure", path: str(p.path), caption: str(p.caption), page: Math.max(1, num(p.page, 1)) }, p);
    case "whiteboard":
      return withLayout({ id, type: "whiteboard", scene: parseObj(p.scene) ?? { elements: [] } }, p);
    default:
      // 其他 BlockNote 內建區塊（列表、引言、程式碼…）降級成段落，避免存檔被 schema 擋下
      return text ? { id, type: "paragraph", text } : null;
  }
}

function flattenLeaves(blocks: readonly BNBlock[]): LeafBlock[] {
  const out: LeafBlock[] = [];
  for (const b of blocks) {
    if (b.type === "columnList" || b.type === "column") {
      out.push(...flattenLeaves(b.children ?? []));
      continue;
    }
    const leaf = bnToLeaf(b);
    if (leaf) out.push(leaf);
    out.push(...flattenLeaves(b.children ?? []));
  }
  return out;
}

function toColumns(b: BNBlock): NoteBlock[] {
  const cols = (b.children ?? [])
    .filter((c) => c.type === "column")
    .map((c) => ({ width: num(c.props?.width, 1), leaves: flattenLeaves(c.children ?? []) }))
    .filter((c) => c.leaves.length > 0);
  if (cols.length < 2 || cols.length > 3) return cols.flatMap((c) => c.leaves);
  const total = cols.reduce((s, c) => s + c.width, 0);
  const widths = cols.map((c) => Math.min(90, Math.max(10, round1((c.width / total) * 100))));
  widths[widths.length - 1] = round1(100 - widths.slice(0, -1).reduce((s, w) => s + w, 0));
  const columns: Column[] = cols.map((c, i) => ({ widthPct: widths[i], blocks: c.leaves }));
  return [{ id: b.id ?? "", type: "columns", columns }];
}

export function editorToNote(blocks: readonly BNBlock[]): Note {
  const out: NoteBlock[] = [];
  for (const b of blocks) {
    if (b.type === "columnList") out.push(...toColumns(b));
    else out.push(...flattenLeaves([b]));
  }
  while (out.length > 0) {
    const last = out[out.length - 1];
    if (last.type === "paragraph" && last.text === "") out.pop();
    else break;
  }
  return { blocks: out };
}
