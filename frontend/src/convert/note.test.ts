import { describe, expect, it } from "vitest";
import { inlineToMarkdown, markdownToInline } from "./inline";
import { DEFAULT_CHART_SPEC, DEFAULT_LAYOUT, editorToNote, noteToEditor, propsToLayout, type BNBlock } from "./note";
import { SAMPLE_NOTE } from "./fixtures";

describe("inline", () => {
  it("markdown 來回轉換不失真", () => {
    const md = "我們提出 **Transformer**，完全使用 *attention*，見 [論文](https://x.org) 與 `softmax`。";
    expect(inlineToMarkdown(markdownToInline(md))).toBe(md);
  });
  it("產生 BlockNote 的 styled text 與 link", () => {
    expect(markdownToInline("a **b** [c](u)")).toEqual([
      { type: "text", text: "a ", styles: {} },
      { type: "text", text: "b", styles: { bold: true } },
      { type: "text", text: " ", styles: {} },
      { type: "link", href: "u", content: [{ type: "text", text: "c", styles: {} }] },
    ]);
  });
});

describe("note <-> editor", () => {
  it("空筆記提供一個段落", () => {
    expect(noteToEditor({ blocks: [] })).toEqual([{ type: "paragraph" }]);
  });

  it("SAMPLE_NOTE 來回轉換完全相同", () => {
    expect(editorToNote(noteToEditor(SAMPLE_NOTE))).toEqual(SAMPLE_NOTE);
  });

  it("columns 轉成 columnList，寬度用相對比例", () => {
    const col = noteToEditor(SAMPLE_NOTE).find((b) => b.type === "columnList")!;
    expect(col.children!.map((c) => [c.type, c.props!.width])).toEqual([["column", 0.8], ["column", 1.2]]);
  });

  it("欄寬比例 1:3 → 25/75", () => {
    const blocks: BNBlock[] = [{ id: "L", type: "columnList", children: [
      { id: "a", type: "column", props: { width: 1 }, children: [{ id: "x", type: "paragraph", content: [] }] },
      { id: "b", type: "column", props: { width: 3 }, children: [{ id: "y", type: "paragraph", content: [] }] },
    ] }];
    const note = editorToNote(blocks);
    expect(note.blocks[0]).toMatchObject({ type: "columns", columns: [{ widthPct: 25 }, { widthPct: 75 }] });
  });

  it.each([
    [85, 5, 10],
    [1, 1, 98],
    [1, 99],
    [1, 1, 1],
  ])("欄寬 %j 轉換後每欄符合範圍且總和為 100", (...widths: number[]) => {
    const note = editorToNote([{ id: "L", type: "columnList", children: widths.map((width, i) => ({
      type: "column", props: { width },
      children: [{ id: `p${i}`, type: "paragraph", content: markdownToInline(`欄 ${i}`) }],
    })) }]);
    const block = note.blocks[0];
    expect(block.type).toBe("columns");
    if (block.type !== "columns") throw new Error("預期保留 columns");
    expect(block.columns).toHaveLength(widths.length);
    const converted = block.columns.map((column) => column.widthPct);
    for (const width of converted) {
      expect(width).toBeGreaterThanOrEqual(10);
      expect(width).toBeLessThanOrEqual(90);
      expect(width).toBeCloseTo(Math.round(width * 10) / 10, 10);
    }
    const total = converted.reduce((sum, width) => sum + width, 0);
    expect(total).toBeGreaterThanOrEqual(99);
    expect(total).toBeLessThanOrEqual(101);
    expect(total).toBeCloseTo(100, 10);
  });

  it.each([
    [{ widthPct: 1, heightPx: 1, marginTopPx: -10, marginBottomPx: 300 },
      { widthPct: 10, heightPx: 50, marginTopPx: 0, marginBottomPx: 200, align: "center" }],
    [{ widthPct: 120, heightPx: 3000, marginTopPx: 300, marginBottomPx: -10 },
      { widthPct: 100, heightPx: 2000, marginTopPx: 200, marginBottomPx: 0, align: "center" }],
  ])("layout 數值夾到後端範圍：%j", (props, expected) => {
    expect(propsToLayout(props)).toEqual(expected);
    expect(editorToNote([{ id: "d", type: "diagram", props: { mermaid: "flowchart LR; A-->B", ...props } }]).blocks[0])
      .toMatchObject({ layout: expected });
  });

  it("layout 保留合法數值，heightPx 0 表示自動且不輸出", () => {
    expect(propsToLayout({ widthPct: 60, heightPx: 300, marginTopPx: 0, marginBottomPx: 200, align: "left" }))
      .toEqual({ widthPct: 60, heightPx: 300, marginTopPx: 0, marginBottomPx: 200, align: "left" });
    expect(propsToLayout({ heightPx: 0 })).toEqual(DEFAULT_LAYOUT);
    expect(propsToLayout({ heightPx: 0 })).not.toHaveProperty("heightPx");
  });

  it.each(["../x.png", "images/x.png", "x.jpg", "x.png\n"])("figure path %j 不符合檔名規則時丟棄", (path) => {
    expect(editorToNote([{ id: "f", type: "figure", props: { path, caption: "", page: 1 } }]).blocks).toEqual([]);
  });

  it("只剩一欄有內容時攤平", () => {
    const blocks: BNBlock[] = [{ id: "L", type: "columnList", children: [
      { id: "a", type: "column", props: { width: 1 }, children: [{ id: "x", type: "paragraph", content: [{ type: "text", text: "留下", styles: {} }] }] },
      { id: "b", type: "column", props: { width: 1 }, children: [] },
    ] }];
    expect(editorToNote(blocks).blocks).toEqual([{ id: "x", type: "paragraph", text: "留下" }]);
  });

  it("未知的內建區塊降級成段落，空的丟棄", () => {
    const blocks: BNBlock[] = [
      { id: "b1", type: "bulletListItem", content: [{ type: "text", text: "清單項目", styles: {} }] },
      { id: "b2", type: "codeBlock", content: [] },
    ];
    expect(editorToNote(blocks).blocks).toEqual([{ id: "b1", type: "paragraph", text: "清單項目" }]);
  });

  it("巢狀 children 攤平到父區塊之後", () => {
    const blocks: BNBlock[] = [{ id: "a", type: "paragraph", content: [{ type: "text", text: "父", styles: {} }],
      children: [{ id: "b", type: "paragraph", content: [{ type: "text", text: "子", styles: {} }] }] }];
    expect(editorToNote(blocks).blocks.map((b) => b.id)).toEqual(["a", "b"]);
  });

  it("結尾的空段落丟棄，中間的保留", () => {
    const blocks: BNBlock[] = [
      { id: "a", type: "paragraph", content: [] },
      { id: "b", type: "paragraph", content: [{ type: "text", text: "x", styles: {} }] },
      { id: "c", type: "paragraph", content: [] },
    ];
    expect(editorToNote(blocks).blocks.map((b) => b.id)).toEqual(["a", "b"]);
  });

  it("heading level 夾到 3、壞掉的 chart spec 用預設、沒選圖的 figure 丟棄", () => {
    const blocks: BNBlock[] = [
      { id: "h", type: "heading", props: { level: 5 }, content: [{ type: "text", text: "H", styles: {} }] },
      { id: "c", type: "chart", props: { spec: "{oops", source: "", verified: false, widthPct: 100, heightPx: 0, marginTopPx: 8, marginBottomPx: 8, align: "center" } },
      { id: "f", type: "figure", props: { path: "", caption: "", page: 1, widthPct: 100, heightPx: 0, marginTopPx: 8, marginBottomPx: 8, align: "center" } },
    ];
    const note = editorToNote(blocks);
    expect(note.blocks).toEqual([
      { id: "h", type: "heading", level: 3, text: "H" },
      { id: "c", type: "chart", spec: DEFAULT_CHART_SPEC, source: "", verified: false },
    ]);
  });
});
