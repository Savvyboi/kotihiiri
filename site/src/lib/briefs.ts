// AI briefs of meetings, items and votes (PLAN.md §20), written by `kunta briefs` into
// data/{city}/briefs/{yyyy}.json — a few files per city, keyed by meeting id, so the site gains no
// files. An item brief is hidden once the item's text has changed since the brief was written.
import fs from 'node:fs';
import path from 'node:path';
import { DATA_DIR, type AgendaItem } from './data';

export interface ItemBrief { brief: string; sha: string; votes?: Record<string, string> }
export interface MeetingBrief {
  model: string; lang: string; stage: string; input_sha256: string;
  summary?: string; highlights?: string[]; items: Record<string, ItemBrief>;
}

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

/** The meeting's brief, when it was written for the meeting's current stage. */
export function meetingBrief(meetingId: string, stage?: string): MeetingBrief | undefined {
  const b = cityBriefs(cityOf(meetingId)).get(meetingId);
  return b && (!stage || b.stage === stage) ? b : undefined;
}

/** The item's brief, unless the item changed after it was written. */
export function itemBrief(item: AgendaItem): ItemBrief | undefined {
  const b = cityBriefs(cityOf(item.meeting_id)).get(item.meeting_id)?.items[String(item.ordinal)];
  return b && b.sha === item.content_sha256 ? b : undefined;
}

export function voteBrief(item: AgendaItem, voteOrdinal: number): string | undefined {
  return itemBrief(item)?.votes?.[String(voteOrdinal)];
}

/** "nvidia/nemotron-nano-9b-v2:free" → "nemotron-nano-9b-v2" */
export function modelName(model: string): string {
  return model.split('/').pop()!.replace(/:free$/, '');
}

/** data/{city}/briefs/digest.json: recent decisions across the city's bodies (PLAN.md §20). */
export interface DigestPoint { text: string; meeting_id?: string }
export interface CityDigest {
  model: string; lang: string; period_start: string; period_end: string;
  summary: string; points: DigestPoint[]; meetings: string[]; input_sha256: string;
}

export function cityDigest(cityId: string): CityDigest | undefined {
  const p = path.join(DATA_DIR, cityId, 'briefs', 'digest.json');
  return fs.existsSync(p) ? (JSON.parse(fs.readFileSync(p, 'utf8')) as CityDigest) : undefined;
}
