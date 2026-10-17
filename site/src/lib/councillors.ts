// Every council member of every enabled municipality in one list (/valtuutetut/): party, election
// votes, and how they voted and attended this term. Members come from each council's roster
// (people.ts), so a municipality without a roster has no rows.
import { cities, councilBody, meetingFiles, peopleFile } from './data';
import { councilRoster, findPerson, personGroup, personRecords, personUrl, TERM_START } from './people';
import { partyOf, type Party } from './parties';

/** One councillor as a row of the councillors page, short keys because everyone is in one file. */
export interface CouncillorRow {
  n: string; // name
  s: string; // sort name ("Sukunimi Etunimi")
  c: string; // municipality id
  p: Party | ''; // party
  g: string; // council group or party as printed
  e: number | null; // votes in the 2025 municipal election
  v: number; // ballots cast this term (Jaa, Ei or blank), in any body
  x: number; // of those, against the majority of their own group
  a: number | null; // share of council meetings attended this term, in percent
  m: number; // motions made this term
  u: string; // person page path (Finnish)
}

let cache: CouncillorRow[] | undefined;

export function councillorRows(): CouncillorRow[] {
  if (cache) return cache;
  const rows: CouncillorRow[] = [];
  for (const c of cities().filter((x) => x.enabled)) {
    const roster = councilRoster(c.id);
    if (!roster) continue;
    const council = councilBody(c.id)?.id;
    const byUrl = new Map(peopleFile(c.id).persons.map((p) => [personUrl(p), p]));
    const records = personRecords(c.id);
    // council meetings this term whose minutes list who was there
    const att = new Map<string, { present: number; listed: number }>();
    for (const { meeting } of meetingFiles(c.id)) {
      if (meeting.body_id !== council || meeting.stage !== 'minutes' || meeting.date < TERM_START) continue;
      for (const a of meeting.attendance) {
        const p = findPerson(c.id, a.person_ref.raw);
        if (!p) continue;
        const n = att.get(p.id) ?? { present: 0, listed: 0 };
        n.listed += 1;
        if (a.present) n.present += 1;
        att.set(p.id, n);
      }
    }
    for (const m of roster.members) {
      const person = m.href ? byUrl.get(m.href) : undefined;
      if (!person) continue;
      const rec = records.get(person.id);
      const votes = (rec?.votes ?? []).filter((v) => v.row.meeting.date >= TERM_START && v.choice !== 'poissa');
      const here = att.get(person.id);
      const group = m.group ?? personGroup(person) ?? '';
      rows.push({
        n: person.name, s: person.sort_name, c: c.id, p: m.party ?? partyOf(group) ?? '', g: group,
        e: person.election?.year === 2025 && person.election.votes != null ? person.election.votes : null,
        v: votes.length, x: votes.filter((v) => v.against).length,
        a: here?.listed ? Math.round((100 * here.present) / here.listed) : null,
        m: (rec?.motions ?? []).filter((x) => x.meeting.date >= TERM_START).length,
        u: personUrl(person),
      });
    }
  }
  cache = rows.sort((a, b) => a.c.localeCompare(b.c) || a.s.localeCompare(b.s, 'fi'));
  return cache;
}
