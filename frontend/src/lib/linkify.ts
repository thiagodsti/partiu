/**
 * Splits free text into plain runs and links, so a note such as
 * "book here https://www.example.com/very/long/path?x=…" renders the link as
 * something tappable and short ("example.com") instead of a wall of URL.
 * Only http(s) is linked: anything else stays text, so a note can never carry
 * a `javascript:` link.
 */
export type TextPart = { text: string } | { url: string; label: string };

const URL_RE = /https?:\/\/[^\s<>"']+/g;
/** Punctuation that ends a sentence, not the URL ("see https://x.com."). */
const TRAILING = /[.,;:!?)\]]$/;

export function splitLinks(text: string): TextPart[] {
  const parts: TextPart[] = [];
  let last = 0;
  for (const m of text.matchAll(URL_RE)) {
    const url = trimTrailing(m[0]);
    const start = m.index ?? 0;
    if (start > last) parts.push({ text: text.slice(last, start) });
    parts.push({ url, label: linkLabel(url) });
    last = start + url.length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}

/**
 * Drops sentence punctuation after a URL, but keeps a closing bracket the URL
 * itself opened: `…/wiki/Fado_(music)` is one link, `(see https://x.com)` is
 * a link inside brackets.
 */
function trimTrailing(url: string): string {
  let out = url;
  for (;;) {
    const last = out.at(-1) ?? '';
    if (!TRAILING.test(last)) return out;
    const open = last === ')' ? '(' : last === ']' ? '[' : '';
    if (open && count(out, open) >= count(out, last)) return out;
    out = out.slice(0, -1);
  }
}

function count(s: string, ch: string): number {
  return s.split(ch).length - 1;
}

/** The host without "www.", which is what a reader recognises. */
export function linkLabel(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}
