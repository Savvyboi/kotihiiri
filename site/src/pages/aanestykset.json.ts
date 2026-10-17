// Every vote of every enabled municipality, for the votes page (/aanestykset/) and as a download.
import type { APIRoute } from 'astro';
import { allVotesRows } from '../lib/data';

export const GET: APIRoute = () =>
  new Response(JSON.stringify(allVotesRows()), { headers: { 'Content-Type': 'application/json' } });
