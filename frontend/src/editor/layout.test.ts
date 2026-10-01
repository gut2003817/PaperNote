import { describe, expect, it } from "vitest";
import { frameStyle, gapLayout, resizeLayout } from "./layout";
import type { Layout } from "../types";

const L: Layout = { widthPct: 50, marginTopPx: 8, marginBottomPx: 8, align: "center" };

describe("layout", () => {
  it("向右拖 100px（容器 1000px）寬度 +10%", () => {
    expect(resizeLayout(L, 100, 0, 1000, 300)).toMatchObject({ widthPct: 60, heightPx: 300 });
  });
  it("寬度夾在 10–100%、高度夾在 50–2000px", () => {
    expect(resizeLayout(L, -2000, -1000, 1000, 300)).toMatchObject({ widthPct: 10, heightPx: 50 });
    expect(resizeLayout(L, 5000, 5000, 1000, 300)).toMatchObject({ widthPct: 100, heightPx: 2000 });
  });
  it("間距夾在 0–200px", () => {
    expect(gapLayout(L, 30).marginBottomPx).toBe(38);
    expect(gapLayout(L, -100).marginBottomPx).toBe(0);
    expect(gapLayout(L, 999).marginBottomPx).toBe(200);
  });
  it("frameStyle：對齊與預設高度", () => {
    expect(frameStyle({ ...L, align: "left" }, 320)).toMatchObject({ width: "50%", height: "320px", marginLeft: 0, marginRight: "auto" });
    expect(frameStyle({ ...L, heightPx: 200, align: "right" }, 320)).toMatchObject({ height: "200px", marginLeft: "auto", marginRight: 0 });
    expect(frameStyle(L, 0).height).toBeUndefined();
  });
});
