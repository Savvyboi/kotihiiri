// RSS feeds of new agenda items (PLAN.md build log 2026-10-18): one for every followed
// municipality, one per municipality and one per topic. Output depends only on the data, never on
// the build time, so a rebuild without new meetings writes the same bytes.
import { bodyName, cities, city, itemUrl, meetingFiles, type AgendaItem, type Meeting } from './data';
import { FORMALITY, itemTopics } from './topics';
import { localePath } from '../i18n';

export const FEED_SIZE = 100;

export interface FeedEntry { date: string; city: string; item: AgendaItem; meeting: Meeting }

let cache: FeedEntry[] | undefined;

/** Every agenda item of every followed municipality except meeting formalities, newest first. */
export function feedEntries(): FeedEntry[] {
  if (cache) return cache;
  const out: FeedEntry[] = [];
  for (const c of cities().filter((x) => x.enabled)) {
    for (const { meeting, items } of meetingFiles(c.id)) {
      for (const item of items) {
        if (item.status === 'tombstone' || FORMALITY.test(item.title)) continue;
        out.push({ date: meeting.date, city: c.id, item, meeting });
      }
    }
  }
  cache = out.sort((a, b) => b.date.localeCompare(a.date) || a.city.localeCompare(b.city)
    || a.item.id.localeCompare(b.item.id, 'fi', { numeric: true }));
  return cache;
}

export const cityEntries = (id: string) => feedEntries().filter((e) => e.city === id).slice(0, FEED_SIZE);
export const topicEntries = (topic: string) => feedEntries().filter((e) => itemTopics(e.item.title).includes(topic)).slice(0, FEED_SIZE);

const STAGE: Record<Meeting['stage'], string> = { agenda: 'Esityslista', decisions: 'Päätökset', minutes: 'Pöytäkirja' };
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' }[c]!));
const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);
/** RFC 822 date at noon UTC, so the day never shifts in a reader's time zone. */
const rfc822 = (iso: string) => new Date(`${iso}T12:00:00Z`).toUTCString();

/** One RSS 2.0 document. `site` is the origin, `self` the feed's own path. */
export function rss(o: { site: string; self: string; page: string; title: string; description: string; entries: FeedEntry[] }): Response {
  const abs = (p: string) => `${o.site}${localePath(p)}`;
  const items = o.entries.map((e) => {
    const name = city(e.city)?.name_fi ?? e.city;
    const [y, m, d] = e.date.split('-').map(Number);
    const desc = [`${name} · ${bodyName(e.meeting.body_id)} · ${STAGE[e.meeting.stage]} · kokous ${d}.${m}.${y}`,
      e.item.votes.length ? `Äänestyksiä: ${e.item.votes.length}` : '',
      e.item.decision_summary ? clip(e.item.decision_summary, 400) : ''].filter(Boolean).join('\n');
    const link = abs(itemUrl(e.item));
    return `<item><title>${esc(`${name}: ${clip(e.item.title, 200)}`)}</title><link>${esc(link)}</link>`
      + `<guid isPermaLink="false">${esc(`${e.item.id}#${e.meeting.stage}`)}</guid><pubDate>${rfc822(e.date)}</pubDate>`
      + `<category>${esc(name)}</category><description>${esc(desc)}</description></item>`;
  });
  const last = o.entries[0]?.date;
  const xml = `<?xml version="1.0" encoding="utf-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>`
    + `<title>${esc(o.title)}</title><link>${esc(abs(o.page))}</link><description>${esc(o.description)}</description>`
    + `<language>fi</language>${last ? `<lastBuildDate>${rfc822(last)}</lastBuildDate>` : ''}`
    + `<atom:link href="${esc(`${o.site}${localePath(o.self).replace(/\/$/, '')}`)}" rel="self" type="application/rss+xml"/>`
    + `${items.join('\n')}</channel></rss>\n`;
  return new Response(xml, { headers: { 'Content-Type': 'application/rss+xml; charset=utf-8' } });
}
