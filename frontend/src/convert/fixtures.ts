import type { Note } from "../types";

export const BAR_SPEC = {
  mark: "bar",
  data: { values: [{ x: "A", y: 1 }, { x: "B", y: 3 }] },
  encoding: { x: { field: "x", type: "nominal" }, y: { field: "y", type: "quantitative" } },
};

export const SAMPLE_NOTE: Note = {
  blocks: [
    { id: "h1", type: "heading", level: 1, text: "Attention Is All You Need" },
    { id: "p1", type: "paragraph", text: "我們提出 **Transformer**，完全使用 *attention*，見 [論文](https://arxiv.org/abs/1706.03762) 與 `softmax`。" },
    { id: "e1", type: "eli5", text: "就像開會時每個人同時聽所有人說話。" },
    { id: "c1", type: "chart", spec: BAR_SPEC, source: "Table 2, p.8", verified: false,
      layout: { widthPct: 60, heightPx: 300, marginTopPx: 8, marginBottomPx: 24, align: "left" } },
    { id: "d1", type: "diagram", mermaid: "flowchart LR\n  A[輸入] --> B[Encoder]" },
    { id: "f1", type: "figure", path: "p3-1.png", caption: "模型架構", page: 3 },
    { id: "w1", type: "whiteboard", scene: { elements: [] } },
    { id: "col", type: "columns", columns: [
      { widthPct: 40, blocks: [{ id: "cl", type: "paragraph", text: "左欄" }] },
      { widthPct: 60, blocks: [{ id: "cr", type: "eli5", text: "右欄" }] },
    ] },
  ],
};
