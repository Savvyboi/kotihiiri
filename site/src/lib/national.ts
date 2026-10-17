// Views across every enabled municipality: all meetings (/kokoukset/) and parties (/puolueet/).
import { allVotes, bodies, bodyName, cities, meetingFiles, meetingUrl, voteOutcome, type Choice } from './data';
import { ballotGroup, councilRoster } from './people';
import { PARTY_ORDER, partyOf, type Party } from './parties';

/** One meeting as a row of the meetings page, short keys because every meeting is in one file. */
export interface MeetingRow {
  d: string; // date
  h: string; // start time, or ''
  c: string; // municipality id
  b: string; // body name
  k: string; // body kind
  s: 'agenda' | 'decisions' | 'minutes';
  n: number; // items
  v: number; // votes
  u: string; // meeting page path (Finnish)
}

let meetingCache: MeetingRow[] | undefined;

export function allMeetingRows(): MeetingRow[] {
  if (meetingCache) return meetingCache;
  const rows: MeetingRow[] = [];
  for (const c of cities().filter((x) => x.enabled)) {
    const kinds = new Map(bodies(c.id).map((b) => [b.id, b.kind]));
    for (const { meeting, items } of meetingFiles(c.id)) {
      rows.push({
        d: meeting.date, h: meeting.start_time ?? '', c: c.id, b: bodyName(meeting.body_id),
        k: kinds.get(meeting.body_id) ?? 'other', s: meeting.stage, n: items.length,
        v: items.reduce((k, i) => k + i.votes.length, 0), u: meetingUrl(meeting),
      });
    }
  }
  meetingCache = rows.sort((a, b) => b.d.localeCompare(a.d) || a.c.localeCompare(b.c) || a.u.localeCompare(b.u));
  return meetingCache;
}

/** Parties named on councils; "other" groups and members without a group are left out. */
export const NAMED_PARTIES = PARTY_ORDER.filter((p) => p !== 'other' && p !== 'none');

export interface PartyStat {
  party: Party;
  seats: number; // council seats this term, summed over municipalities
  munis: number; // municipalities where the party holds a council seat
  positions: number; // votes where the party's members took a side (a Jaa or Ei majority)
  wins: number; // of those, votes the side won
  together: number; // members' ballots cast with the party's majority
  cast: number; // members' Jaa, Ei and blank ballots in those votes
}

export interface PartyView {
  stats: PartyStat[];
  /** For each pair of parties: votes where both took a side, and how often the same one. */
  pairs: Map<string, { both: number; same: number }>;
  votes: number; // votes with members' names and a known party
  munis: number; // municipalities those votes come from
}

export const pairKey = (a: Party, b: Party) => `${a}|${b}`;

let partyCache: PartyView | undefined;

/** Seats from each council's roster; voting behaviour from every vote that names its voters. */
export function partyView(): PartyView {
  if (partyCache) return partyCache;
  const stats = new Map<Party, PartyStat>(NAMED_PARTIES.map((p) => [p, {
    party: p, seats: 0, munis: 0, positions: 0, wins: 0, together: 0, cast: 0,
  }]));
  const pairs = new Map<string, { both: number; same: number }>();
  let votes = 0;
  const voteMunis = new Set<string>();
  for (const c of cities().filter((x) => x.enabled)) {
    const roster = councilRoster(c.id);
    const here = new Set<Party>();
    for (const s of roster?.seats ?? []) {
      const st = stats.get(s.party);
      if (!st) continue;
      st.seats += s.n;
      here.add(s.party);
    }
    for (const p of here) stats.get(p)!.munis += 1;
    for (const row of allVotes(c.id)) {
      const outcome = voteOutcome(row.vote);
      const tally = new Map<Party, Record<Choice, number>>();
      for (const b of row.vote.ballots) {
        const party = partyOf(ballotGroup(c.id, b));
        if (!party || !stats.has(party)) continue;
        const t = tally.get(party) ?? { jaa: 0, ei: 0, tyhja: 0, poissa: 0 };
        t[b.choice] += 1;
        tally.set(party, t);
      }
      if (!tally.size) continue;
      votes += 1;
      voteMunis.add(c.id);
      const side = new Map<Party, 'jaa' | 'ei'>();
      for (const [party, t] of tally) {
        if (t.jaa === t.ei) continue; // split evenly, or no Jaa or Ei at all
        const choice = t.jaa > t.ei ? 'jaa' : 'ei';
        const st = stats.get(party)!;
        side.set(party, choice);
        st.positions += 1;
        if (choice === outcome) st.wins += 1;
        st.together += t[choice];
        st.cast += t.jaa + t.ei + t.tyhja;
      }
      const sided = NAMED_PARTIES.filter((p) => side.has(p));
      for (let i = 0; i < sided.length; i++) {
        for (let j = i + 1; j < sided.length; j++) {
          const k = pairKey(sided[i], sided[j]);
          const pr = pairs.get(k) ?? { both: 0, same: 0 };
          pr.both += 1;
          if (side.get(sided[i]) === side.get(sided[j])) pr.same += 1;
          pairs.set(k, pr);
        }
      }
    }
  }
  partyCache = { stats: [...stats.values()], pairs, votes, munis: voteMunis.size };
  return partyCache;
}
