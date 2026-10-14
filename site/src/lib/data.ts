// Build-time data access. Reads config/*.yaml and the committed data/ tree (PLAN.md §5.3).
// Set KUNTA_DATA_DIR to point at another tree (CI uses site/demo-data for a preview build).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import YAML from 'yaml';

const SITE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const ROOT = path.resolve(SITE_DIR, '..');
const DATA_DIR = process.env.KUNTA_DATA_DIR
  ? path.resolve(SITE_DIR, process.env.KUNTA_DATA_DIR)
  : path.join(ROOT, 'data');
export const IS_DEMO = fs.existsSync(path.join(DATA_DIR, 'DEMO'));

export type Choice = 'jaa' | 'ei' | 'tyhja' | 'poissa';
export interface PersonRef { raw: string; person_id?: string; confidence?: number }
export interface Ballot { person_ref: PersonRef; choice: Choice; group_text?: string }
export interface VoteEvent {
  ordinal: number; jaa_label: string; ei_label: string;
  counts: Record<Choice, number>; ballots: Ballot[]; result_text?: string;
  source: 'html' | 'pdf'; source_url: string; needs_review?: boolean;
}
export interface Section { type: string; heading?: string; text: string }
export interface Motion { kind: string; proposer_ref: PersonRef; seconder_refs?: PersonRef[]; text: string; outcome?: string }
export interface Election { year: number; party: string; result: 'elected' | 'deputy' | 'not_elected'; votes?: number; source: string }
export interface Person {
  id: string; city: string; name: string; sort_name: string; aliases: string[];
  party?: string; election?: Election;
}
export interface Membership {
  person_id: string; body_id: string; role: 'member' | 'deputy' | 'chair' | 'vice_chair' | 'youth_rep' | 'official';
  group?: string; start?: string; end?: string; source: string;
}
export interface PeopleFile { persons: Person[]; memberships: Membership[] }
export interface Speech {
  id: string; meeting_id: string; item_id?: string; ordinal: number; speaker_ref: PersonRef;
  speaker_title: string; kind: 'speech' | 'reply'; lang: 'fi' | 'sv' | 'mixed'; text: string;
  video_offset_s?: number; source_url: string;
}
export interface Attachment { title: string; url: string; kind?: string }
export interface AgendaItem {
  id: string; meeting_id: string; ordinal: number; pykala?: number; title: string;
  case_number?: string; presenter?: string; sections: Section[]; motions: Motion[]; votes: VoteEvent[];
  statements: Section[]; attachments: Attachment[]; decision_summary?: string; source_url: string;
  content_sha256: string; status?: 'active' | 'tombstone';
}
export interface Attendance { person_ref: PersonRef; role_text: string; present: boolean; note?: string }
export interface Meeting {
  id: string; body_id: string; date: string; start_time?: string; end_time?: string; location?: string;
  stage: 'agenda' | 'decisions' | 'minutes'; source_url: string; minutes_pdf_url?: string;
  video_url?: string; attendance: Attendance[]; items: string[];
}
export interface MeetingFile { meeting: Meeting; items: AgendaItem[] }
export interface Body {
  id: string; city: string; name_fi: string; kind: string; included?: boolean;
  active_from?: string; active_to?: string; successor?: string;
}
export interface City {
  id: string; name_fi: string; name_sv?: string; enabled: boolean; reason?: string;
  adapter: string; base_urls: string[]; source_name?: string; video_url?: string;
}

const readJson = <T>(p: string): T => JSON.parse(fs.readFileSync(p, 'utf8')) as T;
const cache = new Map<string, unknown>();
function memo<T>(key: string, fn: () => T): T {
  if (!cache.has(key)) cache.set(key, fn());
  return cache.get(key) as T;
}

export function cities(): City[] {
  return memo('cities', () => {
    const raw = YAML.parse(fs.readFileSync(path.join(ROOT, 'config/cities.yaml'), 'utf8'));
    return Object.entries(raw.cities as Record<string, Omit<City, 'id'>>).map(([id, c]) => ({ id, ...c }));
  });
}

/** City name in the UI language: Swedish names where they exist, Finnish otherwise. */
export function cityName(c: City, locale: string): string {
  return locale === 'sv' && c.name_sv ? c.name_sv : c.name_fi;
}

export function city(id: string): City | undefined {
  return cities().find((c) => c.id === id);
}

export function bodies(cityId: string): Body[] {
  return memo(`bodies:${cityId}`, () => {
    const p = path.join(DATA_DIR, cityId, 'bodies.json');
    const list = fs.existsSync(p) ? readJson<Body[]>(p) : [];
    return list.filter((b) => b.included !== false);
  });
}

export function bodySlug(bodyId: string): string {
  return bodyId.split('/')[1];
}

/** All meeting files for a city, newest first. */
export function meetingFiles(cityId: string): MeetingFile[] {
  return memo(`meetings:${cityId}`, () => {
    const dir = path.join(DATA_DIR, cityId, 'meetings');
    if (!fs.existsSync(dir)) return [];
    const files: MeetingFile[] = [];
    for (const year of fs.readdirSync(dir).sort()) {
      for (const f of fs.readdirSync(path.join(dir, year)).filter((n) => n.endsWith('.json')).sort()) {
        files.push(readJson<MeetingFile>(path.join(dir, year, f)));
      }
    }
    for (const mf of files) mf.items = mf.items.filter((i) => i.status !== 'tombstone');
    return files.sort((a, b) => b.meeting.date.localeCompare(a.meeting.date) || a.meeting.id.localeCompare(b.meeting.id));
  });
}

/** data/{city}/people.json (PLAN.md §5.3), written by `kunta people`; empty until the first run. */
export function peopleFile(cityId: string): PeopleFile {
  return memo(`people:${cityId}`, () => {
    const p = path.join(DATA_DIR, cityId, 'people.json');
    return fs.existsSync(p) ? readJson<PeopleFile>(p) : { persons: [], memberships: [] };
  });
}

/** Speeches of every meeting in data/{city}/speeches/ (PLAN.md §5.3, M6), in meeting order. */
export function speeches(cityId: string): Speech[] {
  return memo(`speeches:${cityId}`, () => {
    const dir = path.join(DATA_DIR, cityId, 'speeches');
    if (!fs.existsSync(dir)) return [];
    return fs.readdirSync(dir).filter((n) => n.endsWith('.json')).sort()
      .flatMap((f) => readJson<Speech[]>(path.join(dir, f)));
  });
}

export function speechesByItem(cityId: string): Map<string, Speech[]> {
  return memo(`speechesByItem:${cityId}`, () => {
    const out = new Map<string, Speech[]>();
    for (const s of speeches(cityId)) if (s.item_id) out.set(s.item_id, [...(out.get(s.item_id) ?? []), s]);
    return out;
  });
}

/** config/project.yaml `features` (PLAN.md §2.2 rule 9 for SPEECHES_BY_PERSON). */
export function feature(name: string): boolean {
  return memo(`feature:${name}`, () => {
    const raw = YAML.parse(fs.readFileSync(path.join(ROOT, 'config/project.yaml'), 'utf8'));
    return raw?.features?.[name] === true;
  });
}

/** URL segment for a meeting: the date, plus -2 for a second same-day meeting (PLAN.md §5.1). */
export function meetingSegment(meetingId: string): string {
  return meetingId.split('/')[2];
}

export function meetingUrl(m: Meeting): string {
  const [c, b, d] = m.id.split('/');
  return `/${c}/${b}/${d}/`;
}

export function itemUrl(item: AgendaItem): string {
  const [c, b, d, n] = item.id.split('/');
  return `/${c}/${b}/${d}/${n}/`;
}

export function bodyName(bodyId: string): string {
  const [c] = bodyId.split('/');
  return bodies(c).find((b) => b.id === bodyId)?.name_fi ?? bodySlug(bodyId);
}

export interface VoteRow { item: AgendaItem; meeting: Meeting; vote: VoteEvent }

/** Every vote of a city's minutes-stage meetings, newest meeting first, agenda order within one. */
export function allVotes(cityId: string): VoteRow[] {
  return memo(`votes:${cityId}`, () => {
    const rows: VoteRow[] = [];
    for (const mf of meetingFiles(cityId)) {
      if (mf.meeting.stage !== 'minutes') continue;
      for (const item of [...mf.items].sort((a, b) => a.ordinal - b.ordinal)) {
        for (const vote of [...item.votes].sort((a, b) => a.ordinal - b.ordinal)) rows.push({ item, meeting: mf.meeting, vote });
      }
    }
    return rows;
  });
}

export function recentVotes(cityId: string, limit = 6): VoteRow[] {
  return allVotes(cityId).slice(0, limit);
}

export function voteYears(cityId: string): string[] {
  return [...new Set(allVotes(cityId).map((r) => r.meeting.date.slice(0, 4)))].sort().reverse();
}

/** The city council (valtuusto), not its question-hour body. */
export function councilBody(cityId: string): Body | undefined {
  const councils = bodies(cityId).filter((b) => b.kind === 'council');
  return councils.find((b) => !/kysely/i.test(b.id)) ?? councils[0];
}

export function cityStats(cityId: string) {
  const files = meetingFiles(cityId);
  const items = files.reduce((n, f) => n + f.items.length, 0);
  const votes = files.reduce((n, f) => n + f.items.reduce((k, i) => k + i.votes.length, 0), 0);
  return { meetings: files.length, items, votes, bodies: bodies(cityId).length };
}

/** Decision text for cards: the stored summary, else the first decision section. */
export function decisionText(item: AgendaItem): string | undefined {
  return item.decision_summary ?? item.sections.find((s) => s.type === 'decision')?.text;
}

export function voteOutcome(v: VoteEvent): 'jaa' | 'ei' | 'tie' {
  if (v.counts.jaa === v.counts.ei) {
    // A tie is settled by the chair's vote: "puheenjohtajan Jaa-ääni ratkaisi"
    const casting = v.result_text?.match(/puheenjohtajan (jaa|ei)-ääni ratkaisi/i);
    return casting ? (casting[1].toLowerCase() as 'jaa' | 'ei') : 'tie';
  }
  return v.counts.jaa > v.counts.ei ? 'jaa' : 'ei';
}
