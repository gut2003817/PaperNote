export type Styles = { bold?: true; italic?: true; code?: true };
export type StyledText = { type: "text"; text: string; styles: Styles };
export type Link = { type: "link"; href: string; content: StyledText[] };
export type Inline = StyledText | Link;

const TOKEN = /\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`/g;

const text = (t: string, styles: Styles = {}): StyledText => ({ type: "text", text: t, styles });

/** 只支援粗體、斜體、行內程式碼、連結；巢狀樣式（粗斜體）不保證保留。 */
export function markdownToInline(md: string): Inline[] {
  const out: Inline[] = [];
  let last = 0;
  for (const m of md.matchAll(TOKEN)) {
    const i = m.index ?? 0;
    if (i > last) out.push(text(md.slice(last, i)));
    if (m[1] !== undefined) out.push({ type: "link", href: m[2], content: [text(m[1])] });
    else if (m[3] !== undefined) out.push(text(m[3], { bold: true }));
    else if (m[4] !== undefined) out.push(text(m[4], { italic: true }));
    else out.push(text(m[5], { code: true }));
    last = i + m[0].length;
  }
  if (last < md.length) out.push(text(md.slice(last)));
  return out;
}

function wrap(t: string, s: Record<string, unknown>): string {
  if (!t) return t;
  if (s.code) return "`" + t + "`";
  let r = t;
  if (s.italic) r = `*${r}*`;
  if (s.bold) r = `**${r}**`;
  return r;
}

export function inlineToMarkdown(content: readonly unknown[]): string {
  return content
    .map((item) => {
      const it = item as { type?: string; text?: string; styles?: Record<string, unknown>; href?: string; content?: unknown[] };
      if (it.type === "link") return `[${inlineToMarkdown(it.content ?? [])}](${it.href ?? ""})`;
      if (it.type === "text") return wrap(it.text ?? "", it.styles ?? {});
      return "";
    })
    .join("");
}
