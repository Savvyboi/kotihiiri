// Turns the plain text of a minutes section into blocks a reader can scan: headings, paragraphs,
// lists, label–value rows and quotes. The crawlers keep the source's text as it is (paragraphs
// separated by blank lines, or PDF lines hard-wrapped at a fixed width); this only decides how to
// show it. Deterministic and conservative: when unsure, a block stays a paragraph.

export type Block =
  | { kind: 'p'; text: string }
  | { kind: 'h'; text: string }
  | { kind: 'meta'; text: string }
  | { kind: 'quote'; text: string }
  | { kind: 'ul'; items: string[] }
  | { kind: 'ol'; items: { n: string; text: string }[] }
  | { kind: 'dl'; rows: [string, string][] };

const MARKER = /^(?:[-–•*▪◦]\s+|o\s+(?=\p{Ll})|\(?([a-zåäö]|\d{1,2})\)\s+|(\d{1,2})\.\s+(?=[A-ZÅÄÖa-zåäö]))/u;
const ENDS_SENTENCE = /[.:!?;"”»)]$/;
// Labels minutes use as section headings even though they are a single word.
const LABELS = /^(päätös|esitys|päätösehdotus|ehdotus|käsittely|asian käsittely|päätöksen perustelut|perustelut|esittelijä|esittelijän perustelut|lisätiedot|tiivistelmä|selostus|valmistelija|valmistelijat|liitteet|oheismateriaali|muutoksenhaku|täytäntöönpano|asia|beslut|förslag|motivering|behandling|bilagor|tilläggsuppgifter)$/i;
const DIARY = /^(?:[A-ZÅÄÖ]{2,6}[ /]\d{4}-\d{4,7}|Dno\s|Dnro\s|[A-ZÅÄÖ]{2,6}\/\d+\/[\d.]+\/\d{4})[\w ./-]*$/;
const KEYVAL_LONG = /^([A-ZÅÄÖ][\p{L}\d ()/-]{1,38}):\s+(\S.{0,400})$/u;
const KEYVAL = /^([A-ZÅÄÖ][\p{L}\d ()/-]{1,38}):\s+(\S.{0,140})$/u;

/** Joins hard-wrapped PDF lines back into paragraphs. */
function unwrap(block: string): string[] {
  const lines = block.split('\n').map((l) => l.trim()).filter(Boolean);
  if (lines.length < 3) return lines.length > 1 && lines.every((l) => l.length > 50) ? [lines.join(' ')] : lines;
  const sorted = lines.map((l) => l.length).sort((a, b) => a - b);
  const width = sorted[Math.floor(sorted.length * 0.9)];
  if (width < 50) return lines; // a column of short lines (names, figures): keep as is
  const out: string[] = [];
  let lastLine = '';
  for (const line of lines) {
    const prev = out[out.length - 1];
    const soft = prev !== undefined && !MARKER.test(line) && !/:$/.test(lastLine) && (
      /^[a-zåäö0-9(,–-]/.test(line) ||
      lastLine.length >= width * 0.8 ||
      (!ENDS_SENTENCE.test(lastLine) && lastLine.length >= width * 0.6));
    if (soft) out[out.length - 1] = `${prev} ${line}`;
    else out.push(line);
    lastLine = line;
  }
  return out;
}

function isHeading(p: string, next: string | undefined): boolean {
  if (LABELS.test(p.replace(/:$/, ''))) return next !== undefined;
  if (next === undefined || p.length > 80 || p.length < 4) return false;
  if (!/^[A-ZÅÄÖ]/.test(p) || /[.,;:]$/.test(p) || /^\d/.test(p)) return false;
  if (p.split(/\s+/).length > 10) return false;
  if (DIARY.test(p) || KEYVAL.test(p)) return false;
  return next.length > p.length * 1.5 && /^[A-ZÅÄÖ"”0-9]/.test(next);
}

export function structure(text: string): Block[] {
  if (!text) return [];
  const all = text.replace(/\r/g, '').split(/\n\s*\n/).flatMap(unwrap).map((p) => p.trim()).filter(Boolean);
  // Page furniture from PDF minutes ("Oulun kaupunki", "Päivämäärä", "3 (12)") repeats on every page.
  const seen = new Map<string, number>();
  for (const p of all) if (p.length < 40) seen.set(p, (seen.get(p) ?? 0) + 1);
  const paras = all.filter((p) => !/^\d+ ?\(\d+\)$/.test(p) && !((seen.get(p) ?? 0) > 2 && !LABELS.test(p.replace(/:$/, '')) && !MARKER.test(p)));
  const blocks: Block[] = [];
  const last = () => blocks[blocks.length - 1];
  for (let i = 0; i < paras.length; i++) {
    const p = paras[i];
    const next = paras[i + 1];
    // Espoo numbers decision points as a bare number on its own line, then the point.
    if (/^\d{1,2}$/.test(p) && next && !/^\d{1,2}$/.test(next)) {
      const prev = last();
      if (prev?.kind === 'ol') prev.items.push({ n: p, text: next });
      else blocks.push({ kind: 'ol', items: [{ n: p, text: next }] });
      i++;
      continue;
    }
    const m = p.match(MARKER);
    if (m) {
      const body = p.slice(m[0].length).trim();
      const n = m[1] ?? m[2];
      const prev = last();
      if (n) {
        if (prev?.kind === 'ol') prev.items.push({ n, text: body });
        else blocks.push({ kind: 'ol', items: [{ n, text: body }] });
      } else if (prev?.kind === 'ul') prev.items.push(body);
      else blocks.push({ kind: 'ul', items: [body] });
      continue;
    }
    if (i === 0 && DIARY.test(p)) { blocks.push({ kind: 'meta', text: p }); continue; }
    const kv = p.match(KEYVAL) ?? (last()?.kind === 'dl' ? p.match(KEYVAL_LONG) : null);
    if (kv && (KEYVAL.test(next ?? '') || last()?.kind === 'dl')) {
      const prev = last();
      if (prev?.kind === 'dl') prev.rows.push([kv[1], kv[2]]);
      else blocks.push({ kind: 'dl', rows: [[kv[1], kv[2]]] });
      continue;
    }
    // Lowercase points after a lead-in ("päättää määrätä … / tuloveroprosentiksi 7,1 %").
    const prev = last();
    if (/^[a-zåäö]/.test(p) && p.length < 400 && prev) {
      if (prev.kind === 'ul' && !prev.items.some((x) => /^[A-ZÅÄÖ]/.test(x))) { prev.items.push(p); continue; }
      const leadIn = prev.kind === 'p' && (/:$/.test(prev.text) || !ENDS_SENTENCE.test(prev.text) || /(päätti|päättää|esittää|esitti|että|seuraavasti)\s*$/i.test(prev.text));
      if (leadIn && (next === undefined || /^[a-zåäö]/.test(next) || /:$/.test(prev.text))) { blocks.push({ kind: 'ul', items: [p] }); continue; }
    }
    if (/^["”“»]/.test(p) && p.length > 40) { blocks.push({ kind: 'quote', text: p.replace(/^["”“»]\s*|\s*["”“»]$/g, '') }); continue; }
    if (isHeading(p, next) && (prev?.kind !== 'h' || LABELS.test(p.replace(/:$/, '')))) { blocks.push({ kind: 'h', text: p.replace(/:$/, '') }); continue; }
    blocks.push({ kind: 'p', text: p });
  }
  // A heading with nothing after it is just a line.
  return blocks.map((b, i) => (b.kind === 'h' && (i === blocks.length - 1 || blocks[i + 1].kind === 'h') ? { kind: 'p', text: b.text } : b));
}

export const blockText = (b: Block): string =>
  b.kind === 'ul' ? b.items.join(' ') : b.kind === 'ol' ? b.items.map((x) => x.text).join(' ')
    : b.kind === 'dl' ? b.rows.map(([k, v]) => `${k} ${v}`).join(' ') : b.text;

export const blockLength = (b: Block): number =>
  b.kind === 'ul' ? b.items.join(' ').length : b.kind === 'ol' ? b.items.reduce((n, x) => n + x.text.length, 0)
    : b.kind === 'dl' ? b.rows.reduce((n, [k, v]) => n + k.length + v.length, 0) : b.text.length;

export const wordCount = (text: string): number => (text.match(/\S+/g) ?? []).length;

/** First sentences of a text, cut at a word boundary. */
export function excerpt(text: string, max = 240): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  if (flat.length <= max) return flat;
  const cut = flat.slice(0, max);
  const stop = cut.lastIndexOf('. ');
  return stop > max * 0.5 ? cut.slice(0, stop + 1) : `${cut.replace(/\s+\S*$/, '')}…`;
}

export type Outcome = 'approved' | 'amended' | 'tabled' | 'returned' | 'rejected' | 'noted' | 'elected' | 'other';

/** What happened to an item, read from its decision text (Finnish and Swedish minutes). */
export function decisionOutcome(decision: string | undefined): Outcome | undefined {
  if (!decision) return undefined;
  const d = decision.toLowerCase().slice(0, 600);
  if (/pöydälle|bordlad/.test(d)) return 'tabled';
  if (/palaut\w* (uudelleen )?valmisteltavaksi|palautettiin|palauttaa asian|återremitt/.test(d)) return 'returned';
  if (/hylättiin|hylkää|förkastades/.test(d)) return 'rejected';
  if (/muutettuna|muutoksin|seuraavin muutoksin|med ändring/.test(d)) return 'amended';
  if (/valitsi|valittiin|valitaan|valde|valdes/.test(d)) return 'elected';
  if (/hyväksyttiin|hyväksyi|hyväksyy|ehdotuksen mukaisesti|esityksen mukaisesti|godkände|godkändes|enligt förslaget/.test(d)) return 'approved';
  if (/merkittiin|merkitsi|tiedoksi|antecknades|för kännedom/.test(d)) return 'noted';
  return 'other';
}

// Opening formalities every meeting starts with; the meeting page folds them away.
const PROCEDURAL = /^(kokouksen (avaus|avaaminen|laillisuus|päätösvaltaisuus|järjestäytyminen)|laillisuus ja päätösvaltaisuus|kokouksen laillisuuden ja päätösvaltaisuuden toteaminen|pöytäkirjan tarkast|pöytäkirjantarkast|työjärjestyksen|esityslistan hyväksyminen|asioiden käsittelyjärjestys|nimenhuuto|ilmoitusasiat|tiedoksi merkittävät|mötets (öppnande|laglighet)|val av protokolljusterare)/i;
export const isProcedural = (title: string): boolean => PROCEDURAL.test(title.trim());

/** The first real sentence(s) of a section, skipping headings, the diary number and bare
 *  lead-ins such as "Valtuusto:". */
export function leadText(text: string, max = 160): string {
  const parts: string[] = [];
  let n = 0;
  for (const b of structure(text)) {
    if (b.kind === 'h' || b.kind === 'meta') continue;
    const t = blockText(b);
    parts.push(t);
    n += t.length;
    if (n >= max || (t.length >= 40 && !/:$/.test(t))) break;
  }
  return excerpt(parts.length ? parts.join(' ') : text, max);
}
