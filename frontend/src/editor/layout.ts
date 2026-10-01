import type { CSSProperties } from "react";
import type { Layout } from "../types";

export const MIN_WIDTH_PCT = 10;
export const MIN_HEIGHT = 50;
export const MAX_HEIGHT = 2000;
export const MAX_GAP = 200;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function resizeLayout(start: Layout, dx: number, dy: number, containerWidthPx: number, startHeightPx: number): Layout {
  const startWidthPx = (containerWidthPx * start.widthPct) / 100;
  const widthPct = clamp(Math.round(((startWidthPx + dx) / containerWidthPx) * 1000) / 10, MIN_WIDTH_PCT, 100);
  const heightPx = clamp(Math.round(startHeightPx + dy), MIN_HEIGHT, MAX_HEIGHT);
  return { ...start, widthPct, heightPx };
}

export function gapLayout(start: Layout, dy: number): Layout {
  return { ...start, marginBottomPx: clamp(Math.round(start.marginBottomPx + dy), 0, MAX_GAP) };
}

export function frameStyle(l: Layout, defaultHeightPx: number): CSSProperties {
  const h = l.heightPx || defaultHeightPx;
  return {
    position: "relative",
    width: `${l.widthPct}%`,
    height: h ? `${h}px` : undefined,
    marginTop: l.marginTopPx,
    marginBottom: l.marginBottomPx,
    marginLeft: l.align === "left" ? 0 : "auto",
    marginRight: l.align === "right" ? 0 : "auto",
  };
}
