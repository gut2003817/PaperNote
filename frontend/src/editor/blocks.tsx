import { useEffect, useMemo, useRef, useState } from "react";
import type { BlockNoteEditor } from "@blocknote/core";
import { createReactBlockSpec } from "@blocknote/react";
import embed from "vega-embed";
import mermaid from "mermaid";
import { Excalidraw } from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";
import { api } from "../api";
import { DEFAULT_CHART_SPEC, DEFAULT_MERMAID, layoutToProps, propsToLayout } from "../convert/note";
import type { Layout } from "../types";
import { ResizableFrame } from "./ResizableFrame";
import { slugStore } from "./slugStore";

const layoutPropSchema = {
  widthPct: { default: 100 },
  heightPx: { default: 0 },
  marginTopPx: { default: 8 },
  marginBottomPx: { default: 8 },
  align: { default: "center" as const, values: ["left", "center", "right"] as const },
};

type LayoutProps = ReturnType<typeof layoutToProps>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyEditor = BlockNoteEditor<any, any, any>;
interface ViewProps<P> {
  block: { id: string; props: P };
  editor: AnyEditor;
}

function useBlockProps<P extends LayoutProps>({ block, editor }: ViewProps<P>) {
  const update = (props: Partial<P>) => editor.updateBlock(block.id, { props } as never);
  const layout = propsToLayout(block.props as unknown as Record<string, unknown>);
  const setLayout = (l: Layout) => update(layoutToProps(l) as Partial<P>);
  return { p: block.props, update, layout, setLayout };
}

/* ---------- ELI5 白話框 ---------- */
export const Eli5Block = createReactBlockSpec(
  { type: "eli5", propSchema: {}, content: "inline" },
  {
    render: (props) => (
      <div className="eli5">
        <span className="eli5-label" contentEditable={false}>白話解釋</span>
        <div className="eli5-text" ref={props.contentRef} />
      </div>
    ),
  },
);

/* ---------- 數據圖 ---------- */
type ChartProps = LayoutProps & { spec: string; source: string; verified: boolean };
const VEGA_VIEW_KEYS = ["mark", "layer", "concat", "hconcat", "vconcat", "facet", "repeat"];

function prettyJson(s: string) {
  try {
    return JSON.stringify(JSON.parse(s), null, 2);
  } catch {
    return s;
  }
}

function ChartView(props: ViewProps<ChartProps>) {
  const { p, update, layout, setLayout } = useBlockProps(props);
  const ref = useRef<HTMLDivElement>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(p.spec);
  const [err, setErr] = useState<string | null>(null);
  const height = layout.heightPx || 320;

  useEffect(() => {
    if (editing || !ref.current) return;
    let spec: Record<string, unknown>;
    try {
      spec = JSON.parse(p.spec);
    } catch {
      setErr("規格不是合法 JSON");
      return;
    }
    let cancelled = false;
    let finalize: (() => void) | undefined;
    embed(ref.current, { ...spec, width: "container", height: Math.max(60, height - 70), autosize: { type: "fit", contains: "padding" } } as never, { actions: false })
      .then((r) => {
        if (cancelled) r.finalize();
        else {
          finalize = r.finalize;
          setErr(null);
        }
      })
      .catch((e: Error) => setErr(`圖表無法繪製：${e.message}`));
    return () => {
      cancelled = true;
      finalize?.();
    };
  }, [p.spec, layout.widthPct, height, editing]);

  const save = () => {
    try {
      const s = JSON.parse(draft);
      if (!VEGA_VIEW_KEYS.some((k) => k in s)) throw new Error("需要 mark、layer 等其中一個欄位");
      update({ spec: JSON.stringify(s) });
      setEditing(false);
      setErr(null);
    } catch (e) {
      setErr(`無法套用：${(e as Error).message}`);
    }
  };

  return (
    <ResizableFrame
      layout={layout}
      onChange={setLayout}
      defaultHeightPx={320}
      toolbar={<button onClick={() => { setDraft(prettyJson(p.spec)); setEditing(!editing); }}>{editing ? "關閉" : "編輯資料"}</button>}
    >
      {!p.verified && (
        <button className="badge-unverified" title="對過論文原文後點擊" onClick={() => update({ verified: true })}>
          AI 抽取，待核對
        </button>
      )}
      {editing ? (
        <>
          <textarea className="spec-editor" value={draft} onChange={(e) => setDraft(e.target.value)} />
          <button onClick={save}>套用</button>
        </>
      ) : (
        <div ref={ref} className="chart-canvas" />
      )}
      {p.source && <div className="chart-source">出處：{p.source}</div>}
      {err && <div className="block-error">{err}</div>}
    </ResizableFrame>
  );
}

export const ChartBlock = createReactBlockSpec(
  {
    type: "chart",
    propSchema: { spec: { default: JSON.stringify(DEFAULT_CHART_SPEC) }, source: { default: "" }, verified: { default: false }, ...layoutPropSchema },
    content: "none",
  },
  { render: ({ block, editor }) => <ChartView block={block as never} editor={editor as AnyEditor} /> },
);

/* ---------- 概念圖 ---------- */
type DiagramProps = LayoutProps & { mermaid: string };
let mermaidReady = false;
let mermaidCounter = 0;

function DiagramView(props: ViewProps<DiagramProps>) {
  const { p, update, layout, setLayout } = useBlockProps(props);
  const ref = useRef<HTMLDivElement>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(p.mermaid);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (editing || !ref.current) return;
    if (!mermaidReady) {
      mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });
      mermaidReady = true;
    }
    let cancelled = false;
    const id = `mmd-${props.block.id}-${++mermaidCounter}`;
    mermaid
      .render(id, p.mermaid)
      .then(({ svg }) => {
        if (!cancelled && ref.current) {
          ref.current.innerHTML = svg;
          setErr(null);
        }
      })
      .catch((e: Error) => {
        document.getElementById(`d${id}`)?.remove();
        if (!cancelled) setErr(`Mermaid 語法錯誤：${e.message}`);
      });
    return () => {
      cancelled = true;
    };
  }, [p.mermaid, editing, props.block.id]);

  const save = async () => {
    try {
      await mermaid.parse(draft);
      update({ mermaid: draft });
      setEditing(false);
    } catch (e) {
      setErr(`無法套用：${(e as Error).message}`);
    }
  };

  return (
    <ResizableFrame
      layout={layout}
      onChange={setLayout}
      defaultHeightPx={0}
      toolbar={<button onClick={() => { setDraft(p.mermaid); setEditing(!editing); }}>{editing ? "關閉" : "編輯原始碼"}</button>}
    >
      {editing ? (
        <>
          <textarea className="spec-editor" style={{ minHeight: 160 }} value={draft} onChange={(e) => setDraft(e.target.value)} />
          <button onClick={save}>套用</button>
        </>
      ) : (
        <div ref={ref} className="diagram-canvas" />
      )}
      {err && <div className="block-error">{err}</div>}
    </ResizableFrame>
  );
}

export const DiagramBlock = createReactBlockSpec(
  { type: "diagram", propSchema: { mermaid: { default: DEFAULT_MERMAID }, ...layoutPropSchema }, content: "none" },
  { render: ({ block, editor }) => <DiagramView block={block as never} editor={editor as AnyEditor} /> },
);

/* ---------- 論文原圖 ---------- */
type FigureProps = LayoutProps & { path: string; caption: string; page: number };

function FigureView(props: ViewProps<FigureProps>) {
  const { p, update, layout, setLayout } = useBlockProps(props);
  const [choices, setChoices] = useState<string[] | null>(null);
  const [caption, setCaption] = useState(p.caption);
  const [err, setErr] = useState<string | null>(null);
  const slug = slugStore.current;

  const openPicker = () => api.figures(slug).then(setChoices).catch((e: Error) => setErr(e.message));
  useEffect(() => {
    if (!p.path) openPicker();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.path]);
  useEffect(() => setCaption(p.caption), [p.caption]);

  const pick = (name: string) => {
    const m = name.match(/^(?:page-|p)(\d+)/);
    update({ path: name, page: m ? Number(m[1]) : 1 });
    setChoices(null);
  };

  return (
    <ResizableFrame layout={layout} onChange={setLayout} defaultHeightPx={0} toolbar={<button onClick={openPicker}>換圖</button>}>
      {choices ? (
        <div className="figure-picker">
          {choices.map((name) => (
            <button key={name} onClick={() => pick(name)}>
              <img src={api.figureUrl(slug, name)} alt={name} loading="lazy" />
              <span>{name}</span>
            </button>
          ))}
        </div>
      ) : (
        p.path && <img className="figure-img" src={api.figureUrl(slug, p.path)} alt={p.caption} />
      )}
      <input
        className="figure-caption"
        value={caption}
        placeholder="圖說"
        onChange={(e) => setCaption(e.target.value)}
        onBlur={() => caption !== p.caption && update({ caption })}
      />
      {err && <div className="block-error">{err}</div>}
    </ResizableFrame>
  );
}

export const FigureBlock = createReactBlockSpec(
  { type: "figure", propSchema: { path: { default: "" }, caption: { default: "" }, page: { default: 1 }, ...layoutPropSchema }, content: "none" },
  { render: ({ block, editor }) => <FigureView block={block as never} editor={editor as AnyEditor} /> },
);

/* ---------- 白板 ---------- */
type WhiteboardProps = LayoutProps & { scene: string };

function WhiteboardView(props: ViewProps<WhiteboardProps>) {
  const { p, update, layout, setLayout } = useBlockProps(props);
  const initial = useMemo(() => {
    try {
      return JSON.parse(p.scene) as { elements?: unknown[] };
    } catch {
      return { elements: [] };
    }
    // 只在掛載時讀一次；之後由 Excalidraw 自己持有狀態
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.block.id]);
  const lastSaved = useRef(p.scene);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const onChange = (elements: readonly unknown[]) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const next = JSON.stringify({ elements });
      if (next !== lastSaved.current) {
        lastSaved.current = next;
        update({ scene: next });
      }
    }, 800);
  };

  return (
    <ResizableFrame layout={layout} onChange={setLayout} defaultHeightPx={420}>
      <div className="whiteboard" onKeyDown={(e) => e.stopPropagation()} onPaste={(e) => e.stopPropagation()}>
        <Excalidraw initialData={{ elements: (initial.elements ?? []) as never, appState: { viewBackgroundColor: "#ffffff" } }} onChange={onChange} />
      </div>
    </ResizableFrame>
  );
}

export const WhiteboardBlock = createReactBlockSpec(
  { type: "whiteboard", propSchema: { scene: { default: '{"elements":[]}' }, ...layoutPropSchema }, content: "none" },
  { render: ({ block, editor }) => <WhiteboardView block={block as never} editor={editor as AnyEditor} /> },
);
