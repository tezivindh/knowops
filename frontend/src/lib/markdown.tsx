/**
 * Minimal, safe Markdown renderer for model output.
 *
 * Supports paragraphs, headings, nested bullet/numbered lists, fenced code,
 * inline code, bold and italics. Everything is rendered as React elements — no
 * HTML from the model ever reaches the DOM. Citation markers like [2] are
 * handed to `renderCitation` so callers can make them interactive.
 */

import { Fragment, type ReactNode } from "react";

type CitationRenderer = (index: number, key: string) => ReactNode;

const INLINE = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|((?:\[\d+\])+)/g;

/**
 * Models emit typographic spaces/hyphens (U+202F, U+2011, …) that many fonts
 * have no glyph for and render as nothing. Map them to plain equivalents.
 */
function normalise(text: string): string {
  return text.replace(/[   ]/g, " ").replace(/[‐‑]/g, "-");
}

function inline(text: string, renderCitation: CitationRenderer | undefined, keyBase: string) {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const match of text.matchAll(INLINE)) {
    const start = match.index ?? 0;
    if (start > last) out.push(text.slice(last, start));
    const token = match[0];
    const key = `${keyBase}-${i++}`;
    if (match[1]) out.push(<code key={key}>{token.slice(1, -1)}</code>);
    else if (match[2]) out.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    else if (match[3]) out.push(<em key={key}>{token.slice(1, -1)}</em>);
    else if (match[4]) {
      if (!renderCitation) {
        out.push(token);
      } else {
        const markers = [...token.matchAll(/\[(\d+)\]/g)].map((m, j) => renderCitation(Number(m[1]), `${key}-${j}`));
        // Keep the markers on the same line as the word before them, and as
        // any punctuation right after (so "year[1]." never wraps as "1.").
        const prev = out[out.length - 1];
        let lead = "";
        if (typeof prev === "string") {
          const m = /(\S+)$/.exec(prev);
          if (m) {
            lead = m[1];
            out[out.length - 1] = prev.slice(0, -lead.length);
          }
        }
        const after = /^[.,;:!?)]+/.exec(text.slice(start + token.length))?.[0] ?? "";
        out.push(
          <span key={key} className="whitespace-nowrap">
            {lead}
            {markers}
            {after}
          </span>,
        );
        last = start + token.length + after.length;
        continue;
      }
    }
    last = start + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const LIST_ITEM = /^(\s*)([-*•]|\d+[.)])\s+(.*)$/;

interface ListNode {
  ordered: boolean;
  items: { text: string; children: ListNode[] }[];
}

/** Parse consecutive list lines into a tree using their indentation. */
function parseList(lines: string[], start: number): [ListNode, number] {
  const first = LIST_ITEM.exec(lines[start])!;
  const baseIndent = first[1].replace(/\t/g, "  ").length;
  const node: ListNode = { ordered: /\d/.test(first[2]), items: [] };
  let i = start;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      // A blank line ends the list unless the next line continues it.
      const next = lines[i + 1];
      if (next !== undefined && LIST_ITEM.test(next)) {
        i++;
        continue;
      }
      break;
    }
    const m = LIST_ITEM.exec(line);
    const indent = (m ? m[1] : (/^(\s*)/.exec(line)?.[1] ?? "")).replace(/\t/g, "  ").length;
    if (m && indent < baseIndent) break;
    if (m && indent > baseIndent && node.items.length) {
      const [child, next] = parseList(lines, i);
      node.items[node.items.length - 1].children.push(child);
      i = next;
      continue;
    }
    if (m) {
      node.items.push({ text: m[3], children: [] });
      i++;
      continue;
    }
    if (indent > baseIndent && node.items.length) {
      // Wrapped continuation of the previous item.
      node.items[node.items.length - 1].text += " " + line.trim();
      i++;
      continue;
    }
    break;
  }
  return [node, i];
}

function renderList(node: ListNode, renderCitation: CitationRenderer | undefined, key: string): ReactNode {
  const children = node.items.map((item, j) => (
    <li key={j}>
      {inline(item.text, renderCitation, `${key}-${j}`)}
      {item.children.map((child, c) => renderList(child, renderCitation, `${key}-${j}-${c}`))}
    </li>
  ));
  return node.ordered ? <ol key={key}>{children}</ol> : <ul key={key}>{children}</ul>;
}

export function Markdown({
  source,
  renderCitation,
}: {
  source: string;
  renderCitation?: CitationRenderer;
}) {
  const lines = normalise(source).replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (/^\s*```/.test(line)) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]);
      i++; // closing fence
      blocks.push(
        <pre key={key++}>
          <code>{code.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      const k = `b${key++}`;
      blocks.push(
        heading[1].length <= 2 ? (
          <h3 key={k}>{inline(heading[2], renderCitation, k)}</h3>
        ) : (
          <h4 key={k}>{inline(heading[2], renderCitation, k)}</h4>
        ),
      );
      i++;
      continue;
    }

    if (LIST_ITEM.test(line)) {
      const [node, next] = parseList(lines, i);
      blocks.push(renderList(node, renderCitation, `b${key++}`));
      i = next;
      continue;
    }

    if (!line.trim()) {
      i++;
      continue;
    }

    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^\s*```/.test(lines[i]) &&
      !/^#{1,6}\s/.test(lines[i]) &&
      !LIST_ITEM.test(lines[i])
    ) {
      para.push(lines[i++]);
    }
    const k = `b${key++}`;
    blocks.push(
      <p key={k}>
        {para.map((p, j) => (
          <Fragment key={j}>
            {j > 0 && <br />}
            {inline(p, renderCitation, `${k}-${j}`)}
          </Fragment>
        ))}
      </p>,
    );
  }

  return <div className="prose-answer">{blocks}</div>;
}
