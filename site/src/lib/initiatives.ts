// Municipal initiatives (kuntalaisaloitteet) from kuntalaisaloite.fi, written by `kunta initiatives`
// to data/initiatives/{city}.json. Author names are never stored; only how many authors there are.
import fs from 'node:fs';
import path from 'node:path';
import { cities, DATA_DIR } from './data';

export interface Initiative {
  id: number; name: string; type?: 'SINGLE' | 'COLLABORATIVE' | 'COLLABORATIVE_CITIZEN';
  collaborative: boolean; publish_date?: string; sent_date?: string; participants: number;
  participants_external?: number; url_fi?: string; url_sv?: string; proposal?: string; authors?: number;
}
export interface InitiativeFile {
  municipality: string; source: string; source_municipality_id: number; active_in_service: boolean;
  initiatives: Initiative[];
}

/** One initiative as a row of the national page, short keys because every initiative is in one file. */
export interface InitiativeRow {
  i: number; // id at kuntalaisaloite.fi
  c: string; // municipality id
  n: string; // title
  d: string; // publish date, or ''
  s: string; // date sent to the municipality, or ''
  p: number; // supporters
  t: 'single' | 'collab'; // made by one person or a group, or collecting supporters
}

const DIR = path.join(DATA_DIR, 'initiatives');
const fileCache = new Map<string, InitiativeFile | null>();

export function initiativeFile(cityId: string): InitiativeFile | null {
  if (!fileCache.has(cityId)) {
    const p = path.join(DIR, `${cityId}.json`);
    fileCache.set(cityId, fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) as InitiativeFile : null);
  }
  return fileCache.get(cityId)!;
}

/** Newest first: by publish date, then by id. */
export function initiatives(cityId: string): Initiative[] {
  return [...(initiativeFile(cityId)?.initiatives ?? [])]
    .sort((a, b) => (b.publish_date ?? '').localeCompare(a.publish_date ?? '') || b.id - a.id);
}

export const initiativeUrl = (x: Initiative, locale: string) =>
  (locale === 'sv' ? x.url_sv : undefined) ?? x.url_fi ?? `https://www.kuntalaisaloite.fi/fi/aloite/${x.id}`;

let rowCache: InitiativeRow[] | undefined;

/** Every stored initiative of every municipality, newest first. */
export function allInitiativeRows(): InitiativeRow[] {
  if (rowCache) return rowCache;
  const rows: InitiativeRow[] = [];
  for (const c of cities()) {
    for (const x of initiatives(c.id)) {
      rows.push({ i: x.id, c: c.id, n: x.name, d: x.publish_date ?? '', s: x.sent_date ?? '', p: x.participants,
        t: x.type === 'SINGLE' ? 'single' : 'collab' });
    }
  }
  rowCache = rows.sort((a, b) => b.d.localeCompare(a.d) || b.i - a.i);
  return rowCache;
}

/** Municipalities with at least one initiative, for links and filters. */
export function initiativeCities(): string[] {
  return cities().filter((c) => initiatives(c.id).length > 0).map((c) => c.id);
}
