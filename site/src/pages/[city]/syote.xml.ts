// New agenda items in one municipality, as RSS (/{city}/syote.xml).
import type { APIRoute } from 'astro';
import { cities, type City } from '../../lib/data';
import { cityEntries, rss } from '../../lib/feeds';

export function getStaticPaths() {
  return cities().filter((c) => c.enabled).map((c) => ({ params: { city: c.id }, props: { city: c } }));
}

export const GET: APIRoute = ({ site, props }) => {
  const c = (props as { city: City }).city;
  return rss({
    site: site?.origin ?? '', self: `/${c.id}/syote.xml`, page: `/${c.id}/`,
    title: `Kotihiiri: ${c.name_fi}`,
    description: `${c.name_fi}: uusimmat asiat esityslistoilta ja pöytäkirjoista.`,
    entries: cityEntries(c.id),
  });
};
