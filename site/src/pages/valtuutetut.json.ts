// Every councillor of every enabled municipality, for the councillors page (/valtuutetut/) and as a download.
import type { APIRoute } from 'astro';
import { councillorRows } from '../lib/councillors';

export const GET: APIRoute = () =>
  new Response(JSON.stringify(councillorRows()), { headers: { 'Content-Type': 'application/json' } });
