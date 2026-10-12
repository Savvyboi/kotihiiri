// UI dictionaries for the client-side translation of shared item pages (SharedI18n.astro).
import type { APIRoute } from 'astro';
import { DICTS, type Locale } from '../../i18n';

export function getStaticPaths() {
  return [{ params: { lang: 'sv' } }, { params: { lang: 'en' } }];
}

export const GET: APIRoute = ({ params }) =>
  new Response(JSON.stringify(DICTS[params.lang as Locale]), { headers: { 'Content-Type': 'application/json' } });
