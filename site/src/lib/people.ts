// Who sits where (PLAN.md §8). Helsinki's council vote tables print every seat with its council
// group, so one vote gives the seat count per group and the votes of the term show who held those
// seats. Espoo and Tampere print names only, in votes and on attendance lists; there the roster
// comes from the attendance lists and the party from the 2025 election, both in
// data/{city}/people.json (`kunta people`). Names are joined on an order-insensitive key.
import { allVotes, councilBody, feature, meetingFiles, peopleFile, speeches, type AgendaItem, type Ballot, type Choice, type Meeting, type Motion, type Person, type PersonRef, type Speech, type VoteRow } from './data';
import { partyOf, PARTY_ORDER, type Party } from './parties';

/** Start of the 2025–2029 council term (PLAN.md §5.2 Term; per-city check pending, S7). */
export const TERM_START = '2025-06-01';

export interface PersonRow { key: string; name: string; group?: string; party?: Party; seen: number; href?: string }
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

const NO_GROUP = /^(ei valtuustoryhm|ingen grupp)/i;
const indexes = new Map<string, Map<string, Person | null>>();

/** Every name form of every person in a city; a form two persons share maps to null. */
function personIndex(cityId: string): Map<string, Person | null> {
  let idx = indexes.get(cityId);
  if (!idx) {
    idx = new Map();
    for (const p of peopleFile(cityId).persons) {
      for (const n of new Set([p.name, p.sort_name, ...p.aliases].map(nameKey))) {
        idx.set(n, idx.has(n) && idx.get(n)?.id !== p.id ? null : p);
      }
    }
    indexes.set(cityId, idx);
  }
  return idx;
}

/** The speaker of a transcript speech: the person `kunta speeches` resolved, or a name match. */
export function speaker(cityId: string, ref: PersonRef): Person | undefined {
  if (ref.person_id) {
    const p = peopleFile(cityId).persons.find((x) => x.id === ref.person_id);
    if (p) return p;
  }
  return findPerson(cityId, ref.raw);
}

/** The person printed as `raw` ("Sukunimi, Etunimi", "Sukunimi Etunimi" or "Etunimi Sukunimi"). */
export function findPerson(cityId: string, raw: string): Person | undefined {
  return personIndex(cityId).get(nameKey(displayName(raw))) ?? undefined;
}

export const personSlug = (p: Person) => p.id.split('/')[1];
export const personUrl = (p: Person) => `/${p.city}/henkilot/${personSlug(p)}/`;

const groupCache = new Map<string, Map<string, string>>();
/** Latest council group per person id, from Helsinki's vote tables ("no group" only as a last resort). */
function latestGroups(cityId: string): Map<string, string> {
  let m = groupCache.get(cityId);
  if (!m) {
    m = new Map();
    const ms = peopleFile(cityId).memberships.filter((x) => x.group)
      .sort((a, b) => Number(NO_GROUP.test(a.group!)) - Number(NO_GROUP.test(b.group!))
        || (b.end ?? '').localeCompare(a.end ?? ''));
    for (const x of ms) if (!m.has(x.person_id)) m.set(x.person_id, x.group!);
    groupCache.set(cityId, m);
  }
  return m;
}

/** What to show as a person's group: their council group where printed, else their 2025 party. */
export function personGroup(p: Person): string | undefined {
  const g = latestGroups(p.city).get(p.id);
  return g && !NO_GROUP.test(g) ? g : p.party ?? g;
}

/** The group a ballot counts under: as printed (Helsinki), else the voter's party. */
export function ballotGroup(cityId: string, b: Ballot): string | undefined {
  if (b.group_text) return b.group_text;
  const p = findPerson(cityId, b.person_ref.raw);
  return p ? personGroup(p) : undefined;
}

function termVotes(rows: VoteRow[]): VoteRow[] {
  const inTerm = rows.filter((r) => r.meeting.date >= TERM_START);
  return inTerm.length ? inTerm : rows;
}

function tally(rows: VoteRow[]): Map<string, PersonRow & { lastDate: string }> {
  const people = new Map<string, PersonRow & { lastDate: string }>();
  // rows are newest first, so the first sighting carries the latest name form and group
  for (const { vote, meeting } of rows) {
    const cityId = meeting.body_id.split('/')[0];
    for (const b of vote.ballots) {
      const key = nameKey(displayName(b.person_ref.raw));
      const p = people.get(key);
      if (p) p.seen += 1;
      else {
        const person = findPerson(cityId, b.person_ref.raw);
        const group = b.group_text ?? (person && personGroup(person));
        people.set(key, {
          key, name: person?.name ?? displayName(b.person_ref.raw), group, party: partyOf(group), seen: 1,
          lastDate: meeting.date, href: person && personUrl(person),
        });
      }
    }
  }
  return people;
}

const byPartyThenName = (a: PersonRow, b: PersonRow) =>
  PARTY_ORDER.indexOf(a.party ?? 'other') - PARTY_ORDER.indexOf(b.party ?? 'other') || a.name.localeCompare(b.name, 'fi');

export interface CouncilRoster {
  bodyId: string; date: string; total: number; votes: number;
  seats: Seats[]; members: PersonRow[]; deputies: PersonRow[];
  /** 'votes': seats from a vote table (Helsinki); 'attendance': from minutes and the election */
  basis: 'votes' | 'attendance';
}

/** Who sits on the council: from the vote tables where they print groups, else from attendance. */
export function councilRoster(cityId: string): CouncilRoster | undefined {
  const council = councilBody(cityId);
  return council && (voteRoster(cityId) ?? attendanceRoster(cityId, council.id));
}

/** Council seats per group (from the latest vote with groups) and who held them this term. */
function voteRoster(cityId: string): CouncilRoster | undefined {
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
    seats, members: members.sort(byPartyThenName), deputies: deputies.sort(byPartyThenName), basis: 'votes',
  };
}

/**
 * Members of a body this term from the attendance lists on its minutes. On the council, members
 * are those present at half of the meetings or more (deputies who took over a seat included),
 * plus anyone elected in 2025 who attended one of the last three meetings; on other bodies, those
 * the minutes list as member, chair or vice-chair.
 * Everyone else who attended is a deputy. Seats are counted per party.
 */
export function attendanceRoster(cityId: string, bodyId: string): CouncilRoster | undefined {
  const meetings = meetingFiles(cityId).filter((f) => f.meeting.body_id === bodyId
    && f.meeting.stage === 'minutes' && f.meeting.date >= TERM_START && f.meeting.attendance.length);
  if (!meetings.length) return undefined;
  const isCouncil = councilBody(cityId)?.id === bodyId;
  const here = peopleFile(cityId).memberships.filter((m) => m.body_id === bodyId);
  const onBody = new Set(here.map((m) => m.person_id));
  const seated = new Set(here.filter((m) => ['member', 'chair', 'vice_chair'].includes(m.role)
    && (m.end ?? '') >= TERM_START).map((m) => m.person_id));
  const present = new Map<string, number>();
  const last = new Map<string, string>();
  const people = new Map<string, Person>();
  for (const { meeting } of meetings) {
    for (const a of meeting.attendance) {
      const p = findPerson(cityId, a.person_ref.raw);
      if (!p || !onBody.has(p.id)) continue;
      people.set(p.id, p);
      if (a.present) {
        present.set(p.id, (present.get(p.id) ?? 0) + 1);
        if (meeting.date > (last.get(p.id) ?? '')) last.set(p.id, meeting.date);
      }
    }
  }
  if (!people.size) return undefined;
  const members: PersonRow[] = [];
  const deputies: PersonRow[] = [];
  for (const p of people.values()) {
    const seen = present.get(p.id) ?? 0;
    const group = personGroup(p);
    const row: PersonRow = { key: p.id, name: p.name, group, party: partyOf(group), seen, href: personUrl(p) };
    // A councillor who attended under half the meetings and none of the last three has left the
    // seat (or is on long leave); they are listed with the deputies.
    const recent = (last.get(p.id) ?? '') >= meetings[Math.min(2, meetings.length - 1)].meeting.date;
    const member = isCouncil
      ? seen * 2 >= meetings.length || (p.election?.result === 'elected' && recent)
      : seated.has(p.id);
    (member ? members : deputies).push(row);
  }
  const counts = new Map<string, Seats>();
  for (const m of members) {
    const g = m.group ?? '';
    const s = counts.get(g) ?? { group: g, party: m.party ?? 'none', n: 0 };
    s.n += 1;
    counts.set(g, s);
  }
  const seats = [...counts.values()].sort((a, b) => PARTY_ORDER.indexOf(a.party) - PARTY_ORDER.indexOf(b.party) || b.n - a.n);
  return {
    bodyId, date: meetings[0].meeting.date, total: members.length, votes: meetings.length, seats,
    members: members.sort(byPartyThenName), deputies: deputies.sort(byPartyThenName), basis: 'attendance',
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
    return c?.group ? { ...p, group: c.group, party: c.party, href: p.href ?? c.href } : p;
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
  const cityId = row.meeting.body_id.split('/')[0];
  for (const b of row.vote.ballots) {
    const g = ballotGroup(cityId, b);
    if (!g) continue;
    const c = groups.get(g) ?? { jaa: 0, ei: 0, tyhja: 0, poissa: 0 };
    c[b.choice] += 1;
    groups.set(g, c);
  }
  return [...groups].map(([group, c]) => {
    const ranked = (['jaa', 'ei', 'tyhja'] as const).map((k) => [k, c[k]] as const).sort((a, b) => b[1] - a[1]);
    const choice = ranked[0][1] === 0 ? 'poissa' : ranked[0][1] === ranked[1][1] ? 'split' : ranked[0][0];
    return { group, party: partyOf(group) ?? 'other', n: c.jaa + c.ei + c.tyhja + c.poissa, choice };
  }).sort((a, b) => PARTY_ORDER.indexOf(a.party) - PARTY_ORDER.indexOf(b.party) || b.n - a.n);
}

export interface PersonVote { row: VoteRow; choice: Choice; group?: string; against: boolean }
export interface PersonMotion { item: AgendaItem; meeting: Meeting; motion: Motion }
export interface PersonSpeech { speech: Speech; meeting?: Meeting; item?: AgendaItem }
export interface PersonRecord {
  votes: PersonVote[]; motions: PersonMotion[]; speeches: PersonSpeech[];
  /** per body id: meetings the minutes list the person at, and how many of those they attended */
  attendance: Map<string, { present: number; listed: number }>;
}

const records = new Map<string, Map<string, PersonRecord>>();
/** Votes, motions and attendance per person id, from every minutes-stage meeting of a city. */
export function personRecords(cityId: string): Map<string, PersonRecord> {
  let out = records.get(cityId);
  if (out) return out;
  out = new Map();
  const rec = (id: string) => {
    let r = out!.get(id);
    if (!r) out!.set(id, r = { votes: [], motions: [], speeches: [], attendance: new Map() });
    return r;
  };
  for (const row of allVotes(cityId)) {
    const majority = new Map(groupMajorities(row).map((g) => [g.group, g.choice]));
    for (const b of row.vote.ballots) {
      const p = findPerson(cityId, b.person_ref.raw);
      if (!p) continue;
      const group = ballotGroup(cityId, b);
      const m = group ? majority.get(group) : undefined;
      const against = b.choice !== 'poissa' && !!m && m !== 'split' && m !== 'poissa' && b.choice !== m;
      rec(p.id).votes.push({ row, choice: b.choice, group, against });
    }
  }
  for (const { meeting, items } of meetingFiles(cityId)) {
    if (meeting.stage !== 'minutes') continue;
    for (const a of meeting.attendance) {
      const p = findPerson(cityId, a.person_ref.raw);
      if (!p) continue;
      const att = rec(p.id).attendance;
      const c = att.get(meeting.body_id) ?? { present: 0, listed: 0 };
      c.listed += 1;
      if (a.present) c.present += 1;
      att.set(meeting.body_id, c);
    }
    for (const item of items) {
      for (const motion of item.motions) {
        const p = findPerson(cityId, motion.proposer_ref.raw);
        if (p) rec(p.id).motions.push({ item, meeting, motion });
      }
    }
  }
  if (feature('SPEECHES_BY_PERSON')) {
    const meetings = new Map(meetingFiles(cityId).map((mf) => [mf.meeting.id, mf]));
    for (const speech of speeches(cityId)) {
      const p = speaker(cityId, speech.speaker_ref);
      if (!p) continue;
      const mf = meetings.get(speech.meeting_id);
      rec(p.id).speeches.push({ speech, meeting: mf?.meeting, item: mf?.items.find((i) => i.id === speech.item_id) });
    }
  }
  records.set(cityId, out);
  return out;
}
