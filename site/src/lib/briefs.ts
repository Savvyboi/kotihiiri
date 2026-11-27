// AI briefs of meetings, items and votes (PLAN.md §20), written by `kunta briefs` into
// data/{city}/briefs/{yyyy}.json — a few files per city, keyed by meeting id, so the site gains no
// files. An item brief is hidden once the item's text has changed since the brief was written.
// Every text is stored per language ({fi, sv, en}); `lang` is the minutes' own language, used when
// a translation is missing.
import fs from 'node:fs';
import path from 'node:path';
import { DATA_DIR, type AgendaItem } from './data';

export const BRIEF_LANGS = ['fi', 'sv', 'en'] as const;
/** Text per language. Briefs written before 2026-11-27 hold a bare string in the source language. */
export type Texts<T> = Record<string, T> | T;

export interface ItemBrief { brief: Texts<string>; sha: string; votes?: Record<string, Texts<string>> }
export interface MeetingBrief {
  model: string; lang: string; stage: string; input_sha256: string;
  summary?: Texts<string>; highlights?: Texts<string[]>; items: Record<string, ItemBrief>;
}
/** One language's version of a brief. */
export interface Variant { lang: string; text: string; highlights?: string[] }

const cache = new Map<string, Map<string, MeetingBrief>>();

export function cityBriefs(cityId: string): Map<string, MeetingBrief> {
  let m = cache.get(cityId);
  if (m) return m;
  m = new Map();
  const dir = path.join(DATA_DIR, cityId, 'briefs');
  if (fs.existsSync(dir)) {
    for (const f of fs.readdirSync(dir).filter((n) => /^\d{4}\.json$/.test(n)).sort()) {
      const data = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')) as Record<string, MeetingBrief>;
      for (const [id, b] of Object.entries(data)) m.set(id, b);
    }
  }
  cache.set(cityId, m);
  return m;
}

const cityOf = (id: string) => id.split('/')[0];

/** {lang: value} from a per-language field or a legacy bare value in `source`. */
export function byLang<T>(v: Texts<T> | undefined, source: string): Record<string, T> {
  if (v === undefined || v === null || v === '') return {};
  if (typeof v === 'object' && !Array.isArray(v)) return v as Record<string, T>;
  return { [source]: v as T };
}

/** The language to show for `locale`: the locale itself, else the minutes' language, else Finnish. */
export function pickLang(available: string[], locale: string, source: string): string | undefined {
  return [locale, source, 'fi', ...available].find((l) => available.includes(l));
}

/** Versions to render: every language (`locale` undefined, for pages built once and switched in the
 * browser) or the one for `locale`. */
function variantsOf(texts: Record<string, string>, source: string, locale?: string, hl: Record<string, string[]> = {}): Variant[] {
  const langs = BRIEF_LANGS.filter((l) => texts[l]) as string[];
  for (const l of Object.keys(texts)) if (!langs.includes(l) && texts[l]) langs.push(l);
  const use = locale === undefined ? langs : [pickLang(langs, locale, source)].filter((l): l is string => !!l);
  return use.map((l) => ({ lang: l, text: texts[l], highlights: hl[l] ?? [] }));
}

/** The meeting's brief, when it was written for the meeting's current stage. */
export function meetingBrief(meetingId: string, stage?: string): MeetingBrief | undefined {
  const b = cityBriefs(cityOf(meetingId)).get(meetingId);
  return b && (!stage || b.stage === stage) ? b : undefined;
}

export function summaryVariants(b: MeetingBrief, locale?: string): Variant[] {
  return variantsOf(byLang(b.summary, b.lang), b.lang, locale, byLang(b.highlights, b.lang));
}

/** The item's brief, unless the item changed after it was written. */
export function itemBrief(item: AgendaItem): ItemBrief | undefined {
  const b = cityBriefs(cityOf(item.meeting_id)).get(item.meeting_id)?.items[String(item.ordinal)];
  return b && b.sha === item.content_sha256 ? b : undefined;
}

const sourceLang = (item: AgendaItem) => meetingBrief(item.meeting_id)?.lang ?? 'fi';

export function itemVariants(item: AgendaItem, locale?: string): Variant[] {
  const b = itemBrief(item);
  return b ? variantsOf(byLang(b.brief, sourceLang(item)), sourceLang(item), locale) : [];
}

export function voteVariants(item: AgendaItem, voteOrdinal: number, locale?: string): Variant[] {
  const v = itemBrief(item)?.votes?.[String(voteOrdinal)];
  return v ? variantsOf(byLang(v, sourceLang(item)), sourceLang(item), locale) : [];
}

/** "nvidia/nemotron-nano-9b-v2:free" → "nemotron-nano-9b-v2" */
export function modelName(model: string): string {
  return model.split('/').pop()!.replace(/:free$/, '');
}

/** data/{city}/briefs/digest.json: recent decisions across the city's bodies (PLAN.md §20). */
export interface DigestPoint { text: Texts<string>; meeting_id?: string }
export interface CityDigest {
  model: string; lang: string; period_start: string; period_end: string;
  summary: Texts<string>; points: DigestPoint[]; meetings: string[]; input_sha256: string;
}

export function cityDigest(cityId: string): CityDigest | undefined {
  const p = path.join(DATA_DIR, cityId, 'briefs', 'digest.json');
  return fs.existsSync(p) ? (JSON.parse(fs.readFileSync(p, 'utf8')) as CityDigest) : undefined;
}

/** The digest in one language: summary and points for `locale`, falling back like the briefs. */
export function digestIn(d: CityDigest, locale: string) {
  const summary = byLang(d.summary, d.lang);
  const lang = pickLang(Object.keys(summary).filter((l) => summary[l]), locale, d.lang) ?? d.lang;
  const points = d.points
    .map((p) => { const t = byLang(p.text, d.lang); return { text: t[lang] ?? t[d.lang], meeting_id: p.meeting_id }; })
    .filter((p) => p.text);
  return { lang, summary: summary[lang] ?? '', points };
}
