// Who sits where, derived from vote records until the roster scraper lands (PLAN.md §8, M5).
// Helsinki's council vote tables print every seat with its council group, so one vote gives the
// seat count per group, and the votes of the term show who held those seats. Other bodies' votes
// list names only; their group comes from the council records when the person is a councillor.
import { allVotes, councilBody, type VoteRow } from './data';
import { partyOf, PARTY_ORDER, type Party } from './parties';

/** Start of the 2025–2029 council term (PLAN.md §5.2 Term; per-city check pending, S7). */
export const TERM_START = '2025-06-01';

export interface PersonRow { key: string; name: string; group?: string; party?: Party; seen: number }
export interface Seats { party: Party; group: string; n: number }

/** "Sukunimi, Etunimi" → "Etunimi Sukunimi"; other forms are kept as printed. */
export function displayName(raw: string): string {
  const m = raw.match(/^([^,]+),\s*(.+)$/);
  return (m ? `${m[2]} ${m[1]}` : raw).replace(/\s+/g, ' ').trim();
}

/** Order-insensitive key, as kunta/people.py name_key does. */
export function nameKey(raw: string): string {
  return (raw.toLowerCase().match(/[\p{L}\p{N}]+(?:-[\p{L}\p{N}]+)*/gu) ?? []).sort().join(' ');
}

function termVotes(rows: VoteRow[]): VoteRow[] {
  const inTerm = rows.filter((r) => r.meeting.date >= TERM_START);
  return inTerm.length ? inTerm : rows;
}

function tally(rows: VoteRow[]): Map<string, PersonRow & { lastDate: string }> {
  const people = new Map<string, PersonRow & { lastDate: string }>();
  // rows are newest first, so the first sighting carries the latest name form and group
  for (const { vote, meeting } of rows) {
    for (const b of vote.ballots) {
      const key = nameKey(displayName(b.person_ref.raw));
      const p = people.get(key);
      if (p) p.seen += 1;
      else people.set(key, {
        key, name: displayName(b.person_ref.raw), group: b.group_text ?? undefined,
        party: partyOf(b.group_text), seen: 1, lastDate: meeting.date,
      });
    }
  }
  return people;
}

const byPartyThenName = (a: PersonRow, b: PersonRow) =>
  PARTY_ORDER.indexOf(a.party ?? 'other') - PARTY_ORDER.indexOf(b.party ?? 'other') || a.name.localeCompare(b.name, 'fi');

export interface CouncilRoster {
  bodyId: string; date: string; total: number; votes: number;
  seats: Seats[]; members: PersonRow[]; deputies: PersonRow[];
}

/** Council seats per group (from the latest vote with groups) and who held them this term. */
export function councilRoster(cityId: string): CouncilRoster | undefined {
  const council = councilBody(cityId);
  if (!council) return undefined;
  const rows = termVotes(allVotes(cityId).filter((r) => r.meeting.body_id === council.id
    && r.vote.ballots.some((b) => b.group_text)));
  if (!rows.length) return undefined;
  const latest = rows[0];
  const seatsByGroup = new Map<string, number>();
  for (const b of latest.vote.ballots) {
    const g = b.group_text ?? '';
    seatsByGroup.set(g, (seatsByGroup.get(g) ?? 0) + 1);
  }
  const people = [...tally(rows).values()];
  const members: PersonRow[] = [];
  const deputies: PersonRow[] = [];
  for (const [group, n] of seatsByGroup) {
    const inGroup = people.filter((p) => (p.group ?? '') === group)
      .sort((a, b) => b.seen - a.seen || a.name.localeCompare(b.name, 'fi'));
    members.push(...inGroup.slice(0, n));
    deputies.push(...inGroup.slice(n));
  }
  // people whose latest group no longer has a seat in the latest vote
  deputies.push(...people.filter((p) => !seatsByGroup.has(p.group ?? '')));
  const seats = [...seatsByGroup].map(([group, n]) => ({ group, n, party: partyOf(group) ?? 'other' }))
    .sort((a, b) => PARTY_ORDER.indexOf(a.party) - PARTY_ORDER.indexOf(b.party) || b.n - a.n);
  return {
    bodyId: council.id, date: latest.meeting.date, total: latest.vote.ballots.length, votes: rows.length,
    seats, members: members.sort(byPartyThenName), deputies: deputies.sort(byPartyThenName),
  };
}

export interface BodyRoster { votes: number; people: PersonRow[]; known: number; groups: Seats[] }

/** People seen in a body's votes this term, with their council group where known. */
export function bodyRoster(cityId: string, bodyId: string): BodyRoster | undefined {
  const rows = allVotes(cityId).filter((r) => r.meeting.body_id === bodyId && r.meeting.date >= TERM_START);
  if (!rows.length) return undefined;
  const council = councilBody(cityId);
  const councilPeople = council
    ? tally(allVotes(cityId).filter((r) => r.meeting.body_id === council.id)) : new Map();
  const people = [...tally(rows).values()].map((p) => {
    if (p.group) return p;
    const c = councilPeople.get(p.key);
    return c?.group ? { ...p, group: c.group, party: c.party } : p;
  });
  const counts = new Map<string, Seats>();
  for (const p of people) {
    if (!p.group) continue;
    const s = counts.get(p.group) ?? { group: p.group, party: p.party ?? 'other', n: 0 };
    s.n += 1;
    counts.set(p.group, s);
  }
  const groups = [...counts.values()].sort((a, b) => PARTY_ORDER.indexOf(a.party) - PARTY_ORDER.indexOf(b.party));
  return {
    votes: rows.length,
    people: people.sort((a, b) => b.seen - a.seen || a.name.localeCompare(b.name, 'fi')),
    known: people.filter((p) => p.group).length,
    groups,
  };
}

/** Each group's majority choice in a vote (jaa/ei/tyhja), or 'split' when tied. */
export function groupMajorities(row: VoteRow): { group: string; party: Party; n: number; choice: 'jaa' | 'ei' | 'tyhja' | 'split' | 'poissa' }[] {
  const groups = new Map<string, { jaa: number; ei: number; tyhja: number; poissa: number }>();
  for (const b of row.vote.ballots) {
    if (!b.group_text) continue;
    const c = groups.get(b.group_text) ?? { jaa: 0, ei: 0, tyhja: 0, poissa: 0 };
    c[b.choice] += 1;
    groups.set(b.group_text, c);
  }
  return [...groups].map(([group, c]) => {
    const ranked = (['jaa', 'ei', 'tyhja'] as const).map((k) => [k, c[k]] as const).sort((a, b) => b[1] - a[1]);
    const choice = ranked[0][1] === 0 ? 'poissa' : ranked[0][1] === ranked[1][1] ? 'split' : ranked[0][0];
    return { group, party: partyOf(group) ?? 'other', n: c.jaa + c.ei + c.tyhja + c.poissa, choice };
  }).sort((a, b) => PARTY_ORDER.indexOf(a.party) - PARTY_ORDER.indexOf(b.party) || b.n - a.n);
}
