// Every stored municipal initiative, for the initiatives page (/aloitteet/) and as a download.
import type { APIRoute } from 'astro';
import { allInitiativeRows } from '../lib/initiatives';

export const GET: APIRoute = () =>
  new Response(JSON.stringify(allInitiativeRows()), { headers: { 'Content-Type': 'application/json' } });
