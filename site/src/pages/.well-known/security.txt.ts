// RFC 9116 security.txt (/.well-known/security.txt): where to report a vulnerability in the site.
// Expires is set 180 days after the build; pages.yml rebuilds at least weekly, so it never lapses.
import type { APIRoute } from 'astro';
import { contactEmail } from '../../lib/data';

const VALID_DAYS = 180;

export const GET: APIRoute = ({ site }) => {
  const origin = site?.origin ?? '';
  const expires = new Date(Date.now() + VALID_DAYS * 86_400_000);
  expires.setUTCHours(0, 0, 0, 0);
  const body = [
    `Contact: mailto:${contactEmail()}`,
    `Expires: ${expires.toISOString()}`,
    'Preferred-Languages: fi, en, sv',
    // Only at a domain root: the GitHub Pages build lives under a base path, where no client looks.
    ...(import.meta.env.BASE_URL === '/' ? [`Canonical: ${origin}/.well-known/security.txt`] : []),
    '',
  ].join('\n');
  return new Response(body, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
};
