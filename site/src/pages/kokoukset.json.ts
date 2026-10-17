// Every meeting of every enabled municipality, for the meetings page (/kokoukset/) and as a download.
import type { APIRoute } from 'astro';
import { allMeetingRows } from '../lib/national';

export const GET: APIRoute = () =>
  new Response(JSON.stringify(allMeetingRows()), { headers: { 'Content-Type': 'application/json' } });
