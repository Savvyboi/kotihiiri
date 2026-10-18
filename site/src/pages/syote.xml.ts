// New agenda items in every followed municipality, as RSS (/syote.xml).
import type { APIRoute } from 'astro';
import { FEED_SIZE, feedEntries, rss } from '../lib/feeds';

export const GET: APIRoute = ({ site }) => rss({
  site: site?.origin ?? '', self: '/syote.xml', page: '/kokoukset/',
  title: 'Kotihiiri: uusimmat asiat kaikista kunnista',
  description: 'Uusimmat esityslistojen ja pöytäkirjojen asiat kaikista Kotihiiren seuraamista kunnista.',
  entries: feedEntries().slice(0, FEED_SIZE),
});
