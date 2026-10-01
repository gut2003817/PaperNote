import { useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import type { Align, Layout } from "../types";
import { frameStyle, gapLayout, resizeLayout } from "./layout";

interface Props {
  layout: Layout;
  onChange: (l: Layout) => void;
  defaultHeightPx: number;
  toolbar?: ReactNode;
  children: ReactNode;
}

const ALIGNS: [Align, string][] = [["left", "靠左"], ["center", "置中"], ["right", "靠右"]];

export function ResizableFrame({ layout, onChange, defaultHeightPx, toolbar, children }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState<Layout | null>(null); // 拖曳中的暫時版面，放開才寫回區塊（一次 undo）
  const shown = draft ?? layout;

  const startDrag = (e: ReactPointerEvent, mode: "resize" | "gap") => {
    e.preventDefault();
    e.stopPropagation();
    const el = ref.current;
    if (!el?.parentElement) return;
    const containerWidth = el.parentElement.getBoundingClientRect().width;
    const startHeight = el.getBoundingClientRect().height;
    const x0 = e.clientX;
    const y0 = e.clientY;
    let latest = layout;
    const move = (ev: PointerEvent) => {
      const dx = ev.clientX - x0;
      const dy = ev.clientY - y0;
      latest = mode === "resize" ? resizeLayout(layout, dx, dy, containerWidth, startHeight) : gapLayout(layout, dy);
      setDraft(latest);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setDraft(null);
      onChange(latest);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div ref={ref} className="frame" style={frameStyle(shown, defaultHeightPx)} contentEditable={false}>
      <div className="frame-toolbar">
        {toolbar}
        {layout.widthPct < 100 &&
          ALIGNS.map(([a, label]) => (
            <button key={a} className={layout.align === a ? "active" : ""} onClick={() => onChange({ ...layout, align: a })}>
              {label}
            </button>
          ))}
      </div>
      <div className="frame-body">{children}</div>
      <div className="frame-resize" title="拖曳調整大小" onPointerDown={(e) => startDrag(e, "resize")} />
      <div className="frame-gap" title="拖曳調整下方間距" onPointerDown={(e) => startDrag(e, "gap")} />
    </div>
  );
}
