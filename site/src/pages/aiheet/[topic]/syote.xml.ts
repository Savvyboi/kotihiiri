// New agenda items on one topic in every followed municipality, as RSS (/aiheet/{topic}/syote.xml).
import type { APIRoute } from 'astro';
import { t, type Key } from '../../../i18n';
import { topicEntries, rss } from '../../../lib/feeds';
import { topicIds } from '../../../lib/topics';

export function getStaticPaths() {
  return topicIds.map((topic) => ({ params: { topic } }));
}

export const GET: APIRoute = ({ site, params }) => {
  const topic = params.topic!;
  const name = t(`topic.${topic}` as Key, {}, 'fi');
  return rss({
    site: site?.origin ?? '', self: `/aiheet/${topic}/syote.xml`, page: `/aiheet/${topic}/`,
    title: `Kotihiiri: ${name}`,
    description: `${name}: uusimmat asiat kaikista seuratuista kunnista.`,
    entries: topicEntries(topic),
  });
};
